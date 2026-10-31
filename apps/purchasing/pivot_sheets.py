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


def record_snapshot(lines, *, staff, run, params, source='download', exported_at=None, file_name=''):
    """Store one sheet. Returns the snapshot, or None when the same sheet is already stored for that day."""
    from .models import PivotSheetSnapshot
    lines = clean_lines(lines)
    digest = _hash(lines)
    when = exported_at or timezone.now()
    same = PivotSheetSnapshot.objects.filter(lines_hash=digest, source=source,
                                             exported_at__date=timezone.localtime(when).date())
    same = same.filter(run=run) if run is not None else same.filter(run__isnull=True)
    if same.exists():
        return None
    s = PivotSheetSnapshot.objects.create(
        source=source, exported_by=staff, run=run, calc_date=getattr(run, 'calc_date', None),
        params=params or {}, lines=lines, line_count=len(lines), lines_hash=digest, file_name=file_name[:200])
    if exported_at is not None:
        PivotSheetSnapshot.objects.filter(pk=s.pk).update(exported_at=exported_at)
        s.exported_at = exported_at
    return s
