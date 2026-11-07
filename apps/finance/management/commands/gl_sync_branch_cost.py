"""python manage.py gl_sync_branch_cost --from YYYY-MM-DD --to YYYY-MM-DD

Ruling P33: reads the SOFTECH cost of sales per branch (stktransm.docvalue2, doccode 115 minus 30;
SELECT only) for every whole month covering the range and upserts GLBranchCost for the branch P&L.
Posts nothing. The drafting run refreshes the same months whenever it drafts sales_tenders.
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.finance.gl.branch_cost import sync_branch_cost


def _day(value):
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise CommandError(f'bad date: {value} (YYYY-MM-DD)')


class Command(BaseCommand):
    help = 'Sync the SOFTECH branch cost of sales (GLBranchCost) for whole months covering a range.'

    def add_arguments(self, parser):
        parser.add_argument('--from', dest='date_from', required=True)
        parser.add_argument('--to', dest='date_to', required=True)

    def handle(self, *args, **opts):
        d1, d2 = _day(opts['date_from']), _day(opts['date_to'])
        if d2 < d1:
            raise CommandError('--to is before --from')
        n = sync_branch_cost(d1, d2)
        self.stdout.write(f'branch cost rows written: {n}')
