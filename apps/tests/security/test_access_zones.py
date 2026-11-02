"""N3 / Task 2 - access zone Z1-Z4 from network and device."""
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.access import context, devices, zones
from apps.access.context import AccessContext
from apps.access.models import Device
from apps.access.network import EXTERNAL, INTERNAL, NetworkInfo
from apps.tests.factories import make_user

WHOAMI = '/api/access/whoami/'


def _net(zone):
    return NetworkInfo(zone=zone, ip=None, site=None)


class ZoneMatrixTests(TestCase):

    def test_zone_matrix(self):
        cases = [
            (INTERNAL, 'approved', 'Z1'), (INTERNAL, 'pending', 'Z2'), (INTERNAL, 'blocked', 'Z2'),
            (INTERNAL, 'retired', 'Z2'), (INTERNAL, None, 'Z2'),
            (EXTERNAL, 'approved', 'Z3'), (EXTERNAL, 'pending', 'Z4'), (EXTERNAL, 'blocked', 'Z4'),
            (EXTERNAL, 'retired', 'Z4'), (EXTERNAL, None, 'Z4'),
        ]
        for net, status, expected in cases:
            with self.subTest(net=net, status=status):
                self.assertEqual(zones.zone_for(net, status), expected)

    def test_labels(self):
        self.assertEqual(set(zones.ZONE_LABELS), {'Z1', 'Z2', 'Z3', 'Z4'})
        self.assertEqual(zones.ZONE_LABELS['Z1'], 'داخل الشبكة — جهاز معتمد')
        self.assertEqual(zones.ZONE_LABELS['Z4'], 'خارج الشبكة — جهاز غير معتمد')

    def test_default_zone_field_and_fallback(self):
        self.assertIsNone(AccessContext(network=_net(INTERNAL), user_id=1, role='admin').zone)
        self.assertIsNone(context.fallback().zone)


@override_settings(NETWORK_HEADER_TRUSTED=True, ACCESS_NETWORKS_TTL=0, NUM_PROXIES=0)
class ZoneContextTests(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user, self.profile, _ = make_user('zn_user', role='pharmacist')

    def _device(self, status):
        secret = devices.new_secret()
        Device.objects.create(secret_hash=devices.hash_secret(secret), name='ج', status=status,
                              owner=self.profile)
        return secret

    def _whoami(self, status=None, network='internal'):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(self.user)}')
        if status:
            c.cookies[devices.COOKIE] = self._device(status)
        kw = {'HTTP_X_ELR_NETWORK': network} if network else {}
        return c.get(WHOAMI, **kw).json()

    def test_anonymous_has_no_zone(self):
        d = APIClient().get(WHOAMI, HTTP_X_ELR_NETWORK='internal').json()
        self.assertIsNone(d['access_zone'])
        self.assertIsNone(d['access_zone_label'])
        self.assertEqual(d['zone'], 'internal')   # the network zone key is unchanged

    def test_whoami_zone_signed_in(self):
        d = self._whoami('approved')
        self.assertEqual((d['access_zone'], d['access_zone_label']), ('Z1', zones.ZONE_LABELS['Z1']))

    def test_whoami_zone_variants(self):
        self.assertEqual(self._whoami(None)['access_zone'], 'Z2')
        self.assertEqual(self._whoami('blocked')['access_zone'], 'Z2')
        self.assertEqual(self._whoami('approved', network=None)['access_zone'], 'Z3')
        self.assertEqual(self._whoami('pending', network=None)['access_zone'], 'Z4')

    def test_current_zone_none_outside_request(self):
        self.assertIsNone(zones.current_zone())
