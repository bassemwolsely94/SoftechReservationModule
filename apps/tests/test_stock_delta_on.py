"""
Stock delta sync, ON mode (doc 40 §3.2–§3.4, §4.1; owner asked for it to be built 2026-11-26, switch stays `shadow`
until the 3 Dec sign-off, S2).

In `on`, each fast run reads only the stkbal rows stamped since the watermark (minus 10 min) and writes those. The
first fast run after 04:00 each day (or any run with no usable watermark, a manual / full-lane run, or a failed
delta read) is a FULL run: today's full read + the sold-out zeroing step, and a record of how many rows it had to
correct (the drift the delta runs left). The zeroing step never runs after a delta read.
"""
import datetime
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.catalog.models import ItemStock
from apps.sync import delta, maintenance, tasks
from apps.sync.models import DeltaShadowRun, StockFullCheck, SyncRun, SyncWatermark

from .factories import make_branch, make_item

T0 = datetime.datetime(2026, 11, 27, 10, 0, 0)


class _Cursor:
    def __init__(self, conn):
        self.conn = conn
        self._rows = []

    def execute(self, sql, params=None):
        s = ' '.join(sql.split()).lower()
        if 'modif_lastupdate >=' in s:
            self.conn.calls.append('delta')
            if self.conn.fail_delta:
                raise Exception('JZ0T3: Read operation timed out')
            self._rows = list(self.conn.delta)
        elif 'stkbal' in s:
            self.conn.calls.append('full')
            self._rows = list(self.conn.stock)
        else:
            self._rows = []

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _Conn:
    def __init__(self, stock=(), delta_rows=(), fail_delta=False):
        self.stock, self.delta, self.fail_delta = list(stock), list(delta_rows), fail_delta
        self.calls = []

    def cursor(self):
        return _Cursor(self)

    def close(self):
        pass


def row(item, qty, stamp, branch='100', store='100'):
    return (item, branch, store, Decimal(str(qty)), Decimal('0'), Decimal('0'), stamp)


def run(conn, **kw):
    return tasks.sync_stock(conn, SyncRun.objects.create(status='running', lane='fast'), **kw)


def at(hour, minute=0, day=27):
    return timezone.make_aware(datetime.datetime(2026, 11, day, hour, minute), timezone.get_default_timezone())


