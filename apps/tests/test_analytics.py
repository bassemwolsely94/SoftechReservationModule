"""
apps/tests/test_analytics.py

Covers the analytics aggregation endpoints — in particular the revenue
convention that the whole module depends on:
  • net revenue = SUM(115 sales) − SUM(30 returns)
  • doccode 80 (SOFTECH reservation preview) is ALWAYS excluded
  • profit/COGS are netted against return lines
Plus auth + smoke coverage for the other dashboards.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from apps.catalog.models import Item
from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
from .factories import make_branch, make_admin, make_customer, make_item

SALES_URL       = '/api/analytics/sales/'
CUSTOMERS_URL   = '/api/analytics/customers/'
PERFORMANCE_URL = '/api/analytics/performance/'
FILTER_OPTS_URL = '/api/analytics/filter-options/'


def _purchase(customer, branch, doc_code, total, inv_id):
    return PurchaseHistory.objects.create(
        customer=customer, branch=branch, doc_code=doc_code,
        total_amount=Decimal(total), softech_invoice_id=inv_id,
        invoice_date=timezone.now(),
    )


def _line(purchase, item, qty, line_total, cost):
    return PurchaseHistoryLine.objects.create(
        purchase=purchase, item=item,
        quantity=Decimal(qty),
        unit_price=Decimal(line_total) / Decimal(qty),
        line_total=Decimal(line_total),
        cost_at_sale=Decimal(cost),
    )


class AnalyticsSalesOverviewTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        _, self.profile, self.client = make_admin('analytics_admin')
        self.customer = make_customer()
        self.item = make_item(name='صنف تحليلي', softech_id='AN001')
        Item.objects.filter(pk=self.item.pk).update(pack_price=120, cost_price=80)

        # Sale: revenue 1000, profit = 1000 − 60×10 = 400
        sale = _purchase(self.customer, self.branch, '115', 1000, 'INV-S1')
        _line(sale, self.item, 10, 1000, 60)
        # Return: revenue 200, profit = 200 − 60×2 = 80
        ret = _purchase(self.customer, self.branch, '30', 200, 'INV-R1')
        _line(ret, self.item, 2, 200, 60)
        # Reservation preview (doccode 80) — MUST be excluded entirely
        prev = _purchase(self.customer, self.branch, '80', 9999, 'INV-80')
        _line(prev, self.item, 50, 9999, 60)

    def test_requires_auth(self):
        self.assertEqual(APIClient().get(SALES_URL).status_code,
                         status.HTTP_401_UNAUTHORIZED)

    def test_net_revenue_excludes_returns_and_doccode_80(self):
        r = self.client.get(SALES_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        s = r.data['summary']
        self.assertEqual(s['sales_revenue'],   1000.0)
        self.assertEqual(s['returns_revenue'], 200.0)
        self.assertEqual(s['total_revenue'],   800.0)   # net; the 9999 preview is gone

    def test_profit_is_net_of_returns(self):
        s = self.client.get(SALES_URL).data['summary']
        self.assertEqual(s['total_profit'], 320.0)   # 400 (sale) − 80 (return)
        self.assertEqual(s['total_cogs'],   480.0)   # 600 − 120
        self.assertEqual(s['returns_count'], 1)
        self.assertEqual(s['sales_count'],   1)

    def test_branch_breakdown_present(self):
        r = self.client.get(SALES_URL)
        self.assertTrue(any(b['branch_id'] == self.branch.id for b in r.data['by_branch']))


class AnalyticsSmokeTests(TestCase):
    """The other dashboards must answer 200 for an authenticated user."""

    def setUp(self):
        self.branch = make_branch()
        _, self.profile, self.client = make_admin('analytics_smoke')

    def test_customers_ok(self):
        self.assertEqual(self.client.get(CUSTOMERS_URL).status_code, status.HTTP_200_OK)

    def test_performance_ok(self):
        self.assertEqual(self.client.get(PERFORMANCE_URL).status_code, status.HTTP_200_OK)

    def test_filter_options_ok(self):
        r = self.client.get(FILTER_OPTS_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('branches', r.data)
        self.assertIn('doc_types', r.data)

    def test_filter_options_requires_auth(self):
        self.assertEqual(APIClient().get(FILTER_OPTS_URL).status_code,
                         status.HTTP_401_UNAUTHORIZED)
