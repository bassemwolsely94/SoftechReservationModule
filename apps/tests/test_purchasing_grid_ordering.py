"""Every sortable header of the purchasing grids (metrics / aggregated / transfer recs) orders on the server."""
import datetime

from django.test import TestCase

from apps.branches.models import Branch
from apps.purchasing.models import (
    DemandCalculationRun, ItemDemandAggregated, ItemDemandMetrics,
    TransferRecommendation, TransferRecommendationRun,
)

from .factories import make_admin, make_item

TODAY = datetime.date(2026, 11, 3)


class PurchasingGridOrderingTests(TestCase):
    def setUp(self):
        self.run = DemandCalculationRun.objects.create(status='success')
        self.b1 = Branch.objects.create(softech_branch_id='101', name='B1', name_ar='ب', is_active=True)
        self.b2 = Branch.objects.create(softech_branch_id='102', name='B2', name_ar='ا', is_active=True)
        self.items = [make_item('CCC', 'P3'), make_item('AAA', 'P1'), make_item('BBB', 'P2')]
        for it, br in zip(self.items, (self.b1, self.b2, self.b1)):
            ItemDemandMetrics.objects.create(run=self.run, item=it, branch=br, calc_date=TODAY, monthly_avg=1)
            ItemDemandAggregated.objects.create(run=self.run, item=it, calc_date=TODAY)
        trun = TransferRecommendationRun.objects.create(demand_run=self.run, status='success')
        for it, st in zip(self.items, (5, 1, 3)):
            TransferRecommendation.objects.create(
                run=trun, item=it, from_branch=self.b1, to_branch=self.b2, quantity=1,
                estimated_value=1, priority_score=1, to_stock=st)
        _u, _p, self.client_ = make_admin('pgrid_admin')

    def names(self, url, ordering, key='item_name'):
        r = self.client_.get(url, {'ordering': ordering, 'page_size': 50})
        self.assertEqual(r.status_code, 200)
        rows = r.data['results'] if isinstance(r.data, dict) else r.data
        return [x[key] for x in rows]

    def test_metrics_by_item_name_and_branch(self):
        self.assertEqual(self.names('/api/purchasing/metrics/', 'item__name'), ['AAA', 'BBB', 'CCC'])
        self.assertEqual(self.names('/api/purchasing/metrics/', '-item__name'), ['CCC', 'BBB', 'AAA'])
        self.assertEqual(self.names('/api/purchasing/metrics/', 'item__softech_id'), ['AAA', 'BBB', 'CCC'])
        # branch_name_ar: 'ا' (AAA's branch b2) sorts before 'ب'
        self.assertEqual(self.names('/api/purchasing/metrics/', 'branch__name_ar')[0], 'AAA')

    def test_aggregated_by_item_name(self):
        self.assertEqual(self.names('/api/purchasing/aggregated/', 'item__name'), ['AAA', 'BBB', 'CCC'])
        self.assertEqual(self.names('/api/purchasing/aggregated/', '-item__softech_id'), ['CCC', 'BBB', 'AAA'])

    def test_transfer_recs_by_name_and_stock(self):
        url = '/api/purchasing/transfer-recs/'
        self.assertEqual(self.names(url, 'item__name'), ['AAA', 'BBB', 'CCC'])
        self.assertEqual(self.names(url, 'to_stock'), ['AAA', 'BBB', 'CCC'])
        self.assertEqual(self.names(url, '-to_stock'), ['CCC', 'BBB', 'AAA'])

    def test_every_whitelisted_field_orders_asc_and_desc(self):
        from apps.purchasing.views import AggregatedListView, MetricsListView, TransferRecommendationListView
        for url, view in (('/api/purchasing/metrics/', MetricsListView), ('/api/purchasing/aggregated/', AggregatedListView),
                          ('/api/purchasing/transfer-recs/', TransferRecommendationListView)):
            for f in view.ordering_fields:
                for o in (f, '-' + f):
                    r = self.client_.get(url, {'ordering': o})
                    self.assertEqual(r.status_code, 200, f'{url} ordering={o}')
