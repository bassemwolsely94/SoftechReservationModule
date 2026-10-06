"""
apps/supply/engine/commitments.py — quantities ALREADY committed but not yet visible in
stock, so the engine never allocates the same surplus twice or orders the same need twice
(§14 / §22 / §31).

Two sources, both read-only:

  • Open transfer requests (apps.transfers) that have not been dispatched yet.
    A draft / pending / approved / needs-revision / sent-to-ERP request that has not been
    physically dispatched still sits in the source branch's stock in SOFTECH, so:
        - it RESERVES that much of the source's surplus   (committed_outbound)
        - it is INCOMING for the requesting branch         (pending_internal_in)
    Once dispatched, SOFTECH books the doccode-125 issue: the source stock drops and the
    engine counts it as in-transit at the destination (already netted in the gap) — so a
    dispatched request is deliberately NOT counted here (no double count).

  • Open purchase decisions recorded by this module (SupplyDecision kind=purchase,
    receipt_status=open) — an order we placed through the order list and haven't received.

Pending supplier POs raised OUTSIDE this module are not visible yet: SOFTECH's
stkbal.onorderqty is only mirrored where nowqty > 0 (apps/sync QUERY_STOCK), i.e. never
for the zero-stock items that matter here. Widening that sync is a separate, gated change.
"""
from __future__ import annotations

from collections import defaultdict

# Transfer statuses whose quantity has NOT yet left the source in SOFTECH.
OPEN_TRANSFER_STATUSES = ('draft', 'pending', 'approved', 'needs_revision', 'sent_to_erp')


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def _open_transfer_items(item_id):
    from apps.transfers.models import TransferRequestItem
    return (TransferRequestItem.objects
            .filter(item_id=int(item_id),
                    request__status__in=OPEN_TRANSFER_STATUSES,
                    request__dispatched_at__isnull=True)
            .select_related('request'))


def _line_qty(tri) -> float:
    # An approver may have trimmed the quantity; that is what will actually move.
    return _f(tri.approved_quantity if tri.approved_quantity is not None else tri.quantity)


def committed_outbound_by_branch(item_id) -> dict:
    """{source_branch_id: qty} reserved by open, undispatched transfer requests."""
    out: dict = defaultdict(float)
    for tri in _open_transfer_items(item_id):
        if tri.request.supplying_branch_id:
            out[tri.request.supplying_branch_id] += _line_qty(tri)
    return dict(out)


def pending_internal_in(item_id, dest_branch_id) -> float:
    """Qty on open, undispatched transfer requests INTO ``dest_branch_id``."""
    if dest_branch_id is None:
        return 0.0          # internal moves are network-neutral
    return sum(_line_qty(t) for t in _open_transfer_items(item_id)
               if t.request.requesting_branch_id == dest_branch_id)


def pending_orders(item_id, branch_id=None) -> float:
    """Qty ordered through this module and not yet received (network-wide when branch
    is None)."""
    from ..models import SupplyDecision
    qs = SupplyDecision.objects.filter(
        item_id=int(item_id), kind=SupplyDecision.KIND_PURCHASE,
        receipt_status=SupplyDecision.RECEIPT_OPEN)
    if branch_id is not None:
        qs = qs.filter(branch_id=branch_id)
    return sum(_f(d.decided_qty) for d in qs.only('decided_qty'))
