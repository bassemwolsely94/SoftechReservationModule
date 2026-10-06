"""
Daily supply follow-up sweep (doc 24 Phase 4).

Refreshes the DemandSignal ledger from its sources, then evaluates every (item, branch)
with open demand or an open case: opens new cases, refreshes open ones, auto-resolves those
whose net requirement is gone on a real demand run. Writes only apps.supply tables; never
touches SOFTECH.

    python manage.py sweep_supply_cases              # sync signals + sweep
    python manage.py sweep_supply_cases --no-sync    # sweep only
    python manage.py sweep_supply_cases --notify     # force alerts on (else SUPPLY_CASE_NOTIFY)
"""
from django.core.management.base import BaseCommand

from apps.supply import cases, demand_signals


class Command(BaseCommand):
    help = 'Refresh the demand ledger and sweep supply cases (daily follow-up).'

    def add_arguments(self, parser):
        parser.add_argument('--no-sync', action='store_true',
                            help='Skip refreshing DemandSignals from their sources first.')
        parser.add_argument('--notify', action='store_true',
                            help='Send alerts even if SUPPLY_CASE_NOTIFY is off.')
        parser.add_argument('--limit', type=int, default=None,
                            help='Evaluate at most N pairs (diagnostics).')

    def handle(self, *args, **opts):
        if not opts['no_sync']:
            t = demand_signals.sync_all()['totals']
            self.stdout.write(f"signals — created {t['created']}, updated {t['updated']}, "
                              f"closed {t['closed']}")
        counts = cases.sweep_cases(notify=True if opts['notify'] else None, limit=opts['limit'])
        self.stdout.write(self.style.SUCCESS(
            'cases — ' + ', '.join(f'{k} {v}' for k, v in counts.items())))
