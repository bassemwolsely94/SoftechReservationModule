"""
apps/notifications/management/commands/send_weekly_summary.py

Run every Sunday at 8:00 AM via Windows Task Scheduler:
    python manage.py send_weekly_summary

Sends a digest to admins and call_center staff summarising:
- Pending reservations older than 7 days (no movement)
- Total active by status
- Urgent reservations with no follow-up date set
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta


class Command(BaseCommand):
    help = 'Send weekly summary of stale and active reservations'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        from apps.reservations.models import Reservation
        from apps.notifications.models import Notification
        from apps.users.models import StaffProfile

        dry_run = options['dry_run']
        now = timezone.now()
        week_ago = now - timedelta(days=7)

        # ── Gather stats ───────────────────────────────────────────────────────

        # Stale pending — no status change in 7+ days
        stale_pending = Reservation.objects.filter(
            status='pending',
            updated_at__lt=week_ago,
        ).count()

        # Active by status
        from django.db.models import Count
        active_counts = dict(
            Reservation.objects.filter(
                status__in=['pending', 'available', 'contacted', 'confirmed']
            ).values('status').annotate(c=Count('id')).values_list('status', 'c')
        )

        total_active = sum(active_counts.values())

        # Urgent with no follow-up
        urgent_no_followup = Reservation.objects.filter(
            priority='urgent',
            status__in=['pending', 'available', 'contacted'],
            follow_up_date__isnull=True,
        ).count()

        # Build message
        status_lines = []
        label_map = {
            'pending': 'قيد الانتظار',
            'available': 'المخزون متاح',
            'contacted': 'تم التواصل',
            'confirmed': 'مؤكد',
        }
        for s, label in label_map.items():
            if active_counts.get(s, 0) > 0:
                status_lines.append(f'  • {label}: {active_counts[s]}')

        title = f'📊 الملخص الأسبوعي — {now.strftime("%d/%m/%Y")}'
        body = (
            f'إجمالي الحجوزات النشطة: {total_active}\n'
            + '\n'.join(status_lines)
            + f'\n\nحجوزات عالقة أكثر من 7 أيام: {stale_pending}'
            + f'\nحجوزات عاجلة بلا تاريخ متابعة: {urgent_no_followup}'
        )

        if dry_run:
            self.stdout.write(f'[DRY RUN] Title: {title}')
            self.stdout.write(f'[DRY RUN] Body:\n{body}')
            return

        # Send to admins and call_center
        recipients = StaffProfile.objects.filter(
            role__in=['admin', 'call_center'],
            is_active=True,
        )

        sent = 0
        for staff in recipients:
            Notification.send_to_user(
                staff=staff,
                notification_type='weekly_summary',
                title=title,
                body=body,
            )
            sent += 1

        self.stdout.write(self.style.SUCCESS(
            f'✅ Weekly summary sent to {sent} staff members.'
        ))
        self.stdout.write(
            f'   Active: {total_active} | Stale: {stale_pending} | '
            f'Urgent no-followup: {urgent_no_followup}'
        )
