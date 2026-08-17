"""
apps/pos_orders/writer.py

Transactional writer for the SOFTECH Indirect-POS pending order — modeled on
apps/discount_approvals/replication.py and apps/loyalty/pic_bridge.py
(INSERT + verify-readback), per docs/architecture/14_PHASE2_INDIRECT_POS_WRITER_DESIGN.md.

⚠️ SAFETY — NO SOFTECH WRITES YET ⚠️
There is no test instance, so this module DOES NOT write to SOFTECH. Every public
entry point is guarded by settings.POS_WRITER_ENABLED (default False). With the gate
OFF, `push_order` only PREPARES (computes values from the catalog mirror) and BUILDS
the payload + the exact SQL it WOULD execute, then returns it as a dry-run plan —
nothing is sent to Sybase. The live INSERT path is intentionally a single, clearly
marked block to be implemented + validated against SOFTECH_TEST_HOST later.
"""
import logging
import uuid
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from . import pricing
from .models import (
    SoftechSalesOrder, SoftechSalesOrderLine, SoftechSalesOrderPayment,
    PTCODE_CUSTOMER,
)

logger = logging.getLogger('elrezeiky.pos_orders')

# Sentinel header columns observed on real native pending rows (spec §6h golden template).
# Tuned to a contract/cash sale; refine the few unknowns (bonusqty/dblitemflag) on a test instance.
HEADER_SENTINELS = {
    'docnumber2': 0, 'origintaxp': 0, 'custdiscp': 0, 'specialdiscp': 0,
    'docvaluereturn': 0, 'saleprice_extrap': 0, 'origdoc': 5, 'mitemsys': 'AR',
    'fatstatuscode': '50', 'bcurrency': 1, 'bcrate': 1,
}


class WriterDisabled(RuntimeError):
    """Raised if a real SOFTECH write is attempted while the gate is off."""


def writer_enabled():
    return bool(getattr(settings, 'POS_WRITER_ENABLED', False))


def _write_charset():
    """Charset for the writeback connection (cp1256 → correct Arabic on INSERT)."""
    return getattr(settings, 'POS_WRITE_CHARSET', 'cp1256') or None


_UNREACHABLE_HINTS = ('connection timed out', 'connection refused', 'jz006', 'jz0',
                      'ioexception', 'connectexception', 'no route to host',
                      'network is unreachable', 'unknownhost', 'socket')


def _is_unreachable(exc):
    """True when the failure is a branch/SOFTECH connectivity problem (→ safe to QUEUE
    and retry), vs. a real data/logic error (→ push_failed). Connectivity errors never
    allocate a serial, so queuing them cannot duplicate a document."""
    msg = str(exc).lower()
    return any(h in msg for h in _UNREACHABLE_HINTS)


def softech_token(order):
    """
    Short idempotency marker stashed in stktransm5.vf2 (varchar(15)) linking the
    SOFTECH row back to our PG order. The full UUID lives in PG (client_token);
    vf2 only needs to fit and be unique per order, so 'POS<pk>' is enough.
    """
    return f'POS{order.pk}'[:15]


# ── 0b. LIVE READ — per-branch item price/tax + stkbal cost (SELECT only) ───────
def read_live_pricing(order: SoftechSalesOrder) -> dict:
    """
    READ-ONLY: fetch the authoritative per-branch values the cashier will see —
    items.itemsaleprice / itemsalestaxp and stkbal.nowcostprice (the running
    weighted-avg cost, spec §6d) — for every line's itemcode, from the order's
    BRANCH database. Returns {itemcode: {item_sale_price, sale_tax_pct, new_cost_price}}.
    Raises if the branch is unreachable (caller decides whether to fall back).
    Never writes to SOFTECH.
    """
    from config.sybase import get_branch_connection

    codes = [str(l.softech_itemcode).strip() for l in order.lines.all() if l.softech_itemcode]
    codes = list(dict.fromkeys(codes))   # de-dup, keep order
    if not codes or not order.branch or not order.branch.db_host:
        return {}

    conn = get_branch_connection(order.branch.db_host, order.branch.db_port or 5000,
                                 order.branch.db_name or 'SOFTECHDB9', charset=_write_charset())
    out = {}
    try:
        cur = conn.cursor()
        ph = ','.join('?' for _ in codes)
        cur.execute(
            f"SELECT itemcode, itemsaleprice, itemsalestaxp FROM items WHERE itemcode IN ({ph})", codes)
        for r in cur.fetchall():
            out[str(r[0]).strip()] = {
                'item_sale_price': r[1], 'sale_tax_pct': r[2], 'new_cost_price': 0,
            }
        cur.execute(
            f"SELECT itemcode, nowcostprice FROM stkbal "
            f"WHERE branchcode=? AND storecode=? AND itemcode IN ({ph})",
            [order.softech_branchcode, order.store_code] + codes)
        for r in cur.fetchall():
            code = str(r[0]).strip()
            if code in out:
                out[code]['new_cost_price'] = r[1]
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return out


