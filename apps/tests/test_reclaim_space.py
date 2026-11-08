"""
Data lifecycle Stage 2: reclaim_space command and per-table autovacuum tuning.

The real VACUUM FULL cannot run inside a transaction, so those tests use SimpleTestCase with
database access and their own scratch table. That also avoids TransactionTestCase, whose flush
would wipe seeded rows from a kept test database.
"""
import datetime as dt
import io
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext

from apps.purchasing.models import DemandCalculationRun
from apps.sync.management.commands import reclaim_space

CAIRO = ZoneInfo('Africa/Cairo')
SCRATCH = 'reclaim_space_scratch'
GB = 1024 ** 3


def at(hour, minute=0):
    return dt.datetime(2026, 11, 7, hour, minute, tzinfo=CAIRO)


def in_window():
    return mock.patch.object(reclaim_space, 'local_now', return_value=at(3))


def plenty_of_disk():
    return mock.patch.object(reclaim_space, 'free_disk_bytes', return_value=500 * GB)


def run(*args):
    out = io.StringIO()
    call_command('reclaim_space', *args, stdout=out)
    return out.getvalue()


class WindowTests(SimpleTestCase):
    def test_window_edges(self):
        self.assertTrue(reclaim_space.in_business_hours(at(0, 59)))
        self.assertFalse(reclaim_space.in_business_hours(at(1, 0)))
        self.assertFalse(reclaim_space.in_business_hours(at(6, 59)))
        self.assertTrue(reclaim_space.in_business_hours(at(7, 0)))
        self.assertTrue(reclaim_space.in_business_hours(at(13, 0)))


class EstimateTests(SimpleTestCase):
    def test_index_estimate_never_exceeds_actual_size(self):
        self.assertEqual(reclaim_space.compact_index_bytes(1000, 'btree', False, 1_000_000, 8), 1000)

    def test_btree_estimate_uses_rows_and_width(self):
        # 10,000 rows x (12 overhead + 8 key) / 0.9 fill = 222,222 bytes.
        self.assertEqual(reclaim_space.compact_index_bytes(10 ** 9, 'btree', False, 10_000, 8), 222_222)

    def test_indexes_we_cannot_estimate_claim_no_gain(self):
        self.assertEqual(reclaim_space.compact_index_bytes(5000, 'gin', False, 10, 8), 5000)
        self.assertEqual(reclaim_space.compact_index_bytes(5000, 'btree', True, 10, 8), 5000)


class RefusalTests(TestCase):
    """Refusals happen before any VACUUM. These run in a transaction, where a VACUUM would fail differently."""

    TABLE = 'purchasing_itemdemandmetrics'

    def assert_refused(self, message_part):
        with CaptureQueriesContext(connection) as queries:
            with self.assertRaises(CommandError) as caught:
                run('--apply', '--table', self.TABLE)
        self.assertIn(message_part, str(caught.exception))
        self.assertFalse([q for q in queries if 'VACUUM' in q['sql'].upper()])

    def test_apply_needs_a_table(self):
        with self.assertRaisesMessage(CommandError, '--table'):
            run('--apply')

    def test_unknown_table_is_refused(self):
        with self.assertRaisesMessage(CommandError, 'not found'):
            run('--table', 'no_such_table')

    def test_a_name_that_is_not_a_table_is_refused_even_with_apply(self):
        with in_window(), plenty_of_disk():
            with self.assertRaisesMessage(CommandError, 'not found'):
                run('--apply', '--table', 'catalog_item; DROP TABLE catalog_item')

    def test_refused_during_business_hours(self):
        with mock.patch.object(reclaim_space, 'local_now', return_value=at(13)), plenty_of_disk():
            self.assert_refused('business hours')

    def test_refused_while_demand_engine_runs(self):
        run_row = DemandCalculationRun.objects.create(status='running')
        with in_window(), plenty_of_disk():
            self.assert_refused(f'#{run_row.pk}')

    def test_finished_engine_run_does_not_block(self):
        DemandCalculationRun.objects.create(status='success')
        self.assertIsNone(reclaim_space.running_engine_run())

    def test_refused_when_disk_cannot_hold_a_copy(self):
        with in_window(), mock.patch.object(reclaim_space, 'free_disk_bytes', return_value=1024):
            self.assert_refused('disk')

    def test_refused_when_free_disk_cannot_be_measured(self):
        with in_window(), mock.patch.object(reclaim_space, 'free_disk_bytes', return_value=None):
            self.assert_refused('--data-dir')

    def test_every_reason_is_reported_together(self):
        DemandCalculationRun.objects.create(status='running')
        with mock.patch.object(reclaim_space, 'local_now', return_value=at(13)), \
                mock.patch.object(reclaim_space, 'free_disk_bytes', return_value=1024):
            with self.assertRaises(CommandError) as caught:
                run('--apply', '--table', self.TABLE)
        for part in ('business hours', 'engine', 'disk'):
            self.assertIn(part, str(caught.exception))

    def test_remote_database_cannot_be_measured_without_data_dir(self):
        with mock.patch.dict(connection.settings_dict, {'HOST': 'db.example.test'}):
            self.assertIsNone(reclaim_space.free_disk_bytes(None))

    def test_data_dir_option_is_measured_for_a_remote_database(self):
        with mock.patch.dict(connection.settings_dict, {'HOST': 'db.example.test'}):
            self.assertGreater(reclaim_space.free_disk_bytes(str(settings.BASE_DIR)), 0)

    def test_data_dir_that_does_not_exist_counts_as_unmeasured(self):
        self.assertIsNone(reclaim_space.free_disk_bytes(str(Path(settings.BASE_DIR) / 'no-such-folder')))


