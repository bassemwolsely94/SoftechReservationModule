"""
remind_markdown_reversals
=========================
Remind purchasing to review reverting near-expiry markdowns that have been live
longer than the grace window and were never rolled back (the batch has likely
cleared/expired by now). Reminder only — never auto-reverts a SOFTECH price.

Runs weekly (APScheduler); can be run manually.

Usage:
  python manage.py remind_markdown_reversals
  python manage.py remind_markdown_reversals --grace 60
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Remind to review reverting stale near-expiry markdowns.'

    def add_arguments(self, parser):
        parser.add_argument('--grace', type=int, default=None,
                            help='Days since execution before reminding '
                                 '(default: SystemSetting near_expiry_markdown_revert_days or 90).')

    def handle(self, *args, **opts):
        from apps.batches.expiry_audit import remind_markdown_reversals
        n = remind_markdown_reversals(grace_days=opts['grace'])
        self.stdout.write(self.style.SUCCESS(
            f'Done. stale near-expiry markdowns flagged for revert review: {n}'))