# ── 1. PREPARE — compute all numeric fields ─────────────────────────────────────
def prepare_order(order: SoftechSalesOrder, tenders=None, live=False):
    """
    Compute line + header money fields and persist them. Returns the order (status
    -> 'ready').

    Source of price/tax/cost per line:
      live=False (default, offline-safe) → explicit line values, else the catalog
                 Item mirror. Used for tests, preview, and when the branch is offline.
      live=True  → read the BRANCH `items` row + `stkbal.nowcostprice` at this moment
                 (read_live_pricing). This is what the cashier will see; formulas are
                 identical. Raises if live is requested but the branch is unreachable.
    """
    if order.is_locked:
        raise ValueError('Order is locked (already pushed/settled/cancelled).')

    live_map = {}
    if live:
        live_map = read_live_pricing(order)
        if not live_map:
            raise ValueError('تعذّر قراءة الأسعار الحية من قاعدة بيانات الفرع.')

    computed_lines = []
    for line in order.lines.select_related('item').all():
        item = line.item
        src = live_map.get(str(line.softech_itemcode).strip()) if live else None
        if src:
            # authoritative live branch values (price/tax) + live stkbal cost
            item_sale_price = src['item_sale_price'] or 0
            sale_tax_pct    = src['sale_tax_pct'] or 0
            new_cost_price  = src['new_cost_price'] or 0
        else:
            # offline: prefer explicit line values, else the catalog mirror
            item_sale_price = line.item_sale_price or (item.pack_price if item else 0)
            sale_tax_pct    = line.sale_tax_pct    or (item.sale_tax_pct if item else 0)
            new_cost_price  = line.new_cost_price  or (item.cost_price if item else 0)

        c = pricing.compute_line(
            item_sale_price=item_sale_price, sale_tax_pct=sale_tax_pct,
            qty=line.qty, cust_discp=line.cust_discp, new_cost_price=new_cost_price,
        )
        line.item_sale_price     = item_sale_price
        line.sale_tax_pct        = sale_tax_pct
        line.trans_price         = c['trans_price']
        line.trans_price_total   = c['trans_price_total']
        line.item_sale_tax       = c['item_sale_tax']
        line.item_sale_price_tax = c['item_sale_price_tax']
        line.new_cost_price      = c['new_cost_price']
        if order.doc_kind == 'return' and order.return_of_invoice:
            line.return_of_invoice = order.return_of_invoice
        line.save()
        computed_lines.append(c)

    if not computed_lines:
        raise ValueError('لا يمكن تجهيز أمر بدون أصناف.')

    hdr = pricing.compute_header(computed_lines)
    doc_value = hdr['doc_value']

    # Resolve tenders: explicit arg wins; else reuse the order's existing payment
    # rows (fixes the case where /ready is called without tenders but rows exist);
    # else split_payment() falls back to a single default tender == doc_value.
    if tenders is None:
        existing = list(order.payments.values('pay_type', 'amount'))
        tenders = existing or None

    pay, patient, norm_tenders = pricing.split_payment(order.channel, doc_value, tenders)

    # Payments MUST balance the order (within a cent) — a half-paid push would
    # leave the cashier with an inconsistent document.
    total_tenders = sum((Decimal(str(t['amount'])) for t in norm_tenders), Decimal('0'))
    due = Decimal(str(doc_value)) - Decimal(str(order.change_discount or 0))   # net of خصم فكة
    if abs(total_tenders - due) > Decimal('0.01'):
        raise ValueError(
            f'مجموع طرق السداد ({total_tenders}) لا يساوي المطلوب ({due}).'
        )

    order.doc_value       = doc_value
    order.doc_value_gross = hdr['doc_value_gross']
    order.doc_value_cogs  = hdr['doc_value_cogs']
    order.doc_value_tax   = hdr['doc_value_tax']
    order.doc_value_pay   = pay
    order.patient_payment = patient
    if not order.client_token:
        order.client_token = uuid.uuid4()
    order.status = SoftechSalesOrder.STATUS_READY
    order.save()

    # Rebuild payment rows from the resolved tenders so PG always reflects the
    # computed split (keeps doc_value_pay/patient_payment and the rows consistent).
    order.payments.all().delete()
    # carry the SOFTECH tender extras (currency/rate/cheque/card/internal serial) when the
    # caller passed full tender dicts that align 1:1 with the resolved split.
    extras = tenders if isinstance(tenders, list) and len(tenders) == len(norm_tenders) else []
    for i, t in enumerate(norm_tenders):
        src = extras[i] if i < len(extras) else {}
        card = src.get('card_brand', src.get('card_type'))
        SoftechSalesOrderPayment.objects.create(
            order=order, pay_type=t['pay_type'], amount=t['amount'],
            ref_invoice=(order.return_of_invoice or None),
            currency=(src.get('currency') or 'L.E'),
            exchange_rate=(src.get('exchange_rate') or 1),
            card_brand=(int(card) if str(card or '').isdigit() else None),
            cheque_date=(src.get('cheque_date') or src.get('due_date') or None),
            cheque_card_no=(src.get('cheque_card_no') or ''),
            internal_payserial=(str(src.get('internal_payserial') or '')),
        )
    return order


