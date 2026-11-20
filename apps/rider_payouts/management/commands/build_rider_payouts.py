"""
python manage.py build_rider_payouts [--from YYYY-MM-DD] [--to YYYY-MM-DD]

Adds one ledger ride per delivered order with a rider (C22). Idempotent: a re-run adds nothing new;
finalized periods are never touched (their orders are reported as held). Default: the last 7 days.
No SOFTECH, cash or payroll write.
"""
import datetime as dt

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.rider_payouts.ledger import build_from_orders


class Command(BaseCommand):
    help = 'Build the rider payout ledger from delivered orders (idempotent).'

    def add_arguments(self, parser):
        parser.add_argument('--from', dest='date_from')
        parser.add_argument('--to', dest='date_to')

    def handle(self, *args, **opts):
        try:
            date_to = dt.date.fromisoformat(opts['date_to']) if opts['date_to'] else timezone.localdate()
            date_from = (dt.date.fromisoformat(opts['date_from']) if opts['date_from']
                         else date_to - dt.timedelta(days=6))
        except ValueError as e:
            raise CommandError(f'bad date: {e}')
        if date_from > date_to:
            raise CommandError('--from is after --to')
        result = build_from_orders(date_from, date_to)
        self.stdout.write(str(result))
