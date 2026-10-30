"""
apps/tests/test_sync_health.py

P-56 (docs/product-review/06_SPEC_P-56): database retention + sync health.
  • engine-run retention keeps the last 10 completed runs + the last run of each month
  • AuditLog money / SOFTECH / approval rows are never deleted; only allow-listed noise ages out
  • PBX raw events age out after 90 days
  • a SyncRun stuck 'running' > 60 min is marked failed
  • sync_stock with an unchanged snapshot writes nothing
  • a lane retries once on a dropped connection, then fails without zeroing stock
  • a scheduled lane skips its tick while a manual run of the same lane is in flight
  • the morning jobs run as one ordered chain
  • requests over the threshold are logged; the slow-endpoint report is admin-only
"""
import datetime
from decimal import Decimal
from unittest import mock

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.catalog.models import ItemStock
from apps.sync import maintenance, tasks
from apps.sync.models import SyncLog, SyncRun
from .factories import make_admin, make_branch, make_item, make_pharmacist


def _aware(y, m, d, h=12):
    return timezone.make_aware(datetime.datetime(y, m, d, h, 0))


class EngineRunRetentionTests(TestCase):

    def setUp(self):
        from apps.purchasing.models import DemandCalculationRun
        self.Run = DemandCalculationRun
        self.item = make_item()
        self.branch = make_branch()

    def _run(self, when, status='success'):
        from apps.purchasing.models import ItemDemandAggregated, ItemDemandMetrics
        run = self.Run.objects.create(status=status, calc_date=when.date())
        self.Run.objects.filter(pk=run.pk).update(started_at=when)
        ItemDemandMetrics.objects.create(run=run, item=self.item, branch=self.branch, calc_date=when.date())
        ItemDemandAggregated.objects.create(run=run, item=self.item, calc_date=when.date())
        return run

    def test_keeps_last_ten_completed_plus_last_of_each_month(self):
        from apps.purchasing.models import ItemDemandMetrics, ItemDemandAggregated
        runs = []
        for month in (8, 9, 10):          # 15 runs, 5 per month
            for day in (3, 9, 15, 21, 27):
                runs.append(self._run(_aware(2026, month, day)))
        failed = self._run(_aware(2026, 10, 28), status='failed')

        maintenance.prune_engine_runs()

        kept = set(ItemDemandMetrics.objects.values_list('run_id', flat=True))
        expected = {r.pk for r in runs[-10:]} | {runs[4].pk}   # + August's last run
        self.assertEqual(kept, expected)
        self.assertEqual(set(ItemDemandAggregated.objects.values_list('run_id', flat=True)), expected)
        self.assertNotIn(failed.pk, kept)
        self.assertEqual(self.Run.objects.count(), 16)       # run headers are kept

    def test_reviewed_transfer_recommendations_survive(self):
        from apps.purchasing.models import TransferRecommendation, TransferRecommendationRun
        from .factories import make_branch2
        other = make_branch2()
        old = self._run(_aware(2026, 1, 5))
        self._run(_aware(2026, 1, 20))     # January's last run is the one kept
        for d in range(1, 12):
            self._run(_aware(2026, 10, d))
        trr = TransferRecommendationRun.objects.create(demand_run=old, status='success')
        common = dict(run=trr, from_branch=self.branch, to_branch=other, quantity=1)
        pending = TransferRecommendation.objects.create(status='pending', item=self.item, **common)
        approved = TransferRecommendation.objects.create(status='approved', item=make_item('ب', 'IT009'), **common)

        maintenance.prune_engine_runs()

        self.assertFalse(TransferRecommendation.objects.filter(pk=pending.pk).exists())
        self.assertTrue(TransferRecommendation.objects.filter(pk=approved.pk).exists())


class AuditAndPbxRetentionTests(TestCase):

    def _audit(self, action, days_old):
        from apps.audit.models import AuditLog
        row = AuditLog.objects.create(action=action)
        AuditLog.objects.filter(pk=row.pk).update(created_at=timezone.now() - datetime.timedelta(days=days_old))
        return row.pk

    def test_only_allow_listed_noise_ages_out(self):
        from apps.audit.models import AuditLog
        old_login = self._audit('user_login', 400)
        new_login = self._audit('user_login', 30)
        money = self._audit('replacement_case_approved', 900)
        softech = self._audit('coupon_batch_stocked', 900)

        maintenance.prune_audit_log()

        left = set(AuditLog.objects.values_list('pk', flat=True))
        self.assertNotIn(old_login, left)
        self.assertTrue({new_login, money, softech} <= left)

    def test_pbx_events_older_than_90_days_go(self):
        from apps.pbx.models import PBXEvent
        old = PBXEvent.objects.create(payload={})
        new = PBXEvent.objects.create(payload={})
        PBXEvent.objects.filter(pk=old.pk).update(received_at=timezone.now() - datetime.timedelta(days=91))

        maintenance.prune_pbx_events()

        self.assertEqual(list(PBXEvent.objects.values_list('pk', flat=True)), [new.pk])


