"""N6 / Task 4 - portal sign-in link guarded, public tracking throttled and on /api/public/."""
from unittest import mock

from django.core import signing
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.customers.models import Customer
from apps.delivery.models import DeliveryOrder
from apps.tests.factories import make_branch
from apps.tests.public_guard_helpers import solved
from core import public_guard

LINK = '/api/portal/request-link/'
GENERIC = 'إذا كان لديك حساب، فسيصلك رابط الدخول عبر واتساب.'


@override_settings(PUBLIC_POW_DIFFICULTY=4, PUBLIC_MIN_FILL_SECONDS=0, PUBLIC_PHONE_DAILY_MAX=3)
class PortalLinkGuardTests(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.c = APIClient()
        self.branch = make_branch()
        Customer.objects.create(softech_pic='01N6T4', name='سعيد', phone='01055667788',
                                preferred_branch=self.branch)

    def _post(self, body):
        return self.c.post(LINK, body, format='json')

    def test_request_link_requires_challenge(self):
        with mock.patch('apps.portal.views.send_magic_link') as send:
            r = self._post({'phone': '01055667788'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['detail'], public_guard.GUARD_MESSAGES['expired'])
        send.assert_not_called()

    def test_request_link_bot_gets_generic_200_and_no_message(self):
        with mock.patch('apps.portal.views.send_magic_link') as send:
            r = self._post(solved('portal_link', phone='01055667788', website='http://spam'))
        self.assertEqual((r.status_code, r.json()), (200, {'detail': GENERIC}))
        send.assert_not_called()

    def test_phone_limit_gets_generic_200_and_no_message(self):
        with mock.patch('apps.portal.views.send_magic_link') as send:
            codes = [self._post(solved('portal_link', phone='01055667788')) for _ in range(4)]
        self.assertEqual([r.status_code for r in codes], [200] * 4)
        self.assertEqual(send.call_count, 3)

    def test_request_link_same_response_known_and_unknown_phone(self):
        with mock.patch('apps.portal.views.send_magic_link') as send:
            r1 = self._post(solved('portal_link', phone='01055667788'))
            r2 = self._post(solved('portal_link', phone='01000000000'))
        self.assertEqual((r1.status_code, r1.content), (r2.status_code, r2.content))
        self.assertEqual(send.call_count, 1)

    def test_invalid_phone_does_not_burn_a_slot(self):
        for _ in range(5):
            r = self._post(solved('portal_link', phone=''))
            self.assertEqual(r.status_code, 400)
        with mock.patch('apps.portal.views.send_magic_link') as send:
            r = self._post(solved('portal_link', phone='01055667788'))
        self.assertEqual(r.status_code, 200)
        send.assert_called_once()


class TrackTests(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.c = APIClient()
        branch = make_branch()
        order = DeliveryOrder.objects.create(branch=branch, customer_name='ع',
                                             status=DeliveryOrder.STATUS_READY)
        self.token = signing.dumps({'oid': order.pk}, salt='delivery-track')

    def test_new_track_path_works(self):
        r = self.c.get(f'/api/public/track/{self.token}/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json(), self.c.get(f'/api/delivery/track/{self.token}/').json())

    def test_old_track_path_still_works(self):
        self.assertEqual(self.c.get(f'/api/delivery/track/{self.token}/').status_code, 200)

    def test_track_throttled(self):
        codes = [self.c.get(f'/api/public/track/{self.token}/').status_code for _ in range(601)]
        self.assertEqual(codes[:600], [200] * 600)
        self.assertEqual(codes[600], 429)
