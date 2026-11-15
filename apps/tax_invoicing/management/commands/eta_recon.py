"""SOFTECH ↔ ETA receipts reconciliation by hand. Reads SOFTECH (HQ) and the local ETA copy only."""
import datetime as dt

from django.core.management.base import BaseCommand, CommandError

from apps.tax_invoicing import eta_recon
from apps.tax_invoicing.eta_reader import SYSTEMS


class Command(BaseCommand):
    help = 'eta_recon --system production [--learn] [--from YYYY-MM-DD --to YYYY-MM-DD | --recent]'

    def add_arguments(self, parser):
        parser.add_argument('--system', required=True, choices=SYSTEMS)
        parser.add_argument('--learn', action='store_true', help='learn which branch each device belongs to')
        parser.add_argument('--from', dest='start')
        parser.add_argument('--to', dest='end')
        parser.add_argument('--recent', action='store_true', help='the last 30 days')

    def handle(self, *args, **o):
        system = o['system']
        if o['learn']:
            self.stdout.write(f'devices: {eta_recon.learn_devices(system)}')
        if o['recent']:
            self.stdout.write(str(eta_recon.recent(system)))
        if o['start'] or o['end']:
            try:
                start, end = dt.date.fromisoformat(o['start']), dt.date.fromisoformat(o['end'])
            except (TypeError, ValueError) as exc:
                raise CommandError('give --from and --to as YYYY-MM-DD') from exc
            self.stdout.write(str(eta_recon.reconcile_range(system, start, end)))
        if not (o['learn'] or o['recent'] or o['start'] or o['end']):
            raise CommandError('nothing to do: give --learn, --recent or --from/--to')
