"""
apps/procurement/receipt_check.py

P-31 (docs/product-review/06_SPEC_P-31_unordered_delivery_detector.md): purchases of items the network already held
plenty of.

Every demand-pivot download is kept as a sent need sheet (purchasing.PivotSheetSnapshot) — its positive
`Total.الفرق-مطلوب/راكد` rows and, in `covers`, the network months of cover of the items already well covered
(and -1 for stock with no sales at all). The first office run (2026-10-31) showed buyers order well beyond the
pivot's 1-month gap, so «not on the sheet» flagged 80 % of deliveries. Owner rule («Use 6 months»): a paid doc-10
line of a pilot supplier is flagged `overstocked` («شراء رغم تغطية عالية») when the newest sheet sent in the N days
before it shows the item at ≥ `receipt_check_cover_months` (default 6) months of network cover, or stock with no
sales. A review list, not a return list. The sheet's gap and supplier are shown, never flagged. No bonus, short or
price checks.

Rows are keyed on the PurchaseLine natural key; re-runs update the numbers, never a person's decision. A later
doc 120 for the same supplier + item closes a «مرتجع مطلوب» row; each return line is used once.
PostgreSQL only — runs after each procurement refresh and daily. `receipt_check_suppliers = []` pauses it.
"""
import datetime as dt
import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger('elrezeiky.procurement')

LOOKBACK_DAYS = 30
DEFAULT_SUPPLIERS = ['565', '30']        # pilot: Pharma Overseas, Ramco (owner 2026-10-31)
DEFAULT_COVER_MONTHS = 6                 # owner 2026-10-31
NO_SALES = -1


def _setting(key, default):
    try:
        from apps.config.models import SystemSetting
        return SystemSetting.get(key, default)
    except Exception:
        return default


def pilot_suppliers():
    v = _setting('receipt_check_suppliers', DEFAULT_SUPPLIERS)
    return [str(s).strip() for s in v if str(s).strip()] if isinstance(v, list) else list(DEFAULT_SUPPLIERS)


def window_days():
    try:
        return max(1, int(_setting('receipt_check_window_days', 14)))
    except (TypeError, ValueError):
        return 14


def cover_months():
    try:
        return max(1.0, float(_setting('receipt_check_cover_months', DEFAULT_COVER_MONTHS)))
    except (TypeError, ValueError):
        return float(DEFAULT_COVER_MONTHS)


def _line_key(pl):
    return f'{pl.branch_code}|{pl.supplier_code}|{pl.doc_number}|{pl.doc_date.isoformat()}|{pl.item_code}|{pl.doccode}'


def _sheets(since):
    """[(date, snapshot, {item_code: (gap, supplier)}, covers)] newest first, sent on/after `since`."""
    from apps.purchasing.models import PivotSheetSnapshot
    out = []
    for s in PivotSheetSnapshot.objects.filter(exported_at__date__gte=since).order_by('-exported_at', '-pk'):
        items = {l['item_code']: (Decimal(str(l['total_gap'])), l.get('supplier_code', ''))
                 for l in (s.lines or [])}
        out.append((timezone.localtime(s.exported_at).date(), s, items, s.covers or {}))
    return out


def _check_lines(today):
    """{natural key: (PurchaseLine, flag, sheet, gap, sheet_supplier, received, cover)} for the lines to flag."""
    from apps.procurement.models import PurchaseLine
    from apps.purchasing.models import PivotSheetSnapshot
    first = PivotSheetSnapshot.objects.order_by('exported_at').values_list('exported_at', flat=True).first()
    if first is None:
        return {}, None
    first_day = timezone.localtime(first).date()
    since = today - dt.timedelta(days=LOOKBACK_DAYS)
    win = dt.timedelta(days=window_days())
    limit = cover_months()
    sheets = _sheets(since - win)
    lines = (PurchaseLine.objects.filter(doccode='10', is_foc=False, doc_date__gte=max(since, first_day),
                                         doc_date__lte=today, supplier_code__in=pilot_suppliers())
             .order_by('doc_date', 'doc_number', 'pk'))
    out = {}
    for pl in lines:
        ref = next(((d, s, it, cv) for d, s, it, cv in sheets if pl.doc_date - win <= d <= pl.doc_date), None)
        if ref is None:
            continue
        _, sheet, items, covers = ref
        cover = covers.get(pl.item_code)
        if cover is None or not (cover == NO_SALES or float(cover) >= limit):
            continue
        gap, sheet_sup = items.get(pl.item_code, (None, ''))
        out[_line_key(pl)] = (pl, 'overstocked', sheet, gap, sheet_sup, None, Decimal(str(cover)))
    return out, first_day


