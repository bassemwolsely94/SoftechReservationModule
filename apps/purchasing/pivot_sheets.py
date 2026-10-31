"""
apps/purchasing/pivot_sheets.py

P-31: the demand pivot is the order sheet buyers send to suppliers (owner 2026-10-31 — they order from
`Total.الفرق-مطلوب/راكد`). Each download is kept as a PivotSheetSnapshot so procurement.receipt_check can tell
what was asked for. Only the items with a positive Total gap are kept, with the item's SOFTECH supplier.

    record_snapshot([{item_code, total_gap, supplier_code}, …], staff=…, run=…, params=…)

The same lines from the same run, recorded again the same day, are not stored twice (viewing the sheet several
times is not several orders).
"""
import hashlib
import json

from django.utils import timezone

GAP_HEADER = 'Total.الفرق-مطلوب/راكد'
CODE_HEADER = 'itemcode'
SUPPLIER_HEADER = 'Items_.كود-المورد'
COVER_HEADER = 'Total.معامل-التغطية-بالشهور'
RATE_HEADER = 'Total.معدل-البيع-الشهرى'
STOCK_HEADER = 'Total.الرصيد-الحالى'
COVER_KEEP_FROM = 3          # months — the sheet keeps covers from here so the flag threshold can move
NO_SALES = -1                # stock on hand and no sales anywhere


def cover_entry(coverage, rate, stock):
    """What a sheet keeps for an item's network cover: months (≥ COVER_KEEP_FROM), NO_SALES, or None."""
    try:
        if not float(rate or 0) and float(stock or 0) > 0:
            return NO_SALES
        if coverage is not None and float(coverage) >= COVER_KEEP_FROM:
            return round(float(coverage), 2)
    except (TypeError, ValueError):
        pass
    return None


def clean_lines(lines):
    """Positive gaps only, one entry per item (summed), stable order."""
    agg = {}
    for l in lines:
        code = str(l.get('item_code') or '').strip()
        try:
            gap = float(l.get('total_gap') or 0)
        except (TypeError, ValueError):
            continue
        if not code or gap <= 0:
            continue
        a = agg.setdefault(code, {'item_code': code, 'total_gap': 0.0,
                                  'supplier_code': str(l.get('supplier_code') or '').strip()})
        a['total_gap'] = round(a['total_gap'] + gap, 3)
    return [agg[c] for c in sorted(agg)]


def _hash(lines):
    return hashlib.sha256(json.dumps(lines, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def record_snapshot(lines, *, staff, run, params, source='download', exported_at=None, file_name='', covers=None):
    """Store one sheet. Returns the snapshot, or None when the same sheet is already stored for that day (an older
    copy without covers gets them filled in — re-importing a file stored before covers existed)."""
    from .models import PivotSheetSnapshot
    lines = clean_lines(lines)
    covers = {str(k).strip(): v for k, v in (covers or {}).items() if str(k).strip() and v is not None}
    digest = _hash(lines)
    when = exported_at or timezone.now()
    same = PivotSheetSnapshot.objects.filter(lines_hash=digest, source=source,
                                             exported_at__date=timezone.localtime(when).date())
    same = same.filter(run=run) if run is not None else same.filter(run__isnull=True)
    old = same.first()
    if old is not None:
        if covers and not old.covers:
            old.covers = covers
            old.save(update_fields=['covers'])
        return None
    s = PivotSheetSnapshot.objects.create(
        source=source, exported_by=staff, run=run, calc_date=getattr(run, 'calc_date', None),
        params=params or {}, lines=lines, line_count=len(lines), lines_hash=digest, file_name=file_name[:200],
        covers=covers)
    if exported_at is not None:
        PivotSheetSnapshot.objects.filter(pk=s.pk).update(exported_at=exported_at)
        s.exported_at = exported_at
    return s
