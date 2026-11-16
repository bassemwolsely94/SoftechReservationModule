"""The keep-out rule and the VAT prefill for ETA production item coding (batch S1).

Deterministic suggestions only: `premark` pre-marks an item from where it was bought and `vat_prefill` proposes a VAT
rate with a "check this" flag. The owner's decision (coding_queue.decide) is what counts; nothing here writes."""
from collections import Counter
from decimal import Decimal

OFFICIAL = frozenset({'OFFICIAL_DISTRIBUTOR', 'DRUG_WAREHOUSE', 'MANUFACTURER', 'SMALL_WAREHOUSE'})
IGNORED = frozenset({'PATIENT_REPURCHASE', 'CUSTOMER_REPURCHASE', 'SISTER_COMPANY', 'INTERNAL_TRANSFER',
                     'EXTERNAL_TRANSFER', 'CLEARING', 'SERVICE_VENDOR', 'FIXED_ASSET_SUPPLIER'})
UNKNOWN = 'UNKNOWN'
_FULLY_OFFICIAL = OFFICIAL - {'SMALL_WAREHOUSE'}

NOTES = {
    'services': 'خدمة / هدية — لا تُكوَّد حالياً',
    'official': 'اشتُري من موزع أو مخزن أو مصنع',
    'small_warehouse_only': 'اشتُري من مخازن صغيرة فقط — تأكد من تسجيله (هيئة الدواء / سلامة الغذاء)',
    'unofficial_only': 'لم يُشترَ من موزع أو مخزن أو مصنع',
    'no_purchase': 'لا مشتريات معتبرة منذ مايو 2025',
}
_PREMARK = {'services': 'keep_out', 'official': 'code', 'small_warehouse_only': 'code',
            'unofficial_only': 'keep_out', 'no_purchase': ''}

ZERO_RATE_SUSPECT_TYPES = frozenset({'Cosmetics', 'Others', 'Body Building'})
STANDARD_RATES = (Decimal('0'), Decimal('14'))


def purchase_sources(itemcodes):
    """{itemcode: Counter(category -> purchased qty)} from every purchase line held (doccode 10). The category is the
    supplier's live segmentation (no row = UNKNOWN), not the copy stamped on the line. Ignored categories (repurchase,
    transfers, sister company...) are dropped, so an item bought only that way has an empty Counter or no key."""
    from django.db.models import Sum
    from apps.procurement.models import PurchaseLine, SupplierSegmentation

    rows = list(PurchaseLine.objects.filter(doccode='10', item_code__in=list(itemcodes))
                .values('item_code', 'supplier_code').annotate(qty=Sum('raw_qty')))
    categories = dict(SupplierSegmentation.objects.filter(supplier_code__in={r['supplier_code'] for r in rows})
                      .values_list('supplier_code', 'supplier_category'))
    out = {}
    for r in rows:
        category = categories.get(r['supplier_code']) or UNKNOWN
        if category in IGNORED:
            continue
        out.setdefault(r['item_code'], Counter())[category] += r['qty'] or 0
    return out


def _is_service_or_gift(item):
    mtype = item.medicine_type_name or ''
    return mtype.startswith('Services') or item.is_stockable is False or 'هدايا' in mtype


def premark(item, sources):
    """(premark, reason_code, note): premark is 'code', 'keep_out' or '' (no suggestion). `item` may be None when
    the item has no catalog row; the purchase sources then decide alone."""
    if item is not None and _is_service_or_gift(item):
        reason = 'services'
    else:
        bought = {c for c in (sources or {}) if c not in IGNORED}
        if bought & _FULLY_OFFICIAL:
            reason = 'official'
        elif 'SMALL_WAREHOUSE' in bought:
            reason = 'small_warehouse_only'
        elif bought:
            reason = 'unofficial_only'
        else:
            reason = 'no_purchase'
    return _PREMARK[reason], reason, NOTES[reason]


def vat_prefill(item, profile):
    """(rate, flagged, why). A treatment the accountant confirmed wins and is never flagged; otherwise the rate is
    SOFTECH's itemsalestaxp, flagged when it looks wrong for the item type (cosmetics/others/body building at 0,
    medicine at 14) or is neither 0 nor 14."""
    if profile is not None and profile.treatment_confirmed_at:
        return Decimal(profile.vat_rate), False, 'confirmed'
    rate = Decimal(str((item.sale_tax_pct if item is not None else 0) or 0))
    mtype = (item.medicine_type_name if item is not None else '') or ''
    if rate not in STANDARD_RATES:
        return rate, True, 'odd_rate'
    if mtype in ZERO_RATE_SUSPECT_TYPES and rate == 0:
        return rate, True, 'zero_for_type'
    if mtype == 'Medicine' and rate == 14:
        return rate, True, 'taxed_medicine'
    return rate, False, 'catalog'
