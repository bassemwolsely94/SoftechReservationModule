"""Query budget for the C30 phantom monthly review list (CLAUDE.md definition of done item 9)."""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.catalog.models import Item

from ..factories import make_admin, make_item
from .budget import assert_budget


class PhantomMonthlyBudget(TestCase):
    def setUp(self):
        _, _, self.client_ = make_admin('perf_phantom_admin')
        self.n = 0

    def _grow(self, n=15):
        for _ in range(n):
            self.n += 1
            it = make_item(softech_id=f'PB{self.n:03d}')
            Item.objects.filter(pk=it.pk).update(is_phantom_substitution=True, phantom_flagged_at=timezone.now(),
                                                 phantom_buyback_qty=Decimal('3'), cost_price=Decimal('10'))

    def test_phantom_monthly(self):
        self._grow(2)
        assert_budget(self, 'purchasing/phantom/monthly', self.client_, '/api/purchasing/phantom/monthly/',
                      grow=self._grow, min_rows=15, rows_of=lambda r: len(r.data['items']))
