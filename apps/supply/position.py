"""
apps/supply/position.py — the read-only "business position" assembler.

Given a set of catalog items, gather the FULL picture already computed elsewhere in
the platform into one dict, so the orchestration layer (and its UI) shows the real
situation after a match without any module recomputing demand, stock, or surplus.

AUTHORITATIVE SOURCES (this module NEVER recomputes them):
  • demand / gap / target / priority / monthly_avg / in-transit / ABC
        → apps.purchasing.ItemDemandMetrics  (latest successful DemandCalculationRun)
  • network rollup (total stock / gap / monthly_avg)
        → apps.purchasing.ItemDemandAggregated
  • live per-branch on-hand stock (quarantine stores 102/103/105 excluded)
        → apps.catalog.ItemStock
  • confirmed customer demand still waiting
        → apps.reservations.Reservation  (open statuses)

Everything is READ-ONLY. The single "latest run" definition is reused from
apps.purchasing.shortage._latest_run so the whole platform agrees on which run is
current.
"""
from __future__ import annotations

from decimal import Decimal

# Quarantine / expired stores excluded from usable stock everywhere in the platform
# (see apps.shortage.stock_check, ItemDemandMetrics docs).
_EXCLUDED_STORES = frozenset({'102', '103', '105'})

# Reservation statuses that are NO LONGER waiting on stock.
_CLOSED_RESERVATION_STATUSES = ('fulfilled', 'cancelled', 'expired')


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def latest_demand_run():
    """The current authoritative DemandCalculationRun (or None). Reuses the platform's
    single definition so every module points at the same run."""
    from apps.purchasing.shortage import _latest_run
    return _latest_run(None)


class PositionService:
    """Assemble the read-only business position for a set of items.

    Usage:
        pos = PositionService.for_items([1, 2, 3])          # network-wide
        pos = PositionService.for_items([1, 2, 3], branch=b) # focus one branch

    Returns ``{item_id: position_dict}`` where each position_dict carries the
    authoritative figures (see build_position). Missing data degrades gracefully to
    zeros / empty lists — an item with no demand run yet simply has empty metrics.
    """

    @staticmethod
    def for_items(item_ids, *, branch=None, run=None) -> dict:
        item_ids = [int(i) for i in item_ids if i]
        if not item_ids:
            return {}

        run = run or latest_demand_run()

        metrics_by_item = _load_metrics(item_ids, run)         # item_id -> {branch_id: metric}
        agg_by_item     = _load_aggregated(item_ids, run)      # item_id -> aggregated
        stock_by_item   = _load_stock(item_ids)                # item_id -> [stock rows]
        resv_by_item    = _load_open_reservations(item_ids)    # item_id -> {'count','qty'}

        branch_id = getattr(branch, 'id', branch) if branch is not None else None

        out = {}
        for iid in item_ids:
            out[iid] = _build_position(
                iid,
                metrics=metrics_by_item.get(iid, {}),
                agg=agg_by_item.get(iid),
                stock_rows=stock_by_item.get(iid, []),
                reservations=resv_by_item.get(iid, {'count': 0, 'qty': 0.0}),
                focus_branch_id=branch_id,
            )
        return out


# ── Loaders (one query each, batched over all item_ids) ───────────────────────

def _load_metrics(item_ids, run) -> dict:
    if run is None:
        return {}
    from apps.purchasing.models import ItemDemandMetrics
    by_item: dict = {}
    qs = (ItemDemandMetrics.objects
          .filter(run=run, item_id__in=item_ids)
          .only('item_id', 'branch_id', 'current_stock', 'in_transit_qty',
                'monthly_avg', 'safety_stock', 'gap', 'priority', 'coverage_months',
                'abc_class'))
    for m in qs.iterator():
        by_item.setdefault(m.item_id, {})[m.branch_id] = m
    return by_item