def _close_returns():
    """«مرتجع مطلوب» rows → «تم الإرجاع» when a doc 120 for the same supplier + item follows; each line once."""
    from apps.procurement.models import PurchaseLine, ReceiptCheck
    rows = list(ReceiptCheck.objects.filter(status='return_requested').order_by('doc_date', 'pk'))
    if not rows:
        return 0
    used = {ref for refs in ReceiptCheck.objects.exclude(returned_refs=[]).values_list('returned_refs', flat=True)
            for ref in (refs or [])}
    closed = 0
    for row in rows:
        pl = (PurchaseLine.objects.filter(doccode='120', supplier_code=row.supplier_code, item_code=row.item_code,
                                          doc_date__gte=row.doc_date)
              .order_by('doc_date', 'doc_number', 'pk'))
        for ret in pl:
            key = _line_key(ret)
            if key in used:
                continue
            used.add(key)
            row.status = 'returned'
            row.returned_refs = [key]
            row.returned_value = abs(ret.raw_value or Decimal('0'))
            row.save(update_fields=['status', 'returned_refs', 'returned_value', 'checked_at'])
            closed += 1
            break
    return closed


def run_check(today=None):
    """Recompute the flags; returns {'flagged', 'cleared', 'returned'}."""
    from apps.procurement.models import ReceiptCheck
    today = today or timezone.localdate()
    found, first_day = _check_lines(today)
    flagged = cleared = 0
    with transaction.atomic():
        existing = {(r.branch_code, r.supplier_code, r.doc_number, r.doc_date, r.item_code): r
                    for r in ReceiptCheck.objects.filter(doc_date__gte=today - dt.timedelta(days=LOOKBACK_DAYS))}
        seen = set()
        for pl, flag, sheet, gap, sheet_sup, got, cover in found.values():
            k = (pl.branch_code, pl.supplier_code, pl.doc_number, pl.doc_date, pl.item_code)
            seen.add(k)
            vals = dict(qty=pl.net_qty or 0, value=pl.raw_value or 0, flag=flag, sheet=sheet, sheet_gap=gap,
                        sheet_supplier_code=sheet_sup or '', received_in_window=got, sheet_cover=cover)
            row = existing.get(k)
            if row is None:
                ReceiptCheck.objects.create(branch_code=pl.branch_code, supplier_code=pl.supplier_code,
                                            doc_number=pl.doc_number, doc_date=pl.doc_date, item_code=pl.item_code,
                                            **vals)
                flagged += 1
            else:
                for f, v in vals.items():
                    setattr(row, f, v)
                row.save(update_fields=list(vals) + ['checked_at'])
        # a line that no longer needs a flag (a sheet was imported later, a re-pull changed it) and that nobody
        # has acted on is removed; a person's decision is kept
        for k, row in existing.items():
            if k not in seen and row.status == 'open' and first_day is not None and row.doc_date >= first_day:
                row.delete()
                cleared += 1
    returned = _close_returns()
    if flagged or cleared or returned:
        logger.info('[receipt check] flagged=%s cleared=%s returned=%s', flagged, cleared, returned)
    return {'flagged': flagged, 'cleared': cleared, 'returned': returned}


def digest_recipients():
    from apps.users.models import StaffProfile
    ids = _setting('receipt_check_recipients', None)
    if isinstance(ids, list) and ids:
        return list(StaffProfile.objects.filter(pk__in=ids, is_active=True))
    qs = StaffProfile.objects.filter(role='purchasing', is_active=True)
    return list(qs) or list(StaffProfile.objects.filter(role='admin', is_active=True))


def send_digest(today=None):
    """One notification a day to the returns owners when open `unordered` rows exist. Returns the count sent."""
    from django.db.models import Count, Min, Sum
    from apps.notifications.models import Notification
    from apps.procurement.models import ReceiptCheck
    today = today or timezone.localdate()
    agg = ReceiptCheck.objects.filter(status='open').aggregate(
        n=Count('id'), value=Sum('value'), oldest=Min('doc_date'))
    if not agg['n']:
        return 0
    age = (today - agg['oldest']).days
    title = f"📦 شراء رغم تغطية عالية — {agg['n']} سطر"
    body = (f"{agg['n']} سطر شراء لأصناف كانت تغطيتها في الشبكة {cover_months():g} شهور أو أكثر (أو بلا مبيعات) "
            f"في آخر شيت احتياج — قيمة {round(agg['value'] or 0):,} ج، أقدمها منذ {age} يوم."
            "\nافتح «التوريد» ← «شراء رغم تغطية عالية» للمراجعة.")
    sent = 0
    for staff in digest_recipients():
        n = Notification.send_to_user(staff, 'receipt_check_digest', title, body,
                                      dedup_key=f'receipt_check_{today.isoformat()}', dedup_once=True)
        sent += int(n is not None)
    return sent
