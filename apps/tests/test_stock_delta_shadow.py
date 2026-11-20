"""
Stock delta sync in SHADOW mode (doc 40 §3, §4.1, §6.1; plan docs/superpowers/plans/2026-11-20-stock-delta-shadow.md).

The full stock read still writes, exactly as today. In `shadow` a second, small read asks SOFTECH only for
rows stamped since the watermark, and the run records which real changes that read would have missed.
Nothing the delta read returns is ever written. Default is `off`.

No real SOFTECH: a fake connection answers the full read (QUERY_STOCK) and the delta read.
"""
import datetime
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.catalog.models import ItemStock
from apps.sync import delta, tasks
from apps.sync.models import DeltaShadowRun, SyncRun, SyncWatermark

from .factories import make_admin, make_branch, make_item, make_pharmacist

T0 = datetime.datetime(2026, 11, 20, 10, 0, 0)          # SOFTECH-side stamps are naive Cairo times


class _Cursor:
    def __init__(self, conn):
        self.conn = conn
        self._rows = []

    def execute(self, sql, params=None):
        s = ' '.join(sql.split()).lower()
        if 'modif_lastupdate >=' in s:                 # the delta read
            self.conn.delta_calls.append(params)
            if self.conn.fail_delta:
                raise Exception('JZ0T3: Read operation timed out')
            self._rows = list(self.conn.delta)
        elif 'stkbal' in s:                            # today's full read
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
        self.delta_calls = []

    def cursor(self):
        return _Cursor(self)

    def close(self):
        pass


def row(item, qty, stamp, branch='100', store='100'):
    """(itemcode, branchcode, storecode, nowqty, monthlyqty, onorderqty, modif_lastupdate)"""
    return (item, branch, store, Decimal(str(qty)), Decimal('0'), Decimal('0'), stamp)


def run(conn):
    return tasks.sync_stock(conn, SyncRun.objects.create(status='running'))


class ModeTests(TestCase):

    def test_default_is_off(self):
        self.assertEqual(delta.stock_mode(), 'off')

    @override_settings(SYNC_DELTA_STOCK='shadow')
    def test_shadow(self):
        self.assertEqual(delta.stock_mode(), 'shadow')

    @override_settings(SYNC_DELTA_STOCK='on')
    def test_on_is_not_built_and_runs_as_shadow(self):
        # ON needs 7 days of SHADOW with 0 misses and the owner's sign-off (doc 40 S2)
        self.assertEqual(delta.stock_mode(), 'shadow')

    @override_settings(SYNC_DELTA_STOCK='maybe')
    def test_junk_is_off(self):
        self.assertEqual(delta.stock_mode(), 'off')