@override_settings(SYNC_DELTA_STOCK='on')
class OnModeTests(TestCase):

    def setUp(self):
        self.branch = make_branch('HQ', '100')
        self.a, self.b, self.c = make_item('A', 'A1'), make_item('B', 'B1'), make_item('C', 'C1')
        self.base = [row('A1', 5, T0), row('B1', 7, T0), row('C1', 2, T0)]
        self.now = mock.patch('apps.sync.delta.timezone.now', return_value=at(10)).start()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(tasks, 'STOCK_RECONCILE_MIN_ROWS', 1).start()

    def qty(self, item):
        return ItemStock.objects.get(item=item).quantity_on_hand

    def full_first(self):
        conn = _Conn(self.base)
        run(conn)
        return conn

    def test_mode_on_is_now_accepted(self):
        self.assertEqual(delta.stock_mode(), 'on')

    def test_first_run_without_a_watermark_is_full(self):
        conn = self.full_first()
        self.assertEqual(conn.calls, ['full'])
        wm = SyncWatermark.objects.get(stream='stkbal')
        self.assertEqual((wm.mode, wm.last_full_ok), ('on', True))
        self.assertEqual(timezone.localtime(wm.value_ts).replace(tzinfo=None), T0)

    def test_next_run_reads_and_writes_only_the_delta(self):
        self.full_first()
        t1 = T0 + datetime.timedelta(minutes=5)
        conn = _Conn(self.base, delta_rows=[row('A1', 3, t1)])
        run(conn)
        self.assertEqual(conn.calls, ['delta'])                         # no full read
        self.assertEqual((self.qty(self.a), self.qty(self.b)), (3, 7))
        wm = SyncWatermark.objects.get(stream='stkbal')
        self.assertEqual(timezone.localtime(wm.value_ts).replace(tzinfo=None), t1)
        self.assertEqual(wm.rows_last_delta, 1)

    def test_a_delta_run_never_zeroes_rows_it_did_not_read(self):
        # doc 40 §4.1 "Deletes": in a delta run every row not in the result would otherwise be zeroed
        self.full_first()
        run(_Conn(self.base, delta_rows=[]))
        self.assertEqual((self.qty(self.a), self.qty(self.b), self.qty(self.c)), (5, 7, 2))

    def test_a_sold_out_row_arrives_as_zero_and_is_written(self):
        self.full_first()
        run(_Conn(self.base, delta_rows=[row('C1', 0, T0 + datetime.timedelta(minutes=5))]))
        self.assertEqual(self.qty(self.c), 0)

    def test_a_failed_delta_read_falls_back_to_a_full_run(self):
        self.full_first()
        changed = [row('A1', 9, T0), row('B1', 7, T0), row('C1', 2, T0)]
        conn = _Conn(changed, fail_delta=True)
        run(conn)
        self.assertEqual(conn.calls, ['delta', 'full'])
        self.assertEqual(self.qty(self.a), 9)

    def test_first_run_after_04_00_is_the_nightly_full(self):
        self.full_first()                                                 # full at 10:00 on the 27th
        self.now.return_value = at(3, 55, day=28)
        conn = _Conn(self.base, delta_rows=[])
        run(conn)
        self.assertEqual(conn.calls, ['delta'])                           # before 04:00: still a delta
        self.now.return_value = at(4, 5, day=28)
        drifted = [row('A1', 4, T0), row('B1', 7, T0)]                   # A drifted, C vanished
        conn = _Conn(drifted)
        run(conn)
        self.assertEqual(conn.calls, ['full'])
        self.assertEqual((self.qty(self.a), self.qty(self.c)), (4, 0))   # corrected + sold-out zeroing
        check = StockFullCheck.objects.latest('at')
        self.assertEqual((check.corrected, check.zeroed), (1, 1))
        self.assertEqual(check.per_branch, {'100': {'corrected': 1, 'zeroed': 1}})
        self.assertFalse(check.ok)                                        # drift found → not ok
        conn = _Conn(drifted, delta_rows=[])
        run(conn)
        self.assertEqual(conn.calls, ['delta'])                           # once a day only

    def test_a_clean_nightly_full_is_ok(self):
        self.full_first()
        self.now.return_value = at(4, 5, day=28)
        run(_Conn(self.base))
        check = StockFullCheck.objects.latest('at')
        self.assertEqual((check.corrected, check.zeroed, check.ok), (0, 0, True))

    def test_full_lane_and_manual_runs_always_read_in_full(self):
        self.full_first()
        conn = _Conn(self.base, delta_rows=[])
        run(conn, full=True)
        self.assertEqual(conn.calls, ['full'])

    def test_a_real_clock_reset_on_the_nightly_full_reseeds(self):
        self.full_first()
        self.now.return_value = at(4, 5, day=28)
        earlier = T0 - datetime.timedelta(days=2)
        run(_Conn([row('A1', 5, earlier), row('B1', 7, earlier), row('C1', 2, earlier)]))
        wm = SyncWatermark.objects.get(stream='stkbal')
        self.assertEqual(timezone.localtime(wm.value_ts).replace(tzinfo=None), earlier)
        self.assertIn('S6', StockFullCheck.objects.latest('at').note)

    def test_on_mode_writes_no_shadow_rows(self):
        self.full_first()
        run(_Conn(self.base, delta_rows=[]))
        self.assertFalse(DeltaShadowRun.objects.exists())


class RetentionTests(TestCase):

    def test_old_shadow_and_full_check_rows_are_pruned(self):
        old = timezone.now() - datetime.timedelta(days=40)
        DeltaShadowRun.objects.create(stream='stkbal', at=old)
        DeltaShadowRun.objects.create(stream='stkbal')
        StockFullCheck.objects.create(at=timezone.now() - datetime.timedelta(days=100))
        StockFullCheck.objects.create()
        removed = maintenance.prune_delta_records()
        self.assertEqual(removed, 2)
        self.assertEqual((DeltaShadowRun.objects.count(), StockFullCheck.objects.count()), (1, 1))
