"""
send_expiry_worklists  (D4)
===========================
Generate a near-term expiry worklist per branch and push a summary in-app
notification to each branch's managers (pharmacist/supervisor). Meant to run
weekly (APScheduler), but can be run manually.

Usage:
  python manage.py send_expiry_worklists
  python manage.py send_expiry_worklists --ahead 120 --back 15 --top 30
  python manage.py send_expiry_worklists --dry-run     # compute, don't notify
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Push weekly per-branch near-expiry worklists to branch managers (D4).'

    def add_arguments(self, parser):
        parser.add_argument('--back', type=int, default=30,
                            help='Include items expiring up to N days in the past (already-expired on shelf).')
        parser.add_argument('--ahead', type=int, default=90,
                            help='Include items expiring within the next N days (default 90).')
        parser.add_argument('--top', type=int, default=25,
                            help='Max items listed per branch notification (default 25).')
        parser.add_argument('--dry-run', action='store_true',
                            help='Compute worklists but send no notifications.')

    def handle(self, *args, **opts):
        from apps.batches.expiry_audit import generate_branch_worklists

        summary = generate_branch_worklists(
            back_days=opts['back'], ahead_days=opts['ahead'],
            top_n=opts['top'], notify=not opts['dry_run'],
        )
        self.stdout.write(self.style.SUCCESS(
            f"Done. branches_scanned={summary['branches_scanned']} "
            f"with_items={summary['branches_with_items']} "
            f"notified={summary['notified']} errors={summary['errors']}"
            + (' (dry-run)' if opts['dry_run'] else '')
        ))