class ShadowTests(TestCase):

    def setUp(self):
        self.branch = make_branch('HQ', '100')
        self.a, self.b, self.c = make_item('A', 'A1'), make_item('B', 'B1'), make_item('C', 'C1')
        self.base = [row('A1', 5, T0), row('B1', 7, T0), row('C1', 2, T0)]

    def seed(self):
        with override_settings(SYNC_DELTA_STOCK='shadow'):
            run(_Conn(self.base))

    def test_off_sends_no_delta_query_and_records_nothing(self):
        conn = _Conn(self.base)
        run(conn)
        self.assertEqual(conn.delta_calls, [])
        self.assertFalse(SyncWatermark.objects.exists())
        self.assertFalse(DeltaShadowRun.objects.exists())

    def test_first_shadow_run_only_seeds_the_watermark(self):
        conn = _Conn(self.base)
        with override_settings(SYNC_DELTA_STOCK='shadow'):
            run(conn)
        self.assertEqual(conn.delta_calls, [])                       # nothing to compare yet
        wm = SyncWatermark.objects.get(stream='stkbal')
        self.assertEqual(timezone.localtime(wm.value_ts).replace(tzinfo=None), T0)
        self.assertEqual(DeltaShadowRun.objects.get().note, 'seed')

    def test_delta_that_covers_every_change_misses_nothing(self):
        self.seed()
        t1 = T0 + datetime.timedelta(minutes=5)
        full = [row('A1', 4, t1), row('B1', 7, T0), row('C1', 2, T0)]
        conn = _Conn(full, delta_rows=[row('A1', 4, t1)])
        with override_settings(SYNC_DELTA_STOCK='shadow'):
            run(conn)
        self.assertEqual(len(conn.delta_calls), 1)
        since = conn.delta_calls[0][0]                               # watermark − 10 min, bound as text
        self.assertEqual(since, (T0 - datetime.timedelta(minutes=10)).strftime('%Y%m%d %H:%M:%S'))
        shadow = DeltaShadowRun.objects.latest('id')
        self.assertEqual((shadow.rows_changed, shadow.rows_delta, shadow.missed), (1, 1, 0))
        self.assertEqual(shadow.missed_sample, [])
        wm = SyncWatermark.objects.get(stream='stkbal')
        self.assertEqual(timezone.localtime(wm.value_ts).replace(tzinfo=None), t1)
        self.assertEqual(wm.misses_last_shadow, 0)

    def test_a_change_the_delta_did_not_return_is_a_miss(self):
        self.seed()
        t1 = T0 + datetime.timedelta(minutes=5)
        full = [row('A1', 4, t1), row('B1', 9, T0), row('C1', 2, T0)]   # B changed WITHOUT a new stamp
        with override_settings(SYNC_DELTA_STOCK='shadow'):
            run(_Conn(full, delta_rows=[row('A1', 4, t1)]))
        shadow = DeltaShadowRun.objects.latest('id')
        self.assertEqual(shadow.missed, 1)
        self.assertEqual(shadow.missed_sample, ['B1/100/100'])         # codes only, no names
        self.assertEqual(SyncWatermark.objects.get(stream='stkbal').misses_last_shadow, 1)

    def test_a_sold_out_row_is_a_real_change(self):
        self.seed()
        t1 = T0 + datetime.timedelta(minutes=5)
        full = [row('A1', 5, T0), row('B1', 7, T0)]                     # C sold out: full read drops it
        with override_settings(SYNC_DELTA_STOCK='shadow'), \
                mock.patch.object(tasks, 'STOCK_RECONCILE_MIN_ROWS', 1):
            run(_Conn(full, delta_rows=[]))                              # …and the delta did not return it
        self.assertEqual(ItemStock.objects.get(item=self.c).quantity_on_hand, 0)
        shadow = DeltaShadowRun.objects.latest('id')
        self.assertEqual((shadow.rows_changed, shadow.missed), (1, 1))
        self.assertEqual(shadow.missed_sample, ['C1/100/100'])

        with override_settings(SYNC_DELTA_STOCK='shadow'), \
                mock.patch.object(tasks, 'STOCK_RECONCILE_MIN_ROWS', 1):
            # the next time C sells out, the delta returns it at 0 (no nowqty > 0 filter): not a miss
            ItemStock.objects.filter(item=self.c).update(quantity_on_hand=3)
            run(_Conn(full, delta_rows=[row('C1', 0, t1)]))
        self.assertEqual(DeltaShadowRun.objects.latest('id').missed, 0)

    def test_delta_rows_are_never_written(self):
        self.seed()
        t1 = T0 + datetime.timedelta(minutes=5)
        with override_settings(SYNC_DELTA_STOCK='shadow'):
            run(_Conn(self.base, delta_rows=[row('A1', 99, t1)]))      # delta disagrees with the full read
        self.assertEqual(ItemStock.objects.get(item=self.a).quantity_on_hand, 5)

    def test_a_delta_error_never_breaks_the_full_sync(self):
        self.seed()
        full = [row('A1', 8, T0 + datetime.timedelta(minutes=5)), row('B1', 7, T0), row('C1', 2, T0)]
        with override_settings(SYNC_DELTA_STOCK='shadow'):
            count = run(_Conn(full, fail_delta=True))
        self.assertEqual(count, 3)
        self.assertEqual(ItemStock.objects.get(item=self.a).quantity_on_hand, 8)
        self.assertIn('error', DeltaShadowRun.objects.latest('id').note)

    def test_a_backwards_watermark_reseeds_and_is_noted(self):
        self.seed()
        earlier = T0 - datetime.timedelta(days=2)                       # SOFTECH clock/sequence reset (S6)
        full = [row('A1', 5, earlier), row('B1', 7, earlier), row('C1', 2, earlier)]
        conn = _Conn(full, delta_rows=[])
        with override_settings(SYNC_DELTA_STOCK='shadow'):
            run(conn)
        self.assertEqual(conn.delta_calls, [])
        self.assertIn('S6', DeltaShadowRun.objects.latest('id').note)
        wm = SyncWatermark.objects.get(stream='stkbal')
        self.assertEqual(timezone.localtime(wm.value_ts).replace(tzinfo=None), earlier)


class ShadowApiTests(TestCase):

    def test_admin_sees_the_report(self):
        _, _, client = make_admin('shadow_admin')
        DeltaShadowRun.objects.create(stream='stkbal', rows_full=32000, rows_changed=12, rows_delta=40,
                                      missed=0, delta_ms=900, full_ms=21000)
        r = client.get('/api/sync/delta-shadow/', {'days': 7})
        self.assertEqual(r.status_code, 200)
        st = r.data['streams'][0]
        self.assertEqual((st['stream'], st['runs'], st['missed_total']), ('stkbal', 1, 0))
        self.assertEqual(r.data['mode']['stkbal'], 'off')

    def test_non_admin_is_refused(self):
        _, _, client = make_pharmacist('shadow_ph', branch=make_branch())
        self.assertEqual(client.get('/api/sync/delta-shadow/').status_code, 403)