# ── 2. BUILD PAYLOAD — the exact column→value maps + SQL we WOULD send ──────────
def build_payload(order: SoftechSalesOrder):
    """
    Build (and return) the table→rows payload and the SQL statements the live writer
    would execute, WITHOUT touching SOFTECH. Used for the dry-run plan / UI preview.
    docnumber/paymentsno are shown as placeholders (allocated atomically at push).
    """
    doccode  = order.softech_doccode
    counter  = order.softech_counter_column
    branch   = order.softech_branchcode
    store    = order.store_code

    header = dict(HEADER_SENTINELS)
    header.update({
        'branchcode': branch, 'doccode': doccode, 'docnumber': '<@docnumber>',
        'docdate': '<today>', 'storecode': store,
        'ptcode': PTCODE_CUSTOMER, 'ptclassifcode': order.softech_ptclassifcode,
        'phcode': order.softech_pic, 'cust_branch_code': order.cust_branch_code,
        'usercode': order.seller_usercode, 'cashiercode': order.cashier_usercode or order.seller_usercode,
        'docvalue': str(order.doc_value), 'docvalue1': str(order.doc_value_gross),
        'docvalue2': str(order.doc_value_cogs), 'docvalue3': str(order.doc_value_tax),
        'docvaluepay': str(order.doc_value_pay), 'patientpayment': str(order.patient_payment),
        'docvaluebc': str(order.doc_value), 'docvaluepaybc': str(order.doc_value_pay),
        'refdoctorcode': order.referral_doctor_code or None,
        'vf2': softech_token(order),   # short idempotency marker (vf2 is varchar(15))
    })

    lines = []
    for ln in order.lines.all():
        row = {
            'branchcode': branch, 'doccode': doccode, 'docnumber': '<@docnumber>',
            'docdate': '<today>', 'storecode': store,
            'itemcode': ln.softech_itemcode, 'transqty': str(ln.qty),
            'itemsaleprice': str(ln.item_sale_price), 'itemsaleprice_tax': str(ln.item_sale_price_tax),
            'itemsalestax': str(ln.item_sale_tax), 'transprice': str(ln.trans_price),
            'transprice_total': str(ln.trans_price_total), 'custdiscp': str(ln.cust_discp),
            'newcostprice': str(ln.new_cost_price),
        }
        if order.doc_kind == 'return':
            row['r_docnumber'] = str(order.return_of_invoice or 0)
        lines.append(row)

    payments = []
    for p in order.payments.all():
        payments.append({
            'branchcode': branch, 'doccode': doccode, 'docnumber': '<@docnumber>',
            'paymentsno': '<@paymentsno>', 'paymenttype': p.softech_paymenttype,
            'paymentvalue': str(p.amount),
            'ref_docnumber': str(order.return_of_invoice or '<@docnumber>'),
            'creditcardtype': p.card_brand, 'cheqdate': (str(p.cheque_date) if p.cheque_date else None),
        })

    sql = _build_sql(branch, counter, len(lines), len(payments))
    return {'header': header, 'lines': lines, 'payments': payments, 'sql': sql}


def _build_sql(branch, counter, n_lines, n_pay):
    """The exact statement sequence (documentation/preview — NOT executed here)."""
    stmts = [
        "BEGIN TRAN",
        f"UPDATE lastdocnumbers SET {counter} = {counter} + 1 WHERE branchcode='000'",
        f"SELECT @docnumber = {counter} FROM lastdocnumbers WHERE branchcode='000'",
        "INSERT INTO stktransm5 (...header columns...) VALUES (...)",
    ]
    for i in range(n_lines):
        stmts.append(f"INSERT INTO stktrans5 (...line {i+1}...) VALUES (...)")
    for i in range(n_pay):
        stmts += [
            "UPDATE lastdocnumbers SET paymentsno = paymentsno + 1 WHERE branchcode='000'",
            f"INSERT INTO branchesales5 (...tender {i+1}...) VALUES (..., paymentsno=@paymentsno, ...)",
        ]
    stmts += ["-- VERIFY-READBACK: re-SELECT header+lines+payments and assert match", "COMMIT"]
    return stmts


