"""
Bulk "confirm all green lines" — only lines matched (score ≥ 0.85), priced, qty>0
and with no review flag are auto-confirmed; the rest stay for manual review.
"""
from django.test import TestCase

from apps.tests.factories import make_branch, make_admin, make_item
from apps.invoices.models import SupplierInvoice, VendorProfile, InvoiceLine


class ConfirmGreenTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        self.vendor = VendorProfile.objects.create(name='مورد', softech_personcode='12345', is_main=True)
        self.user, _, self.client_admin = make_admin()
        self.item = make_item(name='MEMEXA 10MG 30TAB', softech_id='93113')

    def _inv(self):
        return SupplierInvoice.objects.create(branch=self.branch, vendor=self.vendor,
                                              doc_kind='purchase', invoice_number='555', status='review')

    def _url(self, inv):
        return f'/api/invoices/invoices/{inv.id}/confirm-green/'

    def test_confirms_green_leaves_flagged(self):
        inv = self._inv()
        green = InvoiceLine.objects.create(invoice=inv, manual_name='memexa', item=self.item,
                                           quantity=11, unit_price=176.25, public_price=237,
                                           match_score=0.95, is_confirmed=False)
        no_item = InvoiceLine.objects.create(invoice=inv, manual_name='مجهول', quantity=1,
                                             unit_price=0, is_confirmed=False)       # no item + no price
        low = InvoiceLine.objects.create(invoice=inv, manual_name='ضعيف', item=self.item,
                                         quantity=1, unit_price=10, match_score=0.5)  # low score → review

        r = self.client_admin.post(self._url(inv))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['confirmed'], 1)
        green.refresh_from_db(); no_item.refresh_from_db(); low.refresh_from_db()
        self.assertTrue(green.is_confirmed)          # matched + priced + high score
        self.assertFalse(no_item.is_confirmed)       # no item / no price
        self.assertFalse(low.is_confirmed)           # low match score

    def test_idempotent(self):
        inv = self._inv()
        InvoiceLine.objects.create(invoice=inv, manual_name='memexa', item=self.item,
                                   quantity=11, unit_price=176.25, public_price=237, match_score=0.95)
        self.client_admin.post(self._url(inv))
        r2 = self.client_admin.post(self._url(inv))      # nothing left to confirm
        self.assertEqual(r2.data['confirmed'], 0)
