"""
apps/tests/security/test_harness.py

Tests for the security-suite harness itself: the baseline ratchet, the
pending-decision markers, the side-effect tripwire and the role fixtures.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from . import baseline


class BaselineTests(SimpleTestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        patcher = mock.patch.object(baseline, 'BASELINE_DIR', self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def _write(self, name, text):
        (self.dir / f'{name}.txt').write_text(text, encoding='utf-8')

    def test_new_entry_fails(self):
        self._write('demo', 'a\n')
        with self.assertRaises(AssertionError) as ctx:
            baseline.assert_matches_baseline(self, 'demo', {'a', 'b'})
        self.assertIn('NEW', str(ctx.exception))
        self.assertIn('b', str(ctx.exception))

    def test_stale_entry_fails(self):
        self._write('demo', 'a\nb\n')
        with self.assertRaises(AssertionError) as ctx:
            baseline.assert_matches_baseline(self, 'demo', {'a'})
        self.assertIn('STALE', str(ctx.exception))
        self.assertIn('b', str(ctx.exception))

    def test_matching_baseline_passes(self):
        self._write('demo', 'a\nb\n')
        baseline.assert_matches_baseline(self, 'demo', {'b', 'a'})

    def test_missing_file_means_empty_baseline(self):
        baseline.assert_matches_baseline(self, 'absent', set())
        with self.assertRaises(AssertionError):
            baseline.assert_matches_baseline(self, 'absent', {'x'})

    def test_prune_removes_stale_but_still_fails_on_new(self):
        self._write('demo', '# header\na\ns\n')
        with mock.patch.dict(os.environ, {'SECURITY_BASELINE_PRUNE': '1'}):
            with self.assertRaises(AssertionError) as ctx:
                baseline.assert_matches_baseline(self, 'demo', {'a', 'n'})
        self.assertIn('n', str(ctx.exception))
        text = (self.dir / 'demo.txt').read_text(encoding='utf-8')
        self.assertIn('# header', text)
        self.assertIn('a', text.splitlines())
        self.assertNotIn('s', text.splitlines())

    def test_prune_with_only_stale_passes_and_rewrites(self):
        self._write('demo', 'a\ns\n')
        with mock.patch.dict(os.environ, {'SECURITY_BASELINE_PRUNE': '1'}):
            baseline.assert_matches_baseline(self, 'demo', {'a'})
        self.assertEqual((self.dir / 'demo.txt').read_text(encoding='utf-8').split(), ['a'])

    def test_comments_and_blanks_ignored(self):
        self._write('demo', '# owner: batch 4\n\na\n   \n# b\n')
        self.assertEqual(baseline.load_baseline('demo'), {'a'})

    def test_norm_uses_forward_slashes(self):
        self.assertEqual(baseline.norm(baseline.REPO_ROOT / 'apps' / 'x.py'), 'apps/x.py')
        self.assertEqual(baseline.norm('apps\\tests\\y.py'), 'apps/tests/y.py')


class TripwireTests(SimpleTestCase):

    def test_softech_call_is_blocked_and_recorded(self):
        import config.sybase
        from .routes import Tripwire
        with Tripwire() as t:
            with self.assertRaises(ConnectionError):
                config.sybase.get_sybase_connection()
        self.assertEqual(t.softech_calls, ['config.sybase.get_sybase_connection'])

    def test_branch_and_connector_calls_recorded(self):
        import config.sybase
        from .routes import Tripwire
        with Tripwire() as t:
            with self.assertRaises(ConnectionError):
                config.sybase.get_branch_connection('10.0.0.1')
            with self.assertRaises(ConnectionError):
                config.sybase.SoftechConnector().connect()
        self.assertEqual(t.softech_calls, ['config.sybase.get_branch_connection',
                                           'config.sybase.SoftechConnector.connect'])

    def test_thread_start_is_recorded_not_run(self):
        import threading
        from .routes import Tripwire
        ran = []

        def job():
            ran.append(1)
        with Tripwire() as t:
            threading.Thread(target=job).start()
        self.assertEqual(ran, [])
        self.assertEqual(len(t.threads), 1)
        self.assertIn('job', t.threads[0])

    def test_http_is_blocked(self):
        import requests
        from .routes import Tripwire
        with Tripwire() as t:
            with self.assertRaises(ConnectionError):
                requests.get('http://example.invalid/')
        self.assertEqual(len(t.http_calls), 1)

    def test_raw_socket_blocked_and_recorded(self):
        import socket
        from .routes import Tripwire
        with Tripwire() as t:
            with self.assertRaises(OSError):
                socket.create_connection(('192.0.2.1', 5038), timeout=1)   # AMI-style
            s = socket.socket()
            with self.assertRaises(OSError):
                s.connect(('192.0.2.1', 80))
            s.close()
        self.assertEqual(len(t.sockets), 2)

    def test_urllib_blocked_and_recorded(self):
        import urllib.request
        from .routes import Tripwire
        with Tripwire() as t:
            with self.assertRaises(OSError):
                urllib.request.urlopen('http://192.0.2.1/', timeout=1)
        self.assertGreaterEqual(len(t.sockets), 1)

    def test_subprocess_blocked_and_recorded(self):
        import subprocess
        import sys
        from .routes import Tripwire
        with Tripwire() as t:
            with self.assertRaises(OSError):
                subprocess.run([sys.executable, '-c', 'print(1)'])
        self.assertEqual(len(t.subprocesses), 1)

    def test_thread_pool_submit_fails_fast_not_hangs(self):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from .routes import Tripwire
        ran = []
        with Tripwire() as t:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futs = [pool.submit(ran.append, 1) for _ in range(3)]
                done = list(as_completed(futs, timeout=2))
        self.assertEqual(ran, [])
        self.assertEqual(len(done), 3)
        self.assertTrue(all(isinstance(f.exception(), ConnectionError) for f in done))
        self.assertEqual(len(t.threads), 3)

    def test_join_on_blocked_thread_does_not_raise(self):
        import threading
        from .routes import Tripwire
        with Tripwire():
            th = threading.Thread(target=lambda: None)
            th.start()
            th.join()          # an unstarted thread would raise RuntimeError

    def test_patches_removed_on_exit(self):
        import threading
        from .routes import Tripwire
        original = threading.Thread.start
        with Tripwire():
            self.assertIsNot(threading.Thread.start, original)
        self.assertIs(threading.Thread.start, original)


class TripwireDatabaseTests(TestCase):

    def test_database_still_works_inside_tripwire(self):
        from django.contrib.auth.models import User
        from .routes import Tripwire
        with Tripwire() as t:
            User.objects.create(username='tw_db_check')
            self.assertTrue(User.objects.filter(username='tw_db_check').exists())
        self.assertEqual(t.sockets, [])


class RouteRenderingTests(SimpleTestCase):

    def test_sweep_ids_never_exist(self):
        """Detail routes in the role sweep use an id no fixture can create, so results
        don't depend on the database's id sequence (fresh CI DB vs reused local DB)."""
        from .routes import api_routes
        from .sweep import SWEEP_ID
        default = {p for p, _ in api_routes()}
        swept = {p for p, _ in api_routes(id_value=SWEEP_ID)}
        self.assertIn('/api/users/staff/1/', default)
        self.assertIn(f'/api/users/staff/{SWEEP_ID}/', swept)
        self.assertNotIn('/api/users/staff/1/', swept)
        self.assertEqual(len(default), len(swept))


class ClassifyTests(SimpleTestCase):
    """The role sweep's verdict for one request (see sweep.classify)."""

    def test_denied_role_refused_is_ok(self):
        from .sweep import classify
        for code in (401, 403, 405, 301, 503):
            self.assertEqual(classify(False, code, 200), 'ok', code)

    def test_denied_404_is_ok_only_when_admin_gets_further(self):
        from .sweep import classify
        self.assertEqual(classify(False, 404, 200), 'ok')
        self.assertEqual(classify(False, 404, 404), 'unproven')

    def test_denied_anything_else_is_a_leak(self):
        from .sweep import classify
        for code in (200, 201, 202, 204, 302, 400, 406, 409, 415, 422, 429):
            self.assertEqual(classify(False, code, 200), 'leak', code)

    def test_crashes(self):
        from .sweep import classify
        for allowed in (True, False):
            self.assertEqual(classify(allowed, 500, 200), 'crash')
            self.assertEqual(classify(allowed, 'raised KeyError', 200), 'crash')

    def test_granted_role(self):
        from .sweep import classify
        self.assertEqual(classify(True, 403, 200), 'overblock')
        for code in (200, 400, 404, 405):
            self.assertEqual(classify(True, code, 200), 'ok', code)


