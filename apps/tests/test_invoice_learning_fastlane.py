"""
Learning loop (#1): confirming an invoice remembers vendor→item mappings.
Needs-attention fast lane (#6): the invoice list can filter to flagged vs clean.
"""
from django.test import TestCase

from apps.tests.factories import make_branch, make_admin, make_item
from apps.invoices.models import SupplierInvoice, InvoiceLine, VendorProfile, VendorItemMapping


class LearningLoopTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        self.vendor = VendorProfile.objects.create(name='مورد', softech_personcode='12345')
        self.item = make_item(softech_id='70001')
        self.user, _, self.client = make_admin('learner')

    def test_confirm_learns_mapping(self):
        inv = SupplierInvoice.objects.create(branch=self.branch, vendor=self.vendor, status='review')
        InvoiceLine.objects.create(invoice=inv, item=self.item, manual_name='بنادول اكسترا',
                                   vendor_item_code='AB123', quantity=1)
        r = self.client.post(f'/api/invoices/invoices/{inv.pk}/confirm/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['learned_mappings'], 1)
        m = VendorItemMapping.objects.get(vendor=self.vendor)
        self.assertEqual(m.item_id, self.item.id)
        self.assertEqual(m.vendor_item_code, 'AB123')

    def test_confirm_again_increments_use_count(self):
        for _ in range(2):
            inv = SupplierInvoice.objects.create(branch=self.branch, vendor=self.vendor, status='review')
            InvoiceLine.objects.create(invoice=inv, item=self.item, manual_name='بنادول اكسترا', quantity=1)
            self.client.post(f'/api/invoices/invoices/{inv.pk}/confirm/')
        self.assertEqual(VendorItemMapping.objects.get(vendor=self.vendor).use_count, 2)


class FastLaneTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        self.item = make_item(softech_id='70002')
        self.user, _, self.client = make_admin('triager')

    def test_attention_filter(self):
        clean = SupplierInvoice.objects.create(branch=self.branch, status='review')
        InvoiceLine.objects.create(invoice=clean, item=self.item, manual_name='ok', quantity=1)
        flagged = SupplierInvoice.objects.create(branch=self.branch, status='review')
        InvoiceLine.objects.create(invoice=flagged, item=None, manual_name='??', quantity=1)  # unmatched

        att = self.client.get('/api/invoices/invoices/?attention=1').json()
        att_ids = {i['id'] for i in (att.get('results') or att)}
        self.assertIn(flagged.id, att_ids)
        self.assertNotIn(clean.id, att_ids)

        cln = self.client.get('/api/invoices/invoices/?attention=clean').json()
        cln_ids = {i['id'] for i in (cln.get('results') or cln)}
        self.assertIn(clean.id, cln_ids)
        self.assertNotIn(flagged.id, cln_ids)