# ── 3. PUSH — guarded; NO SOFTECH WRITE while the gate is off ────────────────────
def push_order(order: SoftechSalesOrder, *, dry_run=True, live=False):
    """
    Prepare + build the payload. With POS_WRITER_ENABLED off (current state, no test
    instance) this NEVER writes to SOFTECH — it returns the dry-run plan only.

    The live path (gate on + test instance) will, inside ONE Sybase transaction on the
    branch DB: allocate the serial (UPDATE+read = row lock), INSERT the 3 tables,
    verify-readback, COMMIT — or rollback on any mismatch. That block is intentionally
    left unimplemented until it can be validated on SOFTECH_TEST_HOST.
    """
    # Idempotency: if this order already landed in SOFTECH, NEVER write it again — return
    # the existing docnumber. This is what prevents a retry/flush from duplicating a sale.
    if order.softech_docnumber and order.status in (
            SoftechSalesOrder.STATUS_PUSHED, SoftechSalesOrder.STATUS_SETTLED):
        return {'mode': 'idempotent', 'wrote_to_softech': False, 'already_pushed': True,
                'order_id': order.pk, 'docnumber': int(order.softech_docnumber)}
    # Allow retry from queued / push_failed too (a transient branch outage shouldn't strand it).
    if order.status not in (SoftechSalesOrder.STATUS_DRAFT, SoftechSalesOrder.STATUS_READY,
                            SoftechSalesOrder.STATUS_QUEUED, SoftechSalesOrder.STATUS_PUSH_FAILED):
        raise ValueError(f'Cannot push from status={order.status}')
    if order.status == SoftechSalesOrder.STATUS_DRAFT:
        prepare_order(order, live=live)

    plan = build_payload(order)

    if not writer_enabled() or dry_run:
        logger.info('[pos_orders] DRY-RUN push order=%s (writer_enabled=%s) — no SOFTECH write',
                    order.pk, writer_enabled())
        return {'mode': 'dry_run', 'wrote_to_softech': False, 'order_id': order.pk, 'plan': plan}

    # ── LIVE COMMIT PATH (gated by POS_WRITER_ENABLED; run OFF-PEAK) ─────────────
    # Same _execute_write as the validated rollback probe — but COMMIT on a clean
    # verify-readback. Allocation is the native read+1 pattern (triggers bump the
    # counters). On any mismatch/error → rollback + push_failed (never a partial row).
    if not order.branch or not order.branch.db_host:
        raise ValueError('Order branch has no db_host.')
    from config.sybase import get_branch_connection

    seller = (order.seller_usercode
              or getattr(settings, 'POS_DEFAULT_SELLER_USERCODE', '') or '1')
    order.status = SoftechSalesOrder.STATUS_PUSHING
    order.save(update_fields=['status', 'updated_at'])

    conn = None
    try:
        conn = get_branch_connection(order.branch.db_host, order.branch.db_port or 5000,
                                     order.branch.db_name or 'SOFTECHDB9', charset=_write_charset())
        # Crash-recovery: a previous attempt may have COMMITTED before PG saved the number.
        # Adopt the existing row (by our vf2 tag) instead of writing a duplicate. Done
        # OUTSIDE the transaction so the read can't leave a ResultSet open across DML.
        recovered = _pending_docnumber_by_vf2(conn, order)
        if recovered is not None:
            order.softech_docnumber = recovered
            order.status = SoftechSalesOrder.STATUS_PUSHED
            order.save(update_fields=['softech_docnumber', 'status', 'updated_at'])
            logger.warning('[pos_orders] order=%s recovered existing SOFTECH docnumber %s (vf2) — '
                           'no re-insert', order.pk, recovered)
            return {'mode': 'idempotent_recovered', 'wrote_to_softech': False,
                    'already_pushed': True, 'order_id': order.pk, 'docnumber': recovered}
        conn.begin()
        w = _execute_write(conn, order, seller)
        if not w['ok']:
            conn.rollback()
            order.status = SoftechSalesOrder.STATUS_PUSH_FAILED
            order.erp_error = f'verify-readback mismatch: {w}'
            order.save(update_fields=['status', 'erp_error', 'updated_at'])
            logger.error('[pos_orders] order=%s push FAILED (readback mismatch) — rolled back', order.pk)
            return {'mode': 'commit', 'wrote_to_softech': False, 'ok': False,
                    'order_id': order.pk, 'readback': w}
        conn.commit()                                 # ← the only place we persist to SOFTECH
    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        # Branch/SOFTECH unreachable → QUEUE (no serial was allocated, so no duplication
        # risk). A scheduler/flush retries it when the branch comes back. Any OTHER error
        # is a real failure → push_failed + raise.
        if conn is None and _is_unreachable(exc):
            order.status = SoftechSalesOrder.STATUS_QUEUED
            order.erp_error = f'branch unreachable, queued: {exc}'
            order.save(update_fields=['status', 'erp_error', 'updated_at'])
            logger.warning('[pos_orders] order=%s QUEUED (branch unreachable): %s', order.pk, exc)
            return {'mode': 'queued', 'wrote_to_softech': False, 'ok': False,
                    'queued': True, 'order_id': order.pk}
        order.status = SoftechSalesOrder.STATUS_PUSH_FAILED
        order.erp_error = str(exc)
        order.save(update_fields=['status', 'erp_error', 'updated_at'])
        logger.error('[pos_orders] order=%s push EXCEPTION (rolled back): %s', order.pk, exc)
        raise
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    order.softech_docnumber = w['docnumber']
    order.softech_docdate   = timezone.now().date()
    order.status            = SoftechSalesOrder.STATUS_PUSHED
    order.erp_executed_at   = timezone.now()
    order.erp_payload       = plan
    order.erp_readback      = w
    order.erp_error         = ''
    order.save()
    logger.info('[pos_orders] order=%s PUSHED → softech docnumber=%s', order.pk, w['docnumber'])
    return {'mode': 'commit', 'wrote_to_softech': True, 'ok': True,
            'order_id': order.pk, 'docnumber': w['docnumber'], 'readback': w, 'plan': plan}


# ── 3b. ROLLBACK PROBE — execute the REAL inserts on prod, then ROLL BACK ────────
# Validates the live write against production with ZERO persistence: no committed
# rows, no serial gap (the counter UPDATE is rolled back too), and it can never be
# settled. The danger in the whole flow is SETTLEMENT (stock/points/e-invoice) — a
# rolled-back probe never reaches it. See spec §6h.

class _Raw:
    """Marks a value as an inline SQL expression (e.g. a date), not a bound param."""
    def __init__(self, sql):
        self.sql = sql


_TODAY_MIDNIGHT = _Raw("convert(datetime, convert(char(8), getdate(), 112))")  # today 00:00
_NOW = _Raw("getdate()")


# Each statement runs on a FRESH cursor that is closed immediately — leaving a
# ResultSet open on the shared connection silently breaks subsequent DML inside the
# same transaction (observed in probe #1). The transaction lives on the connection,
# so per-statement cursors stay within it.
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


def _sql_literal(val):
    """Render a value as an inline SQL literal. (jConnect's parameterized INSERT
    path silently fails to land rows on this ASE; inline literals work. Our values
    are controlled numbers / short ascii codes, so this is safe — strings are still
    single-quote-escaped.)"""
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
    """INSERT one row using inline literals (see _sql_literal)."""
    cols = list(row.keys())
    vals = [_sql_literal(row[c]) for c in cols]
    _exec(conn, f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(vals)})")


