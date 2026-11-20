"""
apps/notifications/management/commands/notify_stock_available.py

Called automatically after every sync run (hooked into tasks.py).
Can also be run manually:
    python manage.py notify_stock_available

Scans all 'pending' reservations. When SELLABLE stock at the reservation's branch covers
EVERY line (header item + extra lines — C33, apps/reservations/stock_check.py), it:
  1. Auto-promotes reservation to 'available'
  2. Fires a notification to the assigned staff + branch call_center
  3. Logs to the reservation's chatter (ReservationActivity)
A basket with one short line, or with a free-text (manual) line, stays 'pending'.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Check stock for pending reservations and notify when available'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        from apps.reservations.models import Reservation, ReservationStatusLog
        from apps.reservations import stock_check
        from apps.notifications.models import Notification
        from apps.users.models import StaffProfile

        dry_run = options['dry_run']
        pending = Reservation.objects.filter(
            status='pending'
        ).select_related('item', 'branch', 'customer', 'assigned_to', 'created_by'
                         ).prefetch_related('lines__item')

        promoted = 0
        for r in pending:
            result = stock_check.check(r, lines=list(r.lines.all()))
            if result['overall'] != stock_check.ALL_AVAILABLE:
                continue                       # one short / manual line keeps it pending (C33)
            where = r.branch.name_ar or r.branch.name
            detail = stock_check.summary_text(result)
            first = result['lines'][0]['label']
            n = len(result['lines'])
            name = first if n == 1 else f'{first} (+{n - 1})'

            if dry_run:
                self.stdout.write(f'[DRY RUN] Would promote #{r.id} {name} ({detail})')
                continue

            # Promote status
            old_status = r.status
            ReservationStatusLog.objects.create(
                reservation=r,
                old_status=old_status,
                new_status='available',
                note=f'تلقائي: كل الأصناف متاحة في {where} — {detail}'[:500],
            )
            r.status = 'available'
            r.save(update_fields=['status', 'updated_at'])
            from apps.notifications.phone_alerts import hooks as phone_alert_hooks
            phone_alert_hooks.on_reservation_status(r, None)

            # Log to chatter
            try:
                from apps.reservations.models import ReservationActivity
                ReservationActivity.objects.create(
                    reservation=r,
                    activity_type='stock_checked',
                    message=f'✅ المخزون متاح تلقائياً لكل الأصناف في {where}: {detail}',
                    created_by=None,
                )
            except Exception:
                pass  # ReservationActivity may not exist in all installations

            # Build notification content
            title = f'📦 المخزون متاح — {name}'
            customer_name = r.customer.name if r.customer_id else (r.contact_name or 'عميل')
            body = (
                f'الحجز #{r.id} للعميل {customer_name} ({r.contact_phone}) '
                f'أصبحت كل أصنافه متاحة في فرع {where}: {detail}. '
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
            self.stdout.write(f'  ✓ Promoted #{r.id} — {name}')

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(
                f'✅ Stock check complete — {promoted} reservations promoted.'
            ))
        else:
            self.stdout.write(f'[DRY RUN] Would promote {promoted} reservations.')
