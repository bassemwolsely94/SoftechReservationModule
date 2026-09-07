"""
apps/shortage/stock_check.py

Check internal stock levels for all confirmed items in a shortage list.
Returns transfer suggestions when stock is available in other branches.

Uses ItemStock (synced from SOFTECH) — no live SOFTECH query needed.
"""
from __future__ import annotations
from decimal import Decimal


# Store codes to exclude (expired / quarantine stocks at HQ)
_EXCLUDED_STORES = frozenset({'102', '103', '105'})


def check_stock_for_list(shortage_list) -> list[dict]:
    """
    For every confirmed ShortageItem in shortage_list, look up stock
    across all branches (excluding the requesting branch and quarantine stores).

    Returns a list of item-level dicts:
    {
        shortage_item_id: int,
        item_id: int,
        item_code: str,
        item_name: str,
        needed_qty: float,
        requesting_branch_id: int,
        requesting_branch_name: str,
        available_branches: [
            { branch_id, branch_name, qty_on_hand, suggestion }
        ],
        transfer_possible: bool,
        total_available: float,
    }
    """
    from apps.catalog.models import ItemStock

    # Pull only confirmed items that have a matched item
    confirmed_items = list(
        shortage_list.items
        .filter(is_confirmed=True, item__isnull=False)
        .select_related('item', 'shortage_list__branch')
    )

    if not confirmed_items:
        return []

    item_ids           = [si.item_id for si in confirmed_items]
    requesting_branch  = shortage_list.branch

    # Single query for all relevant stock rows
    stock_qs = (
        ItemStock.objects
        .filter(item_id__in=item_ids, quantity_on_hand__gt=0)
        .exclude(softech_store_code__in=_EXCLUDED_STORES)
        .select_related('branch', 'item')
    )

    # Index: item_id → list of stock rows
    stock_map: dict[int, list] = {}
    for row in stock_qs:
        stock_map.setdefault(row.item_id, []).append(row)

    results = []
    for si in confirmed_items:
        item_stock_rows = stock_map.get(si.item_id, [])

        # Separate requesting branch stock from other branches
        other_branches = [
            r for r in item_stock_rows
            if r.branch_id != requesting_branch.id
        ]

        available_branches = []
        total_available    = Decimal('0')

        for row in sorted(other_branches, key=lambda r: r.quantity_on_hand, reverse=True):
            qty = row.quantity_on_hand
            total_available += qty

            needed = Decimal(str(si.quantity_needed))
            if qty >= needed:
                suggestion = f'يمكن تحويل {float(needed):.0f} من {row.branch.name_ar or row.branch.name}'
            elif qty > 0:
                suggestion = f'متاح {float(qty):.0f} فقط في {row.branch.name_ar or row.branch.name}'
            else:
                suggestion = None

            available_branches.append({
                'branch_id':   row.branch_id,
                'branch_name': row.branch.name_ar or row.branch.name,
                'qty_on_hand': float(qty),
                'suggestion':  suggestion,
            })

        results.append({
            'shortage_item_id':       si.id,
            'item_id':                si.item_id,
            'item_code':              si.item.softech_id,
            'item_name':              si.item.name,
            'needed_qty':             float(si.quantity_needed),
            'requesting_branch_id':   requesting_branch.id,
            'requesting_branch_name': requesting_branch.name_ar or requesting_branch.name,
            'available_branches':     available_branches,
            'transfer_possible':      total_available >= Decimal(str(si.quantity_needed)),
            'total_available':        float(total_available),
        })

    return results


def check_stock_for_items(item_ids: list[int], branch_id: int) -> dict[int, dict]:
    """
    Lightweight version: given a list of item_ids and the requesting branch_id,
    returns a dict keyed by item_id with transfer availability info.
    Used by the aggregate view.
    """
    from apps.catalog.models import ItemStock

    stock_qs = (
        ItemStock.objects
        .filter(item_id__in=item_ids, quantity_on_hand__gt=0)
        .exclude(branch_id=branch_id)
        .exclude(softech_store_code__in=_EXCLUDED_STORES)
        .select_related('branch')
    )

    result: dict[int, dict] = {iid: {'available': False, 'branches': []} for iid in item_ids}

    for row in stock_qs:
        entry = result[row.item_id]
        entry['available'] = True
        entry['branches'].append({
            'branch_id':   row.branch_id,
            'branch_name': row.branch.name_ar or row.branch.name,
            'qty':         float(row.quantity_on_hand),
        })

    return result