def _header_row(order, docnumber, seller):
    f = lambda v: float(v or 0)
    # native header fields captured from the source order (contract/patient sales need
    # cust_professional set or the RETURN is rejected — see the 452775 fix).
    h = order.source_header_raw or {}
    return {
        'branchcode': order.softech_branchcode, 'doccode': order.softech_doccode,
        'docnumber': int(docnumber), 'docdate': _TODAY_MIDNIGHT,
        'docvalue': f(order.doc_value), 'cust_branch_code': order.cust_branch_code or None,
        'origintaxp': f(h.get('origintaxp')), 'custdiscp': f(h.get('custdiscp')),
        'cust_professional': (h.get('cust_professional') or None),
        'cust_branch_store': (h.get('cust_branch_store') or None),
        'specialdiscp': 0.0, 'storecode': order.store_code,
        'docvaluepay': f(order.doc_value_pay), 'fatstatuscode': '50',
        'ptcode': PTCODE_CUSTOMER, 'ptclassifcode': order.softech_ptclassifcode,
        'docvaluereturn': 0.0, 'fatcurrentstatus': '15', 'saleprice_extrap': 0.0,
        'usercode': seller or None, 'trans_time': _NOW, 'patientpayment': f(order.patient_payment),
        'docvalue1': f(order.doc_value_gross), 'docvalue2': f(order.doc_value_cogs),
        'docvalue3': f(order.doc_value_tax), 'phcode': order.softech_pic or None,
        'personnewbal': 0.0, 'docvaluebc': f(order.doc_value), 'bcrate': 1.0, 'bcurrency': 1,
        'docvaluepaybc': f(order.doc_value_pay),
        'cashiercode': (order.cashier_usercode or seller) or None, 'mitemsys': 'AR', 'origdoc': 5,
        'refdoctorcode': order.referral_doctor_code or None, 'vf2': softech_token(order),
    }


def _line_row(order, line, docnumber, seller):
    f = lambda v: float(v or 0)
    is_return = order.doc_kind == 'return' and order.return_of_invoice
    row = {
        'branchcode': order.softech_branchcode, 'doccode': order.softech_doccode,
        'docnumber': int(docnumber), 'docdate': _TODAY_MIDNIGHT, 'storecode': order.store_code,
        'itemcode': line.softech_itemcode, 'transqty': f(line.qty),
        'transprice': f(line.trans_price), 'newcostprice': f(line.new_cost_price),
        'itemsaleprice': f(line.item_sale_price), 'itemsalestax': f(line.item_sale_tax),
        'itemsaleprice_tax': f(line.item_sale_price_tax), 'pharmacydiscp': 0.0, 'additionaldiscp': 0.0,
        'transprice_total': f(line.trans_price_total), 'custdiscp': f(line.cust_discp),
        'specialdiscp': 0.0, 'bonusqty': f(line.bonus_qty), 'dblitemflag': 1,
        'usercode': seller or None, 'trans_time': _NOW, 'personcode': order.cust_branch_code or None,
        'r_docnumber': (int(order.return_of_invoice) if is_return else None),
        'retqty': 0.0,   # native pending = 0; settlement sets it to transqty. NEVER leave NULL
                         # (a NULL retqty makes the settled sale un-returnable — observed on 452775).
    }
    # Fresh picked-batch line: write the chosen expiry (clones carry it via source_raw instead).
    if line.item_expiry:
        row['itemexpirydate'] = _raw_value({'__dt__': f'{line.item_expiry:%Y-%m-%d} 00:00:00'})
    return row


# Columns we OVERRIDE when copying a cloned native line (new identity / fresh stamps);
# everything else in source_raw is reproduced verbatim (itemexpirydate, newqty,
# bonusqty, dblitemflag, suppliercode, custdiscp, prices, …).
_LINE_OVERRIDE = {'docnumber', 'docdate', 'trans_time', 'table_dumped', 'usercode'}


def _raw_value(v):
    """Render a stored source_raw value into an inline SQL literal (handles the
    {'__dt__': 'YYYY-MM-DD HH:MM:SS'} datetime marker)."""
    if isinstance(v, dict) and '__dt__' in v:
        return _Raw(f"convert(datetime, '{v['__dt__']}')")
    return _sql_literal(v)


def _line_row_from_raw(order, raw, docnumber, seller):
    """Build a stktrans5 line from a cloned native row — keeping the CRITICAL batch
    field (itemexpirydate) and the native-set fields (newqty, bonusqty, dblitemflag,
    suppliercode…) so the duplicate is returnable. Curated + type-coerced (a blind
    SELECT* copy hit VARCHAR→DECIMAL coercion on this ASE)."""
    def num(k):
        v = raw.get(k)
        return None if v in (None, '') else float(v)

    exp = raw.get('itemexpirydate')   # {'__dt__': 'YYYY-MM-DD HH:MM:SS'} or None
    return {
        'branchcode': order.softech_branchcode, 'doccode': order.softech_doccode,
        'docnumber': int(docnumber), 'docdate': _TODAY_MIDNIGHT, 'storecode': order.store_code,
        'itemcode': str(raw.get('itemcode') or ''),
        'transqty': num('transqty'), 'transprice': num('transprice'),
        'newqty': num('newqty'), 'newcostprice': num('newcostprice'),
        'itemexpirydate': (_raw_value(exp) if exp else None),     # ← the batch (was the bug)
        'itemsaleprice': num('itemsaleprice'), 'itemsalestax': num('itemsalestax'),
        'itemsaleprice_tax': num('itemsaleprice_tax'), 'pharmacydiscp': num('pharmacydiscp'),
        'additionaldiscp': num('additionaldiscp'), 'transprice_total': num('transprice_total'),
        'origintaxp': num('origintaxp'), 'custdiscp': num('custdiscp'), 'specialdiscp': num('specialdiscp'),
        'bonusqty': num('bonusqty'), 'dblitemflag': int(raw.get('dblitemflag') or 1),
        'r_docnumber': (num('r_docnumber') or 0), 'r_docdate': _Raw("convert(datetime, '1900-01-01')"),
        'saleprice_extrap': (num('saleprice_extrap') or 0),
        'suppliercode': str(raw.get('suppliercode') or '0'),
        's_doccode': str(raw.get('s_doccode') or '000'),
        'usercode': seller or None, 'trans_time': _NOW,
        'personcode': (str(raw.get('personcode')).strip() or None) if raw.get('personcode') is not None else None,
        'retqty': (num('retqty') or 0),
    }


