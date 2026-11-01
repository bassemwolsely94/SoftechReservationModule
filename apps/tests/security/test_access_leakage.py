"""N3 / Task 6 - leakage controls: the rider is confined to the rider screen (H4) and customer
phones are masked outside the network. Masking applies only when NETWORK_POLICY_ENFORCEMENT is
'enforce' - the log period never changes what staff see."""
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.access.models import TrustedNetwork
from apps.customers import access
from apps.tests.factories import make_customer, make_user


def _in_zone(zone):
    return mock.patch('apps.access.zones.current_zone', return_value=zone)


@override_settings(NETWORK_POLICY_ENFORCEMENT='enforce', NETWORK_HEADER_TRUSTED=True,
                   NETWORK_PROXY_KEY='', ACCESS_NETWORKS_TTL=0, ACCESS_POLICY_TTL=0)
class RiderConfinementTests(TestCase):

    def setUp(self):
        from rest_framework_simplejwt.tokens import AccessToken
        cache.clear()
        TrustedNetwork.objects.create(name='فرع', cidr='10.60.60.0/24', kind='branch_lan')
        self.user, _, _ = make_user('lk_rider', role='delivery')
        self.kw = dict(HTTP_X_ELR_NETWORK='external', REMOTE_ADDR='10.60.60.9',
                       HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(self.user)}')

    def test_rider_z4_only_rider_paths(self):
        for path in ('/api/customers/', '/api/delivery/', '/api/pos-orders/', '/api/reservations/',
                     '/api/delivery/12/assign/', '/api/delivery/dashboard/'):
            r = self.client.get(path, **self.kw)
            self.assertEqual(r.status_code, 403, path)
            self.assertEqual(r.json()['reason'], 'module', path)
        for path in ('/api/delivery/app/my-route/', '/api/delivery/app/my-orders/',
                     '/api/auth/me/', '/api/users/my-permissions/', '/api/notifications/'):
            r = self.client.get(path, **self.kw)
            self.assertNotIn('reason', r.json() if r.status_code == 403 else {}, (path, r.content))   # a view 403 (no driver profile) is not a zone refusal


class PhoneMaskingOutsideTests(TestCase):

    def setUp(self):
        self.customer = make_customer(phone='01012345678')
        self.pharm, _, _ = make_user('lk_ph', role='pharmacist', access_all=True)
        self.rider, _, _ = make_user('lk_rd', role='delivery', access_all=True)
        self.cc, _, _ = make_user('lk_cc', role='call_center', access_all=True)

    @override_settings(NETWORK_POLICY_ENFORCEMENT='enforce')
    def test_customer_phone_masked_external(self):
        for zone in ('Z3', 'Z4'):
            with _in_zone(zone):
                self.assertFalse(access.phones_visible(self.pharm, self.customer), zone)
                self.assertFalse(access.phones_visible(self.rider, self.customer), zone)
                self.assertFalse(access.record_phones_visible(self.pharm), zone)
                self.assertTrue(access.record_phone(self.pharm, '01012345678').startswith('•'))

    @override_settings(NETWORK_POLICY_ENFORCEMENT='enforce')
    def test_rider_sees_own_order_phone_external(self):
        for zone in ('Z3', 'Z4'):
            with _in_zone(zone):
                self.assertTrue(access.record_phones_visible(self.rider), zone)
                self.assertTrue(access.record_phones_visible(self.cc), zone)
                self.assertEqual(access.record_phone(self.rider, '01012345678'), '01012345678')

    @override_settings(NETWORK_POLICY_ENFORCEMENT='enforce')
    def test_internal_unchanged(self):
        for zone in ('Z1', 'Z2', None):
            with _in_zone(zone):
                self.assertTrue(access.phones_visible(self.pharm, self.customer), zone)
                self.assertTrue(access.record_phones_visible(self.pharm), zone)

    @override_settings(NETWORK_POLICY_ENFORCEMENT='log')
    def test_log_mode_changes_nothing(self):
        with _in_zone('Z4'):
            self.assertTrue(access.phones_visible(self.pharm, self.customer))
            self.assertTrue(access.record_phones_visible(self.pharm))