class PendingTests(SimpleTestCase):

    def test_pending_decorator_marks_expected_failure(self):
        @baseline.pending('P-99')
        def t(self):
            raise AssertionError
        self.assertEqual(t.__pending__, 'P-99')
        self.assertTrue(getattr(t, '__unittest_expecting_failure__', False))

    def test_markers_match_pending_md(self):
        loader = unittest.TestLoader()
        suite = loader.discover(str(baseline.REPO_ROOT / 'apps' / 'tests'),
                                top_level_dir=str(baseline.REPO_ROOT))
        marked = set()

        def walk(s):
            for t in s:
                if isinstance(t, unittest.TestSuite):
                    walk(t)
                else:
                    fn = getattr(type(t), getattr(t, '_testMethodName', ''), None)
                    pid = getattr(fn, '__pending__', None)
                    if pid:
                        marked.add(pid)
        walk(suite)
        self.assertEqual(marked, baseline.pending_ids(),
                         'Every @pending marker needs a "- <X>-<n>: …" line in '
                         'apps/tests/security/PENDING.md and vice versa.')


class RoleFixtureTests(TestCase):

    def test_matrix_matches_code(self):
        from apps.users.models import RoleModuleAccess
        from .fixtures import granted, seed_code_matrix
        seed_code_matrix()
        for role, module, actions in (('viewer', 'finance', ('view',)),
                                      ('call_center', 'pos', ('create',)),
                                      ('salesperson', 'users', ('edit',))):
            in_db = RoleModuleAccess.objects.filter(
                role=role, module=module, action=actions[0], is_allowed=True).exists()
            self.assertEqual(in_db, granted(role, module, actions), (role, module, actions))

    def test_row_count_is_complete(self):
        from apps.users.management.commands.seed_permissions import ALL_ACTIONS, ALL_MODULES
        from apps.users.models import RoleModuleAccess
        from .fixtures import ROLES, seed_code_matrix
        seed_code_matrix()
        self.assertEqual(RoleModuleAccess.objects.count(),
                         len(ROLES) * len(ALL_MODULES) * len(ALL_ACTIONS))

    def test_admin_is_always_granted(self):
        from .fixtures import granted
        self.assertTrue(granted('admin', 'finance', ('delete',)))

    @override_settings(RBAC_ENFORCEMENT='enforce')
    def test_middleware_sees_bearer_client(self):
        from .fixtures import role_clients, seed_code_matrix
        seed_code_matrix()
        r = role_clients()['viewer'].get('/api/sync/logs/')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()['module'], 'sync')

    @override_settings(RBAC_ENFORCEMENT='enforce')
    def test_admin_not_blocked(self):
        from .fixtures import role_clients, seed_code_matrix
        seed_code_matrix()
        self.assertNotEqual(role_clients()['admin'].get('/api/sync/status/').status_code, 403)
