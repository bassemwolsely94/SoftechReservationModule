"""
apps/invoices/writer.py

Transactional writeback of a confirmed supplier invoice into SOFTECH as a FINAL
purchase document — stktransm + stktrans, doccode 10 (purchase) / 120 (return to
supplier). Modeled byte-for-byte on the proven apps/pos_orders/writer.py:
inline-literal INSERTs (parameterized INSERTs silently don't land on this ASE),
one statement per cursor, native serial allocation (read counter +1; the insert
trigger bumps it), verify-readback, idempotency tag in vf2, real BEGIN/COMMIT/ROLLBACK.

Behaviour & field mapping fully reverse-engineered in:
    docs/architecture/SOFTECH_SUPPLIER_INVOICE_WRITEBACK.md

⚠️ SAFETY — GATED, NO PROD WRITE BY DEFAULT ⚠️
Every entry point is guarded by settings.INVOICE_WRITER_ENABLED (default False). With
the gate OFF, push_final() only PREPARES + returns the dry-run plan (the exact SQL it
WOULD run) — nothing is sent to SOFTECH. Unlike the POS pending writer, the purchase
writer targets the FINAL tables, whose (vendor-protected) insert triggers do stock
receive + weighted-avg-cost recompute + supplier-balance — so the live path MUST be
validated on SOFTECH_TEST_HOST first. Use probe_invoice() (real inserts, always
ROLLBACK) to rehearse with zero residue and observe the counter/trigger behaviour.
"""
import logging
import uuid
from datetime import date, datetime
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from . import pricing
from .models import SupplierInvoice

logger = logging.getLogger('elrezeiky.invoices')


class WriterDisabled(RuntimeError):
    """Raised if a real SOFTECH write is attempted while the gate is off."""


def writer_enabled():
    return bool(getattr(settings, 'INVOICE_WRITER_ENABLED', False))


def _write_charset():
    return getattr(settings, 'INVOICE_WRITE_CHARSET', 'cp1256') or None


def _default_usercode(invoice):
    return (getattr(settings, 'INVOICE_DEFAULT_USERCODE', '') or '1')


def softech_token(invoice):
    """Idempotency marker stashed in stktransm.vf2 (varchar(15)) — 'INV<pk>'."""
    return f'INV{invoice.pk}'[:15]


_UNREACHABLE_HINTS = ('connection timed out', 'connection refused', 'jz006', 'jz0',
                      'ioexception', 'connectexception', 'no route to host',
                      'network is unreachable', 'unknownhost', 'socket')


def _is_unreachable(exc):
    msg = str(exc).lower()
    return any(h in msg for h in _UNREACHABLE_HINTS)


# ── 1. COMPUTE — line + header money fields (pure, via pricing.py) ──────────────
def compute(invoice: SupplierInvoice):
    """Return (computed_lines, header) where computed_lines aligns 1:1 with
    invoice.lines.all() (only lines with a matched item + qty>0 are written)."""
    computed = []
    lines = []
    for line in invoice.lines.select_related('item').all():
        if not line.item_id or float(line.quantity or 0) <= 0:
            continue
        c = pricing.compute_line(
            public_price=line.public_price, unit_price=line.unit_price,
            qty=line.quantity, discount_pct=line.discount_pct,
            extra_discount_pct=line.extra_discount_pct, vat_pct=line.vat_pct,
        )
        c['_line'] = line
        computed.append(c)
        lines.append(c)
    header = pricing.compute_header(lines)
    return computed, header


def _parse_expiry(s):
    """InvoiceLine.expiry_date → a date or None.

    Prefers a normalized 'YYYY-MM-DD' (what ocr.normalize_expiry emits), but also
    accepts the RAW printed forms ('08.2027', '08/2027', 'Aug 2027', '31/08/2027')
    that the legacy pipe OCR path stores un-normalized. Used by BOTH the writer
    (batch expiry it sends to SOFTECH) and validations (the expiry_required check),
    so they must agree — otherwise a captured expiry is falsely reported missing
    here AND silently written as NULL to SOFTECH."""
    if not s:
        return None
    if isinstance(s, date):
        return s
    for fmt in ('%Y-%m-%d', '%Y/%m/%d'):
        try:
            return datetime.strptime(str(s)[:10], fmt).date()
        except (ValueError, TypeError):
            continue
    # Fallback: delegate to the same normalizer the structured OCR uses.
    from .ocr import normalize_expiry
    iso = normalize_expiry(str(s))
    if iso:
        try:
            return datetime.strptime(iso[:10], '%Y-%m-%d').date()
        except (ValueError, TypeError):
            pass
    return None


