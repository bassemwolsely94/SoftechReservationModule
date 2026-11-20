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
        assert_budget(self, 'stock-audit/discount-policy', self.client_, '/api/stock-audit/discount-policy/',
                      grow=self._lines, min_rows=20, rows_of=lambda r: r.data['breach_lines'])
