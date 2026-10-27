"""
apps/vouchers/coupon_push.py

Stocks a generated CouponBatch into SOFTECH — replacing the WorkBench DataLoad robot —
through the EXISTING supplier-invoice writer (apps/invoices/writer.py). No new write path.

One batch = two final purchase documents (doccode 10) from supplier 1268 into HQ store 100,
one qty-1 line per serial (serial → stktrans.item_partno, per-serial expiry), usercode 1509:
  * POINTS leg  — item 102230, price 400  (reference doc 100/10/63944)
  * SERVED leg  — item 118639, price −50, cost 0  (reference doc 100/10/63945)
The exact native values beyond the generic purchase template (custdiscp, bonusqty,
pharmacydiscp, the served header's status/docvalue1) are copied from those reference docs
and verified column-by-column by probe_batch() — a real insert that is ALWAYS rolled back.

Safety (CLAUDE.md rule 3 — never double-post):
  * each document gets its own supplier invoice no (docnumber2 = ddmmyyyyNN), allocated
    once and stored on the SupplierInvoice, so a retry is caught by the writer's SofTech
    dup-guard (supplier + doccode + docnumber2) and by its finalized/pushing status checks;
  * a finalized leg is never pushed again; a half-stocked batch resumes with the other leg;
  * live writes need settings.INVOICE_WRITER_ENABLED (default False) — otherwise dry-run.
Spec: docs/architecture/SOFTECH_GIFT_VOUCHER_STOCKING.md
"""
import datetime as dt
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import coupons

logger = logging.getLogger('elrezeiky.vouchers')

LEGS = ('points', 'served')

# Columns that legitimately differ between our insert and the reference document.
IGNORE_HEADER = {'docnumber', 'docdate', 'docwritedate', 'trans_time', 'table_dumped',
                 'docnumber2', 'docpaydue', 'personnewbal'}
IGNORE_LINE = {'docnumber', 'docdate', 'trans_time', 'table_dumped', 'itemexpirydate',
               'item_partno', 'newqty', 'r_docdate', 's_docdate'}


def usercode():
    return str(getattr(settings, 'COUPON_USERCODE', '1509'))


def leg_item(leg):
    return coupons.points_item() if leg == 'points' else coupons.served_item()


def leg_price(leg):
    """Public price of one coupon line on the leg (= the item master price)."""
    if leg == 'points':
        return float(getattr(settings, 'COUPON_POINTS_PRICE', 400))
    return float(getattr(settings, 'COUPON_SERVED_PRICE', -50))


def leg_cost(leg):
    """Net purchase price per coupon: points 400, served 0."""
    return leg_price(leg) if leg == 'points' else 0.0


def reference_doc(leg):
    if leg == 'points':
        return int(getattr(settings, 'COUPON_REF_POINTS_DOC', 63944))
    return int(getattr(settings, 'COUPON_REF_SERVED_DOC', 63945))


def leg_extras(leg, n_lines):
    """(header_extra, line_extra) — native values beyond the generic purchase template,
    as stored on the reference docs 63944 (points) / 63945 (served)."""
    # cashiercode = the operator's usercode: the native save sends it (the insert trigger
    # leaves it NULL — first --probe diff, 2026-10-06).
    if leg == 'points':
        return {'cashiercode': usercode()}, {'custdiscp': 1.0}
    price = leg_price(leg)
    header = {'cashiercode': usercode(), 'fatstatuscode': '30', 'fatcurrentstatus': '90',
              'docvalue1': round(price * n_lines, 4)}
    line = {'custdiscp': 1.0, 'bonusqty': price, 'pharmacydiscp': 100.0}
    return header, line


# ── PG side: the two SupplierInvoices of a batch ───────────────────────────────
def _vendor():
    from apps.invoices.models import VendorProfile
    v = VendorProfile.objects.filter(softech_personcode=coupons.supplier_code()).first()
    if v is None:
        v = VendorProfile.objects.create(softech_personcode=coupons.supplier_code(),
                                         name='هدايا الاداره لخدمة العملاء')
    return v


def _branch():
    from apps.branches.models import Branch
    b = Branch.objects.filter(softech_branch_id=coupons.hq_branch()).first()
    if b is None:
        raise ValueError(f'No Branch with softech_branch_id={coupons.hq_branch()} (HQ).')
    return b


def _item(leg):
    from apps.catalog.models import Item
    code = leg_item(leg)
    item = Item.objects.filter(softech_id=code).first()
    if item is None:
        raise ValueError(f'Item {code} is not in the catalog mirror — run the item sync first.')
    return item