def _docnumber2(invoice):
    """Supplier's printed invoice no → stktransm.docnumber2 (decimal). Digits only;
    0 when the supplier number is non-numeric (kept verbatim in our PG record)."""
    raw = ''.join(ch for ch in str(invoice.invoice_number or '') if ch.isdigit())
    return int(raw) if raw else 0


# ── 2. BUILD PLAN — exact column→value maps + SQL (no SOFTECH contact) ──────────
def build_plan(invoice: SupplierInvoice):
    computed, header = compute(invoice)
    if not computed:
        raise ValueError('لا توجد أسطر مطابقة (صنف + كمية) لترحيلها.')
    if not invoice.vendor or not invoice.vendor.softech_personcode:
        raise ValueError('المورد غير مربوط بكود SOFTECH (VendorProfile.softech_personcode).')

    personcode = invoice.vendor.softech_personcode
    branch = invoice.softech_branchcode or (invoice.branch.softech_branch_id if invoice.branch_id else '')
    store  = invoice.store_code or branch
    doccode = invoice.softech_doccode

    supplier_name = invoice.vendor.name if invoice.vendor else ''
    # Faithful to what _run_write_batch actually sends (32-col header): docwritedate set,
    # NO trans_time/vf2/newcostprice; docvalue1/2/3=0; ptclassif resolved live at push.
    hdr = {
        'branchcode': branch, 'doccode': doccode, 'docnumber': '<next>',
        'docdate': '<today>', 'docwritedate': '<today>', 'storecode': store, 'supp_main_code': '00',
        'docnumber2': _docnumber2(invoice), 'docvalue': header['doc_value'],
        'cust_branch_code': personcode, 'supplier_name': supplier_name, 'cust_branch_store': store,
        'origintaxp': 0, 'custdiscp': 0, 'specialdiscp': 0,
        'docvaluepay': 0, 'fatstatuscode': '10', 'ptcode': '20',
        'ptclassifcode': '<from personsdata at push>', 'docvaluereturn': 0,
        'fatcurrentstatus': '15', 'cust_professional': '0', 'saleprice_extrap': 0,
        'usercode': _default_usercode(invoice),
        'patientpayment': 0, 'docvalue1': 0, 'docvalue2': 0, 'docvalue3': 0,
        'bcurrency': 1, 'docvaluebc': header['doc_value'], 'docvaluepaybc': 0, 'bcrate': 1,
        'origdoc': 0,
    }
    lines = []
    for idx, c in enumerate(computed, start=1):
        ln = c['_line']
        row = {
            'branchcode': branch, 'doccode': doccode, 'docnumber': '<next>',
            'docdate': '<today>', 'storecode': store,
            'itemcode': ln.item.softech_id, 'item_name': (ln.item.name if ln.item else ''),
            'transqty': float(ln.quantity), 'transprice': c['transprice'],
            'newqty': '<computed live at push>',   # trigger validates; = stkbal ± qty (cumulative)
            'itemexpirydate': (str(_parse_expiry(ln.expiry_date)) if _parse_expiry(ln.expiry_date) else None),
            'itemsaleprice': c['itemsaleprice'], 'itemsalestax': c['itemsalestax'],
            'itemsaleprice_tax': c['itemsaleprice_tax'], 'pharmacydiscp': c['pharmacydiscp'],
            'additionaldiscp': c['additionaldiscp'], 'transprice_total': c['transprice_total'],
            'origintaxp': c['origintaxp'], 'custdiscp': 0, 'specialdiscp': 0,
            'bonusqty': 0, 'dblitemflag': idx, 'storecode2': '0', 'suppliercode': personcode,
            'personcode': personcode, 'usercode': _default_usercode(invoice), 'retqty': 0, 'promtype': 1,
        }
        if invoice.doc_kind == 'return':
            row['r_docnumber'] = int(invoice.return_of_docnumber or 0)
            row['r_doccode']   = '10'
        lines.append(row)

    counter = invoice.softech_counter_column
    notes = [
        'الرصيد بعد الاستلام (newqty) وسعر التكلفة المرجّح يحسبهما SOFTECH آلياً عند الترحيل.',
        'يتم تخصيص رقم المستند (docnumber) لحظة الترحيل من عدّاد الفرع.',
        ('نوع المستند: شراء من مورد (doccode 10).' if doccode == '10'
         else 'نوع المستند: مرتجع إلى مورد (doccode 120).'),
    ]
    return {'header': hdr, 'lines': lines, 'notes': notes, 'doc_value': header['doc_value'],
            'doc_kind': invoice.doc_kind, 'doccode': doccode, 'counter': counter,
            'branchcode': branch, 'supplier_name': supplier_name,
            'supplier_code': personcode, 'invoice_number': invoice.invoice_number or ''}


