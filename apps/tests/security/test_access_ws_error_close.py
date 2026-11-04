"""N5 "before enforce" item - a transient error in the socket verdict is not a zone refusal.

It used to close with 4403: in enforce that sent the screen to polling until a reload, and wrote a
`ws_zone_denied` row with reason `error`. It now closes with 4500 (CLOSE_ERROR), which the hooks
treat as an ordinary reconnect, and writes no row.
"""
import importlib
from pathlib import Path
from unittest import mock

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, TransactionTestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.access import ws
from apps.access.context import AccessContext
from apps.access.network import EXTERNAL, NetworkInfo
from apps.audit.models import AuditLog
from apps.tests.factories import make_user

DECIDE = 'apps.access.policy.decide'


def _ctx():
    return AccessContext(network=NetworkInfo(zone=EXTERNAL, ip=None, site=None),
                         user_id=1, role='x', zone='Z3')


def _scope():
    return {'type': 'websocket', 'path': '/ws/notifications/', 'client': ('1.2.3.4', 1),
            'headers': []}


class VerdictErrorTests(TestCase):
    databases = {'default', 'audit_log'}

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def _verdict(self, mode):
        user, _, _ = make_user(f'wserr_{mode}', role='pharmacist')
        with mock.patch('apps.access.ws._mode', return_value=mode), \
                mock.patch('apps.access.ws.context_for_scope', return_value=_ctx()), \
                mock.patch(DECIDE, side_effect=RuntimeError('db blip')):
            return user, ws.verdict(_scope(), user, 'notifications')

    def test_error_closes_4500_not_4403(self):
        _, v = self._verdict('enforce')
        self.assertEqual((v.allowed, v.close_code, v.reason, v.enforced),
                         (False, ws.CLOSE_ERROR, 'error', True))
        self.assertEqual(ws.CLOSE_ERROR, 4500)
        self.assertNotEqual(ws.CLOSE_ERROR, ws.CLOSE_ZONE)

    def test_error_in_log_mode_is_not_enforced(self):
        _, v = self._verdict('log')
        self.assertFalse(v.enforced)

    def test_error_writes_no_zone_denied_row(self):
        user, v = self._verdict('enforce')
        ws._note_refusal(_scope(), user.pk, 'notifications', v)
        self.assertFalse(AuditLog.objects.filter(action=ws.AUDIT_ACTION).exists())


class ConsumerErrorCloseTests(TransactionTestCase):
    databases = {'default', 'audit_log'}

    def setUp(self):
        import config.asgi
        self.app = importlib.reload(config.asgi).application
        cache.clear()
        self.addCleanup(cache.clear)

    def test_connect_error_closes_4500_without_a_row(self):
        user, _, _ = make_user('wserr_consumer', role='pharmacist')
        tok = str(RefreshToken.for_user(user).access_token)

        async def go():
            c = WebsocketCommunicator(self.app, f'/ws/notifications/?token={tok}',
                                      headers=[(b'origin', b'http://localhost')])
            ok, code = await c.connect()
            await c.disconnect()
            return ok, code
        with mock.patch('apps.access.ws._mode', return_value='enforce'), \
                mock.patch('apps.access.ws.context_for_scope', return_value=_ctx()), \
                mock.patch(DECIDE, side_effect=RuntimeError('db blip')):
            self.assertEqual(async_to_sync(go)(), (False, 4500))
        self.assertFalse(AuditLog.objects.filter(action=ws.AUDIT_ACTION).exists())


class HookReconnectTests(TestCase):
    """The client half: 4500 is not in any hook's poll / stay-closed branch."""

    def _src(self, rel):
        return (Path(settings.BASE_DIR) / 'frontend' / 'src' / rel).read_text('utf-8')

    def test_hooks_reconnect_on_4500(self):
        for hook in ('hooks/useNotificationSocket.js', 'hooks/useChatterSocket.js',
                     'hooks/useScreenPop.js'):
            src = self._src(hook)
            self.assertIn('ev.code === 4001 || ev.code === 4403', src, hook)
            self.assertNotIn('=== 4500 ||', src, hook)
            self.assertNotIn('|| ev.code === 4500', src, hook)
            self.assertIn('4500', src, hook)      # documented as an ordinary reconnect

    def test_pbx_live_page_reopens_on_4500(self):
        self.assertIn('ev.code === 4500', self._src('pages/PbxLivePage.jsx'))
