"""
Market Shortage (/market-shortage) — the engine signals are computed once per run, not per call.

UAT W2 (2026-11-19): the screen never finished loading on production-sized data. Its three parallel
calls (candidates, deltas, confirmed) each ran the GROUP BY over a year of sales lines, deltas and
confirmed twice (ensure_snapshot recomputed before checking for the run's snapshot). Now the sales +
stock sums are cached per run and day, and an existing snapshot is returned without computing.
Item flags (in_shortage / dismissed) stay live.
"""
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.catalog.models import Item
from apps.purchasing import shortage as S
from apps.purchasing.models import (DemandCalculationRun, ItemDemandMetrics, SalesTransactionLine,
                                    ShortageSnapshot)
from apps.tests.factories import make_admin, make_branch

SALES_TABLE = 'purchasing_salestransactionline'


def _sales_queries(ctx):
    return [q['sql'] for q in ctx.captured_queries if SALES_TABLE in q['sql']]


class ShortageSignalsCacheTests(TestCase):

    def setUp(self):
        cache.clear()
        self.branch = make_branch('فرع 130', '130')
        self.run = DemandCalculationRun.objects.create(status='success', finished_at=timezone.now())
        self.item = Item.objects.create(softech_id='MS1', name='صنف ناقص', is_stockable=True,
                                        pack_price=Decimal('40'))
        today = timezone.localdate()
        self.dates = [today - timedelta(days=d) for d in (5, 40, 70, 100, 130, 160)]
        # 10 a month over 6 months → 60 / year, 5 / month; 10 in the last 30 days
        for n, day in enumerate(self.dates):
            SalesTransactionLine.objects.create(
                softech_branchcode='130', softech_itemcode='MS1', doccode='115', docnumber=f'MS{n}',
                doc_date=day, item=self.item, transqty=10, net_qty=10)
        ItemDemandMetrics.objects.create(run=self.run, item=self.item, branch=self.branch,
                                         calc_date=today, current_stock=1)

    def tearDown(self):
        cache.clear()

    def test_signals_are_unchanged(self):
        sig, run = S.item_signals()
        s = sig[self.item.id]
        self.assertEqual(run, self.run)
        months = len({d.replace(day=1) for d in self.dates})     # 5 or 6, by calendar
        self.assertEqual((s['annual_qty'], s['qty_30d'], s['sale_months'], s['stock']), (60.0, 10.0, months, 1.0))
        self.assertEqual(s['coverage'], 0.2)
        self.assertTrue(s['is_candidate'])

    def test_second_call_reads_no_sales_lines(self):
        first, _ = S.item_signals()
        with CaptureQueriesContext(connection) as ctx:
            second, _ = S.item_signals()
        self.assertEqual(_sales_queries(ctx), [])
        self.assertEqual(second[self.item.id]['annual_qty'], first[self.item.id]['annual_qty'])

    def test_item_flags_stay_live(self):
        S.item_signals()
        Item.objects.filter(pk=self.item.pk).update(in_shortage=True)
        sig, _ = S.item_signals()
        self.assertTrue(sig[self.item.id]['item'].in_shortage)

    def test_a_new_run_computes_again(self):
        S.item_signals()
        newer = DemandCalculationRun.objects.create(status='success', finished_at=timezone.now())
        ItemDemandMetrics.objects.create(run=newer, item=self.item, branch=self.branch,
                                         calc_date=timezone.localdate(), current_stock=2)
        with CaptureQueriesContext(connection) as ctx:
            sig, run = S.item_signals(newer)
        self.assertEqual(len(_sales_queries(ctx)), 1)
        # 2 on hand vs 5 / month = 0.4 months: still a candidate, with the NEW run's stock
        self.assertEqual(sig[self.item.id]['stock'], 2.0)

    def test_existing_snapshot_needs_no_signals(self):
        snap = S.ensure_snapshot()
        self.assertEqual(ShortageSnapshot.objects.filter(run=self.run).count(), 1)
        cache.clear()
        with CaptureQueriesContext(connection) as ctx:
            again = S.ensure_snapshot()
        self.assertEqual(again.pk, snap.pk)
        self.assertEqual(_sales_queries(ctx), [])

    def test_screen_calls_compute_the_signals_once(self):
        _, _, client = make_admin('ms_admin')
        with CaptureQueriesContext(connection) as ctx:
            for path in ('candidates/', 'deltas/', 'confirmed/'):
                self.assertEqual(client.get(f'/api/purchasing/shortage/{path}').status_code, 200)
        self.assertEqual(len(_sales_queries(ctx)), 1)
        body = client.get('/api/purchasing/shortage/deltas/').json()
        self.assertEqual([c['item_id'] for c in body['new']], [self.item.id])
