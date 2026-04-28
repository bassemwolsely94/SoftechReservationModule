import logging
from apps.reservations.models import Reservation, ReservationStatusLog
from apps.catalog.models import ItemStock

logger = logging.getLogger('elrezeiky.reservations')


def check_stock_for_pending_reservations():
    """
    Called after every sync. Scans all 'pending' reservations and
    auto-promotes to 'available' if stock now covers the requested quantity.
    """
    pending = Reservation.objects.filter(
        status='pending'
    ).select_related('item', 'branch', 'customer')

    flagged = 0
    for r in pending:
        stock = ItemStock.objects.filter(
            item=r.item,
            branch=r.branch,
            quantity_on_hand__gte=r.quantity_requested
        ).first()

        if stock:
            ReservationStatusLog.objects.create(
                reservation=r,
                old_status='pending',
                new_status='available',
                note=f'تلقائي: {stock.quantity_on_hand} وحدة متاحة في {r.branch.name}',
            )
            r.status = 'available'
            r.save(update_fields=['status', 'updated_at'])
            flagged += 1
            logger.info(
                f"Stock available: Reservation #{r.id} "
                f"{r.item.name} → {r.customer.name} ({r.customer.phone})"
            )

    if flagged:
        logger.info(f"Auto-flagged {flagged} reservations as available after sync")
