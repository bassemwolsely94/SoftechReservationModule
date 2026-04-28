"""
apps/notifications/management/commands/send_followup_reminders.py

Run daily at 9:00 AM via Windows Task Scheduler:
    python manage.py send_followup_reminders

Notifies ALL staff assigned to or who created reservations that have
follow_up_date = today and are still in an active status.
Also notifies the branch's call_center and pharmacist staff.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Send daily follow-up reminders for reservations due today'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            default=None,
            help='Override date to check (YYYY-MM-DD). Defaults to today.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would be sent without creating notifications.',
        )

    def handle(self, *args, **options):
        from apps.reservations.models import Reservation
        from apps.notifications.models import Notification

        dry_run = options['dry_run']
        date_str = options['date']

        if date_str:
            from datetime import date
            target_date = date.fromisoformat(date_str)
        else:
            target_date = timezone.now().date()

        self.stdout.write(f'📅 Follow-up reminders for {target_date}')

        reservations = Reservation.objects.filter(
            follow_up_date=target_date,
            status__in=['pending', 'available', 'contacted', 'confirmed'],
        ).select_related(
            'customer', 'item', 'branch',
            'assigned_to__user', 'created_by__user',
        )

        if not reservations.exists():
            self.stdout.write(self.style.SUCCESS('✅ No follow-ups due today.'))
            return

        total_sent = 0

        for r in reservations:
            title = f'📅 متابعة مستحقة اليوم — {r.item.name}'
            body = (
                f'الحجز #{r.id} للعميل {r.customer.name} ({r.contact_phone}) '
                f'بفرع {r.branch.name_ar or r.branch.name} '
                f'يستحق متابعة اليوم.\n'
                f'الحالة الحالية: {r.get_status_display()}'
            )

            if dry_run:
                self.stdout.write(f'  [DRY RUN] Would notify for reservation #{r.id} — {r.item.name}')
                continue

            # Notify assigned staff
            recipients_notified = set()
            if r.assigned_to_id:
                Notification.send_to_user(
                    staff=r.assigned_to,
                    notification_type='follow_up_due',
                    title=title,
                    body=body,
                    reservation=r,
                )
                recipients_notified.add(r.assigned_to_id)
                total_sent += 1

            # Notify creator (if different)
            if r.created_by_id and r.created_by_id not in recipients_notified:
                Notification.send_to_user(
                    staff=r.created_by,
                    notification_type='follow_up_due',
                    title=title,
                    body=body,
                    reservation=r,
                )
                recipients_notified.add(r.created_by_id)
                total_sent += 1

            # Notify branch call_center + pharmacist (excluding already notified)
            from apps.users.models import StaffProfile
            branch_staff = StaffProfile.objects.filter(
                branch=r.branch,
                role__in=['call_center', 'pharmacist'],
                is_active=True,
            ).exclude(id__in=recipients_notified)

            for staff in branch_staff:
                Notification.send_to_user(
                    staff=staff,
                    notification_type='follow_up_due',
                    title=title,
                    body=body,
                    reservation=r,
                )
                total_sent += 1

            self.stdout.write(f'  ✓ Reservation #{r.id} — {r.item.name}')

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(
                f'✅ Done — {reservations.count()} reservations, {total_sent} notifications sent.'
            ))
