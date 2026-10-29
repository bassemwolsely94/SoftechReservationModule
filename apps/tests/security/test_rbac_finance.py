"""
Authorization — finance, payments and cheques follow the matrix in the views themselves
(Batch 4, Z-3).

Before: with RBAC in log mode (production) 143 requests the matrix denies went through —
every finance and A/P reconciliation read (accounts, journal, treasury, P&L, supplier ledgers)
for call center, delivery, salesperson, supervisor and viewer; recording, editing and deleting
customer payments (InstaPay / wallets) for any role; and pharmacist (finance view only) approving
reconciliation candidates and confirming payments through old admin/pharmacist role checks.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase, override_settings

from apps.payments.models import ExternalPayment
from apps.tests.factories import make_branch, make_user
from core.middleware import module_access

from .fixtures import bearer_client, role_clients, seed_code_matrix
from .sweep import sweep

PREFIXES = {'finance', 'payments', 'cheques'}


class FinanceSweepTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.clients = role_clients()

    def tearDown(self):
        module_access.clear_cache()

    def test_no_role_gets_past_the_view_without_the_grant(self):
        res = sweep('log', self.clients, prefixes=PREFIXES)
        self.assertEqual(sorted(res.leaks), [])


@override_settings(RBAC_ENFORCEMENT='log')
class PaymentRecordTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.payment = ExternalPayment.objects.create(
            branch=make_branch(), method=ExternalPayment.METHOD_INSTAPAY, amount=Decimal('250.00'),
            payment_date=date(2026, 10, 27), customer_name='Z3 Customer')

    def tearDown(self):
        module_access.clear_cache()

    def _as(self, role):
        return bearer_client(make_user(f'z3_{role}', role=role)[0])

    def test_salesperson_cannot_change_a_payment(self):
        r = self._as('salesperson').patch(f'/api/payments/{self.payment.pk}/', {'amount': '1.00'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.amount, Decimal('250.00'))

    def test_salesperson_cannot_delete_a_payment(self):
        self.assertEqual(self._as('salesperson').delete(f'/api/payments/{self.payment.pk}/').status_code, 403)
        self.assertTrue(ExternalPayment.objects.filter(pk=self.payment.pk).exists())

    def test_pharmacist_cannot_confirm_a_payment(self):
        # matrix: pharmacist has finance view only
        r = self._as('pharmacist').post(f'/api/payments/{self.payment.pk}/confirm/', {}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_purchasing_can_change_a_payment(self):
        r = self._as('purchasing').patch(f'/api/payments/{self.payment.pk}/', {'notes': 'checked'}, format='json')
        self.assertEqual(r.status_code, 200)
