"""N3 / Task 4 - the zone policy middleware: off / log / enforce."""
import json
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from apps.access.policy import REASON_MESSAGES
from apps.access.policy_middleware import ERROR_MESSAGE, ZonePolicyMiddleware
from apps.tests.factories import make_user


def _ok(request):
    return HttpResponse('ok')


class ZonePolicyMiddlewareTests(TestCase):

    def setUp(self):
        cache.clear()
        self.rf = RequestFactory()
        self.mw = ZonePolicyMiddleware(_ok)

    def _call(self, user, zone, path, method='get', **kw):
        req = getattr(self.rf, method)(path, **kw)
        req.user = user
        req.access = SimpleNamespace(zone=zone)
        return self.mw(req)

    # Review Focus 1
    @override_settings(NETWORK_POLICY_ENFORCEMENT='log')
    def test_log_mode_never_refuses(self):
        user, _, _ = make_user('zp_ph', role='pharmacist')
        with self.assertLogs('elrezeiky.access', 'WARNING') as cm:
            r = self._call(user, 'Z4', '/api/customers/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('zone would-deny', cm.output[0])

    @override_settings(NETWORK_POLICY_ENFORCEMENT='off')
    def test_off_does_nothing(self):
        user, _, _ = make_user('zp_off', role='pharmacist')
        self.assertEqual(self._call(user, 'Z4', '/api/customers/').status_code, 200)

    @override_settings(NETWORK_POLICY_ENFORCEMENT='enforce')
    def test_enforce_refuses_with_arabic_reason(self):
        ph, _, _ = make_user('zp_ph2', role='pharmacist')
        sup, _, _ = make_user('zp_sup', role='supervisor')
        cc, _, _ = make_user('zp_cc', role='call_center')
        cases = [
            (ph, 'Z4', '/api/customers/', 'get', 'blocked'),
            (ph, 'Z2', '/api/customers/', 'post', 'read_only'),
            (cc, 'Z3', '/api/hr/', 'get', 'module'),
            (sup, 'Z3', '/api/customers/export/', 'get', 'export'),
        ]
        for user, zone, path, method, reason in cases:
            with self.subTest(reason=reason):
                r = self._call(user, zone, path, method)
                self.assertEqual(r.status_code, 403)
                self.assertEqual(json.loads(r.content), {
                    'detail': REASON_MESSAGES[reason], 'zone': zone, 'reason': reason})

    # Review Focus 5
    @override_settings(NETWORK_POLICY_ENFORCEMENT='enforce')
    def test_z2_always_open_writes_allowed(self):
        user, _, _ = make_user('zp_z2', role='pharmacist')
        for path in ('/api/auth/change-password/', '/api/auth/logout/'):
            self.assertEqual(self._call(user, 'Z2', path, 'post').status_code, 200, path)
        with self.assertLogs('elrezeiky.access', 'WARNING'):
            self.assertEqual(self._call(user, 'Z2', '/api/customers/', 'post').status_code, 403)

    @override_settings(NETWORK_POLICY_ENFORCEMENT='enforce')
    def test_admin_z3_full_but_no_export(self):
        admin, prof, _ = make_user('zp_admin', role='admin')
        self.assertEqual(self._call(admin, 'Z3', '/api/customers/', 'post').status_code, 200)
        r = self._call(admin, 'Z3', '/api/customers/', 'get', data={'format': 'xlsx'})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(json.loads(r.content)['reason'], 'export')
        prof.external_export = True
        prof.save()
        self.assertEqual(self._call(admin, 'Z3', '/api/customers/', 'get',
                                    data={'format': 'xlsx'}).status_code, 200)

    @override_settings(NETWORK_POLICY_ENFORCEMENT='enforce')
    def test_body_export_detected(self):
        sup, _, _ = make_user('zp_sup2', role='supervisor')
        r = self._call(sup, 'Z3', '/api/reservations/bulk/', 'post',
                       data=json.dumps({'action': 'export'}), content_type='application/json')
        self.assertEqual(json.loads(r.content)['reason'], 'read_only')   # POST refused first
        cc, _, _ = make_user('zp_cc2', role='call_center')
        r = self._call(cc, 'Z3', '/api/reservations/bulk/', 'post',
                       data=json.dumps({'action': 'export'}), content_type='application/json')
        self.assertEqual(json.loads(r.content)['reason'], 'export')
        r = self._call(cc, 'Z3', '/api/reservations/bulk/', 'post',
                       data=json.dumps({'action': 'cancel'}), content_type='application/json')
        self.assertEqual(r.status_code, 200)

    @override_settings(NETWORK_POLICY_ENFORCEMENT='enforce')
    def test_anonymous_and_non_api_untouched(self):
        req = self.rf.get('/api/customers/')
        req.user = SimpleNamespace(is_authenticated=False)
        req.access = SimpleNamespace(zone=None)
        self.assertEqual(self.mw(req).status_code, 200)
        user, _, _ = make_user('zp_na', role='pharmacist')
        self.assertEqual(self._call(user, 'Z4', '/static/x.js').status_code, 200)

    def test_middleware_never_raises(self):
        user, _, _ = make_user('zp_err', role='pharmacist')
        with mock.patch('apps.access.policy.decide', side_effect=RuntimeError('boom')):
            with override_settings(NETWORK_POLICY_ENFORCEMENT='log'):
                self.assertEqual(self._call(user, 'Z4', '/api/customers/').status_code, 200)
            with override_settings(NETWORK_POLICY_ENFORCEMENT='enforce'):
                r = self._call(user, 'Z4', '/api/customers/')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(json.loads(r.content)['reason'], 'error')
        self.assertEqual(json.loads(r.content)['detail'], ERROR_MESSAGE)

    @override_settings(NETWORK_POLICY_ENFORCEMENT='log')
    def test_log_line_deduplicated(self):
        user, _, _ = make_user('zp_dd', role='pharmacist')
        with self.assertLogs('elrezeiky.access', 'WARNING') as cm:
            for _i in range(3):
                self._call(user, 'Z4', '/api/customers/')
            self._call(user, 'Z4', '/api/hr/')
        self.assertEqual(len(cm.output), 2)
