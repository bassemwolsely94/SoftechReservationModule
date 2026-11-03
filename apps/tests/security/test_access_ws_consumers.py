"""
N5 / Task 2 - the sockets check zone, expiry and revocation at connect, every 5 minutes and on push.

A socket used to be checked once, at the handshake, and then lived for as long as the tab stayed
open: a disabled account, a blocked device, an expired token or a zone the role may not use kept
receiving live calls and notifications.
"""
import asyncio
import importlib
import time
from pathlib import Path
from unittest import mock

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.core.cache import cache
from django.test import TransactionTestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.access import ws
from apps.access.context import AccessContext
from apps.access.network import EXTERNAL, NetworkInfo
from apps.audit.models import AuditLog
from apps.reservations.models import Reservation
from apps.tests.factories import make_branch, make_branch2, make_item, make_pharmacist, make_user

ORIGIN = [(b'origin', b'http://localhost')]


def _ctx(zone):
    return AccessContext(network=NetworkInfo(zone=EXTERNAL, ip=None, site=None),
                         user_id=1, role='x', zone=zone)


def _zone(mode, zone):
    """Patches the mode and the socket's zone (the verdict's own lookups)."""
    return (mock.patch('apps.access.ws._mode', return_value=mode),
            mock.patch('apps.access.ws.context_for_scope', return_value=_ctx(zone)))


class _SocketCase(TransactionTestCase):
    databases = {'default', 'audit_log'}

    def setUp(self):
        import config.asgi
        self.app = importlib.reload(config.asgi).application
        cache.clear()
        self.addCleanup(cache.clear)

    def _token(self, user):
        return str(RefreshToken.for_user(user).access_token)

    def _comm(self, path, token):
        return WebsocketCommunicator(self.app, f'{path}?token={token}', headers=ORIGIN)


class ZoneAdmitTests(_SocketCase):

    def test_connect_refused_4403_in_enforce(self):
        user, _, _ = make_user('n5c_pbx', role='call_center')
        tok = self._token(user)
        p_mode, p_ctx = _zone('enforce', 'Z3')

        async def go():
            codes = []
            for _ in range(2):                     # the second refusal is deduplicated
                c = self._comm('/ws/pbx/agent/', tok)
                ok, code = await c.connect()
                codes.append((ok, code))
                await c.disconnect()
            return codes
        with p_mode, p_ctx:
            codes = async_to_sync(go)()
        self.assertEqual(codes, [(False, 4403), (False, 4403)])
        rows = AuditLog.objects.filter(action='ws_zone_denied')
        self.assertEqual(rows.count(), 1)
        row = rows.get()
        self.assertEqual((row.extra['kind'], row.extra['zone'], row.extra['reason'], row.extra['enforced']),
                         ('pbx', 'Z3', 'module', True))
        self.assertEqual(row.user.user_id, user.pk)

    def test_connect_admitted_in_log_mode_with_warning(self):
        user, _, _ = make_user('n5c_pbx_log', role='call_center')
        tok = self._token(user)
        p_mode, p_ctx = _zone('log', 'Z3')

        async def go():
            c = self._comm('/ws/pbx/agent/', tok)
            ok, _ = await c.connect()
            first = await c.receive_json_from() if ok else None
            await c.disconnect()
            return ok, first
        with p_mode, p_ctx, self.assertLogs('elrezeiky.access', 'WARNING') as logs:
            ok, first = async_to_sync(go)()
        self.assertTrue(ok)
        self.assertEqual(first['type'], 'connected')
        lines = [m for m in logs.output if 'ws would-deny' in m]
        self.assertEqual(len(lines), 1, logs.output)
        self.assertIn(f'user={user.pk}', lines[0])
        self.assertIn('kind=pbx', lines[0])
        self.assertIn('zone=Z3', lines[0])
        self.assertIn('reason=module', lines[0])

    def test_chatter_still_checks_record_access_after_zone_admit(self):
        a, b = make_branch(), make_branch2()
        _, prof_a, _ = make_pharmacist('n5c_ch_a', branch=a)
        user_b, _, _ = make_pharmacist('n5c_ch_b', branch=b)
        res = Reservation.objects.create(item=make_item(), branch=a, quantity_requested=1,
                                         contact_name='عميل', contact_phone='01011111111',
                                         created_by=prof_a)
        p_mode, p_ctx = _zone('enforce', 'Z1')

        async def go(token):
            c = self._comm(f'/ws/chatter/reservation/{res.pk}/', token)
            out = await c.connect()
            await c.disconnect()
            return out
        with p_mode, p_ctx:
            self.assertEqual(async_to_sync(go)(self._token(user_b)), (False, 4003))    # W-3, after the zone
            self.assertTrue(async_to_sync(go)(self._token(prof_a.user))[0])