# ── low-level helpers (identical discipline to pos_orders/writer.py) ────────────
class _Raw:
    def __init__(self, sql):
        self.sql = sql


def _docnum(v):
    """docnumber may be a real number or a _Raw SQL variable (e.g. '@dn')."""
    return v if isinstance(v, _Raw) else int(v)


_TODAY_MIDNIGHT = _Raw("convert(datetime, convert(char(8), getdate(), 112))")
_NOW = _Raw("getdate()")


def _exec(conn, sql, params=None):
    cur = conn.cursor()
    try:
        cur.execute(sql, params or [])
    finally:
        cur.close()


def _q1(conn, sql, params=None):
    cur = conn.cursor()
    try:
        cur.execute(sql, params or [])
        return cur.fetchone()
    finally:
        cur.close()


def _jsonify(v):
    """Make a Sybase cell JSON-safe (datetime → ISO, Decimal → float)."""
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def _one_dict(conn, sql, params=None):
    """SELECT one row as an ordered {column: value} dict (JSON-safe values)."""
    cur = conn.cursor()
    try:
        cur.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        r = cur.fetchone()
        return {c: _jsonify(v) for c, v in zip(cols, r)} if r else None
    finally:
        cur.close()


def _all_dicts(conn, sql, params=None):
    cur = conn.cursor()
    try:
        cur.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        return [{c: _jsonify(v) for c, v in zip(cols, row)} for row in cur.fetchall()]
    finally:
        cur.close()


def branch_host(invoice):
    """Write target host: the branch's own server, else HQ (SYBASE_HOST) for the
    HQ branch whose db_host is conventionally left blank."""
    host = (invoice.branch.db_host if invoice.branch_id else '') or getattr(settings, 'SYBASE_HOST', '')
    return host


def _sql_literal(val):
    if isinstance(val, _Raw):
        return val.sql
    if val is None:
        return 'NULL'
    if isinstance(val, bool):
        return '1' if val else '0'
    if isinstance(val, int):
        return str(val)
    if isinstance(val, (float, Decimal)):
        return str(float(val))
    return "'" + str(val).replace("'", "''") + "'"


def _exec_insert(conn, table, row: dict):
    cols = list(row.keys())
    vals = [_sql_literal(row[c]) for c in cols]
    _exec(conn, f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(vals)})")


def read_supplier(conn, personcode):
    """READ-ONLY: the supplier's classification (ptclassifcode) from personsdata
    (ptcode='20'). Returns {'ptclassifcode': str|None}. ptclassifcode varies per
    supplier — must come from the master, never hardcoded (spec §6)."""
    row = _q1(conn, "SELECT ptclassifcode FROM personsdata WHERE personcode=? AND ptcode='20'",
              [str(personcode)])
    return {'ptclassifcode': (str(row[0]).strip() if row and row[0] is not None else None)}


def _return_reason_code():
    try:
        return int(getattr(settings, 'INVOICE_RETURN_REASON_CODE', '4') or 4)
    except (TypeError, ValueError):
        return 4


def _header_row(invoice, header, docnumber, ptclassifcode, usercode):
    """Exact native header. PURCHASE = 32 cols (sets docwritedate). RETURN (doccode 120) =
    31 cols (NO docwritedate; patientpayment = original purchase docnumber; docnumber2 =
    return-reason code). See docs/architecture/SOFTECH_PURCHASE_SAVE_DML.md."""
    branch = invoice.softech_branchcode
    store  = invoice.store_code or branch
    personcode = invoice.vendor.softech_personcode
    dv = float(header['doc_value'])
    if invoice.doc_kind == 'return':
        return {
            'branchcode': branch, 'doccode': invoice.softech_doccode, 'docnumber': _docnum(docnumber),
            'docdate': _TODAY_MIDNIGHT, 'specialdiscp': 0.0, 'origintaxp': 0.0, 'storecode': store,
            'fatstatuscode': '10', 'ptcode': '20', 'ptclassifcode': ptclassifcode,
            'fatcurrentstatus': '15', 'custdiscp': 0.0, 'usercode': usercode,
            'cust_branch_store': store, 'cust_professional': '0', 'saleprice_extrap': 0.0,
            'docvalue': dv, 'docvaluepay': 0.0, 'docvaluereturn': 0.0,
            'patientpayment': float(int(invoice.return_of_docnumber or 0)),   # ← original purchase docnumber
            'docvalue1': 0.0, 'docvalue2': 0.0, 'docvalue3': 0.0, 'bcurrency': 1,
            'docvaluebc': dv, 'docvaluepaybc': 0.0, 'bcrate': 1.0, 'supp_main_code': '00',
            'cust_branch_code': personcode, 'origdoc': 0,
            'docnumber2': _return_reason_code(),                              # ← return-reason code
        }
    return {
        'branchcode': branch, 'doccode': invoice.softech_doccode, 'docnumber': _docnum(docnumber),
        'docdate': _TODAY_MIDNIGHT, 'specialdiscp': 0.0, 'origintaxp': 0.0, 'storecode': store,
        'fatstatuscode': '10', 'ptcode': '20', 'ptclassifcode': ptclassifcode,
        'fatcurrentstatus': '15', 'docwritedate': _TODAY_MIDNIGHT, 'custdiscp': 0.0,
        'usercode': usercode, 'cust_branch_store': store, 'cust_professional': '0',
        'saleprice_extrap': 0.0, 'docvalue': dv, 'docvaluepay': 0.0, 'docvaluereturn': 0.0,
        'patientpayment': 0.0, 'docvalue1': 0.0, 'docvalue2': 0.0, 'docvalue3': 0.0,
        'bcurrency': 1, 'docvaluebc': dv, 'docvaluepaybc': 0.0, 'bcrate': 1.0,
        'supp_main_code': '00', 'cust_branch_code': personcode, 'origdoc': 0,
        'docnumber2': _docnumber2(invoice),
    }


