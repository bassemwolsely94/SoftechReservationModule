import logging
from django.db.models import Sum
from apps.reservations.models import Reservation
from apps.catalog.models import ItemStock, EXCLUDED_STORE_CODES

logger = logging.getLogger('elrezeiky.reservations')


def check_stock_for_pending_reservations():
    """
    Called after every sync. Scans all 'pending' reservations where the item
    now has positive stock at the reservation's branch and sends a notification
    to the assigned staff and branch staff asking them to verify and update the
    reservation status.

    IMPORTANT: Does NOT auto-promote the status. Physical stock may be allocated
    to other uses even when the ERP balance is positive. Staff must verify first.
    """
    pending = Reservation.objects.filter(
        status='pending',
        item__isnull=False,
    ).select_related('item', 'branch', 'customer', 'assigned_to')

    notified = 0
    for r in pending:
        agg = (
            ItemStock.objects
            .filter(item=r.item, branch=r.branch)
            .exclude(softech_store_code__in=EXCLUDED_STORE_CODES)
            .aggregate(total=Sum('quantity_on_hand'))
        )
        available_qty = agg['total'] or 0

        if available_qty > 0:
            customer_label = (
                f"{r.customer.name}" if r.customer_id else r.contact_name or 'العميل'
            )
            item_label = r.item_label
            branch_name = r.branch.name_ar or r.branch.name if r.branch_id else '—'
            title = f'📦 قد يكون المخزون متاحاً — {item_label}'
            body = (
                f'الفرع: {branch_name} | العميل: {customer_label} | '
                f'الكمية الظاهرة: {available_qty:.0f} | '
                f'يرجى التحقق وتحديث حالة الحجز #{r.id}'
            )

            try:
                from apps.notifications.models import Notification

                # Notify the assigned staff member directly if set
                if r.assigned_to:
                    Notification.send_to_user(
                        staff=r.assigned_to,
                        notification_type='reservation_status',
                        title=title,
                        body=body,
                        reservation=r,
                        dedup_key=f'stock_alert_{r.pk}',
                    )
                else:
                    # Fall back to branch + call center
                    if r.branch:
                        Notification.send_to_branch(
                            branch=r.branch,
                            notification_type='reservation_status',
                            title=title,
                            body=body,
                            reservation=r,
                            dedup_key=f'stock_alert_{r.pk}',
                        )
                    Notification.send_to_call_center(
                        notification_type='reservation_status',
                        title=title,
                        body=body,
                        reservation=r,
                        dedup_key=f'stock_alert_cc_{r.pk}',
                    )

                notified += 1
            except Exception as notif_err:
                logger.warning(f'Stock alert notification failed for reservation #{r.pk}: {notif_err}')

    if notified:
        logger.info(f'[stock-alert] Sent {notified} stock-availability notifications for pending reservations')
