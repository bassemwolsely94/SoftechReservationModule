"""
apps/transfers/management/commands/check_transfer_sla.py

Schedule hourly via APScheduler or Windows Task Scheduler:
  python manage.py check_transfer_sla

Sends a notification to admin/purchasing when a pending transfer has not
been reviewed within transfer_sla_hours (default 24h) of submission.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Notify admin/purchasing of pending transfers that breached SLA'

    def handle(self, *args, **options):
        from datetime import timedelta
        from apps.transfers.models import TransferRequest
        from apps.notifications.models import Notification
        from apps.config.models import SystemSetting

        try:
            sla_hours = int(
                SystemSetting.objects.filter(key='transfer_sla_hours').values_list('value', flat=True).first()
                or 24
            )
        except Exception:
            sla_hours = 24

        cutoff = timezone.now() - timedelta(hours=sla_hours)

        breached = TransferRequest.objects.filter(
            status='pending',
            submitted_at__isnull=False,
            submitted_at__lte=cutoff,
        ).select_related('requesting_branch', 'supplying_branch')

        notified = 0
        for tr in breached:
            hours_elapsed = int((timezone.now() - tr.submitted_at).total_seconds() / 3600)
            sup_branch_name = (
                (tr.supplying_branch.name_ar or tr.supplying_branch.name)
                if tr.supplying_branch_id else 'غير محدد'
            )
            title = f'تنبيه SLA — {tr.request_number}'
            body  = (
                f'الطلب منتظر رد الفرع المصدر ({sup_branch_name}) '
                f'منذ {hours_elapsed} ساعة — تجاوز مهلة {sla_hours} ساعة.'
            )
            dedup = f'sla_breach_{tr.id}_{timezone.now().strftime("%Y%m%d%H")}'
            try:
                if tr.supplying_branch_id:
                    Notification.send_to_branch(
                        branch=tr.supplying_branch,
                        notification_type='transfer_request',
                        title=title,
                        body=body,
                        transfer_id=tr.id,
                        dedup_key=dedup,
                        include_admins=True,
                    )
                else:
                    # No supplying branch — notify admins/purchasing only
                    Notification.send_to_admins(
                        notification_type='transfer_request',
                        title=title,
                        body=body,
                        transfer_id=tr.id,
                        dedup_key=dedup,
                    )
                notified += 1
                self.stdout.write(
                    self.style.WARNING(
                        f'  ⚠ SLA breached: {tr.request_number} — {hours_elapsed}h elapsed'
                    )
                )
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  ✗ Failed to notify {tr.request_number}: {e}'))

        self.stdout.write(
            self.style.SUCCESS(f'✅ SLA check done — {notified} breach notifications sent')
        )
