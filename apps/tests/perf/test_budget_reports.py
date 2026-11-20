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
class FridgeLogBudgets(TestCase):
    """C31: the fridge readings list and the month sheet read one fridge's rows in one query."""

    def setUp(self):
        from apps.qa.models import FridgeUnit
        self.branch = make_branch()
        _, _, self.client_ = make_admin('perf_fridge_admin')
        self.fridge = FridgeUnit.objects.create(branch=self.branch, name='ثلاجة الأداء')
        self.day = timezone.localdate().replace(day=1)

    def _readings(self, n=20):
        from apps.qa.models import FridgeReading
        have = FridgeReading.objects.filter(fridge=self.fridge).count()
        for i in range(have, have + n):
            FridgeReading.objects.create(fridge=self.fridge, day=self.day - datetime.timedelta(days=i // 2),
                                         slot='am' if i % 2 == 0 else 'pm', temp_c=Decimal('5'), initials='x')

    def test_fridge_readings_list(self):
        self._readings(2)
        assert_budget(self, 'qa/fridge-readings', self.client_, f'/api/qa/fridge-readings/?fridge={self.fridge.pk}',
                      grow=self._readings, min_rows=20, rows_of=_count_list)

    def test_fridge_month_sheet(self):
        from apps.qa.models import FridgeReading
        FridgeReading.objects.create(fridge=self.fridge, day=self.day, slot='am', temp_c=Decimal('5'), initials='x')

        def grow():
            for d in range(1, 15):
                for s in ('am', 'pm'):
                    FridgeReading.objects.get_or_create(fridge=self.fridge, day=self.day.replace(day=d), slot=s,
                                                        defaults={'temp_c': Decimal('5'), 'initials': 'x'})
        assert_budget(self, 'qa/fridges/<id>/month', self.client_,
                      f'/api/qa/fridges/{self.fridge.pk}/month/?month={self.day:%Y-%m}', grow=grow, min_rows=0)


class DiscountPolicyPreviewBudget(TestCase):
    """C07: the unvalidated discount-policy preview computes check 12 live; its queries stay flat as lines grow."""

    def setUp(self):
        self.branch = make_branch()
        _, _, self.client_ = make_admin('perf_dp_admin')
        from apps.stock_audit.params import ensure_rules
        ensure_rules()   # the first call would otherwise seed the rule rows and skew the count
        self.n = 0

    def _lines(self, n=30):
        from apps.stock_audit.models import StockLedgerLine
        today = timezone.localdate()
        for _ in range(n):
            self.n += 1
            StockLedgerLine.objects.create(branchcode=self.branch.softech_branch_id, doccode='115', docnumber=self.n,
                                           docdate=today, itemcode=f'D{self.n:05d}', transqty=Decimal('1'),
                                           transprice=Decimal('70'), itemsaleprice=Decimal('100'),
                                           custdiscp=Decimal('30'), usercode=str(100 + self.n % 7))

    def test_discount_policy_preview(self):
        self._lines(2)
        # warm once: the first request fills per-process caches (2 queries) that are not per-row work
        self.client_.get('/api/stock-audit/discount-policy/')
        assert_budget(self, 'stock-audit/discount-policy', self.client_, '/api/stock-audit/discount-policy/',
                      grow=self._lines, min_rows=20, rows_of=lambda r: r.data['breach_lines'])
