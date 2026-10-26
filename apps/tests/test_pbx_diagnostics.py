"""
PBX connection diagnostics + bridge status/heartbeat.
A tiny fake AMI server on localhost exercises the real socket path.
"""
import asyncio
import socket
import threading
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.pbx.diagnostics import run_diagnostics
from apps.pbx.models import PBXBridgeStatus
from .factories import make_admin, make_pharmacist


class FakeAMI:
    def __init__(self, secret='good', banner=b'Asterisk Call Manager/5.0.1\r\n'):
        self.secret, self.banner = secret, banner
        self.srv = socket.socket()
        self.srv.bind(('127.0.0.1', 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        conn, _ = self.srv.accept()
        conn.sendall(self.banner)
        buf = b''
        while True:
            try:
                data = conn.recv(4096)
            except OSError:
                break
            if not data:
                break
            buf += data
            while b'\r\n\r\n' in buf:
                raw, buf = buf.split(b'\r\n\r\n', 1)
                f = dict(l.split(': ', 1) for l in raw.decode().split('\r\n') if ': ' in l)
                a = f.get('Action')
                if a == 'Login':
                    ok = f.get('Secret') == self.secret
                    conn.sendall((b'Response: Success\r\n\r\nEvent: FullyBooted\r\n\r\n' if ok
                                  else b'Response: Error\r\nMessage: Authentication failed\r\n\r\n'))
                elif a == 'Ping':
                    conn.sendall(b'Response: Success\r\nPing: Pong\r\n\r\n')
                elif a == 'CoreSettings':
                    conn.sendall(b'Response: Success\r\nAsteriskVersion: 16.30.0\r\n\r\n')
                elif a == 'ModuleCheck':
                    conn.sendall(b'Response: Success\r\nVersion: 1\r\n\r\n')
                elif a == 'Logoff':
                    conn.close()
                    return

    def close(self):
        self.srv.close()


def _by_key(result):
    return {s['key']: s for s in result['steps']}


class DiagnosticsTests(TestCase):

    @override_settings(AMI_HOST='', AMI_USER='', AMI_SECRET='')
    def test_missing_config_blocks_network_steps(self):
        s = _by_key(run_diagnostics())
        self.assertEqual(s['config']['status'], 'fail')
        self.assertIn('AMI_HOST', s['config']['detail'])
        self.assertEqual(s['tcp']['status'], 'skip')
        self.assertEqual(s['login']['status'], 'skip')

    def test_refused_port_explains_ami_disabled(self):
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        sock.close()   # nothing listening now
        with self.settings(AMI_HOST='127.0.0.1', AMI_PORT=port, AMI_USER='u', AMI_SECRET='s'):
            s = _by_key(run_diagnostics(timeout=5))   # Windows retries refusals for ~2s
        self.assertEqual(s['tcp']['status'], 'fail')
        self.assertIn('manager.conf', s['tcp']['hint'])
        self.assertEqual(s['login']['status'], 'skip')

    def test_healthy_server(self):
        fake = FakeAMI()
        PBXBridgeStatus.record(state='connected', last_heartbeat_at=timezone.now(),
                               connected_since=timezone.now())
        with self.settings(AMI_HOST='127.0.0.1', AMI_PORT=fake.port, AMI_USER='u',
                           AMI_SECRET='good', AMI_CHANNEL_TECH='SIP'):
            r = run_diagnostics(timeout=3)
        fake.close()
        s = _by_key(r)
        for key in ('config', 'dns', 'tcp', 'banner', 'login', 'ping', 'version', 'driver', 'bridge'):
            self.assertEqual(s[key]['status'], 'ok', key)
        self.assertEqual(s['version']['detail'], '16.30.0')

    def test_wrong_password(self):
        fake = FakeAMI(secret='right')
        with self.settings(AMI_HOST='127.0.0.1', AMI_PORT=fake.port, AMI_USER='u', AMI_SECRET='wrong'):
            s = _by_key(run_diagnostics(timeout=3))
        fake.close()
        self.assertEqual(s['login']['status'], 'fail')
        self.assertIn('Authentication failed', s['login']['detail'])
        self.assertEqual(s['ping']['status'], 'skip')

    def test_wrong_port_not_ami(self):
        fake = FakeAMI(banner=b'SSH-2.0-OpenSSH\r\n')
        with self.settings(AMI_HOST='127.0.0.1', AMI_PORT=fake.port, AMI_USER='u', AMI_SECRET='good'):
            s = _by_key(run_diagnostics(timeout=3))
        fake.close()
        self.assertEqual(s['banner']['status'], 'fail')

    def test_bridge_step_states(self):
        from apps.pbx.diagnostics import _bridge_step
        self.assertEqual(_bridge_step()['status'], 'fail')                 # never ran
        PBXBridgeStatus.record(state='connected',
                               last_heartbeat_at=timezone.now() - timedelta(minutes=10))
        self.assertIn('دقيقة', _bridge_step()['detail'])                   # stale
        PBXBridgeStatus.record(state='auth_failed', last_error='Login: bad')
        self.assertEqual(_bridge_step()['status'], 'fail')


class StatusEndpointTests(TestCase):

    def test_status_reports_stale_bridge(self):
        _, _, client = make_admin('pbx_st_admin')
        self.assertEqual(client.get('/api/pbx/status/').data['state'], 'unknown')
        PBXBridgeStatus.record(state='connected',
                               last_heartbeat_at=timezone.now() - timedelta(minutes=5))
        data = client.get('/api/pbx/status/').data
        self.assertEqual(data['state'], 'stale')
        self.assertFalse(data['alive'])

    @override_settings(AMI_HOST='', AMI_USER='', AMI_SECRET='')
    def test_diagnostics_supervisor_only(self):
        _, _, pharm = make_pharmacist('pbx_diag_ph')
        self.assertEqual(pharm.post('/api/pbx/diagnostics/').status_code, 403)
        _, _, admin = make_admin('pbx_diag_admin')
        self.assertEqual(admin.post('/api/pbx/diagnostics/').data['overall'], 'fail')


class BridgeEofTests(TestCase):

    def test_eof_raises_instead_of_spinning(self):
        from apps.pbx.ami_bridge import AMIConnection

        async def go():
            reader = asyncio.StreamReader()
            reader.feed_eof()
            conn = AMIConnection('h', 1, 'u', 's')
            conn._reader = reader
            with self.assertRaises(ConnectionError):
                await conn._read_event()
        asyncio.run(go())
