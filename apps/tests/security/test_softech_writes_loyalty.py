"""
SOFTECH write safety — manual purchase-points adjustment (Batch 2, P-4).

POST /api/loyalty/customers/<id>/adjust/ (adjust_type=purchase) INSERTs a picpoints row in
SOFTECH; the tr_picpoints trigger moves the customer's balance. Before P-4 a double click or
a network retry posted the points twice, any size was accepted, and the reason was optional.
"""
from unittest import mock

from django.test import TestCase, override_settings

from apps.tests.factories import make_customer, make_user


URL = '/api/loyalty/customers/{}/adjust/'


@override_settings(LOYALTY_SOFTECH_WRITE_ENABLED=True)
class LoyaltyAdjustSafetyTests(TestCase):

    def setUp(self):
        self.customer = make_customer(phone='01099990001')
        self.customer.softech_pic = '130HD9668'
        self.customer.save(update_fields=['softech_pic'])
        _, _, self.cc = make_user('ly_cc', role='call_center', access_all=True)
        patches = [mock.patch('apps.loyalty.pic_bridge.is_softech_points_enrolled', return_value=True),
                   mock.patch('apps.loyalty.pic_bridge.adjust_softech_points', return_value=150)]
        self.enrolled, self.write = (p.start() for p in patches)
        for p in patches:
            self.addCleanup(p.stop)

    def _post(self, points=50, reason='تعويض عن خطأ فاتورة', client=None):
        return (client or self.cc).post(URL.format(self.customer.id),
                                        {'points': points, 'reason': reason}, format='json')

    def test_double_submit_posts_once(self):
        first, second = self._post(), self._post()
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(self.write.call_count, 1)

    def test_retry_after_a_failed_attempt_is_held_too(self):
        self.write.side_effect = RuntimeError('تعذّر قراءة الرصيد بعد التحديث')   # insert may have landed
        self.assertEqual(self._post().status_code, 502)
        self.write.side_effect = None
        self.assertEqual(self._post().status_code, 409)
        self.assertEqual(self.write.call_count, 1)

    def test_size_is_capped(self):
        with override_settings(LOYALTY_MAX_MANUAL_ADJUST=1000):
            self.assertEqual(self._post(points=1001).status_code, 400)
            self.assertEqual(self._post(points=-1001).status_code, 400)
        self.write.assert_not_called()

    def test_reason_required_for_purchase_points(self):
        self.assertEqual(self._post(reason='  ').status_code, 400)
        self.write.assert_not_called()

    def test_different_adjustments_still_go_through(self):
        self.assertEqual(self._post(points=50).status_code, 200)
        self.assertEqual(self._post(points=-20, reason='استرداد هدية').status_code, 200)
        self.assertEqual(self.write.call_count, 2)

    def test_referral_lane_unchanged(self):
        r = self.cc.post(URL.format(self.customer.id),
                         {'points': 10, 'reason': '', 'adjust_type': 'referral'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.write.assert_not_called()