def _payment_row(order, p, docnumber, pno, seller):
    is_return = order.doc_kind == 'return' and order.return_of_invoice
    rate = float(p.exchange_rate or 1) or 1.0
    amt = float(p.amount or 0)
    # currency label → bcurrency code (1 = local L.E); foreign currencies keep code 0 until
    # the per-install currency table is mapped — value still recorded in paymentvaluebc.
    bcurrency = 1 if (p.currency or 'L.E').upper() in ('L.E', 'LE', 'EGP', '') else 0
    row = {
        'branchcode': order.softech_branchcode, 'doccode': order.softech_doccode,
        'docnumber': int(docnumber), 'docdate': _TODAY_MIDNIGHT, 'paymentsno': int(pno),
        'paymenttype': p.softech_paymenttype, 'paymentvalue': amt,
        'ref_docnumber': int(order.return_of_invoice) if is_return else int(docnumber),
        'usercode': seller or '1', 'trans_time': _NOW,
        'bcurrency': bcurrency, 'bcrate': rate, 'paymentvaluebc': round(amt / rate, 4),
    }
    if p.card_brand is not None:
        row['creditcardtype'] = int(p.card_brand)
    if p.cheque_date:
        row['cheqdate'] = _raw_value({'__dt__': f'{p.cheque_date:%Y-%m-%d} 00:00:00'})
    if (p.cheque_card_no or '').strip():
        row['comment'] = p.cheque_card_no.strip()          # cheque/card/points number
    if (p.internal_payserial or '').strip():
        row['localpayment_sno'] = int(p.internal_payserial) if p.internal_payserial.isdigit() else None
    return row


def _companies_row(order, raw, docnumber):
    """companiesitems5 (insurance/patient claim) built from the source order's row.
    Keeps patient IDs + claim fields; overrides identity/stamps. (patientname is
    Arabic — jConnect may garble it on write; the return keys on patientno/
    membershipno so it still works. cp1256 write-encoding is a separate TODO.)"""
    g = raw.get
    return {
        'branchcode': order.softech_branchcode, 'docnumber': int(docnumber),
        'docdate': _TODAY_MIDNIGHT, 'doccode': order.softech_doccode,
        'cdate': (_raw_value(g('cdate')) if g('cdate') else _TODAY_MIDNIGHT),
        'patientname': g('patientname'), 'patientno': g('patientno'),
        'financialno': g('financialno'), 'fileno': g('fileno'),
        'roshettano': g('roshettano'), 'membershipno': g('membershipno'),
        'deptname': g('deptname'), 'patientnationality': g('patientnationality'),
        'relativedegree': g('relativedegree'), 'comment': g('comment'),
        'examdate': (_raw_value(g('examdate')) if g('examdate') else None),
        'hi_typecode': g('hi_typecode'), 'table_dumped': _NOW, 'vf1': g('vf1'),
    }


def _cc_row(order, raw, docnumber, credit_pno, seller):
    """branchesalescc5 (cost-center / credit record) — paymentsno points at the
    credit tender's allocated serial in THIS order."""
    return {
        'branchcode': order.softech_branchcode, 'doccode': order.softech_doccode,
        'docnumber': int(docnumber), 'docdate': _TODAY_MIDNIGHT,
        'costcentercode': (raw.get('costcentercode') or '00/000'),
        'paymentsno': int(credit_pno) if credit_pno else 0,
        'usercode': seller or '1', 'moneyvalue': float(raw.get('moneyvalue') or 0),
    }


def _pending_docnumber_by_vf2(conn, order):
    """
    Crash-recovery idempotency. If a PRIOR push committed the SOFTECH row but the
    process died before we saved softech_docnumber, the order still carries our unique
    vf2 tag ('POS<pk>') in stktransm5. Finding it here lets us ADOPT that docnumber
    instead of inserting a second pending row (a duplicate with a fresh serial).
    Param SELECT is safe on this ASE; the tag never collides with native rows.
    """
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT docnumber FROM stktransm5 WHERE branchcode=? AND doccode=? AND vf2=?",
            [order.softech_branchcode, order.softech_doccode, _vf2_tag(order)])
        rows = cur.fetchall()
    finally:
        cur.close()
    return int(rows[0][0]) if rows else None


