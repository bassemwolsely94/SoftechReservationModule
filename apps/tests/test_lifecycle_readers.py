"""
Data lifecycle stage 3, task 1 -- readers of demand-engine rows use ONE run.

Once fewer runs are kept, a reader that sums or lists rows across every
successful run double-counts, and one that orders by calc_date alone can pick
an empty run when several runs share a date. All four readers must use
apps.purchasing.shortage._latest_run(None).
"""
import datetime
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.branches.models import Branch
from apps.catalog.models import Item
from apps.purchasing.models import (
    DemandCalculationRun, ItemDemandAggregated, ItemDemandMetrics,
)

TODAY = datetime.date.today()


def _run(status='success'):
    return DemandCalculationRun.objects.create(status=status, calc_date=TODAY)


def _metrics(run, item, branch, **kw):
    kw.setdefault('coverage_months', 12)
    kw.setdefault('monthly_avg', 10)
    return ItemDemandMetrics.objects.create(
        run=run, item=item, branch=branch, calc_date=TODAY, **kw)


class ForecastReaderTests(TestCase):
    def test_forecast_processes_each_item_once(self):
        from apps.forecasting.service import ForecastService
        item = Item.objects.create(softech_id='F1', name='F1', is_stockable=True)
        branch = Branch.objects.create(softech_branch_id='170', name='B')
        old, new = _run(), _run()
        _metrics(old, item, branch)
        newest = _metrics(new, item, branch)

        seen = []
        with mock.patch.object(ForecastService, '_forecast_one',
                               side_effect=lambda m: seen.append(m.pk)):
            out = ForecastService.run_forecast()

        self.assertEqual(out['items_processed'], 1)
        self.assertEqual(seen, [newest.pk])

    def test_forecast_without_a_run_processes_nothing(self):
        from apps.forecasting.service import ForecastService
        out = ForecastService.run_forecast()
        self.assertEqual(out['items_processed'], 0)
        self.assertEqual(out['errors'], 0)


class SlowMoverReaderTests(TestCase):
    def _get(self):
        from apps.incentives.views import SuggestItemsView
        req = Request(APIRequestFactory().get(
            '/api/incentives/suggest-items/', {'include_tags': 'slow_moving'}))
        return SuggestItemsView().get(req).data

    def test_slow_movers_use_latest_run(self):
        item = Item.objects.create(softech_id='S1', name='S1', is_stockable=True)
        branch = Branch.objects.create(softech_branch_id='170', name='B')
        old, new = _run(), _run()
        _metrics(old, item, branch, coverage_months=6)
        _metrics(new, item, branch, coverage_months=12)

        data = self._get()
        self.assertEqual(data['count'], 1)
        # One row: 12 months of cover = 30 points. Two rows would add the old run's 15.
        self.assertEqual(data['items'][0]['score'], 30.0)

    def test_slow_movers_without_a_run_is_empty(self):
        self.assertEqual(self._get()['count'], 0)


class ImageReaderTieTests(TestCase):
    def setUp(self):
        # 4 successful runs on one calc_date; rows only on the newest 3, so the
        # run an unordered tie would pick (the oldest) is empty.
        self.runs = [_run() for _ in range(4)]
        self.a = Item.objects.create(softech_id='A', name='A', is_stockable=True, is_active=True)
        self.b = Item.objects.create(softech_id='B', name='B', is_stockable=True, is_active=True)
        for run in self.runs[1:]:
            for it, cls in ((self.a, 'A'), (self.b, 'B')):
                ItemDemandAggregated.objects.create(
                    run=run, item=it, calc_date=TODAY, abc_class=cls)

    def test_latest_reader_ignores_pruned_tie(self):
        from apps.images import views
        from apps.images.pipeline import _filter_by_abc
        from apps.tests.factories import make_user

        got = _filter_by_abc(Item.objects.all(), 'A')
        self.assertEqual(list(got), [self.a])

        req = APIRequestFactory().get('/api/images/filter-meta/')
        force_authenticate(req, user=make_user('u', role='purchasing')[0])
        resp = views.filter_meta(req)
        # Counted once (newest run only), not once per run.
        self.assertEqual(resp.data['abc_counts'], {'A': 1, 'B': 1})
