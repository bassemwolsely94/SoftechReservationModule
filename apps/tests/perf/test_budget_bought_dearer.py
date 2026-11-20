"""Query budget for the C17 «اشترينا أغلى» report (CLAUDE.md definition of done item 9)."""
import datetime
from decimal import Decimal

from django.test import TestCase

from ..factories import make_admin
from .budget import assert_budget


class BoughtDearerBudget(TestCase):
    def setUp(self):
        from apps.procurement.models import SupplierProfile
        for code, cl in (('D1', '60'), ('D2', '60')):
            SupplierProfile.objects.create(supplier_code=code, supplier_name=code, classif_code=cl)
        _, _, self.client_ = make_admin('perf_dearer_admin')
        self.n = 0

    def _grow(self, n=12):
        from apps.catalog.models import Item
        from apps.procurement.models import PurchaseLine
        for _ in range(n):
            self.n += 1
            it = Item.objects.create(softech_id=f'BD{self.n:03d}', name=f'BD {self.n}', pack_price=100)
            for sup, day, value in (('D2', 2, 700), ('D1', 10, 800)):     # D1 bought dearer than D2 before it
                PurchaseLine.objects.create(
                    branch_code='100', supplier_code=sup, doc_number=f'P{self.n}{sup}', doccode='10',
                    doc_date=datetime.date(2026, 10, day), item_code=it.softech_id, item=it,
                    net_qty=Decimal('10'), raw_qty=Decimal('10'), net_value=Decimal(value), raw_value=Decimal(value),
                    public_price=Decimal('100'), buyer_code=f'B{self.n % 3}')

    def test_bought_dearer(self):
        self._grow(2)
        assert_budget(self, 'supply/bought-dearer', self.client_, '/api/supply/bought-dearer/?month=2026-10',
                      grow=self._grow, min_rows=12, rows_of=lambda r: len(r.data['lines']))
