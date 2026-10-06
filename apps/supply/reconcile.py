"""
apps/supply/reconcile.py — the demand dedup / reconciliation engine.

Collapses same-underlying-requirement echoes across sources WITHOUT summing them, and
WITHOUT destroying provenance (every DemandSignal stays in the ledger). This is the
answer to prompt §22 (duplicate-demand protection) and §23 (source provenance).

Combination rules (deterministic, testable):
  • customer_commitment  → SUM   (each reservation / demand record = an independent
                                   waiting customer; 3 × qty 1 = 3)
  • branch_replenishment → MAX   (repeated shortage expressions of the SAME item at the
                                   SAME branch are echoes of one need; ISR 5 + WhatsApp 5
                                   = 5, not 10; 5 then 8 = 8, the larger single ask)
  • statistical          → indicator only (network market-shortage baseline; surfaced,
                                   NOT added to the demand total)

The reconciled total is a demand *hint*: net_demand in Phase 3 will reconcile THIS against
the engine's authoritative ItemDemandMetrics.gap. Phase 1 only guarantees we never double
count within the ledger and always expose where each number came from.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from .models import DemandSignal

_D0 = Decimal('0')


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def reconcile_item(item_id, *, branch_id=None) -> dict:
    """Reconcile all OPEN demand signals for one item (optionally one branch).

    Returns a dict with the deduped components, the naive raw total (for comparison /
    "double-count avoided"), and the full provenance list — nothing is hidden.
    """
    return reconcile_items([item_id], branch_id=branch_id).get(int(item_id), _empty(item_id))


def reconcile_items(item_ids, *, branch_id=None) -> dict:
    """Batched reconcile_item over many items → {item_id: reconciliation dict}."""
    item_ids = [int(i) for i in item_ids if i]
    if not item_ids:
        return {}

    qs = (DemandSignal.objects
          .filter(item_id__in=item_ids, status=DemandSignal.STATUS_OPEN)
          .select_related('item', 'branch', 'customer'))
    if branch_id is not None:
        qs = qs.filter(branch_id=branch_id)

    by_item: dict[int, list[DemandSignal]] = defaultdict(list)
    for s in qs:
        by_item[s.item_id].append(s)

    out = {}
    for iid in item_ids:
        out[iid] = _reconcile_signals(iid, by_item.get(iid, []))
    return out


def _empty(item_id) -> dict:
    return {
        'item_id': int(item_id),
        'customer_demand': 0.0,
        'branch_request': 0.0,
        'statistical': 0.0,
        'deduped_total': 0.0,
        'raw_total': 0.0,
        'double_count_avoided': 0.0,
        'signal_count': 0,
        'signals': [],
    }


def _reconcile_signals(item_id, signals: list) -> dict:
    if not signals:
        return _empty(item_id)

    customer = [s for s in signals if s.provenance_class == DemandSignal.CLASS_CUSTOMER]
    branch   = [s for s in signals if s.provenance_class == DemandSignal.CLASS_BRANCH]
    stat     = [s for s in signals if s.provenance_class == DemandSignal.CLASS_STATISTICAL]

    # customer_commitment → SUM (each is an independent waiting customer)
    customer_demand = sum((s.qty for s in customer), _D0)

    # branch_replenishment → MAX per branch (dedup echoes), then SUM across branches
    per_branch: dict = defaultdict(lambda: _D0)
    for s in branch:
        if s.qty > per_branch[s.branch_id]:
            per_branch[s.branch_id] = s.qty
    branch_request = sum(per_branch.values(), _D0)

    # statistical → indicator (largest baseline), surfaced but NOT added to the total
    statistical = max((s.qty for s in stat), default=_D0)

    deduped_total = customer_demand + branch_request
    raw_total = sum((s.qty for s in signals if s.provenance_class != DemandSignal.CLASS_STATISTICAL), _D0)

    return {
        'item_id': int(item_id),
        'customer_demand': _f(customer_demand),
        'branch_request': _f(branch_request),
        'statistical': _f(statistical),
        'deduped_total': _f(deduped_total),
        'raw_total': _f(raw_total),
        'double_count_avoided': _f(raw_total - deduped_total),
        'signal_count': len(signals),
        'signals': [_signal_provenance(s) for s in signals],
    }


def _signal_provenance(s: DemandSignal) -> dict:
    """Full provenance for one signal — every reconciled quantity is traceable (§23)."""
    return {
        'id': s.id,
        'source_type': s.source_type,
        'source_ref': s.source_ref,
        'provenance_class': s.provenance_class,
        'qty': _f(s.qty),
        'branch_id': s.branch_id,
        'branch': (s.branch.name_ar or s.branch.name) if s.branch_id else None,
        'customer_id': s.customer_id,
        'raw_name': s.raw_name,
        'source_created_at': s.source_created_at.isoformat() if s.source_created_at else None,
    }
