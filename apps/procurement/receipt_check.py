"""
apps/procurement/receipt_check.py

P-31 (docs/product-review/06_SPEC_P-31_unordered_delivery_detector.md): was this delivery asked for?

The order record is the demand pivot buyers send (purchasing.PivotSheetSnapshot — the positive
`Total.الفرق-مطلوب/راكد` rows of each download). For every paid doc-10 line of the pilot suppliers in the last
30 days:
  • `unordered` — the item was on no sheet sent in the N days before the delivery («بدون طلب — ارجعه»);
  • `over`      — the item's doc-10 quantity received since the newest such sheet exceeds that sheet's Total gap
                  by at least one whole pack («زيادة عن الفرق المطلوب»).
The supplier on the sheet is the item's SOFTECH supplier, not necessarily the one ordered from — shown, never
flagged. No bonus, short-delivery or price checks (no deterministic source; owner: no price check).

Rows are keyed on the PurchaseLine natural key; re-runs update the numbers, never a person's decision. A later
doc 120 for the same supplier + item closes a «مرتجع مطلوب» row; each return line is used once.
PostgreSQL only — runs after each procurement refresh and daily.
"""
import datetime as dt
import logging
from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger('elrezeiky.procurement')

LOOKBACK_DAYS = 30
OVER_MIN_PACKS = Decimal('1')
DEFAULT_SUPPLIERS = ['565', '30']        # pilot: Pharma Overseas, Ramco (owner 2026-10-31)


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


def _line_key(pl):
    return f'{pl.branch_code}|{pl.supplier_code}|{pl.doc_number}|{pl.doc_date.isoformat()}|{pl.item_code}|{pl.doccode}'


def _sheets(since):
    """[(date, snapshot, {item_code: (gap, supplier)})] newest first, sent on/after `since`."""
    from apps.purchasing.models import PivotSheetSnapshot
    out = []
    for s in PivotSheetSnapshot.objects.filter(exported_at__date__gte=since).order_by('-exported_at', '-pk'):
        items = {l['item_code']: (Decimal(str(l['total_gap'])), l.get('supplier_code', ''))
                 for l in (s.lines or [])}
        out.append((timezone.localtime(s.exported_at).date(), s, items))
    return out


def _check_lines(today):
    """{natural key: (PurchaseLine, flag, sheet, gap, sheet_supplier, received)} for the lines to flag."""
    from apps.procurement.models import PurchaseLine
    from apps.purchasing.models import PivotSheetSnapshot
    first = PivotSheetSnapshot.objects.order_by('exported_at').values_list('exported_at', flat=True).first()
    if first is None:
        return {}, None
    first_day = timezone.localtime(first).date()
    since = today - dt.timedelta(days=LOOKBACK_DAYS)
    win = dt.timedelta(days=window_days())
    sheets = _sheets(since - win)
    lines = list(PurchaseLine.objects.filter(doccode='10', is_foc=False, doc_date__gte=max(since, first_day),
                                             doc_date__lte=today, supplier_code__in=pilot_suppliers())
                 .order_by('doc_date', 'doc_number', 'pk'))
    # every paid doc-10 receipt of those items (any supplier), for the "received since the sheet" total
    received = defaultdict(list)
    for pl in (PurchaseLine.objects.filter(doccode='10', is_foc=False, item_code__in={l.item_code for l in lines},
                                           doc_date__gte=since - win, doc_date__lte=today)
               .order_by('doc_date', 'doc_number', 'pk')):
        received[pl.item_code].append(pl)
    out = {}
    for pl in lines:
        ref = next(((d, s, it[pl.item_code]) for d, s, it in sheets
                    if pl.item_code in it and pl.doc_date - win <= d <= pl.doc_date), None)
        if ref is None:
            out[_line_key(pl)] = (pl, 'unordered', None, None, '', None)
            continue
        sheet_day, sheet, (gap, sheet_sup) = ref
        got = Decimal('0')
        for r in received[pl.item_code]:          # this line and every earlier one since the sheet
            if sheet_day <= r.doc_date and (r.doc_date, r.doc_number, r.pk) <= (pl.doc_date, pl.doc_number, pl.pk):
                got += r.net_qty or 0
        if got - gap >= OVER_MIN_PACKS:
            out[_line_key(pl)] = (pl, 'over', sheet, gap, sheet_sup, got)
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
        for pl, flag, sheet, gap, sheet_sup, got in found.values():
            k = (pl.branch_code, pl.supplier_code, pl.doc_number, pl.doc_date, pl.item_code)
            seen.add(k)
            vals = dict(qty=pl.net_qty or 0, value=pl.raw_value or 0, flag=flag, sheet=sheet, sheet_gap=gap,
                        sheet_supplier_code=sheet_sup or '', received_in_window=got)
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
    agg = ReceiptCheck.objects.filter(status='open', flag='unordered').aggregate(
        n=Count('id'), value=Sum('value'), oldest=Min('doc_date'))
    if not agg['n']:
        return 0
    over = ReceiptCheck.objects.filter(status='open', flag='over').count()
    age = (today - agg['oldest']).days
    title = f"📦 استلام بدون طلب — {agg['n']} سطر"
    body = (f"{agg['n']} سطر وصل بدون أن يكون في شيت الاحتياج المُرسَل (قيمة {round(agg['value'] or 0):,} ج، "
            f"أقدمها منذ {age} يوم)" + (f"، و{over} سطر زيادة عن الفرق المطلوب" if over else '')
            + ".\nافتح «التوريد» ← «استلام بدون طلب».")
    sent = 0
    for staff in digest_recipients():
        n = Notification.send_to_user(staff, 'receipt_check_digest', title, body,
                                      dedup_key=f'receipt_check_{today.isoformat()}', dedup_once=True)
        sent += int(n is not None)
    return sent
