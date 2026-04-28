"""
apps/notifications/management/commands/send_monthly_report.py

Run on the 1st of every month at 7:00 AM via Windows Task Scheduler:
    python manage.py send_monthly_report

Delivers a rich monthly digest to admin + purchasing + call_center:
- Reservations fulfilled last month
- Expired / cancelled breakdown
- Transfer request summary (accepted / rejected / unfulfilled)
- Top items reserved
- Branch performance ranking
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta


class Command(BaseCommand):
    help = 'Send monthly operations report'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument(
            '--month',
            type=str, default=None,
            help='Override month as YYYY-MM (defaults to last month)',
        )

    def handle(self, *args, **options):
        from apps.reservations.models import Reservation
        from apps.notifications.models import Notification
        from apps.users.models import StaffProfile
        from django.db.models import Count, Sum

        dry_run = options['dry_run']
        now = timezone.now()

        # Determine the reporting period (last calendar month)
        if options['month']:
            year, month = map(int, options['month'].split('-'))
        else:
            first_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            last_month_end = first_this_month - timedelta(seconds=1)
            year = last_month_end.year
            month = last_month_end.month

        from django.utils.timezone import make_aware
        from datetime import datetime
        period_start = make_aware(datetime(year, month, 1))
        # Last day of month
        if month == 12:
            period_end = make_aware(datetime(year + 1, 1, 1))
        else:
            period_end = make_aware(datetime(year, month + 1, 1))

        month_name_ar = {
            1: 'يناير', 2: 'فبراير', 3: 'مارس', 4: 'أبريل',
            5: 'مايو', 6: 'يونيو', 7: 'يوليو', 8: 'أغسطس',
            9: 'سبتمبر', 10: 'أكتوبر', 11: 'نوفمبر', 12: 'ديسمبر',
        }[month]

        qs = Reservation.objects.filter(
            updated_at__gte=period_start,
            updated_at__lt=period_end,
        )

        # ── Reservation stats ──────────────────────────────────────────────────
        fulfilled = qs.filter(status='fulfilled').count()
        cancelled = qs.filter(status='cancelled').count()
        expired = qs.filter(status='expired').count()

        # Top 5 reserved items
        top_items = (
            Reservation.objects.filter(
                created_at__gte=period_start,
                created_at__lt=period_end,
            )
            .values('item__name')
            .annotate(count=Count('id'))
            .order_by('-count')[:5]
        )

        # Branch fulfillment ranking
        branch_fulfilled = (
            qs.filter(status='fulfilled')
            .values('branch__name_ar', 'branch__name')
            .annotate(count=Count('id'))
            .order_by('-count')[:6]
        )

        # ── Transfer stats (if transfers app is present) ───────────────────────
        transfer_stats = {}
        try:
            from django.apps import apps as django_apps
            TransferRequest = django_apps.get_model('transfers', 'TransferRequest')
            tr_qs = TransferRequest.objects.filter(
                created_at__gte=period_start,
                created_at__lt=period_end,
            )
            transfer_stats = dict(
                tr_qs.values('status').annotate(c=Count('id')).values_list('status', 'c')
            )
        except Exception:
            pass  # transfers app not installed yet

        # ── Build body ────────────────────────────────────────────────────────
        lines = [
            f'📈 تقرير شهر {month_name_ar} {year}',
            '',
            '── الحجوزات ──────────────',
            f'تم التسليم:  {fulfilled}',
            f'ملغي:        {cancelled}',
            f'منتهي:       {expired}',
            '',
        ]

        if top_items:
            lines.append('── أكثر الأصناف طلباً ──')
            for item in top_items:
                lines.append(f'  • {item["item__name"]}: {item["count"]} حجز')
            lines.append('')

        if branch_fulfilled:
            lines.append('── أداء الفروع (تسليم) ──')
            for b in branch_fulfilled:
                name = b['branch__name_ar'] or b['branch__name']
                lines.append(f'  • {name}: {b["count"]}')
            lines.append('')

        if transfer_stats:
            lines.append('── طلبات التحويل ────────')
            status_ar = {
                'accepted': 'مقبول', 'partial': 'جزئي',
                'rejected': 'مرفوض', 'fulfilled': 'منفَّذ',
                'cancelled': 'ملغي',
            }
            for s, count in transfer_stats.items():
                lines.append(f'  • {status_ar.get(s, s)}: {count}')

        body = '\n'.join(lines)
        title = f'📈 التقرير الشهري — {month_name_ar} {year}'

        if dry_run:
            self.stdout.write(f'[DRY RUN] {title}')
            self.stdout.write(body)
            return

        recipients = StaffProfile.objects.filter(
            role__in=['admin', 'purchasing', 'call_center'],
            is_active=True,
        )

        sent = 0
        for staff in recipients:
            Notification.send_to_user(
                staff=staff,
                notification_type='monthly_report',
                title=title,
                body=body,
            )
            sent += 1

        self.stdout.write(self.style.SUCCESS(
            f'✅ Monthly report sent to {sent} staff. '
            f'Fulfilled: {fulfilled} | Cancelled: {cancelled} | Expired: {expired}'
        ))
