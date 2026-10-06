"""
apps/tests/test_repeat_order.py

Revalidating repeat-order (Commerce-OS Phase 2): rebuilds a past order but flags
price drift, out-of-stock, and safety blocks — never a blind copy (rule 4).
"""
from decimal import Decimal
from django.test import TestCase

from apps.customers.models import Customer, PurchaseHistory, PurchaseHistoryLine
from apps.customers.repeat_order import build_repeat_order, last_sale_for
from apps.catalog.models import ItemStock
from .factories import make_branch, make_item, make_user


class RepeatOrderTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.cust = Customer.objects.create(name='C', phone='0100')
        self.item = make_item(name='Panadol', softech_id='RO1')
        self.item.pack_price = Decimal('20.00')
        self.item.save(update_fields=['pack_price'])
        self.ph = PurchaseHistory.objects.create(
            customer=self.cust, softech_invoice_id='INV1', branch=self.branch,
            doc_code='115', total_amount=15)
        PurchaseHistoryLine.objects.create(purchase=self.ph, item=self.item, quantity=2,
                                           unit_price=Decimal('15.00'), line_total=30)

    def test_flags_price_change(self):
        out = build_repeat_order(self.ph)
        line = out['lines'][0]
        self.assertTrue(line['price_changed'])          # paid 15, now 20
        self.assertEqual(line['price_delta'], 5.0)
        self.assertEqual(out['summary']['price_changed'], 1)

    def test_flags_out_of_stock_at_branch(self):
        # no ItemStock rows → qty_available 0 → out of stock for qty 2
        out = build_repeat_order(self.ph, branch_id=self.branch.id)
        self.assertEqual(out['lines'][0]['status'], 'out_of_stock')
        self.assertEqual(out['summary']['out_of_stock'], 1)

    def test_available_when_enough_stock(self):
        ItemStock.objects.create(item=self.item, branch=self.branch,
                                 softech_store_code='01', quantity_on_hand=10)
        out = build_repeat_order(self.ph, branch_id=self.branch.id)
        self.assertEqual(out['lines'][0]['status'], 'ok')
        self.assertEqual(out['summary']['available'], 1)

    def test_blocked_item_flagged(self):
        self.item.item_archive = True   # blocks_sale → True
        self.item.save(update_fields=['item_archive'])
        out = build_repeat_order(self.ph, branch_id=self.branch.id)
        self.assertEqual(out['lines'][0]['status'], 'blocked')
        self.assertTrue(out['lines'][0]['blocked'])
        self.assertEqual(out['summary']['blocked'], 1)

    def test_last_sale_helper(self):
        self.assertEqual(last_sale_for(self.cust).id, self.ph.id)

    def test_api(self):
        _, _, client = make_user('ro_user', role='pharmacist')
        r = client.get(f'/api/customers/{self.cust.id}/repeat-order/', {'branch': self.branch.id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['source_invoice']['id'], self.ph.id)

    def test_api_404_when_no_history(self):
        empty = Customer.objects.create(name='E', phone='0200')
        _, _, client = make_user('ro_user2', role='pharmacist')
        r = client.get(f'/api/customers/{empty.id}/repeat-order/')
        self.assertEqual(r.status_code, 404)
