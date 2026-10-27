"""
catalog/quicksell.py — per-branch top-sellers for the POS Quick-Sell grid.

Deterministic aggregate over the PG sales mirror (PurchaseHistoryLine): busiest
items at a branch over a recent window, sales only (doc_code '115', returns '30'
excluded). Read-only; no SOFTECH call. Complements the client-side favorites grid
(localStorage) with a server-backed, data-driven default.
"""
from datetime import timedelta

from django.db.models import Sum, Count
from django.utils import timezone

from .models import Item, ItemStock, EXCLUDED_STORE_CODES
from .safety import item_safety_flags

DEFAULT_DAYS = 30
DEFAULT_LIMIT = 12
MAX_LIMIT = 40


def top_sellers(branch_id, *, days=DEFAULT_DAYS, limit=DEFAULT_LIMIT):
    """Return the branch's best-selling items over the last `days` days."""
    from apps.customers.models import PurchaseHistoryLine

    limit = max(1, min(int(limit), MAX_LIMIT))
    since = timezone.now() - timedelta(days=max(1, int(days)))

    rows = (
        PurchaseHistoryLine.objects
        .filter(
            purchase__branch_id=branch_id,
            purchase__doc_code='115',                 # sales only (exclude returns '30')
            purchase__invoice_date__gte=since,
            item__isnull=False,
        )
        .values('item_id')
        .annotate(sold_qty=Sum('quantity'), order_count=Count('purchase_id', distinct=True))
        .order_by('-sold_qty')[:limit]
    )
    ordered_ids = [r['item_id'] for r in rows]
    if not ordered_ids:
        return []

    agg = {r['item_id']: r for r in rows}
    items = {i.id: i for i in Item.objects.filter(id__in=ordered_ids)}
    stock = _branch_stock(ordered_ids, branch_id)

    out = []
    for iid in ordered_ids:
        it = items.get(iid)
        if not it:
            continue
        out.append({
            'id': it.id,
            'softech_id': it.softech_id,
            'name': it.name,
            'pack_price': float(it.pack_price or 0),
            'qty_at_branch': stock.get(iid, 0.0),
            'sold_qty': float(agg[iid]['sold_qty'] or 0),
            'order_count': agg[iid]['order_count'],
            'safety_flags': item_safety_flags(it),
        })
    return out


def _branch_stock(item_ids, branch_id):
    rows = (
        ItemStock.objects
        .filter(item_id__in=item_ids, branch_id=branch_id)
        .exclude(softech_store_code__in=EXCLUDED_STORE_CODES)
        .values('item_id').annotate(qty=Sum('quantity_on_hand'))
    )
    return {r['item_id']: float(r['qty'] or 0) for r in rows}
