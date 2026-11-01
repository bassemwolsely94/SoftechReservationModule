"""N3 final fix wave: rider 2FA enrolment (C1), admin Z2 recovery (I2), delivery Z2 = rider (I3)."""
import importlib
from types import SimpleNamespace

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework_simplejwt.tokens import AccessToken

from apps.access.models import TrustedNetwork, ZonePolicy
from apps.access.policy import decide
from apps.tests.factories import make_user

seed = importlib.import_module('apps.access.migrations.0006_seed_zone_policy')


def _p(role):
    return SimpleNamespace(role=role, external_export=False, external_softech_write=False)


class SeedTests(TestCase):

    def test_delivery_z2_is_rider_surface(self):
        row = seed._row('delivery', 'Z2')
        self.assertEqual(row['access'], 'rider')
        self.assertFalse(row['require_mfa'])
        self.assertIsNone(row['max_session_hours'])
        self.assertEqual(seed._row('pharmacist', 'Z2')['access'], 'read_only')

    def test_seeded_row_in_db(self):
        self.assertEqual(ZonePolicy.objects.get(role='delivery', zone='Z2').access, 'rider')


@override_settings(ACCESS_POLICY_TTL=0)
class AdminZ2RecoveryTests(TestCase):

    def test_admin_in_z2_may_approve_devices_and_fix_networks(self):
        for path in ('/api/access/devices/5/approve/', '/api/access/devices/bulk-approve/',
                     '/api/access/networks/', '/api/access/networks/3/'):
            for method in ('POST', 'PATCH'):
                self.assertTrue(decide(_p('admin'), 'Z2', path, method, 'access').allowed, (path, method))

    def test_recovery_is_narrow(self):
        r = decide(_p('admin'), 'Z2', '/api/access/zone-policies/1/', 'PATCH', 'access')
        self.assertEqual((r.allowed, r.reason), (False, 'read_only'))
        self.assertFalse(decide(_p('admin'), 'Z2', '/api/customers/', 'POST', 'customers').allowed)
        self.assertFalse(decide(_p('supervisor'), 'Z2', '/api/access/devices/5/approve/', 'POST').allowed)
        self.assertFalse(decide(_p('admin'), 'Z4', '/api/access/devices/5/approve/', 'POST', 'access').allowed)

    def test_rider_in_z2_keeps_rider_writes(self):
        self.assertTrue(decide(_p('delivery'), 'Z2', '/api/delivery/7/complete/', 'POST').allowed)
        self.assertFalse(decide(_p('delivery'), 'Z2', '/api/customers/', 'GET', 'customers').allowed)


@override_settings(NETWORK_POLICY_ENFORCEMENT='enforce', NETWORK_HEADER_TRUSTED=True, NETWORK_PROXY_KEY='',
                   ACCESS_NETWORKS_TTL=0, ACCESS_POLICY_TTL=0)
class RiderEnrolmentTests(TestCase):
    """C1: a signed-in rider can open the 2FA setup (it lives under /api/auth/, open in every zone);
    the rider screen links to it (/rider/security)."""

    def setUp(self):
        cache.clear()
        TrustedNetwork.objects.create(name='فرع', cidr='10.61.61.0/24', kind='branch_lan')
        self.user, self.profile, _ = make_user('fw_rider', role='delivery')
        self.auth = {'HTTP_AUTHORIZATION': f'Bearer {AccessToken.for_user(self.user)}'}

    def _setup(self, network):
        return self.client.post('/api/auth/2fa/setup/', {}, content_type='application/json',
                                HTTP_X_ELR_NETWORK=network, REMOTE_ADDR='10.61.61.4', **self.auth)

    def test_rider_inside_unapproved_phone_can_start_2fa(self):
        r = self._setup('internal')                      # Z2
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn('qr_png', r.json())

    def test_rider_in_session_outside_can_start_2fa(self):
        r = self._setup('external')                      # Z4: voluntary enrolment in a running session
        self.assertEqual(r.status_code, 200, r.content)

    def test_rider_route_has_help(self):
        from apps.help.content import general
        screen = next(s for s in general.SCREENS if s['key'] == 'general.security')
        self.assertIn('/rider/security', screen['routes'])


class UnsafeEnforceTests(TestCase):
    """I5: enforce on an unsafe setup (E003 / E004) runs as log, with an ERROR line — in the
    middleware, at sign-in and at start-up (config.writers.run_startup_checks)."""

    def setUp(self):
        cache.clear()

    def _mode(self):
        from apps.access.policy_middleware import _mode
        return _mode()

    @override_settings(NETWORK_ENFORCE_GUARD=True, NETWORK_POLICY_ENFORCEMENT='enforce',
                       NETWORK_HEADER_TRUSTED=False, NETWORK_PROXY_KEY='k')
    def test_untrusted_header_degrades_to_log(self):
        with self.assertLogs('elrezeiky.access', 'ERROR') as cm:
            self.assertEqual(self._mode(), 'log')
        self.assertIn('access.E004', cm.output[0])

    @override_settings(NETWORK_ENFORCE_GUARD=True, NETWORK_POLICY_ENFORCEMENT='enforce',
                       NETWORK_HEADER_TRUSTED=True, NETWORK_PROXY_KEY='')
    def test_missing_key_degrades_to_log(self):
        with self.assertLogs('elrezeiky.access', 'ERROR') as cm:
            self.assertEqual(self._mode(), 'log')
        self.assertIn('access.E003', cm.output[0])

    @override_settings(NETWORK_ENFORCE_GUARD=True, NETWORK_POLICY_ENFORCEMENT='enforce',
                       NETWORK_HEADER_TRUSTED=True, NETWORK_PROXY_KEY='k')
    def test_safe_setup_keeps_enforce(self):
        self.assertEqual(self._mode(), 'enforce')

    @override_settings(NETWORK_ENFORCE_GUARD=True, NETWORK_POLICY_ENFORCEMENT='enforce',
                       NETWORK_HEADER_TRUSTED=False, NETWORK_PROXY_KEY='', ACCESS_POLICY_TTL=0)
    def test_middleware_does_not_refuse_when_unsafe(self):
        from django.http import HttpResponse
        from django.test import RequestFactory
        from apps.access.policy_middleware import ZonePolicyMiddleware
        user, _, _ = make_user('fw_unsafe', role='pharmacist')
        req = RequestFactory().get('/api/customers/')
        req.user = user
        req.access = SimpleNamespace(zone='Z4', failed=False)
        with self.assertLogs('elrezeiky.access', 'WARNING') as cm:
            r = ZonePolicyMiddleware(lambda _r: HttpResponse('ok'))(req)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any('ERROR' in line and 'E004' in line for line in cm.output), cm.output)
        self.assertTrue(any('zone would-deny' in line for line in cm.output), cm.output)

    @override_settings(NETWORK_ENFORCE_GUARD=True, NETWORK_POLICY_ENFORCEMENT='enforce',
                       NETWORK_HEADER_TRUSTED=True, NETWORK_PROXY_KEY='', SOFTECH_READ_ONLY=False)
    def test_startup_check_writes_the_error(self):
        import tempfile
        from pathlib import Path
        from config import writers
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / '.env'
            env.write_text('A=1\n', encoding='utf-8')
            with self.assertLogs('elrezeiky.access', 'ERROR') as cm:
                writers.run_startup_checks(env_path=env)
        self.assertIn('access.E003', cm.output[0])
