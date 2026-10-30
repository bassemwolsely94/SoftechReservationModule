"""SOFTECH load telemetry (doc 30, step 1.0): counted at the connection layer,
attributed to job + caller, saved hourly by increments, admin-only report."""
from django.test import TestCase, TransactionTestCase, override_settings

from apps.sync import softech_load as sl
from apps.sync.models import SoftechLoadStat
from apps.tests.factories import make_admin, make_pharmacist
from apps.tests.test_security_hardening import FakeJavaConn, FakeStatement
from config.sybase import ConnectionWrapper


class _RS:
    def __init__(self, n):
        self.left = n

    def next(self):
        self.left -= 1
        return self.left >= 0

    def getMetaData(self):
        class M:
            def getColumnCount(self):
                return 1

            def getColumnTypeName(self, i):
                return 'int'
        return M()

    def getObject(self, i):
        return 7

    def close(self):
        pass


class _RowsStatement(FakeStatement):
    def __init__(self, log, n):
        super().__init__(log)
        self.n = n

    def execute(self, sql=None, *args):
        super().execute(sql)
        return True

    def getResultSet(self):
        return _RS(self.n)


class _RowsConn(FakeJavaConn):
    def __init__(self, n):
        super().__init__()
        self.n = n

    def createStatement(self, *args):
        return _RowsStatement(self.log, self.n)


def read_items_job(conn):
    cur = conn.cursor()
    cur.execute('SELECT itemcode FROM items')
    return cur.fetchall()


@override_settings(SOFTECH_LOAD_TELEMETRY=True)
class TelemetryRecordingTests(TransactionTestCase):

    def setUp(self):
        sl._buffer.clear()

    def test_query_rows_and_caller_are_recorded_under_the_job(self):
        conn = ConnectionWrapper(_RowsConn(5), node='HQ')
        with sl.scope('job:softech_sync_fast'):
            rows = read_items_job(conn)
        self.assertEqual(len(rows), 5)
        self.assertEqual(sl.flush(), 1)
        st = SoftechLoadStat.objects.get()
        self.assertEqual((st.node, st.scope, st.queries, st.rows), ('HQ', 'job:softech_sync_fast', 1, 5))
        self.assertEqual(st.caller, 'apps/tests/test_softech_load.py:read_items_job')

    def test_flush_increments_the_same_hourly_row(self):
        conn = ConnectionWrapper(_RowsConn(2), node='HQ')
        with sl.scope('job:x'):
            read_items_job(conn)
            sl.flush()
            read_items_job(conn)
            sl.flush()
        st = SoftechLoadStat.objects.get()
        self.assertEqual((st.queries, st.rows), (2, 4))

    def test_failed_query_counted_and_still_raises(self):
        class Boom(FakeStatement):
            def execute(self, sql=None, *a):
                raise RuntimeError('JZ0T3')

        class C(FakeJavaConn):
            def createStatement(self, *a):
                return Boom(self.log)

        with self.assertRaises(RuntimeError):
            ConnectionWrapper(C(), node='branch 1.2.3.4').cursor().execute('SELECT 1')
        sl.flush()
        st = SoftechLoadStat.objects.get()
        self.assertEqual((st.node, st.queries, st.query_errors), ('branch 1.2.3.4', 1, 1))

    def test_logins_recorded(self):
        sl.record_connect('HQ', 120, True)
        sl.record_connect('HQ', 3000, False)
        sl.flush()
        st = SoftechLoadStat.objects.get()
        self.assertEqual((st.connects, st.connect_failures, st.connect_ms), (2, 1, 3120))

    def test_scheduler_wrapper_keeps_the_job_result(self):
        seen = []
        job = sl.scoped(lambda: seen.append(sl.current_scope()) or 'done', 'job:pos_orders_reconcile')
        self.assertEqual(job(), 'done')
        self.assertEqual(seen, ['job:pos_orders_reconcile'])
        self.assertNotEqual(sl.current_scope(), 'job:pos_orders_reconcile')

    def test_no_save_inside_a_transaction(self):
        from django.db import transaction
        sl.record_connect('HQ', 1, True)
        sl._last_flush -= sl.FLUSH_SECONDS + 1
        with transaction.atomic():
            sl.record_connect('HQ', 1, True)   # would flush, but is inside atomic
            self.assertEqual(SoftechLoadStat.objects.count(), 0)
        sl.flush()
        self.assertEqual(SoftechLoadStat.objects.get().connects, 2)


class TelemetryOffTests(TestCase):
    def test_off_records_nothing(self):
        sl._buffer.clear()
        with override_settings(SOFTECH_LOAD_TELEMETRY=False):
            sl.record_connect('HQ', 1, True)
            ConnectionWrapper(_RowsConn(1), node='HQ').cursor().execute('SELECT 1')
        self.assertEqual(sl._buffer, {})


class LoadReportTests(TestCase):
    def setUp(self):
        from django.utils import timezone
        hour = timezone.now().replace(minute=0, second=0, microsecond=0)
        SoftechLoadStat.objects.create(hour=hour, node='HQ', scope='job:softech_sync_fast',
                                       caller='apps/sync/tasks.py:sync_stock', connects=12,
                                       queries=12, query_ms=9000, max_query_ms=1500, rows=130000)
        SoftechLoadStat.objects.create(hour=hour, node='HQ', scope='web',
                                       caller='apps/catalog/views.py:_softech_live_search',
                                       connects=3, queries=3, query_ms=300, rows=9)

    def test_admin_sees_totals_and_groups(self):
        _, _, client = make_admin()
        r = client.get('/api/sync/softech-load/?hours=24')
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d['totals']['connects'], 15)
        self.assertEqual(d['totals']['rows'], 130009)
        self.assertEqual(d['by_scope'][0]['scope'], 'job:softech_sync_fast')   # heaviest first
        self.assertEqual(d['by_node'][0]['label'], 'HQ')
        self.assertEqual(len(d['hourly']), 1)

    def test_non_admin_refused(self):
        _, _, client = make_pharmacist()
        self.assertEqual(client.get('/api/sync/softech-load/').status_code, 403)
