"""
apps/tests/test_receipt_service.py

Unified digital-receipt service (Commerce-OS Phase 2). Builds a structured
receipt payload; channel delivery returns HONEST statuses — never a false success
when a provider isn't configured (rule: report outcomes faithfully).
"""
from django.test import TestCase

from apps.customers.models import Customer, PurchaseHistory, PurchaseHistoryLine
from apps.customers.receipt import build_receipt, send_receipt
from .factories import make_branch, make_item, make_user


class ReceiptServiceTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.cust = Customer.objects.create(name='C', phone='0101', whatsapp_phone='0102')
        self.item = make_item(name='Panadol', softech_id='RC1')
        self.ph = PurchaseHistory.objects.create(
            customer=self.cust, softech_invoice_id='INVX', branch=self.branch,
            doc_code='115', total_amount=50)
        PurchaseHistoryLine.objects.create(purchase=self.ph, item=self.item, quantity=2,
                                           unit_price=25, line_total=50)

    def test_build_receipt_shape(self):
        r = build_receipt(self.ph)
        self.assertEqual(r['invoice']['softech_invoice_id'], 'INVX')
        self.assertEqual(r['totals']['line_count'], 1)
        self.assertEqual(r['lines'][0]['name'], 'Panadol')
        self.assertEqual(r['customer']['whatsapp_phone'], '0102')

    def test_print_channel_ready(self):
        out = send_receipt(self.ph, 'print')
        self.assertTrue(out['ok'])
        self.assertEqual(out['status'], 'ready')
        self.assertIn('payload', out)

    def test_invalid_channel(self):
        self.assertEqual(send_receipt(self.ph, 'carrier_pigeon')['status'], 'invalid_channel')

    def test_whatsapp_stub_when_unconfigured(self):
        # test settings have no WhatsApp creds → honest stub, not a fake success
        out = send_receipt(self.ph, 'whatsapp')
        self.assertFalse(out['ok'])
        self.assertEqual(out['status'], 'stub')
        self.assertEqual(out['to'], '0102')

    def test_sms_email_are_stubs(self):
        self.assertEqual(send_receipt(self.ph, 'sms')['status'], 'stub')
        self.assertEqual(send_receipt(self.ph, 'email')['status'], 'stub')

    def test_api_get_and_post(self):
        _, _, client = make_user('rcpt_user', role='pharmacist')
        g = client.get(f'/api/customers/{self.cust.id}/receipt/', {'invoice': self.ph.id})
        self.assertEqual(g.status_code, 200)
        self.assertEqual(g.data['invoice']['id'], self.ph.id)
        p = client.post(f'/api/customers/{self.cust.id}/receipt/',
                        {'channel': 'print', 'invoice': self.ph.id}, format='json')
        self.assertEqual(p.status_code, 200)
        self.assertTrue(p.data['ok'])
