"""Watchdog for jConnect reads that have no query timeout (column-type metadata), and
stale StockExpirySyncRun cleanup — 2026-10-27 the expiry sweep hung for hours on a
branch that dropped its session mid-metadata-read."""
import threading
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

import config.sybase as sy
from apps.batches.models import StockExpirySyncRun


class WithDeadlineTests(SimpleTestCase):

    def test_fast_call_returns_and_never_aborts(self):
        with mock.patch.object(sy, 'abort_connection') as abort:
            self.assertEqual(sy._with_deadline(object(), 5, lambda: 42), 42)
        abort.assert_not_called()

    def test_hung_call_is_aborted_and_raises_deadline(self):
        released = threading.Event()

        def blocked_read():
            released.wait(5)              # stands in for socketRead0
            raise RuntimeError('JZ006: socket closed')

        with mock.patch.object(sy, 'abort_connection', side_effect=lambda c: released.set()) as abort:
            with self.assertRaises(sy.SybaseDeadlineExceeded):
                sy._with_deadline('conn', 0.05, blocked_read)
        abort.assert_called_once_with('conn')

    def test_ordinary_errors_propagate_unchanged(self):
        def boom():
            raise ValueError('bad sql')
        with mock.patch.object(sy, 'abort_connection') as abort:
            with self.assertRaises(ValueError):
                sy._with_deadline(object(), 5, boom)
        abort.assert_not_called()


class AbortConnectionTests(SimpleTestCase):

    def _fake_conn(self):
        sock = mock.Mock()
        dbio = SimpleNamespace(_socket=sock)
        conn = SimpleNamespace(_protocol=SimpleNamespace(_inStreamMgr=SimpleNamespace(_dbio=dbio)))
        return conn, sock

    def test_closes_the_socket_through_the_read_only_proxy(self):
        conn, sock = self._fake_conn()
        proxy = SimpleNamespace(_jc=conn)
        with mock.patch.object(sy, '_jfield', side_effect=getattr):
            self.assertTrue(sy.abort_connection(proxy))
        sock.close.assert_called_once()

    def test_failure_is_reported_not_raised(self):
        with mock.patch.object(sy, '_jfield', side_effect=AttributeError('_protocol')):
            self.assertFalse(sy.abort_connection(object()))


class CursorMetadataGuardTests(SimpleTestCase):

    def test_column_types_are_read_under_the_watchdog(self):
        cur = sy.CursorWrapper('conn')
        meta = mock.Mock(getColumnCount=mock.Mock(return_value=2),
                         getColumnTypeName=mock.Mock(side_effect=['VARCHAR', 'int']))
        cur._rs = mock.Mock(getMetaData=mock.Mock(return_value=meta))
        with mock.patch.object(sy, '_with_deadline', wraps=sy._with_deadline) as wd:
            self.assertEqual(cur._ensure_col_types(), ['varchar', 'int'])
            self.assertEqual(cur._ensure_col_types(), ['varchar', 'int'])   # cached
        wd.assert_called_once()
        self.assertEqual(wd.call_args[0][:2], ('conn', sy.SYBASE_METADATA_TIMEOUT_SECONDS))


class StaleExpiryRunTests(TestCase):

    def test_old_running_runs_are_failed_recent_and_finished_kept(self):
        old = StockExpirySyncRun.objects.create(triggered_by='t')
        recent = StockExpirySyncRun.objects.create(triggered_by='t')
        done = StockExpirySyncRun.objects.create(triggered_by='t', status='success')
        StockExpirySyncRun.objects.filter(pk__in=[old.pk, done.pk]).update(
            started_at=timezone.now() - timedelta(hours=5))

        self.assertEqual(StockExpirySyncRun.fail_stale(), 1)

        old.refresh_from_db(); recent.refresh_from_db(); done.refresh_from_db()
        self.assertEqual(old.status, 'failed')
        self.assertIsNotNone(old.finished_at)
        self.assertIn('fatal', old.detail)
        self.assertEqual(recent.status, 'running')
        self.assertEqual(done.status, 'success')

    def test_command_closes_stale_runs_before_sweeping(self):
        old = StockExpirySyncRun.objects.create(triggered_by='t')
        StockExpirySyncRun.objects.filter(pk=old.pk).update(
            started_at=timezone.now() - timedelta(hours=5))
        from django.core.management import call_command
        with mock.patch('apps.batches.stock_expiry.sync_stock_expiry_all',
                        return_value={'nodes': 0, 'ok': 0, 'failed': 0, 'rows': 0, 'detail': {}}):
            call_command('sync_stock_expiry', stdout=mock.Mock(), stderr=mock.Mock())
        old.refresh_from_db()
        self.assertEqual(old.status, 'failed')
