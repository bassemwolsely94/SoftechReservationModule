"""ETA history mirror by hand: plan windows, run backfill rounds, top up. Read only towards ETA."""
import datetime as dt

from django.core.management.base import BaseCommand, CommandError

from apps.tax_invoicing import eta_history
from apps.tax_invoicing.eta_reader import SYSTEMS


class Command(BaseCommand):
    help = 'ETA history mirror: --plan, --step N, --topup for one ETA system.'

    def add_arguments(self, parser):
        parser.add_argument('--system', required=True, choices=SYSTEMS)
        parser.add_argument('--plan', action='store_true')
        parser.add_argument('--step', type=int, default=0, help='backfill rounds to run per kind')
        parser.add_argument('--topup', action='store_true')
        parser.add_argument('--days', type=int, default=0, help='top-up span (default: 30 documents / 7 receipts)')
        parser.add_argument('--retry-failed', action='store_true')

    def handle(self, *args, **o):
        system = o['system']
        if o['plan']:
            end = dt.date.today() - dt.timedelta(days=1)
            for kind in eta_history.KINDS:
                n = eta_history.plan_windows(system, kind, eta_history.start_date(), end)
                self.stdout.write(f'{kind}: {n} new windows')
        for _ in range(o['step']):
            for kind in eta_history.KINDS:
                self.stdout.write(f'{kind}: {eta_history.step(system, kind)}')
        if o['retry_failed']:
            self.stdout.write(f"{eta_history.retry_failed(system)} failed windows back to planned")
        if o['topup']:
            self.stdout.write(str(eta_history.top_up(system, days=o['days'] or None)))
        if not (o['plan'] or o['step'] or o['topup'] or o['retry_failed']):
            raise CommandError('nothing to do: give --plan, --step N, --topup or --retry-failed')
