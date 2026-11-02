"""N3 final fix wave: rider 2FA enrolment (C1), admin Z2 recovery (I2), delivery Z2 = rider (I3)."""
import importlib
import json
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


def _mw_call(user, access, path, method='get'):
    from django.http import HttpResponse
    from django.test import RequestFactory
    from apps.access.policy_middleware import ZonePolicyMiddleware
    req = getattr(RequestFactory(), method)(path)
    req.user = user
    req.access = access
    return ZonePolicyMiddleware(lambda _r: HttpResponse('ok'))(req)


@override_settings(NETWORK_POLICY_ENFORCEMENT='enforce', ACCESS_POLICY_TTL=0)
class MiddlewareParityTests(TestCase):
    """M1: the middleware applies the same subject as sign-in / refresh; M2: a failed context is
    open on an internal network (F3), closed outside."""

    def setUp(self):
        cache.clear()

    def test_no_profile_account_follows_viewer_rows(self):
        from django.contrib.auth.models import User
        svc = User.objects.create_user('fw_svc', password='x')
        with self.assertLogs('elrezeiky.access', 'WARNING'):
            r = _mw_call(svc, SimpleNamespace(zone='Z4', failed=False), '/api/customers/')
        self.assertEqual((r.status_code, json.loads(r.content)['reason']), (403, 'blocked'))
        self.assertEqual(_mw_call(svc, SimpleNamespace(zone='Z1', failed=False), '/api/customers/').status_code, 200)

    def test_superuser_without_profile_follows_admin_rows(self):
        from django.contrib.auth.models import User
        su = User.objects.create_superuser('fw_su', password='x')
        self.assertEqual(_mw_call(su, SimpleNamespace(zone='Z3', failed=False), '/api/customers/').status_code, 200)
        with self.assertLogs('elrezeiky.access', 'WARNING'):
            r = _mw_call(su, SimpleNamespace(zone='Z4', failed=False), '/api/customers/')
        self.assertEqual(r.status_code, 403)

    def test_failed_context_inside_is_open_and_logged(self):
        from apps.access.network import NetworkInfo
        user, _, _ = make_user('fw_ctx', role='pharmacist')
        ctx = SimpleNamespace(zone=None, failed=True, network=NetworkInfo(zone='internal', ip=None, site=None))
        with self.assertLogs('elrezeiky.access', 'ERROR'):
            r = _mw_call(user, ctx, '/api/customers/', 'post')
        self.assertEqual(r.status_code, 200)

    def test_failed_context_outside_is_closed(self):
        from apps.access.network import NetworkInfo
        user, _, _ = make_user('fw_ctx2', role='pharmacist')
        ctx = SimpleNamespace(zone=None, failed=True, network=NetworkInfo(zone='external', ip=None, site=None))
        with self.assertLogs('elrezeiky.access', 'WARNING'):
            r = _mw_call(user, ctx, '/api/customers/')
        self.assertEqual((r.status_code, json.loads(r.content)['reason']), (403, 'blocked'))

    @override_settings(NETWORK_HEADER_TRUSTED=True, NETWORK_PROXY_KEY='k')
    def test_fallback_keeps_the_label_without_the_database(self):
        from django.test import RequestFactory
        from apps.access import context
        req = RequestFactory().get('/api/x/', HTTP_X_ELR_NETWORK='internal', HTTP_X_ELR_PROXY_KEY='k')
        ctx = context.fallback(req)
        self.assertEqual((ctx.network.zone, ctx.failed, ctx.zone), ('internal', True, None))
        forged = RequestFactory().get('/api/x/', HTTP_X_ELR_NETWORK='internal')
        self.assertEqual(context.fallback(forged).network.zone, 'external')


@override_settings(ACCESS_POLICY_TTL=0)
class AlwaysOpenAndNoRowsTests(TestCase):
    """M5: help + announcements are open for reading (and a few own-session writes) only; M6: a role
    without rows is open inside and blocked outside."""

    def test_help_and_announcements_reads_only(self):
        ph = _p('pharmacist')
        self.assertTrue(decide(ph, 'Z2', '/api/help/screens/x/', 'GET').allowed)
        self.assertTrue(decide(ph, 'Z2', '/api/notifications/announcements/', 'GET').allowed)
        for path in ('/api/help/onboarding/learned/', '/api/help/quizzes/pos/submit/',
                     '/api/help/tour-event/', '/api/notifications/announcements/4/ack/',
                     '/api/notifications/4/read/', '/api/notifications/preferences/'):
            self.assertTrue(decide(ph, 'Z2', path, 'POST').allowed, path)
        for path in ('/api/notifications/announcements/', '/api/notifications/announcements/4/',
                     '/api/help/feedback/3/resolve/', '/api/help/training/screen/x/', '/api/help/glossary/2/'):
            r = decide(ph, 'Z2', path, 'POST')
            self.assertEqual((r.allowed, r.reason), (False, 'read_only'), path)
        r = decide(_p('delivery'), 'Z4', '/api/help/glossary/2/', 'PATCH')
        self.assertEqual((r.allowed, r.reason), (False, 'module'))

    def test_role_without_rows(self):
        from apps.access import session_policy
        ZonePolicy.objects.filter(role='viewer').delete()
        v = _p('viewer')
        for zone in ('Z1', 'Z2'):
            self.assertTrue(decide(v, zone, '/api/customers/', 'POST', 'customers').allowed, zone)
            self.assertFalse(session_policy.blocked(v, zone), zone)
        for zone in ('Z3', 'Z4', None):
            r = decide(v, zone, '/api/customers/', 'GET', 'customers')
            self.assertEqual((r.allowed, r.reason), (False, 'blocked'), zone)
            self.assertTrue(session_policy.blocked(v, zone), zone)


