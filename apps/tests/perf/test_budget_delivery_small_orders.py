"""Query budget for the C20 delivery small-order report (CLAUDE.md definition of done item 9)."""
import datetime as dt
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from ..factories import make_admin, make_branch, make_customer, make_item
from .budget import assert_budget

DAY = dt.date(2026, 11, 10)


class DeliverySmallOrdersBudget(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.item = make_item(softech_id='SO01')
        self.customer = make_customer()
        _, _, self.client_ = make_admin('perf_c20_admin')
        self.n = 0

    def _grow(self, n=12):
        from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
        for _ in range(n):
            self.n += 1
            inv = PurchaseHistory.objects.create(
                customer=self.customer, softech_invoice_id=f'PB-C20-{self.n}', branch=self.branch, doc_code='115',
                docnumber=str(self.n), sales_channel='90', softech_phcode=f'P{self.n}', total_amount=Decimal('50'),
                invoice_date=timezone.make_aware(dt.datetime.combine(DAY, dt.time(12, 0))))
            PurchaseHistoryLine.objects.create(purchase=inv, item=self.item, quantity=Decimal('1'),
                                               unit_price=Decimal('50'), line_total=Decimal('50'),
                                               cost_at_sale=Decimal('40'))

    def test_small_orders(self):
        self._grow(2)
        assert_budget(self, 'delivery/small-orders', self.client_,
                      f'/api/delivery/small-orders/?date_from={DAY}&date_to={DAY}',
                      grow=self._grow, min_rows=12, rows_of=lambda r: len(r.data['orders']))
