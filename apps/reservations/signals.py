import logging
from django.db.models import Sum
from apps.reservations.models import Reservation, ReservationStatusLog
from apps.catalog.models import ItemStock, EXCLUDED_STORE_CODES

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
        # Manual-item reservations have no catalog entry — skip stock check
        if not r.item_id:
            continue

        agg = (
            ItemStock.objects
            .filter(item=r.item, branch=r.branch)
            .exclude(softech_store_code__in=EXCLUDED_STORE_CODES)
            .aggregate(total=Sum('quantity_on_hand'))
        )
        available_qty = agg['total'] or 0

        if available_qty >= r.quantity_requested:
            ReservationStatusLog.objects.create(
                reservation=r,
                old_status='pending',
                new_status='available',
                note=f'تلقائي: {available_qty} وحدة متاحة في {r.branch.name}',
            )
            r.status = 'available'
            r.save(update_fields=['status', 'updated_at'])
            flagged += 1
            customer_label = (
                f"{r.customer.name} ({r.customer.phone})"
                if r.customer_id else r.contact_name
            )
            logger.info(
                f"Stock available: Reservation #{r.id} "
                f"{r.item_label} → {customer_label}"
            )

    if flagged:
        logger.info(f"Auto-flagged {flagged} reservations as available after sync")