def _line_row(invoice, c, docnumber, usercode, newqty, dblitemflag=1, *, newcostprice=None, r_docdate=None):
    """Exact native line. PURCHASE = 28 cols, `newcostprice` OMITTED (the trigger computes
    weighted-avg cost). RETURN = 32 cols, INCLUDES `newcostprice` (from the original
    purchase) + `r_docnumber`/`r_docdate`/`r_doccode='10'` linkage. `newqty` is the resulting
    running balance (stkbal ± transqty). `dblitemflag` = 1-based line number (unique-index
    component). See docs/architecture/SOFTECH_PURCHASE_SAVE_DML.md."""
    ln = c['_line']
    branch = invoice.softech_branchcode
    store  = invoice.store_code or branch
    personcode = invoice.vendor.softech_personcode
    exp = _parse_expiry(ln.expiry_date)
    exp_lit = (_Raw(f"convert(datetime, '{exp:%Y-%m-%d} 00:00:00')") if exp else None)
    if invoice.doc_kind == 'return':
        rdd = r_docdate if isinstance(r_docdate, _Raw) else _Raw("convert(datetime, '1900-01-01')")
        return {
            'branchcode': branch, 'doccode': invoice.softech_doccode, 'docnumber': _docnum(docnumber),
            'docdate': _TODAY_MIDNIGHT, 'storecode': store,
            'itemsalestax': float(c['itemsalestax']), 'itemsaleprice_tax': float(c['itemsaleprice_tax']),
            'pharmacydiscp': float(c['pharmacydiscp']), 'additionaldiscp': float(c['additionaldiscp']),
            'itemexpirydate': exp_lit, 'transprice': float(c['transprice']),
            'newcostprice': float(newcostprice if newcostprice is not None else c['transprice']),
            'transprice_total': float(c['transprice_total']), 'origintaxp': float(c['origintaxp']),
            'custdiscp': 0.0, 'specialdiscp': 0.0, 'saleprice_extrap': 0.0, 'usercode': usercode,
            'bonusqty': 0.0, 'dblitemflag': int(dblitemflag), 'storecode2': '0',
            'r_docnumber': int(invoice.return_of_docnumber or 0), 'r_docdate': rdd,
            'transqty': float(ln.quantity), 'newqty': float(newqty), 'retqty': 0.0,
            'itemcode': str(ln.item.softech_id), 'suppliercode': personcode, 'personcode': personcode,
            'itemsaleprice': float(c['itemsaleprice']), 'r_doccode': '10', 'promtype': 1,
        }
    return {
        'branchcode': branch, 'doccode': invoice.softech_doccode, 'docnumber': _docnum(docnumber),
        'docdate': _TODAY_MIDNIGHT, 'storecode': store, 'itemcode': str(ln.item.softech_id),
        'itemsalestax': float(c['itemsalestax']), 'itemsaleprice_tax': float(c['itemsaleprice_tax']),
        'pharmacydiscp': float(c['pharmacydiscp']), 'additionaldiscp': float(c['additionaldiscp']),
        'itemexpirydate': exp_lit,
        'transprice': float(c['transprice']), 'transprice_total': float(c['transprice_total']),
        'origintaxp': float(c['origintaxp']), 'custdiscp': 0.0, 'specialdiscp': 0.0,
        'saleprice_extrap': 0.0, 'usercode': usercode, 'bonusqty': 0.0, 'dblitemflag': int(dblitemflag),
        'storecode2': '0', 'transqty': float(ln.quantity), 'newqty': float(newqty),
        'retqty': 0.0, 'suppliercode': personcode, 'personcode': personcode,
        'itemsaleprice': float(c['itemsaleprice']), 'promtype': 1,
    }