@transaction.atomic
def ensure_invoices(batch, created_by=None):
    """Create (once) the batch's two SupplierInvoices — status 'confirmed', one line per
    serial in serial order. Idempotent; never touches a pushed invoice."""
    from apps.invoices.models import InvoiceLine, SupplierInvoice
    from .models import CouponBatch

    batch = CouponBatch.objects.select_for_update().get(pk=batch.pk)
    if batch.status == 'void':
        raise ValueError('batch is void')
    serials = list(batch.serials.order_by('number'))
    if not serials:
        raise ValueError('batch has no serials')
    vendor, branch = _vendor(), _branch()
    for leg in LEGS:
        field = f'{leg}_invoice'
        if getattr(batch, field + '_id'):
            continue
        item = _item(leg)
        inv = SupplierInvoice.objects.create(
            branch=branch, vendor=vendor, doc_kind='purchase', status='confirmed',
            supplier_name=vendor.name, invoice_date=timezone.localdate(), created_by=created_by,
            notes=f'[coupon batch #{batch.pk} — {leg} leg {leg_item(leg)}, '
                  f'serials {batch.serial_from}–{batch.serial_to}]')
        exp_field = f'{leg}_expiry'
        InvoiceLine.objects.bulk_create([
            InvoiceLine(invoice=inv, item=item, manual_name=item.name, quantity=1,
                        public_price=leg_price(leg), unit_price=leg_cost(leg),
                        line_total=leg_cost(leg), batch_number=c.serial,
                        expiry_date=getattr(c, exp_field).isoformat(), is_confirmed=True, order=i)
            for i, c in enumerate(serials, start=1)])
        setattr(batch, field, inv)
    batch.save(update_fields=['points_invoice', 'served_invoice', 'updated_at'])
    return batch


def _invoices(batch):
    return {'points': batch.points_invoice, 'served': batch.served_invoice}


# ── supplier invoice no (docnumber2 = ddmmyyyyNN) ──────────────────────────────
def docnumber2_base(day):
    """ddmmyyyy as the house pattern stores it (no leading zero: 5/10/2026 → 5102026)."""
    return int(day.strftime('%d%m%Y'))


def assign_docnumber2(batch, conn, day=None):
    """Give each unpushed leg its own docnumber2 = ddmmyyyy·100 + NN, above every number
    already used that day for supplier 1268 — in SOFTECH (read-only) and in our own
    not-yet-pushed invoices. Stored once; never changed after a push."""
    from apps.invoices.models import SupplierInvoice

    day = day or timezone.localdate()
    lo = docnumber2_base(day) * 100
    hi = lo + 99
    cur = conn.cursor()
    cur.execute("SELECT max(docnumber2) FROM stktransm WHERE doccode='10' AND cust_branch_code=? "
                "AND docnumber2 BETWEEN ? AND ?", [coupons.supplier_code(), lo, hi])
    row = cur.fetchone()
    top = int(float(row[0])) if row and row[0] is not None else lo
    for n in (SupplierInvoice.objects.filter(vendor__softech_personcode=coupons.supplier_code())
              .exclude(invoice_number='').values_list('invoice_number', flat=True)):
        if n.isdigit() and lo <= int(n) <= hi:
            top = max(top, int(n))
    for leg, inv in _invoices(batch).items():
        if inv is None or inv.invoice_number or inv.status in ('pushing', 'finalized'):
            continue
        top += 1
        if top > hi:
            raise ValueError(f'no free supplier invoice number left for {day} (NN > 99)')
        inv.invoice_number = str(top)
        inv.save(update_fields=['invoice_number', 'updated_at'])
    return {leg: (inv.invoice_number if inv else None) for leg, inv in _invoices(batch).items()}


# ── rollback probe + column diff vs the reference docs ─────────────────────────
def _norm(v):
    if v is None:
        return None
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()[:10]
    s = str(v).strip()
    try:
        return round(float(s), 3)
    except ValueError:
        pass
    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
        return s[:10]
    return s


def diff_rows(ours, ref, ignore):
    """[(column, ours, reference)] for every compared column that differs."""
    out = []
    for col in ref:
        if col in ignore:
            continue
        a, b = _norm((ours or {}).get(col)), _norm(ref.get(col))
        if a != b:
            out.append((col, (ours or {}).get(col), ref.get(col)))
    return out


def _read_reference(conn, docnumber):
    def one(sql, params):
        cur = conn.cursor()
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        r = cur.fetchone()
        return dict(zip(cols, r)) if r else None
    hdr = one("SELECT * FROM stktransm WHERE branchcode=? AND doccode='10' AND docnumber=?",
              [coupons.hq_branch(), docnumber])
    line = one("SELECT * FROM stktrans WHERE branchcode=? AND doccode='10' AND docnumber=? AND dblitemflag=1",
               [coupons.hq_branch(), docnumber])
    return hdr, line


