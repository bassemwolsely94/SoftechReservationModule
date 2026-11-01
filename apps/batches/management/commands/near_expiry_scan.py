"""
python manage.py near_expiry_scan

Flags expired batches and fires NearExpiryAlert rows for the 30/60/90/180-day
thresholds.  Safe to run multiple times — uses get_or_create, no duplicates.

DEPRECATED (P-26, 2026-10-31): no longer scheduled. It scans StockBatch, which nothing fills;
expiry numbers come from the StockExpiryBalance mirror (apps/batches/stock_expiry.py).
"""
from django.core.management.base import BaseCommand
from apps.batches.service import BatchService


class Command(BaseCommand):
    help = 'Scan batches for expiry and near-expiry alerts'

    def handle(self, *args, **options):
        summary = BatchService.scan_near_expiry()
        self.stdout.write(self.style.SUCCESS(
            f'Done — {summary["expired"]} batches expired, '
            f'{summary["alerts_created"]} new near-expiry alerts created.'
        ))
