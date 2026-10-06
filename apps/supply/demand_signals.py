"""
apps/supply/demand_signals.py — ingestion adapters into the DemandSignal ledger.

Each adapter READS an existing source (reservations, structured demand, branch shortage
lists, the market-shortage detector) and UPSERTS DemandSignal rows idempotently. It never
mutates the source — this is a one-way, re-runnable projection, like the platform's other
sync engines. Running it twice produces the same ledger (upsert on (source_type,
source_ref)); rows whose source is no longer an active demand are marked superseded.

Provenance-class mapping (see models + reconcile):
  reservation / demand_item → customer_commitment   (additive)
  shortage_item             → branch_replenishment   (echoes deduped)
  market_shortage           → statistical            (indicator)

Adapters ingest rows that carry a resolved catalog item (item_id) — an unmatched raw line
has no item to reconcile against yet; it is left in its source until matched. This keeps
Phase 1 reconciliation unambiguous. (Unmatched-signal carry-through is a later refinement.)
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from .models import DemandSignal

logger = logging.getLogger('elrezeiky.supply')


# ── Core upsert ───────────────────────────────────────────────────────────────

def record_signal(source_type, source_ref, *, provenance_class, qty,
                  item=None, item_id=None, branch=None, branch_id=None,
                  customer=None, customer_id=None, raw_name='',
                  status=DemandSignal.STATUS_OPEN, source_created_at=None):
    """Idempotent upsert of one DemandSignal keyed on (source_type, source_ref).

    Returns (signal, created). Re-recording the same source row updates its mutable
    fields (qty / status / item) rather than duplicating it."""
    defaults = {
        'provenance_class': provenance_class,
        'qty': qty or 0,
        'status': status,
        'raw_name': raw_name or '',
        'source_created_at': source_created_at,
    }
    if item is not None or item_id is not None:
        defaults['item_id'] = item_id if item_id is not None else item.pk
    if branch is not None or branch_id is not None:
        defaults['branch_id'] = branch_id if branch_id is not None else branch.pk
    if customer is not None or customer_id is not None:
        defaults['customer_id'] = customer_id if customer_id is not None else customer.pk

    signal, created = DemandSignal.objects.update_or_create(
        source_type=source_type, source_ref=str(source_ref), defaults=defaults,
    )
    return signal, created


def _close_stale(source_type, active_refs, *, status=DemandSignal.STATUS_SUPERSEDED) -> int:
    """Mark OPEN signals of a source type whose source_ref is no longer active as closed.

    Keeps the reconciler honest: only currently-active source rows count as open demand.
    Provenance is preserved — the row stays, only its status changes."""
    stale = (DemandSignal.objects
             .filter(source_type=source_type, status=DemandSignal.STATUS_OPEN)
             .exclude(source_ref__in=[str(r) for r in active_refs]))
    return stale.update(status=status, updated_at=timezone.now())


# ── Reservation adapter (customer_commitment) ─────────────────────────────────

_RES_CANCELLED = ('cancelled', 'expired')


@transaction.atomic
def sync_reservations() -> dict:
    """Project active reservations (and their multi-item lines) into the ledger.

    Each reservation/line with a catalog item = one independent customer commitment.
    Fulfilled/cancelled/expired reservations are excluded and their open signals closed."""
    from apps.reservations.models import Reservation

    created = updated = 0
    active_refs = []
    qs = (Reservation.objects
          .exclude(status__in=('fulfilled',) + _RES_CANCELLED)
          .select_related('customer', 'branch', 'item')
          .prefetch_related('lines'))
    for res in qs.iterator():
        lines = [l for l in res.lines.all() if l.item_id]
        # Multi-item basket → one signal per line; else the header item.
        entries = ([(f'{res.pk}:{l.pk}', l.item_id, l.quantity_requested) for l in lines]
                   if lines else
                   ([(str(res.pk), res.item_id, res.quantity_requested)] if res.item_id else []))
        for ref, item_id, qty in entries:
            active_refs.append(ref)
            _, was_created = record_signal(
                DemandSignal.SOURCE_RESERVATION, ref,
                provenance_class=DemandSignal.CLASS_CUSTOMER,
                qty=qty, item_id=item_id, branch=res.branch, customer_id=res.customer_id,
                source_created_at=res.created_at,
            )
            created += was_created
            updated += (not was_created)

    closed = _close_stale(DemandSignal.SOURCE_RESERVATION, active_refs)
    return {'source': 'reservation', 'created': created, 'updated': updated, 'closed': closed}


# ── Structured demand adapter (customer_commitment) ───────────────────────────

_DEMAND_ITEM_ACTIVE = ('pending', 'sourcing', 'available_again')


@transaction.atomic
def sync_demand_items() -> dict:
    """Project active DemandItem lines (structured customer demand) into the ledger."""
    from apps.demand.models import DemandItem

    created = updated = 0
    active_refs = []
    qs = (DemandItem.objects
          .filter(item_id__isnull=False, item_status__in=_DEMAND_ITEM_ACTIVE)
          .select_related('demand', 'demand__branch', 'demand__customer', 'item'))
    for di in qs.iterator():
        ref = str(di.pk)
        active_refs.append(ref)
        _, was_created = record_signal(
            DemandSignal.SOURCE_DEMAND_ITEM, ref,
            provenance_class=DemandSignal.CLASS_CUSTOMER,
            qty=di.quantity, item_id=di.item_id,
            branch_id=di.demand.branch_id, customer_id=di.demand.customer_id,
            source_created_at=di.demand.created_at,
        )
        created += was_created
        updated += (not was_created)

    closed = _close_stale(DemandSignal.SOURCE_DEMAND_ITEM, active_refs)
    return {'source': 'demand_item', 'created': created, 'updated': updated, 'closed': closed}


# ── Branch shortage adapter (branch_replenishment) ────────────────────────────

@transaction.atomic
def sync_shortage_items() -> dict:
    """Project matched shortage-list items (branch stock needs) into the ledger.

    Items on a resolved list, or without a catalog match, are excluded; the reconciler
    dedups repeated expressions of the same item at the same branch (max, not sum)."""
    from apps.shortage.models import ShortageItem

    created = updated = 0
    active_refs = []
    qs = (ShortageItem.objects
          .filter(item_id__isnull=False)
          .exclude(shortage_list__status='resolved')
          .select_related('item', 'shortage_list', 'shortage_list__branch'))
    for si in qs.iterator():
        ref = str(si.pk)
        active_refs.append(ref)
        _, was_created = record_signal(
            DemandSignal.SOURCE_SHORTAGE, ref,
            provenance_class=DemandSignal.CLASS_BRANCH,
            qty=si.quantity_needed, item_id=si.item_id,
            branch_id=si.shortage_list.branch_id, raw_name=si.raw_name,
            source_created_at=si.created_at,
        )
        created += was_created
        updated += (not was_created)

    closed = _close_stale(DemandSignal.SOURCE_SHORTAGE, active_refs)
    return {'source': 'shortage_item', 'created': created, 'updated': updated, 'closed': closed}


# ── Market-shortage adapter (statistical) ─────────────────────────────────────

@transaction.atomic
def sync_market_shortage() -> dict:
    """Project the market-shortage detector's current candidates into the ledger as
    network-level statistical baselines (one per item, qty = historical monthly demand).

    Read-only over apps.purchasing.shortage; gracefully no-ops when no demand run exists."""
    from apps.purchasing.shortage import compute_shortage_candidates

    try:
        candidates = compute_shortage_candidates()
    except Exception as exc:
        logger.warning('sync_market_shortage: detector unavailable (%s)', exc)
        candidates = []

    created = updated = 0
    active_refs = []
    for c in candidates:
        ref = str(c.item_id)
        active_refs.append(ref)
        _, was_created = record_signal(
            DemandSignal.SOURCE_MARKET, ref,
            provenance_class=DemandSignal.CLASS_STATISTICAL,
            qty=c.monthly_hist, item_id=c.item_id, raw_name=c.name,
        )
        created += was_created
        updated += (not was_created)

    closed = _close_stale(DemandSignal.SOURCE_MARKET, active_refs)
    return {'source': 'market_shortage', 'created': created, 'updated': updated, 'closed': closed}


# ── Orchestrator ──────────────────────────────────────────────────────────────

def sync_all() -> dict:
    """Run every adapter; returns per-source counts + totals. Order is irrelevant
    (each adapter owns its own source_type namespace)."""
    results = [
        sync_reservations(),
        sync_demand_items(),
        sync_shortage_items(),
        sync_market_shortage(),
    ]
    totals = {'created': 0, 'updated': 0, 'closed': 0}
    for r in results:
        for k in totals:
            totals[k] += r.get(k, 0)
    return {'sources': results, 'totals': totals}
