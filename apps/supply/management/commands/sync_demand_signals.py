"""
Project all demand sources (reservations, structured demand, branch shortage lists,
market-shortage detector) into the DemandSignal ledger. Read-only over the sources;
idempotent and re-runnable.

    python manage.py sync_demand_signals            # all sources
    python manage.py sync_demand_signals --source reservation
"""
from django.core.management.base import BaseCommand

from apps.supply import demand_signals


_ADAPTERS = {
    'reservation':     demand_signals.sync_reservations,
    'demand_item':     demand_signals.sync_demand_items,
    'shortage_item':   demand_signals.sync_shortage_items,
    'market_shortage': demand_signals.sync_market_shortage,
}


class Command(BaseCommand):
    help = 'Sync demand sources into the DemandSignal provenance/dedup ledger.'

    def add_arguments(self, parser):
        parser.add_argument('--source', choices=sorted(_ADAPTERS), default=None,
                            help='Sync only one source (default: all).')

    def handle(self, *args, **opts):
        source = opts.get('source')
        if source:
            res = _ADAPTERS[source]()
            self._print(res)
            return

        result = demand_signals.sync_all()
        for r in result['sources']:
            self._print(r)
        t = result['totals']
        self.stdout.write(self.style.SUCCESS(
            f"TOTAL — created {t['created']}, updated {t['updated']}, closed {t['closed']}"))

    def _print(self, r):
        self.stdout.write(
            f"  {r['source']:16s} created {r.get('created', 0):5d}  "
            f"updated {r.get('updated', 0):5d}  closed {r.get('closed', 0):5d}")