def _load_aggregated(item_ids, run) -> dict:
    if run is None:
        return {}
    from apps.purchasing.models import ItemDemandAggregated
    return {a.item_id: a for a in ItemDemandAggregated.objects
            .filter(run=run, item_id__in=item_ids)
            .only('item_id', 'total_current_stock', 'total_in_transit',
                  'total_monthly_avg', 'total_gap', 'abc_class')}


def _load_stock(item_ids) -> dict:
    from apps.catalog.models import ItemStock
    by_item: dict = {}
    qs = (ItemStock.objects
          .filter(item_id__in=item_ids, quantity_on_hand__gt=0)
          .exclude(softech_store_code__in=_EXCLUDED_STORES)
          .select_related('branch')
          .only('item_id', 'branch_id', 'quantity_on_hand',
                'branch__name', 'branch__name_ar'))
    for row in qs.iterator():
        by_item.setdefault(row.item_id, []).append(row)
    return by_item


def _load_open_reservations(item_ids) -> dict:
    """Open (still-waiting) reservation demand per item — a confirmed-customer signal
    that distinguishes a zero-stock item with waiting customers from one with none."""
    from django.db.models import Count, Sum
    from apps.reservations.models import Reservation
    by_item: dict = {}
    qs = (Reservation.objects
          .filter(item_id__in=item_ids)
          .exclude(status__in=_CLOSED_RESERVATION_STATUSES)
          .values('item_id')
          .annotate(count=Count('id'), qty=Sum('quantity_requested')))
    for row in qs:
        by_item[row['item_id']] = {
            'count': row['count'],
            'qty': _f(row['qty']),
        }
    return by_item


# ── Position builder ──────────────────────────────────────────────────────────

def _build_position(item_id, *, metrics, agg, stock_rows, reservations, focus_branch_id):
    """Compose one item's read-only position dict from already-computed sources."""
    # Cross-branch on-hand (usable stores only)
    branches = [{
        'branch_id':   r.branch_id,
        'branch_name': r.branch.name_ar or r.branch.name,
        'qty_on_hand': _f(r.quantity_on_hand),
    } for r in sorted(stock_rows, key=lambda r: _f(r.quantity_on_hand), reverse=True)]
    total_on_hand = sum(b['qty_on_hand'] for b in branches)

    # Network figures from the aggregated rollup (authoritative), falling back to the
    # live stock sum when no demand run has produced an aggregate yet.
    if agg is not None:
        network = {
            'total_stock':     _f(agg.total_current_stock),
            'total_in_transit': _f(agg.total_in_transit),
            'total_monthly_avg': _f(agg.total_monthly_avg),
            'total_gap':       _f(agg.total_gap),
            'abc_class':       agg.abc_class,
        }
    else:
        network = {
            'total_stock':      total_on_hand,
            'total_in_transit': 0.0,
            'total_monthly_avg': 0.0,
            'total_gap':        0.0,
            'abc_class':        'X',
        }

    # Focus-branch metric (or the highest-priority branch metric when unfocused).
    focus_metric = None
    if focus_branch_id is not None:
        focus_metric = metrics.get(focus_branch_id)
    elif metrics:
        focus_metric = max(metrics.values(), key=lambda m: _f(m.priority))

    if focus_metric is not None:
        demand = {
            'branch_id':      focus_metric.branch_id,
            'current_stock':  _f(focus_metric.current_stock),
            'in_transit':     _f(focus_metric.in_transit_qty),
            'monthly_avg':    _f(focus_metric.monthly_avg),
            'safety_stock':   _f(focus_metric.safety_stock),
            'gap':            _f(focus_metric.gap),
            'priority':       _f(focus_metric.priority),
            'coverage_months': _f(focus_metric.coverage_months),
            'abc_class':      focus_metric.abc_class,
        }
    else:
        demand = None

    return {
        'item_id':      item_id,
        'demand':       demand,             # authoritative gap/target/priority (branch)
        'network':      network,            # network rollup
        'branches':     branches,           # cross-branch usable on-hand
        'total_on_hand': total_on_hand,
        'reservations': reservations,       # {count, qty} open customer demand
        'has_run':      bool(metrics) or agg is not None,
    }
