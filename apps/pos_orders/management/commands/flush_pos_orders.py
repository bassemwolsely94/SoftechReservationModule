"""
flush_pos_orders — retry POS orders that were queued because the branch/SOFTECH was
unreachable. Safe to run on a schedule (e.g. every 2 min).

Why this can't duplicate a document:
  • A queued order has NO SOFTECH serial (the outage happened before allocation).
  • push_order allocates the serial atomically AT WRITE TIME (native read+1) and is
    idempotent: an order that already has a softech_docnumber is never re-written.
So each queued order gets exactly one fresh document number when it finally lands.
"""
from django.core.management.base import BaseCommand

from apps.pos_orders.models import SoftechSalesOrder
from apps.pos_orders import writer


class Command(BaseCommand):
    help = 'Retry queued/failed POS orders (run when the branch may be reachable again).'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=50)
        parser.add_argument('--include-failed', action='store_true',
                            help='also retry push_failed (use with care — those are non-connectivity errors)')

    def handle(self, *args, **opts):
        if not writer.writer_enabled():
            self.stdout.write('POS writer disabled (POS_WRITER_ENABLED=False) — nothing flushed.')
            return
        statuses = [SoftechSalesOrder.STATUS_QUEUED]
        if opts['include_failed']:
            statuses.append(SoftechSalesOrder.STATUS_PUSH_FAILED)
        qs = (SoftechSalesOrder.objects.filter(status__in=statuses)
              .select_related('branch').order_by('created_at')[:opts['limit']])
        pushed = queued = failed = 0
        for order in qs:
            try:
                res = writer.push_order(order, dry_run=False)
            except Exception as e:                       # real data/logic error
                failed += 1
                self.stderr.write(f'  order {order.pk}: FAILED {e}')
                continue
            if res.get('queued'):                        # still unreachable
                queued += 1
            elif res.get('ok') or res.get('already_pushed'):
                pushed += 1
                self.stdout.write(f'  order {order.pk} → SOFTECH docnumber {res.get("docnumber")}')
            else:
                failed += 1
        self.stdout.write(self.style.SUCCESS(
            f'flush done: pushed={pushed} still_queued={queued} failed={failed}'))