def _read_original_purchase(conn, branch, docnumber):
    """For a RETURN: read the original purchase's docdate (→ r_docdate) and per-item
    newcostprice (weighted-avg cost at receipt) from its stktrans (doccode 10) lines."""
    row = _q1(conn, "SELECT docdate FROM stktransm WHERE branchcode=? AND doccode='10' AND docnumber=?",
              [branch, int(docnumber)])
    docdate = row[0] if row else None
    costs = {}
    cur = conn.cursor()
    try:
        cur.execute("SELECT itemcode, newcostprice FROM stktrans "
                    "WHERE branchcode=? AND doccode='10' AND docnumber=?", [branch, int(docnumber)])
        for r in cur.fetchall():
            costs[str(r[0]).strip()] = float(r[1]) if r[1] is not None else 0.0
    finally:
        cur.close()
    rdd = _Raw(f"convert(datetime, '{docdate:%Y-%m-%d} 00:00:00')") if docdate else _Raw("convert(datetime, '1900-01-01')")
    return costs, rdd, (docdate is not None)


def read_stkbal(conn, branch, store, itemcodes):
    """READ current stock balance per item (stkbal.nowqty) — needed to compute the
    running `newqty` sp_expirytrans expects. Missing row → 0 (new item at this store)."""
    out = {}
    for code in dict.fromkeys(str(x).strip() for x in itemcodes if str(x).strip()):
        row = _q1(conn, "SELECT nowqty FROM stkbal WHERE branchcode=? AND storecode=? AND itemcode=?",
                  [branch, store, code])
        out[code] = float(row[0]) if row and row[0] is not None else 0.0
    return out


# ── UNCHAINED-mode single-batch writer (the fix) ────────────────────────────────
# The native client runs in UNCHAINED transaction mode with explicit begin/commit
# tran. jConnect setAutoCommit(false) = CHAINED mode, under which SofTech's
# sp_expirytrans (called by tr_stktrans) hits its error path → err 2732. So we run
# the whole document as ONE batch, in autocommit(=unchained) mode, with explicit
# begin tran … (verify) … commit/rollback tran, exactly like the client.
def _insert_sql(table, row: dict):
    cols = list(row.keys())
    vals = [_sql_literal(row[c]) for c in cols]
    return f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(vals)})"


def _run_batch_lastrow(jst, batch):
    """Execute a multi-statement batch on a raw java Statement; return the LAST
    result set's first row (list of Java objects) — our trailing status SELECT."""
    has_rs = jst.execute(batch)
    last = None
    while True:
        if has_rs:
            rs = jst.getResultSet()
            if rs is not None:
                cnt = rs.getMetaData().getColumnCount()
                if rs.next():
                    last = [rs.getObject(i) for i in range(1, cnt + 1)]
                rs.close()
        elif jst.getUpdateCount() == -1:
            break
        has_rs = jst.getMoreResults()
    return last


