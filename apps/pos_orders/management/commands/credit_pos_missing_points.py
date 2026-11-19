"""
credit_pos_missing_points — D-11 (owner 2026-11-19): credit the loyalty points that settled POS sales
missed because the branch points-rate read failed at push time.

DRY RUN by default (lists what each open record would credit; reads only). --commit writes, and only
with POS_POINTS_RECOVERY_ENABLED + LOYALTY_SOFTECH_WRITE_ENABLED on. Each record is credited at most
once: claimed by a conditional UPDATE and checked against the SOFTECH picpoints vf1 tag first
(apps/pos_orders/live_checks.credit_missing_points). Safe to run again.
"""
from django.core.management.base import BaseCommand

from apps.pos_orders import live_checks
from apps.pos_orders.models import PosLiveCheckGap as Gap, SoftechSalesOrder


class Command(BaseCommand):
    help = 'Credit missed POS loyalty points once (D-11). Dry run unless --commit.'

    def add_arguments(self, parser):
        parser.add_argument('--commit', action='store_true', help='really write to SOFTECH picpoints')
        parser.add_argument('--limit', type=int, default=50)

    def handle(self, *args, **opts):
        commit = opts['commit']
        qs = (Gap.objects.filter(kind=Gap.KIND_POINTS, status=Gap.STATUS_OPEN,
                                 order__status=SoftechSalesOrder.STATUS_SETTLED)
              .select_related('order').order_by('created_at')[:opts['limit']])
        done = refused = 0
        for gap in qs:
            try:
                res = live_checks.credit_missing_points(gap, actor=None, commit=commit)
            except live_checks.CreditRefused as e:
                refused += 1
                self.stdout.write(f'  POS-{gap.order_ref}: skipped — {e}')
                continue
            done += 1
            self.stdout.write(f'  POS-{gap.order_ref}: {res}')
        mode = 'COMMIT' if commit else 'DRY RUN'
        self.stdout.write(self.style.SUCCESS(f'{mode}: handled={done} skipped={refused}'))
