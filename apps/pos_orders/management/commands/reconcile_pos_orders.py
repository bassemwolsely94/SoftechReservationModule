"""
python manage.py reconcile_pos_orders

READ-ONLY: reconcile pushed Indirect-POS orders against the branch DBs — mark
settled ones (and record the final invoice #). Safe to schedule (e.g. every 5 min)
alongside the other APScheduler jobs. Never writes to SOFTECH.
"""
from django.core.management.base import BaseCommand

from apps.pos_orders.reconcile import run_reconcile


class Command(BaseCommand):
    help = 'Reconcile pushed POS orders vs branch DBs (read-only settlement detection)'

    def add_arguments(self, parser):
        parser.add_argument('--profile', default=None, help='SOFTECH profile (optional)')

    def handle(self, *args, **options):
        summary = run_reconcile(profile=options.get('profile'))
        self.stdout.write(self.style.SUCCESS(
            '[pos_orders] reconcile: '
            f"checked={summary['checked']} settled={summary['settled']} "
            f"still_pending={summary['still_pending']} errors={summary['errors']} "
            f"branches_down={summary['branches_down']}"
        ))
