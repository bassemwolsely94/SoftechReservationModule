"""
apps/supply/engine/demand.py — net demand resolution.

Combines the AUTHORITATIVE engine gap (apps.purchasing.ItemDemandMetrics) with the
DemandSignal ledger (apps/supply/reconcile.py) into one explainable "required" quantity,
WITHOUT recomputing either and WITHOUT double-counting.

RULE (deterministic, documented) — both terms are NET requirements on the same basis:

    engine_need = max(0, gap)
    ledger_need = max(0, ledger_demand − current_stock − in_transit)
    gross       = max(engine_need, ledger_need)
    required    = max(0, gross − pending_internal_in − pending_orders)

  • pending_internal_in / pending_orders (engine/commitments.py) are quantities this module
    already put in motion — open, undispatched transfer drafts INTO the branch, and orders
    placed through the order list and not yet received. Netting them out is what stops the
    same need being transferred or ordered twice (§14/§22/§31).

  • gap (ItemDemandMetrics) is ALREADY net of on-hand AND in-transit: the purchasing engine
    computes gap = calc_gap(current_stock + in_transit, …) (engine.py). So in-transit must
    NOT be subtracted again downstream — doing so double-counts incoming stock.
  • ledger_demand is the GROSS reconciled DemandSignal total (customer commitments + branch
    requests). A commitment is a claim ON stock, so it only creates a purchasing need for the
    part not already covered by what we hold or have in transit (§7: never buy for a
    reservation the shelf can already serve). It still CATCHES what the sales history misses
    — zero stock + 3 waiting customers + gap 0 → required 3.

We take the MAX (not the sum): a branch shortage list usually re-expresses the engine gap,
and a reservation is often the reason the gap exists — summing would double-count. Every
component is returned so the operator sees exactly where the number came from (§19/§20/§23).
"""
from __future__ import annotations

from ..position import PositionService


def net_demand(item_id, *, branch_id=None) -> dict:
    """Resolve the required quantity for an item (optionally at one branch).

    Returns the full component breakdown + the single ``required`` figure. Read-only."""
    return net_demand_many([item_id], branch_id=branch_id)[int(item_id)]


def net_demand_many(item_ids, *, branch_id=None) -> dict:
    """net_demand for many items at once ({item_id: dict}) — the position and the ledger
    are loaded in one batch each (a supplier list of 140 items × several branches would
    otherwise cost thousands of queries). Same rule, same numbers as net_demand.

    Branch scope uses ONLY that branch's own figures. A branch with no engine metric for
    the item has no engine need, and its stock is its live on-hand (owner decision
    2026-10-05 — it used to fall back to the NETWORK gap and stock, e.g. a branch case
    showing the company gap 16 for a branch that needed 1)."""
    from ..reconcile import reconcile_items
    item_ids = [int(i) for i in item_ids if i]
    positions = PositionService.for_items(item_ids, branch=branch_id)
    recons = reconcile_items(item_ids, branch_id=branch_id)
    return {iid: _compose(iid, positions.get(iid, {}), recons[iid], branch_id) for iid in item_ids}


def _compose(item_id, pos, recon, branch_id) -> dict:
    demand = pos.get('demand')
    network = pos.get('network') or {}

    if branch_id is not None:
        if demand and demand.get('branch_id') == branch_id:
            calculated_demand = max(0.0, demand.get('gap', 0.0))
            confirmed_incoming = demand.get('in_transit', 0.0)
            current_stock = demand.get('current_stock', 0.0)
        else:
            # No target for this item at the branch: no engine need; what it holds is its
            # live on-hand (so a waiting customer is netted against real shelf stock).
            calculated_demand = confirmed_incoming = 0.0
            current_stock = sum(b['qty_on_hand'] for b in (pos.get('branches') or [])
                                if b['branch_id'] == branch_id)
    else:
        # Network scope (no single destination branch).
        calculated_demand = max(0.0, network.get('total_gap', 0.0))
        confirmed_incoming = network.get('total_in_transit', 0.0)
        current_stock = network.get('total_stock', 0.0)

    ledger_demand = recon['deduped_total']
    # Commitments only need buying for the part our stock + in-transit can't cover.
    ledger_need = max(0.0, ledger_demand - current_stock - confirmed_incoming)
    gross_requirement = max(calculated_demand, ledger_need)

    # What this module already set in motion (never transfer / order the same need twice).
    from .commitments import pending_internal_in, pending_orders
    internal_in = pending_internal_in(item_id, branch_id)
    ordered = pending_orders(item_id, branch_id)
    required = max(0.0, gross_requirement - internal_in - ordered)

    return {
        'item_id': item_id,
        'branch_id': branch_id,
        'required': required,                       # NET requirement after everything in motion
        'gross_requirement': gross_requirement,     # before this module's own commitments
        'pending_internal_in': internal_in,         # open, undispatched transfer drafts in
        'pending_orders': ordered,                  # ordered via this module, not yet received
        'calculated_demand': calculated_demand,     # engine gap⁺ (already net of stock + in-transit)
        'ledger_demand': ledger_demand,             # reconciled, deduped signals (gross)
        'ledger_need': ledger_need,                 # ledger demand not covered by stock/in-transit
        'customer_demand': recon['customer_demand'],
        'branch_request': recon['branch_request'],
        'statistical': recon['statistical'],
        'current_stock': current_stock,
        'confirmed_incoming': confirmed_incoming,   # in-transit — informational, ALREADY netted
        'has_run': pos.get('has_run', False),
        'double_count_avoided': recon['double_count_avoided'],
        'provenance': recon['signals'],
    }
