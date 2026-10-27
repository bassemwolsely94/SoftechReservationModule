"""
apps/tests/test_customer_pos_summary.py

Compact Customer-360 for the POS drawer (Commerce-OS Phase 2). Composes CRM +
clinical safety flags + purchases + open reservations + loyalty. Read-only.
"""
from django.test import TestCase

from apps.customers.models import Customer, CustomerHealthProfile
from apps.customers.pos_summary import build_pos_summary
from .factories import make_branch, make_item, make_user


class PosSummaryTests(TestCase):
    def setUp(self):
        self.c = Customer.objects.create(name='سعاد', phone='0100', segment='vip', ltv=1234)

    def test_shape(self):
        s = build_pos_summary(self.c)
        for key in ('crm', 'health', 'purchases', 'reservations', 'loyalty'):
            self.assertIn(key, s)
        self.assertEqual(s['crm']['segment_label'], 'VIP 👑')
        self.assertEqual(s['crm']['ltv'], 1234.0)

    def test_health_allergies_surfaced(self):
        CustomerHealthProfile.objects.create(
            customer=self.c, known_allergies=[{'name': 'Penicillin'}], pregnancy_flag=True)
        s = build_pos_summary(self.c)
        self.assertIn('Penicillin', s['health']['allergies'])
        self.assertTrue(s['health']['pregnancy'])

    def test_no_health_profile_safe(self):
        s = build_pos_summary(self.c)
        self.assertFalse(s['health']['has_profile'])
        self.assertEqual(s['health']['allergies'], [])

    def test_open_reservations_counted(self):
        from apps.reservations.models import Reservation
        branch = make_branch()
        item = make_item(name='X', softech_id='RX1')
        Reservation.objects.create(customer=self.c, item=item, branch=branch,
                                   status='pending', contact_phone='0100', contact_name='سعاد',
                                   quantity_requested=1)
        s = build_pos_summary(self.c)
        self.assertEqual(s['reservations']['open_count'], 1)

    def test_api_endpoint(self):
        _, _, client = make_user('sum_user', role='pharmacist')
        r = client.get(f'/api/customers/{self.c.id}/pos-summary/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['crm']['id'], self.c.id)