class StaleRunTests(TestCase):

    def test_running_over_an_hour_becomes_failed(self):
        stale = SyncRun.objects.create(status='running')
        fresh = SyncRun.objects.create(status='running')
        SyncRun.objects.filter(pk=stale.pk).update(started_at=timezone.now() - datetime.timedelta(minutes=61))

        self.assertEqual(maintenance.mark_stale_runs(), 1)

        stale.refresh_from_db()
        fresh.refresh_from_db()
        self.assertEqual(stale.status, 'failed')
        self.assertIn('stale', stale.error_message)
        self.assertIsNotNone(stale.completed_at)
        self.assertEqual(fresh.status, 'running')

    def test_heartbeat_marks_stale_runs(self):
        stale = SyncRun.objects.create(status='running')
        SyncRun.objects.filter(pk=stale.pk).update(started_at=timezone.now() - datetime.timedelta(hours=3))
        tasks._write_heartbeat()
        stale.refresh_from_db()
        self.assertEqual(stale.status, 'failed')


# ── fake SOFTECH for the stock lane ───────────────────────────────────────────

class _Cursor:
    def __init__(self, conn):
        self.conn = conn
        self._rows = []

    def execute(self, sql, params=None):
        s = ' '.join(sql.split()).lower()
        if 'stkbal' in s:
            if self.conn.fail_stock:
                raise Exception('JZ0C0: Connection is already closed.')
            self._rows = list(self.conn.stock)
        else:
            self._rows = []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class _Conn:
    def __init__(self, stock=(), fail_stock=False):
        self.stock = list(stock)
        self.fail_stock = fail_stock
        self.closed = False

    def cursor(self):
        return _Cursor(self)

    def close(self):
        self.closed = True


class StockChangeOnlyTests(TestCase):

    def setUp(self):
        self.item = make_item()
        self.branch = make_branch('HQ', '100')
        # (itemcode, branchcode, storecode, nowqty, monthlyqty, onorder)
        self.snapshot = [('IT001', '100', '100', 5, 2, 0)]

    def test_unchanged_snapshot_writes_nothing(self):
        tasks.sync_stock(_Conn(self.snapshot), SyncRun.objects.create(status='running'))
        self.assertEqual(ItemStock.objects.get().quantity_on_hand, 5)

        with CaptureQueriesContext(connection) as ctx:
            tasks.sync_stock(_Conn(self.snapshot), SyncRun.objects.create(status='running'))
        writes = [q['sql'] for q in ctx.captured_queries
                  if 'catalog_itemstock' in q['sql'] and q['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE'))]
        self.assertEqual(writes, [])

    def test_changed_row_is_written(self):
        tasks.sync_stock(_Conn(self.snapshot), SyncRun.objects.create(status='running'))
        tasks.sync_stock(_Conn([('IT001', '100', '100', 7, 2, 0)]), SyncRun.objects.create(status='running'))
        self.assertEqual(ItemStock.objects.get().quantity_on_hand, 7)

    def test_sold_out_row_is_still_zeroed(self):
        other = make_item('أموكسيسيلين', 'IT002')
        both = self.snapshot + [('IT002', '100', '100', 3, 1, 0)]
        with mock.patch.object(tasks, 'STOCK_RECONCILE_MIN_ROWS', 1):
            tasks.sync_stock(_Conn(both), SyncRun.objects.create(status='running'))
            tasks.sync_stock(_Conn(self.snapshot), SyncRun.objects.create(status='running'))
        self.assertEqual(ItemStock.objects.get(item=other).quantity_on_hand, 0)
        self.assertEqual(ItemStock.objects.get(item=self.item).quantity_on_hand, 5)