def _run_write_batch(conn, invoice, computed, header, ptclassifcode, usercode, nowqty, *, do_commit):
    """One unchained batch: allocate docnumber (HOLDLOCK read+1), INSERT header +
    lines, UPDATE the supplier counter, verify (header present + all lines present),
    then COMMIT (do_commit and verified) or ROLLBACK. Returns a result dict."""
    branch  = invoice.softech_branchcode
    counter = invoice.softech_counter_column
    doccode = invoice.softech_doccode
    is_return = invoice.doc_kind == 'return'
    n = len(computed)
    bc = _sql_literal(branch)

    # RETURN: link to the original purchase — pull its per-item cost + docdate (r_docdate).
    orig_cost, r_docdate = {}, None
    if is_return and invoice.return_of_docnumber:
        orig_cost, r_docdate, orig_found = _read_original_purchase(conn, branch, invoice.return_of_docnumber)
        if not orig_found:
            return {'ok': False, 'err': -1, 'docnumber': None, 'lines_found': 0,
                    'lines_expected': n, 'error': f'الفاتورة الأصلية {invoice.return_of_docnumber} غير موجودة في SOFTECH'}

    stmts = [_insert_sql('stktransm', _header_row(invoice, header, _Raw('@dn'), ptclassifcode, usercode))]
    newqtys = {}
    running = dict(nowqty)   # per-item running balance, accumulates across lines
    for idx, c in enumerate(computed, start=1):
        code = str(c['_line'].item.softech_id).strip()
        qty  = float(c['_line'].quantity or 0)
        running[code] = running.get(code, 0.0) + (-qty if is_return else qty)
        nq = running[code]
        newqtys[code] = nq
        # dblitemflag = 1-based line number (unique-index component for repeated items)
        stmts.append(_insert_sql('stktrans', _line_row(
            invoice, c, _Raw('@dn'), usercode, nq, idx,
            newcostprice=orig_cost.get(code), r_docdate=r_docdate)))
    inserts = '\n'.join(stmts)
    final = 'commit tran' if do_commit else 'rollback tran'

    batch = f"""
set chained off
declare @dn numeric(9,0), @lines int, @hdr int, @err int
begin tran
select @dn = {counter} + 1 from lastdocnumbers holdlock where branchcode = {bc}
{inserts}
select @err = @@error
update lastdocnumbers set {counter} = @dn where branchcode = {bc}
select @hdr = count(*) from stktransm where branchcode={bc} and doccode='{doccode}' and docnumber=@dn
select @lines = count(*) from stktrans where branchcode={bc} and doccode='{doccode}' and docnumber=@dn
if @hdr = 1 and @lines = {n} {final}
else rollback tran
select @dn as docnumber, @hdr as hdr, @lines as lines, isnull(@err,0) as err,
       case when @hdr=1 and @lines={n} then 1 else 0 end as verified
"""
    jst = conn._conn.createStatement()
    try:
        row = _run_batch_lastrow(jst, batch)
    finally:
        try:
            jst.close()
        except Exception:
            pass

    def _i(v, d=0):
        try:
            return int(str(v))
        except Exception:
            return d
    docnumber = _i(row[0]) if row else 0
    hdr_found = _i(row[1]) if row else 0
    lines_found = _i(row[2]) if row else 0
    err = _i(row[3], -1) if row else -1
    verified = _i(row[4]) if row else 0
    ok = bool(verified == 1)
    return {'ok': ok, 'docnumber': docnumber, 'counter_column': counter,
            'hdr_found': hdr_found, 'lines_found': lines_found, 'lines_expected': n,
            'err': err, 'committed': bool(do_commit and ok), 'newqtys': newqtys}