def _execute_write(conn, order, seller):
    """
    Run the full pending-order write INSIDE an already-open transaction (caller owns
    begin/commit/rollback): native serial allocation → stktransm5 + stktrans5 +
    branchesales5 INSERTs → verify-readback. Returns a result dict (docnumber, ok,
    readback fields). Used identically by probe_order (always rolls back) and the
    committed push path — so the rollback probe is a true rehearsal of the commit.
    """
    counter = order.softech_counter_column
    # NATIVE allocation: read current (HOLDLOCK) + insert current+1; INSERT triggers bump the counters.
    docnumber = int(_q1(conn, f"SELECT {counter} FROM lastdocnumbers HOLDLOCK WHERE branchcode='000'")[0]) + 1

    _exec_insert(conn, 'stktransm5', _header_row(order, docnumber, seller))
    for ln in order.lines.all():
        if ln.source_raw:
            # cloned line → reproduce the native row VERBATIM (keeps itemexpirydate,
            # newqty, bonusqty, dblitemflag, suppliercode…) so it is returnable.
            row = _line_row_from_raw(order, ln.source_raw, docnumber, seller)
        else:
            row = _line_row(order, ln, docnumber, seller)
        _exec_insert(conn, 'stktrans5', row)
    pnos = []
    tender_pnos = []   # (pay_type, paymentsno) — used to link branchesalescc5 to the credit tender
    for p in order.payments.all():
        pno = int(_q1(conn, "SELECT paymentsno FROM lastdocnumbers HOLDLOCK WHERE branchcode='000'")[0]) + 1
        pnos.append(pno)
        tender_pnos.append((p.pay_type, pno))
        _exec_insert(conn, 'branchesales5', _payment_row(order, p, docnumber, pno, seller))

    # Contract/insurance companions (only when cloned from a contract order that has
    # them) — so the settled duplicate is RETURNABLE without manual patching.
    if order.source_companies_raw:
        _exec_insert(conn, 'companiesitems5', _companies_row(order, order.source_companies_raw, docnumber))
    if order.source_cc_raw:
        credit_pno = next((pno for pt, pno in tender_pnos if pt == 'credit'),
                          (tender_pnos[0][1] if tender_pnos else None))
        for ccraw in order.source_cc_raw:
            _exec_insert(conn, 'branchesalescc5', _cc_row(order, ccraw, docnumber, credit_pno, seller))

    hdr = _q1(conn, "SELECT branchcode, doccode, docnumber, docvalue, docvaluepay, "
                    "ptclassifcode, trans_time FROM stktransm5 "
                    "WHERE branchcode=? AND doccode=? AND docnumber=?",
              [order.softech_branchcode, order.softech_doccode, docnumber])
    nlines = int(_q1(conn, "SELECT COUNT(*) FROM stktrans5 WHERE branchcode=? AND doccode=? AND docnumber=?",
                     [order.softech_branchcode, order.softech_doccode, docnumber])[0])
    npay = int(_q1(conn, "SELECT COUNT(*) FROM branchesales5 WHERE branchcode=? AND doccode=? AND docnumber=?",
                   [order.softech_branchcode, order.softech_doccode, docnumber])[0])
    lines_exp = int(_q1(conn, "SELECT COUNT(*) FROM stktrans5 WHERE branchcode=? AND doccode=? "
                              "AND docnumber=? AND itemexpirydate IS NOT NULL",
                        [order.softech_branchcode, order.softech_doccode, docnumber])[0])
    # contract companions (only when this order carries them)
    ncomp = int(_q1(conn, "SELECT COUNT(*) FROM companiesitems5 WHERE branchcode=? AND docnumber=?",
                    [order.softech_branchcode, docnumber])[0]) if order.source_companies_raw else 0
    ncc = int(_q1(conn, "SELECT COUNT(*) FROM branchesalescc5 WHERE branchcode=? AND doccode=? AND docnumber=?",
                  [order.softech_branchcode, order.softech_doccode, docnumber])[0]) if order.source_cc_raw else 0
    companions_ok = (ncomp == (1 if order.source_companies_raw else 0)
                     and ncc == len(order.source_cc_raw or []))
    ok = bool(hdr is not None and nlines == order.lines.count()
              and npay == order.payments.count() and companions_ok)
    return {
        'docnumber': docnumber, 'paymentsnos': pnos, 'ok': ok,
        'lines_found': nlines, 'lines_expected': order.lines.count(),
        'lines_with_expiry': lines_exp,                       # ← must equal lines_found for returnability
        'payments_found': npay, 'payments_expected': order.payments.count(),
        'companiesitems5_found': ncomp, 'branchesalescc5_found': ncc,
        'header': [str(x) for x in hdr] if hdr else None,
        'trans_time_stamped': bool(hdr and hdr[6] is not None),
    }


def probe_order(order: SoftechSalesOrder, *, confirm=False, live=True):
    """
    ROLLBACK PROBE against the order's BRANCH DB. Executes the real serial
    allocation + stktransm5/stktrans5/branchesales5 INSERTs + a verify-readback,
    then ALWAYS rolls back. Nothing is committed. Requires confirm=True.
    Returns a result dict (ok, allocated_docnumber, readback, error).
    """
    if not confirm:
        raise ValueError('probe_order requires confirm=True (executes real prod DML, then rolls back).')
    if not order.branch or not order.branch.db_host:
        raise ValueError('Order branch has no db_host.')
    if order.status == SoftechSalesOrder.STATUS_DRAFT:
        prepare_order(order, live=live)
    if not order.lines.exists():
        raise ValueError('Order has no lines.')

    from config.sybase import get_branch_connection

    seller = (order.seller_usercode
              or getattr(settings, 'POS_DEFAULT_SELLER_USERCODE', '') or '1')
    counter = order.softech_counter_column
    res = {'mode': 'rollback_probe', 'committed': False, 'ok': False,
           'branch': order.softech_branchcode}

    conn = get_branch_connection(order.branch.db_host, order.branch.db_port or 5000,
                                 order.branch.db_name or 'SOFTECHDB9', charset=_write_charset())
    try:
        conn.begin()                                  # autocommit OFF — one transaction
        w = _execute_write(conn, order, seller)       # identical to the commit path
        res['allocated_docnumber'] = w['docnumber']
        res['readback'] = w
        res['ok'] = w['ok']
        logger.info('[pos_orders] PROBE ok=%s order=%s docnumber=%s lines=%s/%s pay=%s/%s — ROLLING BACK',
                    w['ok'], order.pk, w['docnumber'], w['lines_found'], w['lines_expected'],
                    w['payments_found'], w['payments_expected'])
    except Exception as exc:
        res['error'] = str(exc)
        logger.warning('[pos_orders] PROBE error order=%s: %s', order.pk, exc)
    finally:
        try:
            conn.rollback()                            # ALWAYS — discard everything
            res['rolled_back'] = True
        except Exception as exc:
            res['rollback_error'] = str(exc)
        try:
            conn.close()
        except Exception:
            pass
    return res


