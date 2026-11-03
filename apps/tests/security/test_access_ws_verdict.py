"""N5 / Task 1 - socket access context and verdict."""
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from apps.access import devices, ws
from apps.access.context import AccessContext
from apps.access.models import Device
from apps.access.network import EXTERNAL, INTERNAL, NetworkInfo
from apps.tests.factories import make_user

NOW = 1_000_000


def _scope(headers=(), client=('10.0.0.5', 1234), path='/ws/notifications/'):
    return {'type': 'websocket', 'path': path, 'client': client,
            'headers': [(k.encode(), v.encode()) for k, v in headers]}


def _ctx(zone, net_zone=EXTERNAL, failed=False):
    return AccessContext(network=NetworkInfo(zone=net_zone, ip=None, site=None),
                         user_id=1, role='x', zone=zone, failed=failed)


class WsVerdictTests(TestCase):

    def setUp(self):
        cache.clear()

    def _verdict(self, user, kind, zone, mode, scope=None, **kw):
        with mock.patch('apps.access.ws._mode', return_value=mode), \
                mock.patch('apps.access.ws.context_for_scope', return_value=_ctx(zone)):
            return ws.verdict(scope or _scope(), user, kind, now=NOW, **kw)

    def test_scope_request_maps_headers_cookies_client(self):
        req = ws.ScopeRequest(_scope([('x-elr-network', 'internal'), ('cookie', 'erp_device=abc')]))
        self.assertEqual(req.META['HTTP_X_ELR_NETWORK'], 'internal')
        self.assertEqual(req.COOKIES['erp_device'], 'abc')
        self.assertEqual(req.META['REMOTE_ADDR'], '10.0.0.5')
        self.assertEqual((req.method, req.path_info, req.GET), ('GET', '/ws/notifications/', {}))

    def test_inactive_user_closes_4001_in_every_mode(self):
        user, _, _ = make_user('wsv_inactive', role='pharmacist')
        user.is_active = False
        user.save()
        v = self._verdict(user, 'notifications', 'Z1', 'off')
        self.assertEqual((v.allowed, v.close_code, v.reason, v.enforced), (False, 4001, 'inactive', True))

    def test_revoked_device_closes_4001(self):
        user, _, _ = make_user('wsv_rev', role='pharmacist')
        secret = devices.new_secret()
        Device.objects.create(secret_hash=devices.hash_secret(secret), status='blocked')
        scope = _scope([('cookie', f'erp_device={secret}')])
        v = self._verdict(user, 'notifications', 'Z1', 'enforce', scope=scope)
        self.assertEqual((v.allowed, v.close_code, v.reason, v.enforced), (False, 4001, 'device_revoked', True))

    def test_revoked_token_dev_closes_4001(self):
        user, _, _ = make_user('wsv_tokdev', role='pharmacist')
        dev = Device.objects.create(secret_hash=devices.hash_secret('x'), status='retired')
        scope = dict(_scope(), token_dev=str(dev.public_id))
        v = self._verdict(user, 'notifications', 'Z1', 'log', scope=scope)
        self.assertEqual((v.close_code, v.reason, v.enforced), (4001, 'device_revoked', True))

    def test_expired_token_closes_4002(self):
        user, _, _ = make_user('wsv_exp', role='pharmacist')
        v = self._verdict(user, 'notifications', 'Z1', 'off', token_exp=NOW - 1)
        self.assertEqual((v.allowed, v.close_code, v.reason, v.enforced), (False, 4002, 'expired', True))

    def test_pbx_outside_refused_4403_in_enforce(self):
        user, _, _ = make_user('wsv_pbx', role='call_center')
        v = self._verdict(user, 'pbx', 'Z3', 'enforce')
        self.assertEqual((v.allowed, v.close_code, v.reason, v.zone, v.enforced),
                         (False, 4403, 'module', 'Z3', True))

    def test_pbx_outside_log_mode_not_enforced(self):
        user, _, _ = make_user('wsv_pbx2', role='call_center')
        v = self._verdict(user, 'pbx', 'Z3', 'log')
        self.assertFalse(v.allowed)
        self.assertFalse(v.enforced)

    def test_notifications_allowed_for_rider_outside(self):
        user, _, _ = make_user('wsv_rider', role='delivery')
        self.assertTrue(self._verdict(user, 'notifications', 'Z4', 'enforce').allowed)

    def test_blocked_role_outside_notifications_parity(self):
        # /api/notifications/ is always open over HTTP, so the socket is too (parity, on purpose)
        user, _, _ = make_user('wsv_ph', role='pharmacist')
        self.assertTrue(self._verdict(user, 'notifications', 'Z3', 'enforce').allowed)

    def test_context_failure_internal_allowed_external_refused(self):
        user, _, _ = make_user('wsv_fail', role='call_center')
        for net_zone, expect in ((INTERNAL, True), (EXTERNAL, False)):
            ctx = AccessContext(network=NetworkInfo(zone=net_zone, ip=None, site=None),
                                user_id=None, role=None, failed=True)
            with mock.patch('apps.access.ws._mode', return_value='enforce'), \
                    mock.patch('apps.access.ws.context_for_scope', return_value=ctx):
                v = ws.verdict(_scope(), user, 'pbx', now=NOW)
            self.assertEqual(v.allowed, expect, net_zone)

    def test_context_for_scope_never_raises(self):
        user, _, _ = make_user('wsv_cfs', role='pharmacist')
        with mock.patch('apps.access.ws.request_network', side_effect=RuntimeError('boom')),                 self.assertLogs('elrezeiky.access', 'WARNING'):
            ctx = ws.context_for_scope(_scope(), user)
        self.assertTrue(ctx.failed)
        self.assertEqual(ctx.user_id, user.pk)
