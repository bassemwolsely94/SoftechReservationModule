"""
apps/stockcount/valuation.py — C14 / P-08: count variance valued at cost, with the sales made between
the snapshot and the count netted out (docs/full-project-audit/08_BUSINESS_OPTIMIZATION_OPPORTUNITIES.md
§C14).

Why: the snapshot freezes «الكمية المتوقعة»; the branch keeps selling while the shelves are counted, so
every pack sold after the snapshot shows up as a shortage that is not one. Managers chase it.

  window        = (session.snapshot_at, end of counting]; end = the last count entry
                  (session.variance_at), else the upload time, else now
  moved         = packs sold − packs returned on the branch's sales invoices (doc 115 / 30, our synced
                  sales mirror, timed by the till clock trans_time) inside the window
  net expected  = expected − moved
  net diff      = counted − net expected      (positive = surplus, negative = shortage)
  value         = diff × unit cost; basis = the item's CURRENT cost (catalog Item.cost_price) — named on
                  every response so nobody reads it as the sale value

Display only. The raw difference and the adjustment export for SOFTECH (doc 50 / 150) are unchanged:
whether a count is posted, and with which quantity, stays the existing, human, SOFTECH-side step.
Read-only; no SOFTECH read or write.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

VALUATION_BASIS = 'current_cost'
VALUATION_BASIS_LABEL = {'ar': 'بالتكلفة الحالية للصنف', 'en': "at the item's current cost"}
SALE_DOC, RETURN_DOC = '115', '30'
ZERO = Decimal('0')
TOL = Decimal('0.001')


def count_window(session):
    """(start, end) of the counting window, or (None, None) when there is no snapshot."""
    if not session.snapshot_at:
        return None, None
    end = session.variance_at or session.uploaded_at or timezone.now()
    return session.snapshot_at, max(end, session.snapshot_at)


def moved_since(branch_code, item_codes, start, end) -> dict:
    """{item_code: packs sold − packs returned} on the branch's invoices in (start, end]."""
    from apps.customers.models import PurchaseHistoryLine
    if not (start and end and item_codes):
        return {}
    when = Coalesce('purchase__trans_time', 'purchase__invoice_date')
    rows = (PurchaseHistoryLine.objects
            .annotate(at=when)
            .filter(purchase__branch__softech_branch_id=branch_code, at__gt=start, at__lte=end,
                    purchase__doc_code__in=(SALE_DOC, RETURN_DOC), item__softech_id__in=list(item_codes))
            .values('item__softech_id')
            .annotate(sold=Sum('quantity', filter=Q(purchase__doc_code=SALE_DOC)),
                      returned=Sum('quantity', filter=Q(purchase__doc_code=RETURN_DOC))))
    return {r['item__softech_id']: (r['sold'] or ZERO) - abs(r['returned'] or ZERO) for r in rows}


def unit_costs(item_codes) -> dict:
    from apps.catalog.models import Item
    return {code: (cost or ZERO) for code, cost in
            Item.objects.filter(softech_id__in=list(item_codes)).values_list('softech_id', 'cost_price')}


def net_variance(expected, counted, moved, unit_cost) -> dict:
    """One counted item — pure. Quantities as Decimal; None counted = not counted."""
    if counted is None:
        return {'moved_qty': moved, 'net_expected': expected - moved, 'net_difference': None,
                'net_type': '', 'raw_value': None, 'net_value': None}
    raw = counted - expected
    net = counted - (expected - moved)
    kind = 'ok' if abs(net) < TOL else ('surplus' if net > 0 else 'deficit')
    return {'moved_qty': moved, 'net_expected': expected - moved, 'net_difference': net, 'net_type': kind,
            'raw_value': (raw * unit_cost).quantize(Decimal('0.01')),
            'net_value': (net * unit_cost).quantize(Decimal('0.01'))}


def value_session(session, snapshots) -> tuple[dict, dict]:
    """({item_code: valuation}, summary) for the session's snapshot rows."""
    codes = [s.item_code for s in snapshots]
    start, end = count_window(session)
    moved = moved_since(session.branch_code, codes, start, end)
    costs = unit_costs(codes)
    per, s = {}, {'raw_deficit_value': ZERO, 'raw_surplus_value': ZERO, 'net_deficit_value': ZERO,
                  'net_surplus_value': ZERO, 'items_moved': 0, 'cleared_by_sales': 0}
    for snap in snapshots:
        v = net_variance(snap.expected_qty, snap.counted_qty, moved.get(snap.item_code, ZERO),
                         costs.get(snap.item_code, ZERO))
        v['unit_cost'] = costs.get(snap.item_code, ZERO)
        per[snap.item_code] = v
        if v['moved_qty']:
            s['items_moved'] += 1
        if v['raw_value'] is None:
            continue
        s['raw_deficit_value' if v['raw_value'] < 0 else 'raw_surplus_value'] += abs(v['raw_value'])
        s['net_deficit_value' if v['net_value'] < 0 else 'net_surplus_value'] += abs(v['net_value'])
        if snap.variance_type == 'deficit' and v['net_type'] == 'ok':
            s['cleared_by_sales'] += 1                 # a «shortage» that was only sales during the count
    summary = {k: (float(v) if isinstance(v, Decimal) else v) for k, v in s.items()}
    summary.update(basis=VALUATION_BASIS, basis_label=VALUATION_BASIS_LABEL,
                   window_start=start, window_end=end)
    return per, summary
