"""
UAT W5a P1 — the rider's «تم التسليم» (POST /api/delivery/<id>/complete/) sent
collected_amount as text and the server crashed (str − Decimal) AFTER saving the order as
delivered, so a cash order lost its cash-collection row. The amount is now parsed as a
Decimal before any write, and the delivered status + cash-collection row are one
transaction.
"""
from decimal import Decimal
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from apps.delivery.models import CashCollection, DeliveryDriver, DeliveryOrder, DeliveryStatusLog
from apps.tests.factories import make_branch, make_user
from core.middleware import module_access


class DeliveryCompleteAmountTests(TestCase):
    def setUp(self):
        call_command('seed_permissions', verbosity=0)
        module_access.clear_cache()
        self.branch = make_branch()
        _, prof, self.rider = make_user('w5a_rider', role='delivery', branch=self.branch)
        self.driver = DeliveryDriver.objects.create(full_name='سائق', mobile='0100000077',
                                                    staff_profile=prof)
        self.order = DeliveryOrder.objects.create(
            branch=self.branch, customer_name='عميل', assigned_driver=self.driver,
            status=DeliveryOrder.STATUS_OUT, payment_method=DeliveryOrder.PAY_CASH,
            total_value=Decimal('100.00'), delivery_fees=Decimal('10.00'))

    def tearDown(self):
        module_access.clear_cache()

    def _complete(self, **body):
        return self.rider.post(f'/api/delivery/{self.order.pk}/complete/', body, format='json')

    def test_string_amount_completes_and_writes_collection(self):
        r = self._complete(collected_amount='105.50')
        self.assertEqual(r.status_code, 200, r.content)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, DeliveryOrder.STATUS_DELIVERED)
        self.assertEqual(self.order.collected_amount, Decimal('105.50'))
        cash = CashCollection.objects.get(order=self.order)
        self.assertEqual(cash.expected_amount, Decimal('110.00'))
        self.assertEqual(cash.collected_amount, Decimal('105.50'))
        self.assertEqual(cash.status, 'shortage')
        self.assertEqual(cash.shortage_amount, Decimal('4.50'))

    def test_rider_form_upload_amount(self):
        # the /rider screen posts FormData (multipart), so every value arrives as text
        r = self.rider.post(f'/api/delivery/{self.order.pk}/complete/',
                            {'collected_amount': '110', 'pod_recipient_name': 'البواب'},
                            format='multipart')
        self.assertEqual(r.status_code, 200, r.content)
        cash = CashCollection.objects.get(order=self.order)
        self.assertEqual(cash.collected_amount, Decimal('110.00'))
        self.assertEqual(cash.status, 'collected')

    def test_blank_amount_keeps_old_behaviour(self):
        r = self._complete(collected_amount='')
        self.assertEqual(r.status_code, 200, r.content)
        self.order.refresh_from_db()
        self.assertIsNone(self.order.collected_amount)
        cash = CashCollection.objects.get(order=self.order)
        self.assertEqual(cash.collected_amount, Decimal('110.00'))
        self.assertEqual(cash.status, 'collected')

    def test_junk_amount_is_400_and_order_not_delivered(self):
        for junk in ('abc', '-5', '10.505', 'NaN', 'Infinity', '1e20', True):
            r = self._complete(collected_amount=junk)
            self.assertEqual(r.status_code, 400, (junk, r.content))
            self.assertEqual(r.json().get('field'), 'collected_amount')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, DeliveryOrder.STATUS_OUT)
        self.assertIsNone(self.order.delivered_at)
        self.assertFalse(CashCollection.objects.filter(order=self.order).exists())

    def test_failure_in_collection_step_leaves_order_not_delivered(self):
        logs_before = DeliveryStatusLog.objects.filter(order=self.order).count()
        self.rider.raise_request_exception = False
        with mock.patch.object(CashCollection.objects, 'update_or_create',
                               side_effect=RuntimeError('boom')):
            r = self._complete(collected_amount='110')
        self.assertEqual(r.status_code, 500)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, DeliveryOrder.STATUS_OUT)
        self.assertIsNone(self.order.delivered_at)
        self.assertIsNone(self.order.collected_amount)
        self.assertEqual(DeliveryStatusLog.objects.filter(order=self.order).count(), logs_before)

    def test_backfill_rejects_junk_amount(self):
        sup = make_user('w5a_sup', role='supervisor', branch=self.branch)[2]
        r = sup.post(f'/api/delivery/{self.order.pk}/backfill/',
                     {'confirm_delivery': True, 'collected_amount': 'abc'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, DeliveryOrder.STATUS_OUT)
        r = sup.post(f'/api/delivery/{self.order.pk}/backfill/',
                     {'confirm_delivery': True, 'collected_amount': '110'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(CashCollection.objects.get(order=self.order).collected_amount,
                         Decimal('110.00'))