# ── 4. CANCEL / cleanup (mirrors the cashier Delete — spec §6k) ──────────────────
def _delete_pending_from_softech(order):
    """
    DELETE the pending rows (branchesales5 → stktrans5 → stktransm5) by
    (branchcode, doccode, docnumber) — the same operation as the cashier's Delete
    button. No triggers fire on delete and there is no archive (§6k), so it is
    side-effect-free. Inline literals (param DML is unreliable on this ASE).

    Guards: the header must STILL be present in stktransm5 (else it was settled or
    already deleted — we must not relabel a settled order as cancelled); and all
    three tables must be empty after, or we rollback. Commits on success.
    """
    if not order.branch or not order.branch.db_host:
        raise ValueError('Order branch has no db_host.')
    from config.sybase import get_branch_connection

    bcl  = _sql_literal(order.softech_branchcode)
    dcl  = _sql_literal(order.softech_doccode)
    docn = int(order.softech_docnumber)
    where = f"WHERE branchcode={bcl} AND doccode={dcl} AND docnumber={docn}"

    conn = get_branch_connection(order.branch.db_host, order.branch.db_port or 5000,
                                 order.branch.db_name or 'SOFTECHDB9', charset=_write_charset())
    try:
        conn.begin()
        present = int(_q1(conn, f"SELECT COUNT(*) FROM stktransm5 {where}")[0])
        if present == 0:
            conn.rollback()
            raise ValueError('الأمر لم يعد معلّقاً في SOFTECH (تم تحصيله أو حذفه) — شغّل التسوية.')
        for tbl in ('branchesales5', 'stktrans5', 'stktransm5'):
            _exec(conn, f"DELETE FROM {tbl} {where}")
        remain = int(_q1(conn, f"SELECT COUNT(*) FROM stktransm5 {where}")[0])
        if remain != 0:
            conn.rollback()
            raise RuntimeError('فشل حذف الأمر المعلّق من SOFTECH (still present after delete).')
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


def probe_cancel(host, port, dbname, branchcode, doccode, docnumber, *, confirm=False):
    """
    ROLLBACK PROBE of the cancel/delete: DELETE the pending rows for an EXISTING
    order then ROLL BACK — proves the delete works (rows would go to 0) WITHOUT
    actually removing the live row. Zero persistence. Requires confirm=True.
    Returns a result dict (before_counts, after_counts_in_txn, ok).
    """
    if not confirm:
        raise ValueError('probe_cancel requires confirm=True (executes a real DELETE, then rolls back).')
    from config.sybase import get_branch_connection

    where = f"WHERE branchcode={_sql_literal(branchcode)} AND doccode={_sql_literal(doccode)} AND docnumber={int(docnumber)}"
    tables = ('stktransm5', 'stktrans5', 'branchesales5')
    res = {'mode': 'cancel_rollback_probe', 'committed': False, 'ok': False,
           'branchcode': branchcode, 'doccode': doccode, 'docnumber': int(docnumber)}

    conn = get_branch_connection(host, port or 5000, dbname or 'SOFTECHDB9')
    try:
        conn.begin()
        before = {t: int(_q1(conn, f"SELECT COUNT(*) FROM {t} {where}")[0]) for t in tables}
        res['before_counts'] = before
        for t in ('branchesales5', 'stktrans5', 'stktransm5'):   # delete order (no FKs/triggers anyway)
            _exec(conn, f"DELETE FROM {t} {where}")
        after = {t: int(_q1(conn, f"SELECT COUNT(*) FROM {t} {where}")[0]) for t in tables}
        res['after_counts_in_txn'] = after
        # valid only if the header existed and all rows are gone within the txn
        res['ok'] = bool(before['stktransm5'] > 0 and after['stktransm5'] == 0
                         and after['stktrans5'] == 0 and after['branchesales5'] == 0)
        logger.info('[pos_orders] CANCEL-PROBE ok=%s doc=%s before=%s after=%s — ROLLING BACK',
                    res['ok'], docnumber, before, after)
    except Exception as exc:
        res['error'] = str(exc)
        logger.warning('[pos_orders] CANCEL-PROBE error doc=%s: %s', docnumber, exc)
    finally:
        try:
            conn.rollback()
            res['rolled_back'] = True
        except Exception as exc:
            res['rollback_error'] = str(exc)
        try:
            conn.close()
        except Exception:
            pass
    return res


def cancel_order(order: SoftechSalesOrder):
    """
    Cancel an order. If it was pushed to SOFTECH (has a docnumber and is still
    pending), DELETE its pending rows there first (cashier-style Delete, §6k) — this
    requires POS_WRITER_ENABLED. Orders never pushed just flip PG status. Settled
    orders cannot be cancelled (issue a return instead).
    """
    if order.status == SoftechSalesOrder.STATUS_SETTLED:
        raise ValueError('Settled orders cannot be cancelled — issue a return instead.')
    if order.status == SoftechSalesOrder.STATUS_CANCELLED:
        return order  # idempotent

    was_pushed = bool(order.softech_docnumber) and order.status in (
        SoftechSalesOrder.STATUS_PUSHING,
        SoftechSalesOrder.STATUS_PUSHED,
        SoftechSalesOrder.STATUS_PUSH_FAILED,
    )
    if was_pushed:
        if not writer_enabled():
            raise WriterDisabled(
                'Order exists in SOFTECH — enable POS_WRITER_ENABLED to delete its pending rows.')
        _delete_pending_from_softech(order)
        logger.info('[pos_orders] order=%s pending rows DELETED from SOFTECH (docnumber=%s)',
                    order.pk, order.softech_docnumber)

    order.status = SoftechSalesOrder.STATUS_CANCELLED
    order.save(update_fields=['status', 'updated_at'])
    return order
