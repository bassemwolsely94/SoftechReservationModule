"""
N1 / Task 2 — apps/access: the trusted-network list and the per-request network label.
The label comes only from nginx's X-ElR-Network header, and only when NETWORK_HEADER_TRUSTED.
"""
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase, override_settings

from apps.access.models import TrustedNetwork
from apps.access.network import EXTERNAL, INTERNAL, match_site, proxy_key_ok, request_network, zone_from_request


def _req(header=None, ip='10.50.50.9', key=None):
    extra = {'REMOTE_ADDR': ip}
    if key is not None:
        extra['HTTP_X_ELR_PROXY_KEY'] = key
    if header is not None:
        extra['HTTP_X_ELR_NETWORK'] = header
    return RequestFactory().get('/', **extra)


def _net(name, cidr, **kw):
    return TrustedNetwork.objects.create(name=name, cidr=cidr, kind=kw.pop('kind', 'staff_vpn'), **kw)


@override_settings(ACCESS_NETWORKS_TTL=0)
class ZoneTests(TestCase):

    @override_settings(NETWORK_HEADER_TRUSTED=True)
    def test_trusted_header_internal(self):
        self.assertEqual(zone_from_request(_req('internal')), INTERNAL)

    @override_settings(NETWORK_HEADER_TRUSTED=True)
    def test_trusted_header_missing_is_external(self):
        self.assertEqual(zone_from_request(_req()), EXTERNAL)

    @override_settings(NETWORK_HEADER_TRUSTED=True)
    def test_trusted_header_garbage_is_external(self):
        for junk in ('Internal', 'internal ', 'yes', '', 'internal,internal'):
            self.assertEqual(zone_from_request(_req(junk)), EXTERNAL, repr(junk))

    @override_settings(NETWORK_HEADER_TRUSTED=False, NETWORK_UNTRUSTED_ZONE='internal')
    def test_untrusted_ignores_client_header(self):
        self.assertEqual(zone_from_request(_req('external')), INTERNAL)
        with override_settings(NETWORK_UNTRUSTED_ZONE='external'):
            self.assertEqual(zone_from_request(_req('internal')), EXTERNAL)


@override_settings(ACCESS_NETWORKS_TTL=0, NETWORK_HEADER_TRUSTED=True, NETWORK_PROXY_KEY='s3cret-key')
class ProxyKeyTests(TestCase):

    def test_key_set_and_missing_header_is_external(self):
        self.assertEqual(zone_from_request(_req('internal')), EXTERNAL)
        self.assertFalse(proxy_key_ok(_req('internal')))

    def test_key_set_and_wrong_key_is_external(self):
        self.assertEqual(zone_from_request(_req('internal', key='nope')), EXTERNAL)
        self.assertEqual(zone_from_request(_req('internal', key='')), EXTERNAL)

    def test_key_matches_internal_trusted(self):
        self.assertTrue(proxy_key_ok(_req('internal', key='s3cret-key')))
        self.assertEqual(zone_from_request(_req('internal', key='s3cret-key')), INTERNAL)
        self.assertEqual(zone_from_request(_req('external', key='s3cret-key')), EXTERNAL)

    @override_settings(NETWORK_PROXY_KEY='')
    def test_no_key_configured_keeps_n1_behaviour(self):
        self.assertTrue(proxy_key_ok(_req()))
        self.assertEqual(zone_from_request(_req('internal')), INTERNAL)
        self.assertEqual(zone_from_request(_req()), EXTERNAL)


@override_settings(ACCESS_NETWORKS_TTL=0, NETWORK_HEADER_TRUSTED=True, NUM_PROXIES=0)
class SiteTests(TestCase):

    def test_longest_prefix_wins(self):
        _net('wide', '10.0.0.0/8')
        _net('zt', '10.50.50.0/24')
        self.assertEqual(match_site('10.50.50.9').name, 'zt')
        self.assertEqual(match_site('10.9.9.9').name, 'wide')

    def test_internal_unlisted_ip_has_no_site(self):
        _net('zt', '10.50.50.0/24')
        info = request_network(_req('internal', ip='172.16.1.1'))
        self.assertEqual((info.zone, info.site), (INTERNAL, None))
        self.assertEqual(info.label_ar, 'شبكة داخلية غير مسجلة')

    def test_internal_listed_ip_gets_site_and_label(self):
        _net('ZT staff', '10.50.50.0/24')
        info = request_network(_req('internal'))
        self.assertEqual(info.site.name, 'ZT staff')
        self.assertEqual(info.label_ar, 'داخل الشبكة — ZT staff')

    def test_external_never_gets_site(self):
        _net('zt', '10.50.50.0/24')
        info = request_network(_req('external'))
        self.assertEqual((info.zone, info.site), (EXTERNAL, None))
        self.assertEqual(info.label_ar, 'خارج الشبكة')

    def test_inactive_network_ignored(self):
        _net('zt', '10.50.50.0/24', is_active=False)
        self.assertIsNone(match_site('10.50.50.9'))

    def test_bad_ip_and_ipv6(self):
        _net('v6', '2001:db8:1::/64')
        self.assertIsNone(match_site('abc'))
        self.assertIsNone(match_site(None))
        self.assertEqual(match_site('2001:db8:1::5').name, 'v6')
        self.assertIsNone(match_site('2001:db8:2::5'))

    def test_cache_invalidated_on_save_and_delete(self):
        with override_settings(ACCESS_NETWORKS_TTL=60):
            self.assertIsNone(match_site('10.50.50.9'))
            n = _net('zt', '10.50.50.0/24')
            self.assertEqual(match_site('10.50.50.9').name, 'zt')
            n.delete()
            self.assertIsNone(match_site('10.50.50.9'))


class CidrTests(TestCase):

    def test_cidr_normalised_and_validated(self):
        n = TrustedNetwork(name='x', cidr='192.168.3.7/24', kind='branch_lan')
        n.full_clean()
        self.assertEqual(n.cidr, '192.168.3.0/24')
        bad = TrustedNetwork(name='y', cidr='300.1.1.1/24', kind='branch_lan')
        with self.assertRaises(ValidationError):
            bad.full_clean()