class ZoneRecheckTests(_SocketCase):

    def test_recheck_push_closes_disabled_user(self):
        user, _, _ = make_user('n5c_push', role='pharmacist')
        tok = self._token(user)

        async def go():
            c = self._comm('/ws/notifications/', tok)
            ok, _ = await c.connect()
            assert ok
            await c.receive_nothing(timeout=0.2)
            await database_sync_to_async(
                type(user).objects.filter(pk=user.pk).update)(is_active=False)
            await get_channel_layer().group_send(f'access_user_{user.pk}',
                                                 {'type': 'access.recheck'})
            out = await c.receive_output(timeout=3)
            await c.disconnect()
            return out
        out = async_to_sync(go)()
        self.assertEqual(out, {'type': 'websocket.close', 'code': 4001})

    def test_expired_token_closes_4002_and_hook_reconnects(self):
        user, _, _ = make_user('n5c_exp', role='pharmacist')
        tok = self._token(user)
        # the loop must run, so the token is still valid at the handshake (+0.5 s, not +0.01 s:
        # the handshake's own queries may take longer than 10 ms on a slow machine)
        claims = lambda token: (time.time() + 0.5, None)      # noqa: E731

        async def go():
            c = self._comm('/ws/notifications/', tok)
            ok, code = await c.connect()
            assert ok, code
            while True:
                out = await c.receive_output(timeout=3)
                if out['type'] == 'websocket.close':
                    break
            await c.disconnect()
            return out
        with mock.patch('apps.access.ws.WS_RECHECK_SECONDS', 0.05), \
                mock.patch('apps.notifications.middleware._token_claims', side_effect=claims):
            out = async_to_sync(go)()
        self.assertEqual(out, {'type': 'websocket.close', 'code': 4002})
        # the client half: 4002 reconnects (delay reset to the minimum), never polls
        for hook in ('useNotificationSocket.js', 'useChatterSocket.js'):
            src = (Path(settings.BASE_DIR) / 'frontend' / 'src' / 'hooks' / hook).read_text('utf-8')
            self.assertIn('ev.code === 4002', src, hook)
            self.assertIn('ev.code === 4001 || ev.code === 4403', src, hook)

    def test_disconnect_cancels_recheck_task(self):
        user, _, _ = make_user('n5c_cancel', role='pharmacist')
        tok = self._token(user)
        calls = []

        def fake(scope, u, kind, token_exp=None, now=None):
            calls.append(kind)
            return ws.WsVerdict(True, None, None, 'Z1', False)

        async def go():
            c = self._comm('/ws/notifications/', tok)
            ok, _ = await c.connect()
            assert ok
            await asyncio.sleep(0.3)
            await c.disconnect()
            after_disconnect = len(calls)
            await asyncio.sleep(0.3)
            return after_disconnect, len(calls)
        with mock.patch('apps.access.ws.WS_RECHECK_SECONDS', 0.05), \
                mock.patch('apps.access.ws.verdict', side_effect=fake):
            after_disconnect, later = async_to_sync(go)()
        self.assertGreater(after_disconnect, 2, 'the re-check loop never ran')
        self.assertEqual(later, after_disconnect, 're-check loop still running after disconnect')