# ── 3. PUSH — guarded; dry-run plan unless gate on + dry_run=False ─────────────
def push_final(invoice: SupplierInvoice, *, dry_run=True, force=False):
    """
    Prepare + build the plan. With INVOICE_WRITER_ENABLED off (current state) this
    NEVER writes to SOFTECH — returns the dry-run plan only.

    Live path (gate on, dry_run=False, OFF-PEAK): validate (SofTech save-time rules) →
    one Sybase transaction on the branch DB — allocate serial, INSERT stktransm +
    stktrans, verify-readback, COMMIT; rollback + push_failed on any mismatch.
    Validation errors refuse the push; warnings refuse unless force=True.
    """
    if invoice.softech_docnumber and invoice.status == 'finalized':
        return {'mode': 'idempotent', 'wrote_to_softech': False, 'already_finalized': True,
                'invoice_id': invoice.pk, 'docnumber': int(invoice.softech_docnumber)}
    if invoice.status == 'pushing':
        raise ValueError('الفاتورة قيد الترحيل بالفعل.')

    plan = build_plan(invoice)

    if not writer_enabled() or dry_run:
        logger.info('[invoices] DRY-RUN push invoice=%s (writer_enabled=%s) — no SOFTECH write',
                    invoice.pk, writer_enabled())
        return {'mode': 'dry_run', 'wrote_to_softech': False, 'invoice_id': invoice.pk, 'plan': plan}

    # ── VALIDATE (SofTech save-time rules) before any write ─────────────────────
    from . import validations
    v = validations.validate_invoice(invoice, live=True)
    if v['errors'] or (v['warnings'] and not force):
        invoice.erp_error = ('؛ '.join(e['message'] for e in v['errors'])[:1000]
                             if v['errors'] else 'توجد تحذيرات تتطلب التأكيد قبل الترحيل')
        invoice.save(update_fields=['erp_error', 'updated_at'])
        logger.info('[invoices] invoice=%s push BLOCKED by validation (errors=%d warnings=%d force=%s)',
                    invoice.pk, len(v['errors']), len(v['warnings']), force)
        return {'mode': 'validation_blocked', 'wrote_to_softech': False, 'ok': False,
                'blocked': True, 'invoice_id': invoice.pk, 'validation': v}

    # ── LIVE COMMIT (gated; run OFF-PEAK; TEST-INSTANCE-validated) ──────────────
    host = branch_host(invoice)
    if not host:
        raise ValueError('No branch db_host and no SYBASE_HOST fallback configured.')
    from config.sybase import get_branch_connection

    computed, header = compute(invoice)
    usercode = _default_usercode(invoice)
    branch = invoice.softech_branchcode
    store  = invoice.store_code or branch
    if not invoice.client_token:
        invoice.client_token = uuid.uuid4()
    invoice.status = 'pushing'
    invoice.save(update_fields=['status', 'client_token', 'updated_at'])

    conn = None
    try:
        conn = get_branch_connection(host, invoice.branch.db_port or 5000,
                                     invoice.branch.db_name or 'SOFTECHDB9', charset=_write_charset())
        # Idempotency = SofTech's own dup guard: same supplier + doccode + printed invoice no.
        # Only meaningful for PURCHASES (docnumber2 = supplier invoice no). Returns write
        # docnumber2 = reason code (not unique), so they rely on PG-status idempotency (the
        # softech_docnumber/finalized check at the top) instead.
        dn2 = _docnumber2(invoice)
        if dn2 and invoice.doc_kind == 'purchase':
            dup = _q1(conn, "SELECT docnumber FROM stktransm WHERE cust_branch_code=? AND doccode=? "
                            "AND docnumber2=?", [invoice.vendor.softech_personcode, invoice.softech_doccode, dn2])
            if dup:
                invoice.softech_docnumber = int(dup[0]); invoice.status = 'finalized'
                invoice.save(update_fields=['softech_docnumber', 'status', 'updated_at'])
                return {'mode': 'idempotent', 'wrote_to_softech': False, 'already_finalized': True,
                        'invoice_id': invoice.pk, 'docnumber': int(dup[0])}

        nowqty = read_stkbal(conn, branch, store, [c['_line'].item.softech_id for c in computed])
        ptclassifcode = read_supplier(conn, invoice.vendor.softech_personcode)['ptclassifcode']
        # UNCHAINED single-batch write: begin tran → inserts → verify → commit/rollback.
        w = _run_write_batch(conn, invoice, computed, header, ptclassifcode, usercode, nowqty, do_commit=True)
        if not (w['ok'] and w['committed']):
            invoice.status = 'push_failed'
            invoice.erp_error = f'verify/commit failed: {w}'
            invoice.save(update_fields=['status', 'erp_error', 'updated_at'])
            return {'mode': 'commit', 'wrote_to_softech': False, 'ok': False,
                    'invoice_id': invoice.pk, 'readback': w}
    except Exception as exc:
        if conn is None and _is_unreachable(exc):
            invoice.status = 'queued'
            invoice.erp_error = f'branch unreachable, queued: {exc}'
            invoice.save(update_fields=['status', 'erp_error', 'updated_at'])
            return {'mode': 'queued', 'wrote_to_softech': False, 'ok': False,
                    'queued': True, 'invoice_id': invoice.pk}
        invoice.status = 'push_failed'
        invoice.erp_error = str(exc)
        invoice.save(update_fields=['status', 'erp_error', 'updated_at'])
        logger.error('[invoices] invoice=%s push EXCEPTION (rolled back): %s', invoice.pk, exc)
        raise
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    invoice.softech_docnumber = w['docnumber']
    invoice.softech_docdate   = timezone.now().date()
    invoice.status            = 'finalized'
    invoice.erp_executed_at   = timezone.now()
    invoice.erp_payload       = plan
    invoice.erp_readback      = w
    invoice.erp_error         = ''
    invoice.save()
    logger.info('[invoices] invoice=%s FINALIZED → softech docnumber=%s', invoice.pk, w['docnumber'])
    return {'mode': 'commit', 'wrote_to_softech': True, 'ok': True,
            'invoice_id': invoice.pk, 'docnumber': w['docnumber'], 'readback': w}


