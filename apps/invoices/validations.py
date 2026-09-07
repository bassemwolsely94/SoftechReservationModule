"""
apps/invoices/validations.py

Replicate SofTech's save-time PURCHASE/RETURN validations (docs/architecture/
SOFTECH_PURCHASE_VALIDATIONS.md). SofTech enforces these client-side (not in DB
procs), so our module must run them itself by reading the same master data.

validate_invoice(invoice, live=True) -> {ok, errors:[...], warnings:[...], doc_value}
  each entry: {code, severity, line_id|None, message}
Errors block a push; warnings are surfaced and require an explicit override (force).
"""
import logging
from django.conf import settings

logger = logging.getLogger('elrezeiky.invoices')

# personmaxbal at/above this is a "no real limit" sentinel (seen 1e10 … 1e11).
UNLIMITED_CREDIT = 1e10


def _f(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _cfg(name, default):
    return getattr(settings, name, default)


def _net(line):
    """Net purchase price/pack = explicit unit_price, else public × (1−disc)(1−extra)."""
    n = _f(line.unit_price)
    if n <= 0:
        n = round(_f(line.public_price) * (1 - _f(line.discount_pct) / 100)
                  * (1 - _f(line.extra_discount_pct) / 100), 4)
    return n


def validate_invoice(invoice, *, live=True):
    errors, warnings = [], []

    def err(code, msg, line_id=None):
        errors.append({'code': code, 'severity': 'error', 'line_id': line_id, 'message': msg})

    def warn(code, msg, line_id=None):
        warnings.append({'code': code, 'severity': 'warning', 'line_id': line_id, 'message': msg})

    lines = list(invoice.lines.select_related('item').all())
    is_return = invoice.doc_kind == 'return'

    # ── PG-side checks (no SOFTECH) ──────────────────────────────────────────
    if not invoice.vendor or not invoice.vendor.softech_personcode:
        err('supplier_unlinked', 'المورد غير مربوط بكود SOFTECH (VendorProfile.softech_personcode)')
    matched = [l for l in lines if l.item_id]
    if not matched:
        err('item_unmatched', 'لا توجد أصناف مطابقة لترحيلها')
    for l in lines:
        if not l.item_id:
            err('item_unmatched', f'صنف غير مطابق: {l.manual_name or l.raw_text or "—"}', l.id)
            continue
        if _f(l.quantity) <= 0:
            err('qty_invalid', f'كمية غير صحيحة (≤0): {l.item.name}', l.id)
        if _net(l) <= 0:
            err('price_invalid', f'سعر شراء غير صحيح (≤0): {l.item.name}', l.id)

    if not live or not matched:
        return {'ok': not errors, 'errors': errors, 'warnings': warnings}

    # ── live SOFTECH master-data reads (one connection) ──────────────────────
    from config.sybase import get_branch_connection
    from . import writer
    host = writer.branch_host(invoice)
    if not host:
        warn('offline', 'تعذّر التحقق الحي من بيانات SOFTECH (لا يوجد اتصال بالفرع)')
        return {'ok': not errors, 'errors': errors, 'warnings': warnings}

    personcode = invoice.vendor.softech_personcode
    branch = invoice.softech_branchcode
    codes = list(dict.fromkeys(str(l.item.softech_id).strip() for l in matched))
    items, credit, maxbal, linked, orig_qty, orig_present = {}, 0.0, 0.0, set(), {}, True
    conn = get_branch_connection(host, invoice.branch.db_port or 5000,
                                 invoice.branch.db_name or 'SOFTECHDB9', charset=writer._write_charset())
    try:
        ph = ','.join('?' for _ in codes)
        cur = conn.cursor()
        cur.execute(f"SELECT itemcode, itemnomoreuse, itemarchive, itemexpiry, itemcostprice, "
                    f"itemsaleprice, itemsalestaxp, itemtrans3 FROM items WHERE itemcode IN ({ph})", codes)
        for r in cur.fetchall():
            items[str(r[0]).strip()] = {
                'nomoreuse': str(r[1] or '').strip(), 'archive': int(_f(r[2])),
                'expiry': str(r[3] or '').strip(), 'cost': _f(r[4]),
                'public': _f(r[5]), 'taxp': _f(r[6]), 'trans3': int(_f(r[7]))}
        srow = writer._q1(conn, "SELECT personcredit, personmaxbal FROM personsdata WHERE personcode=?",
                          [personcode])
        if srow:
            credit, maxbal = _f(srow[0]), _f(srow[1])
        cur2 = conn.cursor()
        cur2.execute(f"SELECT itemcode FROM itemssuppliers WHERE suppcode=? AND itemcode IN ({ph})",
                     [personcode] + codes)
        linked = {str(x[0]).strip() for x in cur2.fetchall()}
        # returns: original purchase must exist; capture received qty per item
        if is_return and invoice.return_of_docnumber:
            orig = writer._q1(conn, "SELECT count(*) FROM stktransm WHERE branchcode=? AND doccode='10' "
                                    "AND docnumber=?", [branch, int(invoice.return_of_docnumber)])
            orig_present = bool(orig and int(orig[0]) > 0)
            cur3 = conn.cursor()
            cur3.execute("SELECT itemcode, SUM(transqty) FROM stktrans WHERE branchcode=? AND doccode='10' "
                         "AND docnumber=? GROUP BY itemcode", [branch, int(invoice.return_of_docnumber)])
            for r in cur3.fetchall():
                orig_qty[str(r[0]).strip()] = _f(r[1])
    finally:
        try:
            conn.close()
        except Exception:
            pass

    inc = _f(_cfg('INVOICE_MAX_COST_INCREASE_PCT', 25))
    dec = _f(_cfg('INVOICE_MAX_COST_DECREASE_PCT', 40))
    hi_disc = _f(_cfg('INVOICE_HIGH_DISCOUNT_PCT', 50))
    doc_value = 0.0

    if is_return and not orig_present:
        err('original_missing', f'فاتورة الشراء الأصلية #{invoice.return_of_docnumber} غير موجودة في SOFTECH')

    for l in matched:
        code = str(l.item.softech_id).strip()
        it = items.get(code)
        net = _net(l)
        doc_value += net * _f(l.quantity)
        if not it:
            err('item_unmatched', f'الصنف {code} غير موجود في SOFTECH', l.id)
            continue
        # ── errors ──
        if it['nomoreuse'] == '1':
            err('item_discontinued', f'صنف موقوف (غير مسموح بشرائه): {l.item.name}', l.id)
        if it['archive'] == 1:
            err('item_archived', f'صنف مؤرشف: {l.item.name}', l.id)
        # itemtrans3 = supplier transaction permission (كارت الصنف → الموردين):
        #   0 شراء+ارتجاع | 1 شراء فقط | 2 ارتجاع فقط | 3 إيقاف كامل
        if not is_return and it['trans3'] in (2, 3):
            reason = 'موقوف بالكامل' if it['trans3'] == 3 else 'ارتجاع فقط'
            err('item_purchase_blocked', f'الصنف غير مسموح بشرائه من الموردين ({reason}): {l.item.name}', l.id)
        if is_return and it['trans3'] in (1, 3):
            reason = 'موقوف بالكامل' if it['trans3'] == 3 else 'شراء فقط'
            err('item_return_blocked', f'الصنف غير مسموح بإرجاعه للموردين ({reason}): {l.item.name}', l.id)
        if it['expiry'] == '1' and not writer._parse_expiry(l.expiry_date):
            err('expiry_required', f'تاريخ صلاحية مطلوب للصنف: {l.item.name}', l.id)
        if is_return and code in orig_qty and _f(l.quantity) > orig_qty[code] + 0.0001:
            err('return_exceeds_received',
                f'كمية المرتجع ({_f(l.quantity):g}) أكبر من المستلَم ({orig_qty[code]:g}): {l.item.name}', l.id)
        # ── warnings ──
        if it['public'] > 0 and net > it['public']:
            warn('cost_gt_public',
                 f'تكلفة الشراء ({net:.2f}) أعلى من سعر البيع للجمهور ({it["public"]:.2f}): {l.item.name}', l.id)
        if it['cost'] > 0 and net > it['cost'] * (1 + inc / 100):
            warn('price_spike',
                 f'ارتفاع غير معتاد في سعر الشراء ({net:.2f} مقابل {it["cost"]:.2f}): {l.item.name}', l.id)
        if it['cost'] > 0 and net < it['cost'] * (1 - dec / 100):
            warn('price_drop',
                 f'انخفاض حاد في سعر الشراء ({net:.2f} مقابل {it["cost"]:.2f}): {l.item.name}', l.id)
        if abs(_f(l.vat_pct) - it['taxp']) > 0.01:
            warn('tax_mismatch',
                 f'نسبة ضريبة مختلفة عن الصنف ({_f(l.vat_pct):g}% مقابل {it["taxp"]:g}%): {l.item.name}', l.id)
        if _f(l.discount_pct) > hi_disc:
            warn('discount_high', f'خصم مرتفع ({_f(l.discount_pct):g}%): {l.item.name}', l.id)
        if not is_return and code not in linked:
            warn('supplier_not_listed', f'الصنف غير مُدرج لدى هذا المورد في SOFTECH: {l.item.name}', l.id)

    # ── credit limit (purchase only) ─────────────────────────────────────────
    if (not is_return and _cfg('INVOICE_ENFORCE_CREDIT_LIMIT', True)
            and 0 < maxbal < UNLIMITED_CREDIT and credit + doc_value > maxbal):
        err('credit_limit_exceeded',
            f'تجاوز حد ائتمان المورد: الرصيد الحالي {credit:,.0f} + قيمة الفاتورة {doc_value:,.0f} '
            f'يتجاوز الحد {maxbal:,.0f}')

    return {'ok': not errors, 'errors': errors, 'warnings': warnings, 'doc_value': round(doc_value, 2)}
