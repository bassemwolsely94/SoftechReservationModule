"""
apps/tests/test_quick_sell.py

Per-branch POS Quick-Sell top-sellers (Commerce-OS Phase 1). Aggregates the PG
sales mirror; sales only (returns excluded), windowed, ranked by quantity.
"""
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone

from apps.customers.models import Customer, PurchaseHistory, PurchaseHistoryLine
from apps.catalog.quicksell import top_sellers
from .factories import make_branch, make_item, make_user

BASE = '/api/items/quick-sell/'


def _sale(branch, customer, item, qty, days_ago=1, doc_code='115', inv='INV'):
    ph = PurchaseHistory.objects.create(
        customer=customer, softech_invoice_id=inv, branch=branch, doc_code=doc_code,
        total_amount=qty * 10, invoice_date=timezone.now() - timedelta(days=days_ago),
    )
    PurchaseHistoryLine.objects.create(purchase=ph, item=item, quantity=qty,
                                       unit_price=10, line_total=qty * 10)
    return ph


class QuickSellTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.cust = Customer.objects.create(name='C', phone='0100', is_guest=False)
        self.hot = make_item(name='Hot', softech_id='H1')
        self.cold = make_item(name='Cold', softech_id='C1')
        # hot sold 3x more than cold, recent window
        _sale(self.branch, self.cust, self.hot, 30, days_ago=2, inv='I1')
        _sale(self.branch, self.cust, self.cold, 10, days_ago=2, inv='I2')

    def test_ranks_by_quantity(self):
        rows = top_sellers(self.branch.id, days=30, limit=10)
        self.assertEqual(rows[0]['softech_id'], 'H1')
        self.assertGreater(rows[0]['sold_qty'], rows[1]['sold_qty'])

    def test_excludes_returns(self):
        _sale(self.branch, self.cust, self.cold, 999, days_ago=2, doc_code='30', inv='R1')
        rows = top_sellers(self.branch.id, days=30, limit=10)
        cold = next(r for r in rows if r['softech_id'] == 'C1')
        self.assertEqual(cold['sold_qty'], 10.0)   # the 999 return is not counted

    def test_respects_window(self):
        # a huge sale outside the window must not appear
        _sale(self.branch, self.cust, self.cold, 500, days_ago=90, inv='OLD')
        rows = top_sellers(self.branch.id, days=30, limit=10)
        cold = next(r for r in rows if r['softech_id'] == 'C1')
        self.assertEqual(cold['sold_qty'], 10.0)

    def test_api_requires_branch(self):
        _, _, client = make_user('qs_user', role='pharmacist')
        r = client.get(BASE)   # no branch, user may have none
        self.assertIn(r.status_code, (200, 400))

    def test_api_returns_ranked(self):
        _, _, client = make_user('qs_user2', role='pharmacist')
        r = client.get(BASE, {'branch': self.branch.id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['results'][0]['softech_id'], 'H1')
