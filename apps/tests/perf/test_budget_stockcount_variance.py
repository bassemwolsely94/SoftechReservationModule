"""Query budget for the stock-count variance report with C14 valuation (CLAUDE.md definition of done item 9)."""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.stockcount.models import StockCountSession, StockCountSnapshot

from ..factories import make_admin, make_branch
from .budget import assert_budget


class StockCountVarianceBudget(TestCase):
    def setUp(self):
        b = make_branch()
        _, _, self.client_ = make_admin('perf_c14_admin')
        self.s = StockCountSession.objects.create(name='perf', branch_code=b.softech_branch_id, status='uploaded',
                                                  snapshot_at=timezone.now(), variance_at=timezone.now())
        self.n = 0

    def _grow(self, n=15):
        for _ in range(n):
            self.n += 1
            StockCountSnapshot.objects.create(session=self.s, item_code=f'PV{self.n:03d}', item_name='x',
                                              branch_code=self.s.branch_code, expected_qty=Decimal('5'),
                                              counted_qty=Decimal('4'), difference=Decimal('-1'),
                                              variance_type='deficit')

    def test_variance_report(self):
        self._grow(2)
        assert_budget(self, 'stockcount/variance-report', self.client_,
                      f'/api/stockcount/sessions/{self.s.pk}/variance-report/',
                      grow=self._grow, min_rows=15, rows_of=lambda r: len(r.data['items']))
