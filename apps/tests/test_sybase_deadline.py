"""Column types come from the row-format header (getColumnTypeName ran a hidden statement
that buffered the whole open result and could hang on a dropped branch), and stale
StockExpirySyncRun cleanup — 2026-10-27 the expiry sweep hung for hours mid-metadata-read."""
from datetime import timedelta
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

import config.sybase as sy
from apps.batches.models import StockExpirySyncRun
from apps.tests.test_sales_customer_link import FakeConn as _SalesConn, _sale


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


# ── Round 2, R6 step 3: every SOFTECH connection and statement gets its timeouts ──────────
import ast as _ast
import pathlib as _pathlib
import sys as _sys
import types as _types

from django.conf import settings as _settings
from django.test import override_settings as _override

from apps.tests.security.baseline import pending as _pending

_REPO = _pathlib.Path(__file__).resolve().parents[2]


class _Props(dict):
    def setProperty(self, k, v):
        self[k] = v


def _fake_java():
    """sys.modules entries standing in for jConnect / java.* (no JVM, no network)."""
    dm = mock.Mock()
    mods = {name: _types.ModuleType(name) for name in
            ('com', 'com.sybase', 'com.sybase.jdbc3', 'com.sybase.jdbc3.jdbc', 'java', 'java.util',
             'java.sql')}
    mods['com.sybase.jdbc3.jdbc'].SybDriver = mock.Mock()
    mods['java.util'].Properties = _Props
    mods['java.sql'].DriverManager = dm
    return mods, dm


@_override(SYBASE_HOST='softech.test', SYBASE_USER='u', SYBASE_PASSWORD='test-only',
           SOFTECH_BRANCH_HOST_OVERRIDE='')
