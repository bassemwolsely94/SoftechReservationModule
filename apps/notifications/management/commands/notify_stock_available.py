"""
apps/notifications/management/commands/notify_stock_available.py

Called automatically after every sync run (hooked into tasks.py).
Can also be run manually:
    python manage.py notify_stock_available

Scans all 'pending' reservations. When stock covers the requested qty
at the reservation's branch, it:
  1. Auto-promotes reservation to 'available'
  2. Fires a notification to the assigned staff + branch call_center
  3. Logs to the reservation's chatter (ReservationActivity)
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Check stock for pending reservations and notify when available'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        from apps.reservations.models import Reservation, ReservationStatusLog
        from apps.catalog.models import ItemStock
        from apps.notifications.models import Notification
        from apps.users.models import StaffProfile

        dry_run = options['dry_run']
        pending = Reservation.objects.filter(
            status='pending'
        ).select_related('item', 'branch', 'customer', 'assigned_to', 'created_by')

        promoted = 0
        for r in pending:
            stock = ItemStock.objects.filter(
                item=r.item,
                branch=r.branch,
                quantity_on_hand__gte=r.quantity_requested,
            ).first()

            if not stock:
                continue

            if dry_run:
                self.stdout.write(
                    f'[DRY RUN] Would promote #{r.id} {r.item.name} '
                    f'({stock.quantity_on_hand} available)'
                )
                continue

            # Promote status
            old_status = r.status
            ReservationStatusLog.objects.create(
                reservation=r,
                old_status=old_status,
                new_status='available',
                note=f'تلقائي: {stock.quantity_on_hand} وحدة متاحة في {r.branch.name_ar or r.branch.name}',
            )
            r.status = 'available'
            r.save(update_fields=['status', 'updated_at'])

            # Log to chatter
            try:
                from apps.reservations.models import ReservationActivity
                ReservationActivity.objects.create(
                    reservation=r,
                    activity_type='stock_checked',
                    message=(
                        f'✅ المخزون متاح تلقائياً: {stock.quantity_on_hand} وحدة '
                        f'في {r.branch.name_ar or r.branch.name}'
                    ),
                    created_by=None,
                )
            except Exception:
                pass  # ReservationActivity may not exist in all installations

            # Build notification content
            title = f'📦 المخزون متاح — {r.item.name}'
            body = (
                f'الحجز #{r.id} للعميل {r.customer.name} ({r.contact_phone}) '
                f'أصبح المخزون متاحاً: {stock.quantity_on_hand} وحدة '
                f'في فرع {r.branch.name_ar or r.branch.name}. '
                f'يرجى التواصل مع العميل.'
            )

            # Notify assigned staff
            notified = set()
            if r.assigned_to:
                Notification.send_to_user(
                    staff=r.assigned_to,
                    notification_type='stock_available',
                    title=title,
                    body=body,
                    reservation=r,
                )
                notified.add(r.assigned_to_id)

            # Notify creator if different
            if r.created_by and r.created_by_id not in notified:
                Notification.send_to_user(
                    staff=r.created_by,
                    notification_type='stock_available',
                    title=title,
                    body=body,
                    reservation=r,
                )
                notified.add(r.created_by_id)

            # Notify call_center at that branch
            branch_cc = StaffProfile.objects.filter(
                branch=r.branch,
                role__in=['call_center', 'pharmacist'],
                is_active=True,
            ).exclude(id__in=notified)
            for staff in branch_cc:
                Notification.send_to_user(
                    staff=staff,
                    notification_type='stock_available',
                    title=title,
                    body=body,
                    reservation=r,
                )

            promoted += 1
            self.stdout.write(f'  ✓ Promoted #{r.id} — {r.item.name}')

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(
                f'✅ Stock check complete — {promoted} reservations promoted.'
            ))
        else:
            self.stdout.write(f'[DRY RUN] Would promote {promoted} reservations.')
