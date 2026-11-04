"""Project 3 (a): build missed-sale reservation SUGGESTIONS from our POS carts (Postgres only).

    python manage.py detect_missed_sales           # no-op while MISSED_SALES_ENABLED is off
    python manage.py detect_missed_sales --force   # run once even with the flag off (preview)
"""
from django.core.management.base import BaseCommand

from apps.pos_orders.missed_sales import detect_missed_sales, enabled


class Command(BaseCommand):
    help = 'Build «مبيعات فائتة» reservation suggestions from POS carts (never creates reservations).'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='run even when the flag is off')

    def handle(self, *args, **opts):
        if not (enabled() or opts['force']):
            self.stdout.write('MISSED_SALES_ENABLED is off — nothing done (use --force to preview).')
            return
        self.stdout.write(str(detect_missed_sales()))
