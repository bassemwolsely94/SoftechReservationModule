"""
apps/supply/engine/allocation.py — internal (branch→branch) allocation for ONE item.

Reuses the transfer engine's authoritative surplus rule (apps.purchasing.transfer_engine):

    surplus at a branch = current_stock − safety_stock   (never drops the source below its
                          own safety stock → moving stock never RELOCATES a shortage, §9)

The full TransferEngine matches every deficit↔surplus pair across a whole demand run; here
we need the same logic scoped to one item and one requesting branch, on demand, so the
orchestrator can show "how much can we cover internally before buying". Same surplus
definition, same MIN_TRANSFER_QTY threshold, same greedy richest-source-first draw —
imported, not re-invented.
"""
from __future__ import annotations

from ..position import latest_demand_run
# Reuse the transfer engine's own threshold so the two never diverge.
from apps.purchasing.transfer_engine import MIN_TRANSFER_QTY


def _f(v) -> float:
    return float(v) if v is not None else 0.0


_EXCLUDED_STORES = frozenset({'102', '103', '105'})   # quarantine — never transferable


def _live_stock_by_branch(item_id) -> dict:
    """Live usable on-hand per branch from the 5-minute ItemStock sync (quarantine
    stores excluded). Used to REVALIDATE a recommendation before it is executed (§31)."""
    from django.db.models import Sum
    from apps.catalog.models import ItemStock
    return {r['branch_id']: _f(r['q']) for r in
            ItemStock.objects.filter(item_id=int(item_id))
            .exclude(softech_store_code__in=_EXCLUDED_STORES)
            .values('branch_id').annotate(q=Sum('quantity_on_hand'))}


def transferable_surplus(item_id, *, exclude_branch_id=None, run=None, live=False) -> list:
    """Per-branch transferable surplus for an item, richest first:

        surplus = current_stock − safety_stock − committed_outbound

    safety_stock comes from the latest demand run (authoritative). current_stock is the
    run's snapshot by default, or LIVE ItemStock when ``live=True`` (execution-time
    revalidation). committed_outbound is what open, undispatched transfer requests already
    claim from that branch — so two cases can never draw the same surplus. The requesting
    branch is excluded (it can't transfer to itself)."""
    from apps.purchasing.models import ItemDemandMetrics
    from .commitments import committed_outbound_by_branch

    run = run or latest_demand_run()
    if run is None:
        return []

    rows = (ItemDemandMetrics.objects
            .filter(run=run, item_id=int(item_id))
            .select_related('branch')
            .only('branch_id', 'current_stock', 'safety_stock',
                  'branch__name', 'branch__name_ar'))
    live_stock = _live_stock_by_branch(item_id) if live else None
    committed = committed_outbound_by_branch(item_id)

    out = []
    for m in rows:
        if exclude_branch_id is not None and m.branch_id == exclude_branch_id:
            continue
        stock = live_stock.get(m.branch_id, 0.0) if live else _f(m.current_stock)
        claimed = committed.get(m.branch_id, 0.0)
        surplus = stock - _f(m.safety_stock) - claimed
        if surplus >= MIN_TRANSFER_QTY:
            out.append({
                'branch_id': m.branch_id,
                'branch_name': (m.branch.name_ar or m.branch.name) if m.branch_id else '',
                'current_stock': stock,
                'safety_stock': _f(m.safety_stock),
                'committed_outbound': claimed,
                'surplus': surplus,
            })
    out.sort(key=lambda r: r['surplus'], reverse=True)
    return out


def network_internal_cover(item_id, *, run=None) -> dict:
    """Company-level internal cover for an item, from the engine's own per-branch gaps.

    A branch with gap < 0 holds stock BEYOND its own target (−gap units), which can cover
    other branches' deficits without creating a new shortage at the donor (§9). So for a
    company-level buy decision (e.g. a supplier's availability offer):

        deficit   = Σ max(0,  gap_b)        (what short branches need)
        overstock = Σ max(0, −gap_b)        (what over-target branches can spare)
        cover     = min(deficit, overstock) → company need to buy = deficit − cover

    Open transfer drafts are NOT subtracted here: an internal move is network-neutral
    (the destination's gap still counts the need the draft will cover)."""
    from apps.purchasing.models import ItemDemandMetrics

    run = run or latest_demand_run()
    if run is None:
        return {'deficit': 0.0, 'overstock': 0.0, 'cover': 0.0, 'donors': []}
    deficit = overstock = 0.0
    donors = []
    for m in (ItemDemandMetrics.objects.filter(run=run, item_id=int(item_id))
              .select_related('branch').only('branch_id', 'gap', 'branch__name', 'branch__name_ar')):
        g = _f(m.gap)
        if g > 0:
            deficit += g
        elif g < 0:
            overstock += -g
            donors.append({'branch_id': m.branch_id,
                           'branch_name': (m.branch.name_ar or m.branch.name) if m.branch_id else '',
                           'over_target': -g})
    donors.sort(key=lambda d: d['over_target'], reverse=True)
    return {'deficit': round(deficit, 3), 'overstock': round(overstock, 3),
            'cover': round(min(deficit, overstock), 3), 'donors': donors}


def allocate_internal(item_id, need, *, to_branch_id=None, run=None, live=False) -> dict:
    """Greedily cover ``need`` for one item from other branches' transferable surplus.

    Returns the proposed transfers (each explainable), the total internally allocated, and
    the total surplus that existed — so the operator sees why each branch gave what it gave
    (§10). Never allocates below MIN_TRANSFER_QTY. Read-only (proposes, writes nothing).
    ``live=True`` revalidates against live stock (used right before execution)."""
    need = max(0.0, float(need or 0))
    sources = transferable_surplus(item_id, exclude_branch_id=to_branch_id, run=run, live=live)
    total_surplus = sum(s['surplus'] for s in sources)

    transfers = []
    remaining = need
    for s in sources:
        if remaining < MIN_TRANSFER_QTY:
            break
        qty = min(remaining, s['surplus'])
        if qty < MIN_TRANSFER_QTY:
            continue
        transfers.append({
            'from_branch_id': s['branch_id'],
            'from_branch_name': s['branch_name'],
            'to_branch_id': to_branch_id,
            'qty': round(qty, 3),
            'from_surplus': s['surplus'],
            'from_stock': s['current_stock'],
            'from_safety': s['safety_stock'],
            'reason': (f"فائض {s['surplus']:.1f} في {s['branch_name']} "
                       f"(رصيد {s['current_stock']:.1f} − أمان {s['safety_stock']:.1f})"),
        })
        remaining -= qty

    allocated = sum(t['qty'] for t in transfers)
    return {
        'need': need,
        'internally_allocated': round(allocated, 3),
        'total_surplus_available': round(total_surplus, 3),
        'transfers': transfers,
        'fully_covered_internally': remaining < MIN_TRANSFER_QTY,
    }