class MfaClaimTests(TestCase):
    """M3: a session that never passed 2FA cannot be refreshed into a zone that requires it."""

    def test_refresh_into_mfa_zone_needs_the_claim(self):
        from apps.access import session_policy
        _, admin, _ = make_user('fw_mfa_admin', role='admin')
        self.assertEqual(session_policy.refresh_allowed(admin, {'mfa': False}, 'Z3'), (False, 'mfa'))
        self.assertEqual(session_policy.refresh_allowed(admin, {}, 'Z3'), (False, 'mfa'))
        ok, _ = session_policy.refresh_allowed(admin, {'mfa': True, 'iat': 9e9}, 'Z3')
        self.assertTrue(ok)
        self.assertEqual(session_policy.refresh_allowed(admin, {}, 'Z1'), (True, None))
        self.assertEqual(session_policy.message('mfa'), session_policy.MFA_AGAIN_MESSAGE)

    def test_claim_stamped_at_sign_in_and_carried_on_rotation(self):
        from rest_framework_simplejwt.tokens import RefreshToken
        from apps.users.mfa import build_login_response
        from apps.users.views import _stamp_zone
        user, _, _ = make_user('fw_mfa_user', role='admin')
        plain = build_login_response(user, zone='Z1')
        self.assertFalse(RefreshToken(plain['refresh'])['mfa'])
        passed = build_login_response(user, zone='Z1', mfa=True)
        self.assertTrue(RefreshToken(passed['refresh'])['mfa'])
        self.assertTrue(AccessToken(passed['access'])['mfa'])
        access, refresh = _stamp_zone(passed['access'], passed['refresh'], 'Z3', 123, mfa=True)
        self.assertTrue(RefreshToken(refresh)['mfa'])
        self.assertEqual(RefreshToken(refresh)['zone'], 'Z3')
        self.assertTrue(AccessToken(access)['mfa'])

    @override_settings(NETWORK_POLICY_ENFORCEMENT='enforce', NETWORK_HEADER_TRUSTED=True, NETWORK_PROXY_KEY='',
                       ACCESS_POLICY_TTL=0, ACCESS_NETWORKS_TTL=0)
    def test_refresh_view_refuses_without_mfa_on_an_approved_device_outside(self):
        from apps.access import devices
        from apps.access.models import Device
        from core.auth_cookies import REFRESH_COOKIE
        from apps.users.mfa import build_login_response
        user, _, _ = make_user('fw_mfa_ref', role='supervisor')      # Z3 read_only + require_mfa
        secret = devices.new_secret()
        Device.objects.create(secret_hash=devices.hash_secret(secret), name='lap', status='approved')
        self.client.cookies[devices.COOKIE] = secret
        self.client.cookies[REFRESH_COOKIE] = build_login_response(user, zone='Z1')['refresh']
        with self.assertLogs('elrezeiky.access', 'WARNING'):
            r = self.client.post('/api/auth/refresh/', {}, content_type='application/json',
                                 HTTP_X_ELR_NETWORK='external')
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()['reason'], 'mfa')
        self.client.cookies[REFRESH_COOKIE] = build_login_response(user, zone='Z3', mfa=True)['refresh']
        r = self.client.post('/api/auth/refresh/', {}, content_type='application/json',
                             HTTP_X_ELR_NETWORK='external')
        self.assertEqual(r.status_code, 200, r.content)


class ResolveOnceTests(TestCase):
    """F6: the JWT user is worked out once per request, whoever asks."""

    def test_user_from_request_memoised(self):
        from django.test import RequestFactory
        from core.auth_cookies import user_from_request
        user, _, _ = make_user('fw_once', role='pharmacist')
        req = RequestFactory().get('/api/x/', HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
        self.assertEqual(user_from_request(req), user)
        with self.assertNumQueries(0):
            self.assertEqual(user_from_request(req), user)
        anon = RequestFactory().get('/api/x/')
        self.assertIsNone(user_from_request(anon))
        self.assertIsNone(user_from_request(anon))
