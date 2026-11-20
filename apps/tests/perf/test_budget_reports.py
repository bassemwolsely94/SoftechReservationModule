"""
Query budgets for on-screen reports and the screen-view tracker (performance stage 1, design §4:
"report" ≤ 2 s, "track" ≤ 100 ms p95). The market-shortage endpoints get their budget in the Stage 3
market-shortage PR, which owns that code.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.batches.models import StockExpiryBalance
from apps.incentives.models import SalesTarget

from ..factories import make_admin, make_branch, make_pharmacist
from .budget import assert_budget


def _count_list(resp):
    data = resp.data
    if isinstance(data, dict):
        return len(data['results']) if isinstance(data.get('results'), list) else 0
    return len(data)


class ReportBudgets(TestCase):
    def setUp(self):
        self.branch = make_branch()
        _, self.admin, self.client_ = make_admin('perf_r_admin')
        self.n = 0

    def _expiry(self, n=30):
        today = timezone.localdate()
        for _ in range(n):
            self.n += 1
            StockExpiryBalance.objects.create(branch_code=self.branch.softech_branch_id, store_code='101',
                                              item_code=f'X{self.n:05d}',
                                              expiry_date=today + datetime.timedelta(days=10 + self.n % 200),
                                              qty=Decimal('2'))

    def _targets(self, n=10):
        for _ in range(n):
            self.n += 1
            SalesTarget.objects.create(scope_type=SalesTarget.SCOPE_BRANCH, branch=self.branch,
                                       metric='cash_delivery', period_start=datetime.date(2026, 6, 1),
                                       period_end=datetime.date(2026, 6, 30),
                                       target_value=Decimal(1000 + self.n))

    def test_stock_expiry_summary(self):
        self._expiry(3)
        assert_budget(self, 'batches/stock-expiry/summary', self.client_, '/api/batches/stock-expiry/summary/',
                      grow=self._expiry, min_rows=0)

    def test_incentives_targets(self):
        self._targets(2)
        # Stage 1 found an N+1 here (12 → 52 queries for 10 targets); Stage 3 batches the attainments.
        assert_budget(self, 'incentives/targets', self.client_, '/api/incentives/targets/',
                      grow=self._targets, min_rows=10, rows_of=_count_list)


class TrackBudgets(TestCase):
    def test_screen_view(self):
        _, _, client = make_pharmacist('perf_track', branch=make_branch())
        assert_budget(self, 'audit/screen-view', client, '/api/audit/screen-view/', method='post',
                      data={'route': '/reservations/123', 'tab': 'grid'}, grow=lambda: None, min_rows=0)


class OutHereBudget(TestCase):
    """C06 /supply «ناقص هنا · موجود هناك»: flat however many short items there are."""

    def setUp(self):
        from apps.branches.models import Branch
        from apps.purchasing.models import DemandCalculationRun
        self.run = DemandCalculationRun.objects.create(status='success', calc_date=timezone.localdate(),
                                                       finished_at=timezone.now())
        self.here = Branch.objects.create(softech_branch_id='131', name='H', name_ar='H', kind='retail',
                                          is_active=True)
        self.there = Branch.objects.create(softech_branch_id='141', name='T', name_ar='T', kind='retail',
                                           is_active=True)
        _, _, self.client_ = make_admin('perf_outhere')
        self.n = 0

    def _short(self, n=30):
        from apps.catalog.models import ItemStock
        from apps.purchasing.models import ItemDemandMetrics
        from ..factories import make_item
        for _ in range(n):
            self.n += 1
            it = make_item(f'OH {self.n}', f'OH{self.n:04d}')
            ItemDemandMetrics.objects.create(run=self.run, item=it, branch=self.here, calc_date=self.run.calc_date,
                                             monthly_avg=10, gap=10, abc_class='A', pack_price=5)
            ItemDemandMetrics.objects.create(run=self.run, item=it, branch=self.there, calc_date=self.run.calc_date,
                                             monthly_avg=10, safety_stock=2, abc_class='A', pack_price=5)
            ItemStock.objects.create(item=it, branch=self.there, softech_store_code='101', quantity_on_hand=40)

    def test_out_here(self):
        self._short(2)
        # warm once: apps/config/item_types keeps the medicine-type map per process (planning_excluded_codes),
        # so the first request in a process reads it (2 queries) and every later one does not
        self.assertEqual(self.client_.get('/api/supply/out-here/').status_code, 200)
        assert_budget(self, 'supply/out-here', self.client_, '/api/supply/out-here/',
                      grow=self._short, min_rows=30, rows_of=lambda r: len(r.data['rows']))
