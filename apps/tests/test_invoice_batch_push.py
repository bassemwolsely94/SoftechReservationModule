"""
Batch push (push-batch) — per-invoice isolation, status gating, RBAC, idempotency.
Runs with the writer gate OFF, so push_final returns a pure dry-run plan (no SOFTECH).
"""
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.invoices.models import SupplierInvoice, InvoiceLine, VendorProfile
from .factories import make_branch, make_item, make_admin, make_pharmacist


class BatchPushTests(TestCase):
    def setUp(self):
        self.user, _, self.client = make_admin('pusher')
        self.br = make_branch()
        self.item = make_item(softech_id='90792')
        self.vendor = VendorProfile.objects.create(name='V', softech_personcode='5014', is_main=True)

    def _inv(self, status='confirmed', num='111'):
        inv = SupplierInvoice.objects.create(branch=self.br, vendor=self.vendor,
                                             supplier_name='S', invoice_number=num, status=status)
        InvoiceLine.objects.create(invoice=inv, item=self.item, manual_name='X',
                                   quantity=5, public_price=28, unit_price=22.10)
        return inv

    @override_settings(INVOICE_WRITER_ENABLED=False)
    def test_batch_isolates_skips_and_reports(self):
        c = self._inv('confirmed', '111')
        p = self._inv('pending', '222')
        r = self.client.post('/api/invoices/invoices/push-batch/',
                             {'invoice_ids': [c.id, p.id, 999999]}, format='json')
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d['total'], 3)
        byid = {x['id']: x for x in d['results']}
        # confirmed → dry-run (gate off), counted as ok
        self.assertEqual(byid[c.id].get('mode'), 'dry_run')
        self.assertTrue(byid[c.id]['ok'])
        # unconfirmed → skipped, not ok
        self.assertTrue(byid[p.id].get('skipped'))
        self.assertFalse(byid[p.id]['ok'])
        # missing id → isolated error, does not break the batch
        self.assertFalse(byid[999999]['ok'])
        self.assertIn('error', byid[999999])
        self.assertEqual(d['succeeded'], 1)
        self.assertEqual(d['failed'], 2)

    def test_requires_push_role(self):
        _, _, c = make_pharmacist('ph2')
        r = c.post('/api/invoices/invoices/push-batch/', {'invoice_ids': [1]}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_empty_ids_rejected(self):
        r = self.client.post('/api/invoices/invoices/push-batch/',
                             {'invoice_ids': []}, format='json')
        self.assertEqual(r.status_code, 400)
