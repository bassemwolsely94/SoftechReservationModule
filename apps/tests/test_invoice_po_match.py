"""
PO/GRN matching (#5) — a separate advisory workflow, not wired into posting.
Verifies the variance report (qty/price/missing/extra) and the API action.
"""
from django.test import TestCase

from apps.tests.factories import make_branch, make_admin, make_item
from apps.invoices.models import (SupplierInvoice, InvoiceLine, VendorProfile,
                                   PurchaseOrder, PurchaseOrderLine)
from apps.invoices import po as po_mod


class POMatchLogicTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        self.vendor = VendorProfile.objects.create(name='مورد')
        self.a = make_item(softech_id='80001')
        self.b = make_item(softech_id='80002')
        self.c = make_item(softech_id='80003')

    def _po(self, lines):
        po = PurchaseOrder.objects.create(branch=self.branch, vendor=self.vendor, po_number='PO1')
        for item, qty, price in lines:
            PurchaseOrderLine.objects.create(po=po, item=item, quantity=qty, unit_price=price)
        return po

    def _inv(self, lines):
        inv = SupplierInvoice.objects.create(branch=self.branch, vendor=self.vendor)
        for item, qty, price in lines:
            InvoiceLine.objects.create(invoice=inv, item=item, quantity=qty, unit_price=price)
        return inv

    def test_perfect_match(self):
        po = self._po([(self.a, 10, 5), (self.b, 4, 20)])
        inv = self._inv([(self.a, 10, 5), (self.b, 4, 20)])
        r = po_mod.match_invoice_to_po(inv, po)
        self.assertEqual(r['summary']['matched'], 2)
        self.assertEqual(r['summary']['qty_mismatch'], 0)
        self.assertEqual(r['missing_from_invoice'], [])
        self.assertEqual(r['extra_in_invoice'], [])

    def test_qty_and_price_variance(self):
        po = self._po([(self.a, 10, 5)])
        inv = self._inv([(self.a, 8, 6)])          # under-delivered + price up 20%
        r = po_mod.match_invoice_to_po(inv, po)
        line = r['lines'][0]
        self.assertEqual(line['status'], 'both')
        self.assertEqual(line['qty_variance'], -2.0)
        self.assertGreater(line['price_variance_pct'], 0.1)

    def test_missing_and_extra(self):
        po = self._po([(self.a, 10, 5), (self.b, 4, 20)])
        inv = self._inv([(self.a, 10, 5), (self.c, 2, 9)])   # b missing, c extra
        r = po_mod.match_invoice_to_po(inv, po)
        self.assertEqual(r['summary']['missing'], 1)
        self.assertEqual(r['summary']['extra'], 1)
        self.assertEqual(r['missing_from_invoice'][0]['item_id'], self.b.id)
        self.assertEqual(r['extra_in_invoice'][0]['item_id'], self.c.id)


class POMatchApiTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        self.vendor = VendorProfile.objects.create(name='مورد')
        self.item = make_item(softech_id='80010')
        self.user, _, self.client = make_admin('poadmin')

    def test_po_match_action_links_and_reports(self):
        po = PurchaseOrder.objects.create(branch=self.branch, vendor=self.vendor, po_number='PO9')
        PurchaseOrderLine.objects.create(po=po, item=self.item, quantity=5, unit_price=10)
        inv = SupplierInvoice.objects.create(branch=self.branch, vendor=self.vendor)
        InvoiceLine.objects.create(invoice=inv, item=self.item, quantity=5, unit_price=10)

        r = self.client.post(f'/api/invoices/invoices/{inv.pk}/po-match/', {'po': po.pk}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['summary']['matched'], 1)
        inv.refresh_from_db()
        self.assertEqual(inv.po_id, po.pk)             # link persisted

    def test_po_match_no_po(self):
        inv = SupplierInvoice.objects.create(branch=self.branch, vendor=self.vendor)
        r = self.client.get(f'/api/invoices/invoices/{inv.pk}/po-match/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['linked'])

    def test_po_crud(self):
        r = self.client.post('/api/invoices/purchase-orders/', {
            'branch': self.branch.id, 'vendor': self.vendor.id, 'po_number': 'PO-X',
            'lines': [{'item': self.item.id, 'quantity': 3, 'unit_price': 7}]}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['line_count'], 1)
