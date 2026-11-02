"""
N1 / Task 3 — the per-request access context, the login log's network + browser, and SOFTECH
load filed by network and role. Log only: nothing here refuses a request.
"""
import pyotp
from django.core.cache import cache
from django.http import JsonResponse
from django.test import TestCase, override_settings
from django.urls import path
from rest_framework.test import APIClient

from apps.access import context
from apps.access.models import TrustedNetwork
from apps.tests.factories import make_user
from apps.users.models import UserActivityLog

SITE_IP = '10.50.50.9'
UA = 'Mozilla/5.0 (Test) Browser/1.0'


def _probe(request):
    from apps.sync import softech_load
    acc = getattr(request, 'access', None)
    return JsonResponse({
        'scope': softech_load.current_scope(),
        'zone': acc.network.zone if acc else None,
        'site': acc.network.site.name if acc and acc.network.site else None,
        'ctx': context.current() is not None,
    })


urlpatterns = [path('probe/', _probe), path('api/probe/', _probe)]


@override_settings(NETWORK_HEADER_TRUSTED=True, ACCESS_NETWORKS_TTL=0,
                   ROOT_URLCONF='apps.tests.security.test_access_context')
class AccessContextTests(TestCase):

    def setUp(self):
        cache.clear()
        TrustedNetwork.objects.create(name='فرع المعادي', cidr='10.50.50.0/24', kind='branch_lan')

    def test_request_access_attached(self):
        r = self.client.get('/probe/', HTTP_X_ELR_NETWORK='internal', REMOTE_ADDR=SITE_IP)
        self.assertEqual(r.json()['site'], 'فرع المعادي')
        self.assertEqual(r.json()['zone'], 'internal')

    def test_contextvar_reset_after_response(self):
        r = self.client.get('/probe/', HTTP_X_ELR_NETWORK='internal', REMOTE_ADDR=SITE_IP)
        self.assertTrue(r.json()['ctx'])
        self.assertIsNone(context.current())

    def test_softech_scope_label(self):
        from apps.sync import softech_load
        from rest_framework_simplejwt.tokens import AccessToken
        user, _, _ = make_user('ctx_ph', role='pharmacist')
        r = self.client.get('/probe/', REMOTE_ADDR=SITE_IP,   # no header, trusted -> external
                            HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
        self.assertEqual(r.json()['scope'], 'web:external:pharmacist')
        self.assertNotEqual(softech_load.current_scope(), 'web:external:pharmacist')

    def test_scope_anonymous(self):
        r = self.client.get('/probe/', HTTP_X_ELR_NETWORK='internal', REMOTE_ADDR=SITE_IP)
        self.assertEqual(r.json()['scope'], 'web:internal:anon')

    def test_middleware_never_raises(self):
        from unittest import mock
        with mock.patch('apps.access.context.request_network', side_effect=RuntimeError('boom')), \
                self.assertLogs('elrezeiky.access', 'WARNING'):
            r = self.client.get('/probe/', HTTP_X_ELR_NETWORK='internal', REMOTE_ADDR=SITE_IP)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['zone'], 'external')
        self.assertEqual(r.json()['scope'], 'web:external:anon')

    @override_settings(NETWORK_POLICY_ENFORCEMENT='log')
    def test_external_api_request_logged_in_log_mode(self):
        with self.assertLogs('elrezeiky.access', 'INFO') as cm:
            self.client.get('/api/probe/', REMOTE_ADDR='203.0.113.9')
        self.assertTrue(any('203.0.113.9' in m and '/api/probe/' in m for m in cm.output))

    @override_settings(NETWORK_POLICY_ENFORCEMENT='log')
    def test_repeated_identical_request_logged_once(self):
        cache.clear()
        with self.assertLogs('elrezeiky.access', 'INFO') as cm:
            for _ in range(3):
                self.client.get('/api/probe/', REMOTE_ADDR='203.0.113.77')
            self.client.get('/api/probe/', REMOTE_ADDR='203.0.113.78')
        self.assertEqual(len([m for m in cm.output if '203.0.113.77' in m]), 1)
        self.assertEqual(len([m for m in cm.output if '203.0.113.78' in m]), 1)

    @override_settings(NETWORK_POLICY_ENFORCEMENT='log')
    def test_log_dedupe_never_raises_when_cache_fails(self):
        from unittest import mock
        with mock.patch('apps.access.middleware.cache.add', side_effect=RuntimeError('boom')):
            r = self.client.get('/api/probe/', REMOTE_ADDR='203.0.113.9')
        self.assertEqual(r.status_code, 200)

    @override_settings(NETWORK_POLICY_ENFORCEMENT='off')
    def test_nothing_logged_when_off(self):
        with self.assertNoLogs('elrezeiky.access', 'INFO'):
            self.client.get('/api/probe/', REMOTE_ADDR='203.0.113.9')


@override_settings(NETWORK_HEADER_TRUSTED=True, ACCESS_NETWORKS_TTL=0)
class LoginLogTests(TestCase):

    def setUp(self):
        cache.clear()
        TrustedNetwork.objects.create(name='فرع المعادي', cidr='10.50.50.0/24', kind='branch_lan')
        self.user, self.profile, _ = make_user('ctx_login', role='purchasing', password='Ctx-pw-1234')

    def _login(self, pw, **extra):
        return APIClient().post('/api/auth/login/', {'username': 'ctx_login', 'password': pw},
                                format='json', HTTP_USER_AGENT=UA, **extra)

    def test_login_rows_record_network_and_agent(self):
        self._login('wrong', HTTP_X_ELR_NETWORK='internal', REMOTE_ADDR=SITE_IP)
        self._login('Ctx-pw-1234', HTTP_X_ELR_NETWORK='internal', REMOTE_ADDR=SITE_IP)
        self._login('wrong', REMOTE_ADDR='203.0.113.9')
        rows = {(r.action, r.network): r for r in UserActivityLog.objects.filter(target_user=self.profile)}
        failed = rows[('login_failed', 'internal')]
        self.assertEqual(failed.network_site, 'فرع المعادي')
        self.assertEqual(failed.user_agent, UA)
        self.assertIn(('login_success', 'internal'), rows)
        ext = rows[('login_failed', 'external')]
        self.assertEqual(ext.network_site, '')

    def test_user_agent_truncated(self):
        APIClient().post('/api/auth/login/', {'username': 'ctx_login', 'password': 'x'},
                         format='json', HTTP_USER_AGENT='A' * 500, REMOTE_ADDR=SITE_IP)
        row = UserActivityLog.objects.filter(target_user=self.profile).first()
        self.assertEqual(len(row.user_agent), 300)

    def test_mfa_rows_record_network(self):
        _, profile, me = make_user('ctx_mfa', role='purchasing', password='Ctx-pw-1234')
        me.post('/api/auth/2fa/setup/', {}, format='json')
        profile.refresh_from_db()
        totp = pyotp.TOTP(profile.mfa_secret)
        me.post('/api/auth/2fa/enable/', {'code': totp.now()}, format='json',
                HTTP_X_ELR_NETWORK='internal', REMOTE_ADDR=SITE_IP, HTTP_USER_AGENT=UA)
        cache.clear()
        row = UserActivityLog.objects.filter(target_user=profile, action='mfa_enabled').first()
        self.assertEqual(row.network, 'internal')
        self.assertEqual(row.network_site, 'فرع المعادي')
        self.assertEqual(row.user_agent, UA)