class LoginTimeoutAppliedTests(SimpleTestCase):
    """SYBASE_LOGIN_TIMEOUT bounds the handshake on every way a connection is opened."""

    def _open(self, opener):
        mods, dm = _fake_java()
        seen = {}

        def fake_connect(driver, url, props, label=''):
            seen['props'] = dict(props)
            return mock.Mock()
        with mock.patch.dict(_sys.modules, mods), mock.patch.object(sy, '_ensure_jvm'), \
                mock.patch.object(sy, 'jpype'), \
                mock.patch.object(sy, '_connect_with_retry', side_effect=fake_connect):
            opener()
        return seen['props'], dm

    def _check(self, opener):
        props, dm = self._open(opener)
        self.assertEqual(props.get('LOGIN_TIMEOUT'), str(sy.SYBASE_LOGIN_TIMEOUT_SECONDS))
        dm.setLoginTimeout.assert_called_with(sy.SYBASE_LOGIN_TIMEOUT_SECONDS)

    def test_hq_connection(self):
        self._check(sy.get_sybase_connection)

    def test_branch_connection(self):
        self._check(lambda: sy.get_branch_connection('10.0.0.9'))

    def test_profile_connector(self):
        self._check(lambda: sy.SoftechConnector('prod').connect())

    def test_values_come_from_settings(self):
        for name, const, default in (('SYBASE_LOGIN_TIMEOUT', sy.SYBASE_LOGIN_TIMEOUT_SECONDS, 15),
                                     ('SYBASE_QUERY_TIMEOUT', sy.SYBASE_QUERY_TIMEOUT_SECONDS, 30),
                                     ('SYBASE_FETCH_TIMEOUT', sy.SYBASE_FETCH_TIMEOUT_SECONDS, 600)):
            self.assertEqual(const, int(getattr(_settings, name, default)), name)
        self.assertGreaterEqual(sy.SYBASE_FETCH_TIMEOUT_SECONDS, sy.SYBASE_QUERY_TIMEOUT_SECONDS)

    def test_every_connect_in_config_sybase_sets_the_login_timeout(self):
        tree = _ast.parse((_REPO / 'config' / 'sybase.py').read_text(encoding='utf-8'))
        bad = []
        for fn in _ast.walk(tree):
            if not isinstance(fn, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                continue
            src = _ast.unparse(fn)
            connects = '_connect_with_retry(' in src or 'SybDriver().connect(' in src
            if connects and fn.name != '_connect_with_retry' and not (
                    '_apply_login_timeout(' in src or "'LOGIN_TIMEOUT'" in src):
                bad.append(fn.name)
        self.assertEqual(bad, [])


class StatementTimeoutAppliedTests(SimpleTestCase):

    def test_prepared_statements_get_query_then_fetch_budget(self):
        stmt = mock.Mock(execute=mock.Mock(return_value=True))
        conn = mock.Mock(prepareStatement=mock.Mock(return_value=stmt))
        sy.CursorWrapper(conn)._execute('SELECT 1 WHERE a = ?', ['x'], None)
        self.assertEqual([c.args[0] for c in stmt.setQueryTimeout.call_args_list],
                         [sy.SYBASE_QUERY_TIMEOUT_SECONDS, sy.SYBASE_FETCH_TIMEOUT_SECONDS])

    def test_probe_statement_is_bounded(self):
        src = _ast.unparse(next(n for n in _ast.walk(_ast.parse(
            (_REPO / 'config' / 'sybase.py').read_text(encoding='utf-8')))
            if isinstance(n, _ast.FunctionDef) and n.name == 'probe_connection'))
        self.assertIn('_apply_query_timeout(stmt', src)


# Statements opened on the raw jConnect connection outside config/sybase.py skip CursorWrapper,
# so nothing arms their query timeout. Each is listed with its reason.
_RAW_STATEMENT_SITES = {
    # owner-run diagnostics (manual commands, never scheduled)
    'apps/invoices/management/commands/diag_chained.py': 'manual diagnostic',
    'apps/invoices/management/commands/diag_purchase3.py': 'manual diagnostic',
    'apps/sync/management/commands/capture_dbcc_sqltext.py': 'manual diagnostic',
}
# SOFTECH write batches (one T-SQL batch in its own transaction) — a timeout there is a
# stop-and-ask change to a write path, held as S-2 in PENDING.md.
_RAW_STATEMENT_WRITERS = {'apps/invoices/writer.py', 'apps/invoices/supplier_items.py'}


def _raw_statement_files():
    out = set()
    for base in ('apps', 'core', 'config'):
        for p in (_REPO / base).rglob('*.py'):
            rel = p.relative_to(_REPO).as_posix()
            if rel.startswith('apps/tests/') or rel == 'config/sybase.py' or '/migrations/' in rel:
                continue
            text = p.read_text(encoding='utf-8', errors='ignore')
            if '.createStatement(' in text or '.prepareStatement(' in text:
                out.add(rel)
    return out


class RawStatementSitesTests(SimpleTestCase):

    def test_no_new_unbounded_statement_sites(self):
        self.assertEqual(_raw_statement_files() - set(_RAW_STATEMENT_SITES) - _RAW_STATEMENT_WRITERS,
                         set())

    @_pending('S-2')
    def test_softech_write_batches_have_a_query_timeout(self):
        self.assertEqual(_raw_statement_files() & _RAW_STATEMENT_WRITERS, set())


# ── Round 2, R6 step 3: the sales syncs pick up again after a mid-run failure ──────────────
# The fast lane re-reads today + yesterday every tick and the 03:45 catch-up re-reads 7 days;
# both upsert by softech_invoice_id and replace an invoice's lines, so the next run after a
# failure IS the resume point: nothing is lost inside the window and nothing is doubled.


class _DroppedConn(_SalesConn):
    """Connects, then the stktrans read dies the way a dropped VPN does (JZ0T3)."""

    def cursor(self):
        class Cur:
            def execute(self, *a, **kw):
                raise RuntimeError('JZ0T3: Read operation timed out')
        return Cur()


class SalesSyncResumeTests(TestCase):

    def setUp(self):
        from apps.branches.models import Branch
        Branch.objects.create(softech_branch_id='130', name='B130', name_ar='فرع ١٣٠')
        self.rows = [_sale('1510', 500000 + i, '') for i in range(1005)]     # > one 1000-invoice batch

    def _fast(self, *conns):
        from apps.sync import tasks
        with mock.patch.object(tasks, 'get_sybase_connection', side_effect=list(conns)), \
                mock.patch.object(tasks, 'sync_branches', return_value=0), \
                mock.patch.object(tasks, 'sync_stock', return_value=0), \
                mock.patch.object(tasks, '_run_reactive_hooks'):
            return tasks.run_fast_sync()

    def _counts(self):
        from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
        return PurchaseHistory.objects.count(), PurchaseHistoryLine.objects.count()

    def test_a_dropped_read_reconnects_once_and_finishes(self):
        run = self._fast(_DroppedConn([]), _SalesConn(self.rows))
        self.assertEqual(run.status, 'success')
        self.assertEqual(self._counts(), (1005, 1005))

    def test_a_failed_tick_is_made_good_by_the_next_with_nothing_doubled(self):
        run = self._fast(_DroppedConn([]), _DroppedConn([]))
        self.assertEqual(run.status, 'failed')
        self.assertEqual(self._counts(), (0, 0))
        self.assertEqual(self._fast(_SalesConn(self.rows)).status, 'success')
        self.assertEqual(self._counts(), (1005, 1005))
        self.assertEqual(self._fast(_SalesConn(self.rows)).status, 'success')       # re-run: same rows
        self.assertEqual(self._counts(), (1005, 1005))

    def test_a_crash_between_batches_is_completed_by_the_next_run(self):
        from apps.customers.models import PurchaseHistoryLine
        real = PurchaseHistoryLine.objects.bulk_create
        calls = {'n': 0}

        def second_batch_dies(objs, *a, **kw):
            calls['n'] += 1
            if calls['n'] == 2:
                raise RuntimeError('could not extend file: disk full')
            return real(objs, *a, **kw)
        with mock.patch.object(PurchaseHistoryLine.objects, 'bulk_create', side_effect=second_batch_dies):
            self.assertEqual(self._fast(_SalesConn(self.rows)).status, 'failed')
        headers, lines = self._counts()
        self.assertLess(lines, 1005)                       # the second batch's lines never landed
        self.assertEqual(self._fast(_SalesConn(self.rows)).status, 'success')
        self.assertEqual(self._counts(), (1005, 1005))

    def test_the_catch_up_resumes_after_a_failed_night(self):
        from apps.sync import tasks
        from apps.sync.models import SyncRun
        with mock.patch.object(tasks, 'get_sybase_connection',
                               side_effect=[RuntimeError('JZ006: connection refused'),
                                            _SalesConn(self.rows)]):
            tasks._run_sales_history_catchup()
            tasks._run_sales_history_catchup()
        self.assertEqual(list(SyncRun.objects.order_by('pk').values_list('status', flat=True)),
                         ['failed', 'success'])
        self.assertEqual(self._counts(), (1005, 1005))

    def test_the_windows_overlap_the_gap(self):
        # fast: today + yesterday, re-read every tick; catch-up: the last 7 days, nightly
        import inspect
        from apps.sync import tasks
        from apps.sync.sybase_queries import QUERY_CUSTOMER_SALES_LINES_RECENT
        self.assertIn('days=7', str(inspect.signature(tasks._run_sales_history_catchup)))
        self.assertRegex(QUERY_CUSTOMER_SALES_LINES_RECENT.lower(), r'dateadd|getdate')