class ReclaimOnRealTableTests(SimpleTestCase):
    databases = {'default'}

    def setUp(self):
        self.addCleanup(self._drop)
        with connection.cursor() as cur:
            cur.execute(f'DROP TABLE IF EXISTS {SCRATCH}')
            cur.execute(f'CREATE TABLE {SCRATCH} (id serial PRIMARY KEY, payload text)')
            cur.execute(f"INSERT INTO {SCRATCH} (payload) SELECT repeat('x', 200) FROM generate_series(1, 20000)")
            # Live rows stay scattered, so the file cannot shrink from the end. Plain VACUUM clears
            # the dead rows without shrinking the file. VACUUM FULL alone would keep them whenever
            # any database on this server has an open transaction, such as a parallel test run.
            cur.execute(f'DELETE FROM {SCRATCH} WHERE id % 20 <> 0')
            cur.execute(f'VACUUM ANALYZE {SCRATCH}')

    def _drop(self):
        with connection.cursor() as cur:
            cur.execute(f'DROP TABLE IF EXISTS {SCRATCH}')

    def _sizes(self):
        with connection.cursor() as cur:
            cur.execute(
                f"SELECT pg_relation_size('{SCRATCH}'), pg_indexes_size('{SCRATCH}'), count(*) FROM {SCRATCH}")
            return cur.fetchone()

    def test_dry_run_reports_gain_and_changes_nothing(self):
        before = self._sizes()
        output = run('--table', SCRATCH)
        self.assertEqual(self._sizes(), before)
        self.assertIn(SCRATCH, output)
        self.assertIn('Dry run', output)

        info = reclaim_space.table_info(SCRATCH)
        # Roughly 1,000 of 20,000 rows are live, so most of the table is empty space.
        self.assertGreater(info.expected_gain, before[0] // 2)
        self.assertLess(info.real_bytes, before[0] // 5)
        self.assertLess(info.expected_gain, info.total_bytes)

    def test_dry_run_is_allowed_during_business_hours(self):
        with mock.patch.object(reclaim_space, 'local_now', return_value=at(13)):
            output = run('--table', SCRATCH)
        self.assertIn('business hours', output)

    def test_list_shows_large_tables_only(self):
        output = run()
        self.assertNotIn(SCRATCH, output)  # under the listing floor
        self.assertIn('Dry run', output)

    def test_apply_keeps_every_row_and_shrinks_the_table(self):
        heap_before, index_before, rows_before = self._sizes()
        with in_window(), plenty_of_disk():
            output = run('--apply', '--table', SCRATCH)
        heap_after, index_after, rows_after = self._sizes()
        self.assertEqual(rows_after, rows_before)
        self.assertLess(heap_after, heap_before // 5)
        self.assertLess(index_after, index_before)
        self.assertIn('Reclaimed', output)
        self.assertNotIn('open transaction', output)

    def test_small_result_is_explained_when_an_open_transaction_keeps_deleted_rows(self):
        other = connection.copy()
        try:
            with connection.cursor() as cur:
                cur.execute(f"INSERT INTO {SCRATCH} (payload) SELECT repeat('y', 200) FROM generate_series(1, 40000)")
            other.set_autocommit(False)
            with other.cursor() as cur:
                cur.execute('SELECT txid_current()')  # an open transaction, older than the delete below
            with connection.cursor() as cur:
                cur.execute(f"DELETE FROM {SCRATCH} WHERE payload LIKE 'y%'")
                cur.execute(f'ANALYZE {SCRATCH}')
            with in_window(), plenty_of_disk():
                output = run('--apply', '--table', SCRATCH)
        finally:
            other.rollback()
            other.close()
        self.assertIn('open transaction', output)

    def test_lock_timeout_gives_up_and_leaves_session_clean(self):
        other = connection.copy()
        try:
            other.set_autocommit(False)
            with other.cursor() as cur:
                cur.execute(f'LOCK TABLE {SCRATCH} IN ACCESS SHARE MODE')
            with in_window(), plenty_of_disk(), mock.patch.object(reclaim_space, 'LOCK_TIMEOUT_MS', 200):
                with self.assertRaisesMessage(CommandError, 'busy'):
                    run('--apply', '--table', SCRATCH)
        finally:
            other.rollback()
            other.close()
        with connection.cursor() as cur:
            cur.execute('SHOW lock_timeout')
            self.assertEqual(cur.fetchone()[0], '0')


class ManualOnlyTests(SimpleTestCase):
    def test_nothing_scheduled_or_deployed_runs_the_command(self):
        base = Path(settings.BASE_DIR)
        sources = [base / 'apps/sync/tasks.py', base / 'apps/sync/maintenance.py',
                   base / 'apps/sync/management/commands/run_scheduler.py',
                   *sorted((base / 'deploy').glob('*.service')), base / 'deploy/release.sh']
        for source in sources:
            self.assertNotIn('reclaim_space', source.read_text(encoding='utf-8'), source)


class AutovacuumTuningTests(TestCase):
    EXPECTED = {
        'purchasing_itemdemandmetrics': '0.02',
        'purchasing_itemdemandaggregated': '0.02',
        'purchasing_transferrecommendation': '0.02',
        'notifications_notification': '0.05',
        'notifications_notificationlog': '0.05',
    }

    def test_high_churn_tables_have_their_own_settings(self):
        with connection.cursor() as cur:
            for table, scale in self.EXPECTED.items():
                cur.execute('SELECT reloptions FROM pg_class WHERE oid = %s::regclass', [table])
                options = cur.fetchone()[0] or []
                with self.subTest(table=table):
                    self.assertIn(f'autovacuum_vacuum_scale_factor={scale}', options)
                    self.assertIn(f'autovacuum_analyze_scale_factor={scale}', options)