# ── 3b. ROLLBACK PROBE — real inserts on the target DB, then ALWAYS rollback ───
def probe_invoice(invoice: SupplierInvoice, *, confirm=False):
    """
    Execute the real serial allocation + stktransm/stktrans INSERTs + verify-readback
    on the invoice's BRANCH DB, then ALWAYS roll back — zero residue. Reveals the
    exact NOT-NULL behaviour AND whether the insert trigger bumps the supplier
    counter (readback.trigger_bumped_counter). Requires confirm=True.
    """
    if not confirm:
        raise ValueError('probe_invoice requires confirm=True (executes real DML, then rolls back).')
    host = branch_host(invoice)
    if not host:
        raise ValueError('No branch db_host and no SYBASE_HOST fallback configured.')
    computed, header = compute(invoice)
    if not computed:
        raise ValueError('لا توجد أسطر مطابقة لترحيلها.')
    if not invoice.vendor or not invoice.vendor.softech_personcode:
        raise ValueError('المورد غير مربوط بكود SOFTECH.')

    from config.sybase import get_branch_connection
    usercode = _default_usercode(invoice)
    branch = invoice.softech_branchcode
    store  = invoice.store_code or branch
    res = {'mode': 'rollback_probe', 'committed': False, 'ok': False, 'branchcode': branch}
    conn = get_branch_connection(host, invoice.branch.db_port or 5000,
                                 invoice.branch.db_name or 'SOFTECHDB9', charset=_write_charset())
    try:
        nowqty = read_stkbal(conn, branch, store, [c['_line'].item.softech_id for c in computed])
        ptclassifcode = read_supplier(conn, invoice.vendor.softech_personcode)['ptclassifcode']
        # UNCHAINED single-batch write with do_commit=False → always rolls back.
        w = _run_write_batch(conn, invoice, computed, header, ptclassifcode, usercode, nowqty, do_commit=False)
        res['readback'] = w
        res['ok'] = w['ok']
        res['allocated_docnumber'] = w.get('docnumber')
        res['rolled_back'] = True
        logger.info('[invoices] PROBE ok=%s invoice=%s docnumber=%s lines=%s/%s err=%s — ROLLED BACK',
                    w['ok'], invoice.pk, w.get('docnumber'), w.get('lines_found'),
                    w.get('lines_expected'), w.get('err'))
    except Exception as exc:
        res['error'] = str(exc)
        logger.warning('[invoices] PROBE error invoice=%s: %s', invoice.pk, exc)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return res


# ── 4. RECONCILE — read-only verify a pushed doc still exists in SOFTECH ─────────
def reconcile(invoice: SupplierInvoice) -> dict:
    """
    READ-ONLY: read back the finalized purchase/return document from SOFTECH by its
    (branchcode, doccode, docnumber) and report:
      - present:  the stktransm header still exists (not deleted),
      - docvalue: its current header value (to spot post-edit),
      - lines:    line count,
      - returned: for a purchase, whether a return-to-supplier (doccode 120) references it.
    Never writes to SOFTECH. Stamps invoice.erp_readback['reconciled_at'] and, if the
    doc has vanished, flips status→push_failed with a note so the list surfaces it.
    """
    if invoice.status != 'finalized' or not invoice.softech_docnumber:
        raise ValueError('الفاتورة غير مُرحّلة إلى SOFTECH.')
    host = branch_host(invoice)
    if not host:
        raise ValueError('No branch db_host and no SYBASE_HOST fallback configured.')
    from config.sybase import get_branch_connection

    bc = invoice.softech_branchcode
    dc = invoice.softech_doccode
    dn = int(invoice.softech_docnumber)
    conn = get_branch_connection(host, invoice.branch.db_port or 5000,
                                 invoice.branch.db_name or 'SOFTECHDB9', charset=_write_charset())
    try:
        hdr = _q1(conn, "SELECT docvalue, docdate FROM stktransm "
                        "WHERE branchcode=? AND doccode=? AND docnumber=?", [bc, dc, dn])
        present = hdr is not None
        nlines = 0
        returned = False
        if present:
            nlines = int(_q1(conn, "SELECT COUNT(*) FROM stktrans "
                                   "WHERE branchcode=? AND doccode=? AND docnumber=?", [bc, dc, dn])[0])
            if invoice.doc_kind == 'purchase':
                r = _q1(conn, "SELECT COUNT(*) FROM stktrans "
                              "WHERE branchcode=? AND doccode='120' AND r_docnumber=?", [bc, dn])
                returned = bool(r and int(r[0]) > 0)
        result = {
            'present': present, 'docnumber': dn, 'doccode': dc, 'branchcode': bc,
            'docvalue': (float(hdr[0]) if present and hdr[0] is not None else None),
            'lines': nlines, 'returned': returned,
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # Persist the reconcile outcome on the invoice audit.
    rb = dict(invoice.erp_readback or {})
    rb['reconcile'] = {**result, 'at': timezone.now().isoformat()}
    invoice.erp_readback = rb
    if not present:
        invoice.status = 'push_failed'
        invoice.erp_error = f'المستند {dn} لم يعد موجوداً في SOFTECH (حُذف؟) — أعد الترحيل.'
        invoice.save(update_fields=['erp_readback', 'status', 'erp_error', 'updated_at'])
    else:
        invoice.save(update_fields=['erp_readback', 'updated_at'])
    return result
