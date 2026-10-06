"""
apps/notifications/management/commands/send_followup_reminders.py

Sends daily reminders for TWO distinct follow-up systems:

  A) Reservation follow-ups  (apps/reservations)
     — Reservations with follow_up_date = today and status still active

  B) Chronic refill follow-up tasks  (apps/followups)
     — FollowUpTasks with due_date = today or overdue (pending/called)
     — Notifies assigned staff + branch call_center
     — Includes a WhatsApp-ready deep link for each task

Run: python manage.py send_followup_reminders
     python manage.py send_followup_reminders --dry-run
     python manage.py send_followup_reminders --date 2024-03-15
     python manage.py send_followup_reminders --overdue-days 7
     python manage.py send_followup_reminders --skip-reservations
     python manage.py send_followup_reminders --skip-chronic
"""
from django.core.management.base import BaseCommand
from django.db import models
from django.utils import timezone


class Command(BaseCommand):
    help = 'Send daily follow-up reminders for reservations AND chronic refill tasks'

    def add_arguments(self, parser):
        parser.add_argument('--date',               type=str, default=None,
            help='Override target date (YYYY-MM-DD). Defaults to today.')
        parser.add_argument('--dry-run',            action='store_true',
            help='Print what would be sent without creating notifications.')
        parser.add_argument('--overdue-days',       type=int, default=3,
            help='Include FollowUpTasks due in the last N days (default 3)')
        parser.add_argument('--skip-reservations',  action='store_true',
            help='Skip reservation follow-ups')
        parser.add_argument('--skip-chronic',       action='store_true',
            help='Skip chronic refill task follow-ups')
        parser.add_argument('--skip-demand-recovery', action='store_true',
            help='Skip back-in-stock demand recovery reminders')

    def _make_stdout_safe(self):
        """Windows consoles default to cp1256 here, so the emoji in our output
        would raise UnicodeEncodeError. Wrap write() to fall back to a
        replace-encoded string only when the active console can't represent it.
        No-op on UTF-8 terminals and under the scheduler."""
        enc = (getattr(self.stdout, '_out', None) and getattr(self.stdout._out, 'encoding', None)) or 'utf-8'
        if enc.lower().replace('-', '') in ('utf8', 'utf16', 'utf32'):
            return
        orig_write = self.stdout.write
        def safe_write(msg='', *a, **k):
            try:
                return orig_write(msg, *a, **k)
            except UnicodeEncodeError:
                return orig_write(str(msg).encode(enc, 'replace').decode(enc, 'replace'), *a, **k)
        self.stdout.write = safe_write

    def handle(self, *args, **options):
        self._make_stdout_safe()
        dry_run      = options['dry_run']
        overdue_days = options['overdue_days']
        date_str     = options['date']

        if date_str:
            from datetime import date
            target_date = date.fromisoformat(date_str)
        else:
            target_date = timezone.now().date()

        self.stdout.write(f'📅 Follow-up reminders for {target_date}')
        total_sent = 0

        # ── A: Reservation follow-ups ─────────────────────────────────────────
        if not options['skip_reservations']:
            sent = self._handle_reservations(target_date, dry_run)
            total_sent += sent
            self.stdout.write(self.style.SUCCESS(
                f'  Reservations: {sent} notifications'
                + ('  [DRY RUN]' if dry_run else '')
            ))

        # ── B: Chronic refill follow-up tasks ─────────────────────────────────
        if not options['skip_chronic']:
            sent = self._handle_chronic_tasks(target_date, overdue_days, dry_run)
            total_sent += sent
            self.stdout.write(self.style.SUCCESS(
                f'  Chronic tasks: {sent} notifications'
                + ('  [DRY RUN]' if dry_run else '')
            ))

        # ── C: Back-in-stock demand recovery reminders ────────────────────────
        if not options['skip_demand_recovery']:
            sent = self._handle_demand_recovery(dry_run)
            total_sent += sent
            self.stdout.write(self.style.SUCCESS(
                f'  Demand recovery: {sent} notifications'
                + ('  [DRY RUN]' if dry_run else '')
            ))

        self.stdout.write(self.style.SUCCESS(
            f'✅ Done — {total_sent} total notifications sent.'
        ))

    # ── A: Reservation follow-ups ─────────────────────────────────────────────

    def _handle_reservations(self, target_date, dry_run: bool) -> int:
        from apps.reservations.models import Reservation
        from apps.notifications.models import Notification

        reservations = Reservation.objects.filter(
            follow_up_date=target_date,
            status__in=['pending', 'available', 'contacted', 'confirmed'],
        ).select_related('customer', 'item', 'branch', 'assigned_to__user', 'created_by__user')

        total_sent = 0
        for r in reservations:
            item_name = r.item.name if r.item else r.manual_item_name or '—'
            customer_name = r.customer.name if r.customer else r.contact_phone
            title = f'📅 متابعة مستحقة اليوم — {item_name}'
            body  = (
                f'الحجز #{r.id} للعميل {customer_name} '
                f'بفرع {r.branch.name_ar or r.branch.name}. '
                f'الحالة: {r.get_status_display()}'
            )

            if dry_run:
                self.stdout.write(f'  [DRY RUN] Reservation #{r.id} — {item_name}')
                total_sent += 1
                continue

            recipients_notified = set()
            for attr in ('assigned_to', 'created_by'):
                staff = getattr(r, attr, None)
                if staff and staff.pk not in recipients_notified:
                    try:
                        Notification.objects.create(
                            recipient=staff, title=title, body=body,
                            notification_type='follow_up_due',
                        )
                        recipients_notified.add(staff.pk)
                        total_sent += 1
                    except Exception:
                        pass

            from apps.users.models import StaffProfile
            for staff in StaffProfile.objects.filter(
                branch=r.branch, role__in=['call_center', 'pharmacist'], is_active=True,
            ).exclude(pk__in=recipients_notified):
                try:
                    Notification.objects.create(
                        recipient=staff, title=title, body=body,
                        notification_type='follow_up_due',
                    )
                    total_sent += 1
                except Exception:
                    pass

            self.stdout.write(f'  ✓ Reservation #{r.id} — {item_name}')

        return total_sent

    # ── B: Chronic refill tasks ───────────────────────────────────────────────
    # IMPORTANT: only notify for tasks that are pinned OR have assigned_to set.
    # Auto-generated tasks (is_pinned=False, assigned_to=None) are SILENT.
    # This prevents flooding the notification system with 64k auto-generated tasks.

    def _handle_chronic_tasks(self, target_date, overdue_days: int, dry_run: bool) -> int:
        from datetime import timedelta
        from apps.followups.models import FollowUpTask
        from apps.followups.services import notify_reminder

        cutoff = target_date - timedelta(days=overdue_days)

        # Only tasks that a human has explicitly tracked (pinned or assigned)
        tasks = (
            FollowUpTask.objects
            .filter(
                status__in=('pending', 'called'),
                due_date__gte=cutoff,
                due_date__lte=target_date,
            )
            .filter(
                # At least one human is watching this task
                models.Q(assigned_to__isnull=False) |
                models.Q(is_pinned=True)
            )
            .select_related(
                'customer', 'local_customer',
                'item', 'branch',
                'assigned_to__user', 'pinned_by__user',
            )
        )

        total_sent = 0
        for task in tasks:
            customer_name = task.customer_name or task.phcode or '—'
            item_name     = task.item.name if task.item_id else '—'
            is_overdue    = task.due_date < target_date

            if dry_run:
                self.stdout.write(
                    f'  [DRY RUN] Task #{task.pk} — {customer_name} — {item_name}'
                    f' | assigned={task.assigned_to} pinned={task.is_pinned}'
                )
                total_sent += 1
                continue

            notify_reminder(task)
            total_sent += 1

        return total_sent

    # ── C: Back-in-stock demand recovery reminders ─────────────────────────────
    # Re-surfaces recovery opportunities that have sat un-actioned. The 30-day
    # filters give the "at least monthly" cadence (§5.5) regardless of how often
    # this command runs. Stops automatically once a line is recovered /
    # disqualified / opted-out / past the 12-month window (awaiting_winback()).

    def _handle_demand_recovery(self, dry_run: bool) -> int:
        from datetime import timedelta
        from apps.demand.models import DemandItem
        from apps.demand.service import _notify_back_in_stock

        stale_cutoff = timezone.now() - timedelta(days=30)
        items = (
            DemandItem.objects.awaiting_winback()
            .filter(back_in_stock_at__lt=stale_cutoff)
            .filter(
                models.Q(notified_customer_at__isnull=True) |
                models.Q(notified_customer_at__lt=stale_cutoff)
            )
            .select_related('demand', 'demand__branch', 'item', 'demand__assigned_to')
        )

        total_sent = 0
        for di in items:
            if dry_run:
                self.stdout.write(
                    f'  [DRY RUN] Recovery reminder — {di.item_display_name}'
                    f' for {di.demand.phone} (waiting {di.days_waiting}d)'
                )
                total_sent += 1
                continue
            _notify_back_in_stock(di)
            total_sent += 1

        return total_sent
