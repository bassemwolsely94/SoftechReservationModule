"""Column types come from the row-format header (getColumnTypeName ran a hidden statement
that buffered the whole open result and could hang on a dropped branch), and stale
StockExpirySyncRun cleanup — 2026-10-27 the expiry sweep hung for hours mid-metadata-read."""
from datetime import timedelta
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

import config.sybase as sy
from apps.batches.models import StockExpirySyncRun


class CursorColumnTypeTests(SimpleTestCase):

    def _cursor(self, codes):
        cur = sy.CursorWrapper('conn')
        meta = mock.Mock(getColumnCount=mock.Mock(return_value=len(codes)),
                         getColumnType=mock.Mock(side_effect=codes))
        cur._rs = mock.Mock(getMetaData=mock.Mock(return_value=meta))
        return cur, meta

    def test_types_come_from_the_header_codes_never_the_name_lookup(self):
        # varchar, char, text, datetime, decimal, numeric, int, smallint, tinyint, float, image
        cur, meta = self._cursor([12, 1, -1, 93, 3, 2, 4, 5, -6, 8, -4])
        self.assertEqual(cur._ensure_col_types(), [
            'varchar', 'char', 'text', 'datetime', 'decimal', 'numeric',
            'int', 'smallint', 'tinyint', 'double', 'other'])
        cur._ensure_col_types()                                      # cached
        self.assertEqual(meta.getColumnType.call_count, 11)
        meta.getColumnTypeName.assert_not_called()

    def test_rows_convert_by_family(self):
        cur, _ = self._cursor([4, 3, 8])
        cur._rs.getObject = mock.Mock(side_effect=['7', '12.50', '0.25'])
        self.assertEqual(cur._convert_row(cur._ensure_col_types()), [7, 12.5, 0.25])


class FetchTimeoutTests(SimpleTestCase):
    """The query timeout is one deadline over the whole read, so once rows are back the
    statement gets the longer fetch budget (items needs ~46 s; the default is 30)."""

    def _run(self, **kw):
        stmt = mock.Mock(execute=mock.Mock(return_value=True))
        conn = mock.Mock(createStatement=mock.Mock(return_value=stmt))
        cur = sy.CursorWrapper(conn)
        cur._execute('SELECT 1', None, kw.get('timeout'))
        return [c.args[0] for c in stmt.setQueryTimeout.call_args_list]

    def test_rows_get_the_fetch_budget_after_the_query_deadline(self):
        self.assertEqual(self._run(), [sy.SYBASE_QUERY_TIMEOUT_SECONDS, sy.SYBASE_FETCH_TIMEOUT_SECONDS])

    def test_a_longer_caller_timeout_is_kept(self):
        self.assertEqual(self._run(timeout=1800), [1800, 1800])

    def test_no_result_set_no_rearm(self):
        stmt = mock.Mock(execute=mock.Mock(return_value=False))
        cur = sy.CursorWrapper(mock.Mock(createStatement=mock.Mock(return_value=stmt)))
        cur._execute('SET ROWCOUNT 0', None, None)
        stmt.setQueryTimeout.assert_called_once_with(sy.SYBASE_QUERY_TIMEOUT_SECONDS)


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