class LaneRetryTests(TestCase):

    def setUp(self):
        self.item = make_item()
        self.branch = make_branch('HQ', '100')
        ItemStock.objects.create(item=self.item, branch=self.branch, softech_store_code='100',
                                 quantity_on_hand=9)
        self.good = [('IT001', '100', '100', 4, 1, 0)]

    def _lane(self, conns):
        with mock.patch.object(tasks, 'get_sybase_connection', side_effect=conns), \
             mock.patch.object(tasks, 'sync_branches', return_value=0), \
             mock.patch.object(tasks, 'sync_sales', return_value=0), \
             mock.patch.object(tasks, '_run_reactive_hooks'), \
             mock.patch.object(tasks, 'STOCK_RECONCILE_MIN_ROWS', 1):
            return tasks.run_fast_sync()

    def test_dropped_connection_is_retried_once(self):
        first = _Conn(self.good, fail_stock=True)
        run = self._lane([first, _Conn(self.good)])
        self.assertEqual(run.status, 'success')
        self.assertTrue(first.closed)
        self.assertEqual(ItemStock.objects.get().quantity_on_hand, 4)

    def test_second_failure_fails_the_lane_without_zeroing(self):
        run = self._lane([_Conn(self.good, fail_stock=True), _Conn(self.good, fail_stock=True)])
        self.assertEqual(run.status, 'failed')
        self.assertEqual(ItemStock.objects.get().quantity_on_hand, 9)

    def test_non_connection_error_is_not_retried(self):
        boom = mock.Mock(side_effect=ValueError('bad data'))
        with mock.patch.object(tasks, 'get_sybase_connection', side_effect=[_Conn(), _Conn()]) as gc, \
             mock.patch.object(tasks, 'sync_branches', boom), \
             mock.patch.object(tasks, '_run_reactive_hooks'):
            run = tasks.run_fast_sync()
        self.assertEqual(run.status, 'failed')
        self.assertEqual(gc.call_count, 1)

    def test_scheduled_tick_skips_while_manual_run_in_flight(self):
        SyncRun.objects.create(status='running', lane='fast', manual=True)
        with mock.patch.object(tasks, 'run_fast_sync') as lane:
            self.assertIsNone(tasks._scheduled_fast_sync())
        lane.assert_not_called()

    def test_scheduled_tick_runs_when_only_other_lane_in_flight(self):
        SyncRun.objects.create(status='running', lane='slow', manual=True)
        with mock.patch.object(tasks, 'run_fast_sync') as lane:
            tasks._scheduled_fast_sync()
        lane.assert_called_once()


class MorningChainTests(TestCase):

    def test_runs_in_order_and_logs_each_step(self):
        order = []
        names = ['_run_ap_reconciliation_sync', '_insights_daily',
                 '_run_supply_case_sweep', '_run_replacement_check']
        patches = [mock.patch.object(tasks, n, side_effect=lambda n=n: order.append(n)) for n in names]
        # a failing step must not stop the ones after it
        patches[1] = mock.patch.object(tasks, '_insights_daily',
                                       side_effect=lambda: (order.append('_insights_daily'), 1 / 0))
        for p in patches:
            p.start()
        try:
            tasks._run_morning_chain()
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(order, names)
        run = SyncRun.objects.get(lane='morning_chain')
        self.assertEqual(run.status, 'failed')
        self.assertEqual(SyncLog.objects.filter(sync_run=run).count(), 4)


@override_settings(SLOW_REQUEST_MS=0)
class SlowRequestTests(TestCase):

    def test_slow_request_logged_with_route_pattern(self):
        from apps.sync.models import SlowRequest
        _, _, client = make_admin()
        client.get('/api/sync/logs/?x=1')
        row = SlowRequest.objects.get()
        self.assertEqual(row.path, 'api/sync/logs/')
        self.assertEqual(row.status_code, 200)
        self.assertEqual(row.role, 'admin')

    def test_report_is_admin_only(self):
        _, _, client = make_pharmacist()
        self.assertEqual(client.get('/api/sync/slow-requests/').status_code, 403)

    def test_report_ranks_by_p95(self):
        from apps.sync.models import SlowRequest
        for ms in (1200, 1300, 9000):
            SlowRequest.objects.create(path='api/a/', method='GET', status_code=200, duration_ms=ms)
        SlowRequest.objects.create(path='api/b/', method='GET', status_code=200, duration_ms=2000)
        _, _, client = make_admin('admin_slow')
        with override_settings(SLOW_REQUEST_MS=60_000):
            rows = client.get('/api/sync/slow-requests/').json()['endpoints']
        self.assertEqual([r['path'] for r in rows], ['api/a/', 'api/b/'])
        self.assertEqual(rows[0]['count'], 3)


class SchedulerWiringTests(TestCase):

    def test_morning_chain_and_retention_registered(self):
        from .test_scheduler_jobs import _FakeScheduler
        with mock.patch.object(tasks, 'BackgroundScheduler', _FakeScheduler), \
             mock.patch.object(tasks, '_patch_apscheduler_for_python312', lambda: None), \
             mock.patch.object(tasks, '_scheduler', None):
            tasks.start_scheduler()
            ids = {j[1] for j in tasks._scheduler.jobs}
        self.assertTrue({'morning_chain', 'daily_retention'} <= ids)
        self.assertFalse({'ap_reconciliation_sync', 'insights_daily',
                          'supply_case_sweep', 'replacement_daily_check'} & ids)


class SchemaDriftDefaultTests(TestCase):
    """P-56 §4: columns a pre-migration process leaves out must not abort its inserts."""

    def _default(self, table, column):
        with connection.cursor() as c:
            c.execute('SELECT column_default FROM information_schema.columns '
                      'WHERE table_name = %s AND column_name = %s', [table, column])
            return (c.fetchone() or [None])[0] or ''

    def test_server_defaults_present(self):
        self.assertIn("''", self._default('customers_customer', 'merged_into_pic'))
        self.assertIn("''", self._default('sync_syncrun', 'lane'))
        self.assertIn('false', self._default('sync_syncrun', 'manual'))