def probe_batch(batch):
    """Rollback rehearsal of both legs on HQ: real INSERTs of the full 200-line documents
    → read back → ROLLBACK (zero residue), then diff header + line 1 against the reference
    docs 63944 / 63945. Nothing is kept in SOFTECH."""
    from config.sybase import get_sybase_connection
    from apps.invoices import writer

    batch = ensure_invoices(batch)
    conn = get_sybase_connection()
    try:
        assign_docnumber2(batch, conn)
        refs = {leg: _read_reference(conn, reference_doc(leg)) for leg in LEGS}
    finally:
        conn.close()
    report = {}
    for leg, inv in _invoices(batch).items():
        inv.refresh_from_db()
        n = inv.lines.count()
        h_extra, l_extra = leg_extras(leg, n)
        res = writer.probe_invoice(inv, confirm=True, usercode=usercode(), header_extra=h_extra,
                                   line_extra=l_extra, capture=True)
        rb = res.get('readback') or {}
        ref_h, ref_l = refs[leg]
        lines = rb.get('full_lines') or []
        report[leg] = {
            'ok': bool(res.get('ok')), 'error': res.get('error'), 'rolled_back': res.get('rolled_back'),
            'reference_doc': reference_doc(leg), 'lines_found': rb.get('lines_found'),
            'lines_expected': rb.get('lines_expected'),
            'header_diff': diff_rows(rb.get('full_header'), ref_h or {}, IGNORE_HEADER),
            'line_diff': diff_rows(lines[0] if lines else None, ref_l or {}, IGNORE_LINE),
            'serials_ok': [l.get('item_partno') for l in lines] ==
                          list(inv.lines.order_by('order').values_list('batch_number', flat=True)),
        }
    return report


# ── push (live only with INVOICE_WRITER_ENABLED) ───────────────────────────────
def push_batch(batch, *, commit=False, force=False):
    """Push both legs. Without commit (or with the writer gate off) returns the dry-run
    plans only. A finalized leg is skipped, so re-running resumes a half-stocked batch."""
    from config.sybase import get_sybase_connection
    from apps.invoices import writer

    if commit and not writer.writer_enabled():
        raise ValueError('INVOICE_WRITER_ENABLED is off — nothing can be written to SOFTECH.')
    batch = ensure_invoices(batch)
    if commit:
        conn = get_sybase_connection()
        try:
            assign_docnumber2(batch, conn)
        finally:
            conn.close()
    results = {}
    for leg, inv in _invoices(batch).items():
        inv.refresh_from_db()
        if inv.status == 'finalized':
            results[leg] = {'mode': 'already_finalized', 'docnumber': int(inv.softech_docnumber)}
            continue
        h_extra, l_extra = leg_extras(leg, inv.lines.count())
        res = writer.push_final(inv, dry_run=not commit, force=force, usercode=usercode(),
                                header_extra=h_extra, line_extra=l_extra)
        results[leg] = res
        if res.get('wrote_to_softech') or res.get('already_finalized'):
            inv.refresh_from_db()
            _mark_leg_stocked(batch, leg, inv)
        elif commit:
            break    # do not push the served leg if the points leg did not land
    batch.refresh_from_db()
    if all(i is not None and i.status == 'finalized' for i in _invoices(batch).values()):
        batch.status = 'stocked'
        batch.save(update_fields=['status', 'updated_at'])
    return results


def _mark_leg_stocked(batch, leg, inv):
    from .models import CouponSerial
    rows = list(batch.serials.all())
    for c in rows:
        setattr(c, f'{leg}_docnumber', int(inv.softech_docnumber))
        setattr(c, f'{leg}_docdate', inv.softech_docdate)
        setattr(c, f'{leg}_qty', 1)
        c.status = coupons._status_for(c)
    CouponSerial.objects.bulk_update(rows, [f'{leg}_docnumber', f'{leg}_docdate', f'{leg}_qty', 'status'])
    logger.info('[coupons] batch #%s %s leg stocked → SOFTECH 100/10/%s', batch.pk, leg,
                inv.softech_docnumber)


# ── verify (read-only) ─────────────────────────────────────────────────────────
def verify_batch(batch):
    """READ-ONLY check of a stocked batch: both documents still in SOFTECH with all their
    lines (writer.reconcile), HQ stock of both items, and how many of the batch's
    per-serial stock rows (stkbalexpiry, by expiry range) HQ holds."""
    from config.sybase import get_sybase_connection
    from apps.invoices import writer

    out = {'legs': {}, 'stock': {}, 'serial_rows': {}}
    for leg, inv in _invoices(batch).items():
        if inv is None or inv.status != 'finalized':
            out['legs'][leg] = {'present': False, 'note': 'not pushed'}
            continue
        out['legs'][leg] = writer.reconcile(inv)
    conn = get_sybase_connection()
    try:
        for leg in LEGS:
            code = leg_item(leg)
            cur = conn.cursor()
            cur.execute("SELECT nowqty FROM stkbal WHERE branchcode=? AND storecode=? AND itemcode=?",
                        [coupons.hq_branch(), coupons.hq_branch(), code])
            r = cur.fetchone()
            out['stock'][code] = float(r[0]) if r and r[0] is not None else 0.0
            if batch.expiry_from and batch.expiry_to:
                cur = conn.cursor()
                cur.execute("SELECT count(*), sum(itemqty) FROM stkbalexpiry WHERE storecode=? AND itemcode=? "
                            "AND itemexpirydate BETWEEN ? AND ?",
                            [coupons.hq_branch(), code, batch.expiry_from.isoformat(),
                             batch.expiry_to.isoformat() + ' 23:59:59'])
                r = cur.fetchone()
                out['serial_rows'][code] = {'rows': int(r[0] or 0), 'qty': float(r[1] or 0)}
    finally:
        conn.close()
    return out
