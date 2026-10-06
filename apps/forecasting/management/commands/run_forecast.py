"""
Management command: run_forecast
Usage:
  python manage.py run_forecast
  python manage.py run_forecast --branch 1 3 5
  python manage.py run_forecast --item 100 200
  python manage.py run_forecast --branch 1 --item 100

Schedule: daily, recommended 02:00 Cairo (after near_expiry_scan at 06:00 is fine too).
"""
from django.core.management.base import BaseCommand
from apps.forecasting.service import ForecastService


class Command(BaseCommand):
    help = 'Run the sales forecast engine and update ItemDemandMetrics'

    def add_arguments(self, parser):
        parser.add_argument('--branch', nargs='*', type=int, dest='branch_ids', help='Branch IDs to forecast (default: all)')
        parser.add_argument('--item',   nargs='*', type=int, dest='item_ids',   help='Item IDs to forecast (default: all)')

    def handle(self, *args, **options):
        branch_ids = options.get('branch_ids')
        item_ids   = options.get('item_ids')

        self.stdout.write(self.style.NOTICE('Starting forecast run…'))
        result = ForecastService.run_forecast(branch_ids=branch_ids, item_ids=item_ids)

        self.stdout.write(self.style.SUCCESS(
            f"Forecast complete: {result['items_processed']} items processed, "
            f"{result['errors']} errors. Run #{result['run_id']}"
        ))
