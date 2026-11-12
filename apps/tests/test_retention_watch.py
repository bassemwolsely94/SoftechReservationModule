"""Retention job dependability (data lifecycle stage 1): overlap lock + catch-up."""
from datetime import datetime, timedelta

from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.notifications.models import Notification
from apps.sync import tasks
from apps.sync.maintenance import (MORNING_CHAIN_LOCK_KEY, RETENTION_LOCK_KEY, alert_missed_runs,
                                   morning_chain_catchup_due, retention_catchup_due, retention_watch,
                                   run_daily_retention, run_morning_chain_catchup,
                                   run_retention_catchup)
from apps.sync.models import SyncLog, SyncRun

from .factories import make_admin


class RetentionCatchupTests(TestCase):
    def _run(self, status, hours_ago, lane='retention'):
        run = SyncRun.objects.create(status=status, lane=lane)
        SyncRun.objects.filter(pk=run.pk).update(
            started_at=timezone.now() - timedelta(hours=hours_ago))
        return run

    def test_never_ran_is_due(self):
        self.assertTrue(retention_catchup_due())

    def test_recent_success_is_not_due(self):
        self._run('success', 25)
        self.assertFalse(retention_catchup_due())

    def test_old_success_is_due(self):
        self._run('success', 27)
        self.assertTrue(retention_catchup_due())

    def test_running_row_is_not_due(self):
        self._run('success', 27)
        self._run('running', 0)
        self.assertFalse(retention_catchup_due())

    def test_failed_attempt_waits_six_hours(self):
        self._run('success', 40)
        self._run('failed', 5)
        self.assertFalse(retention_catchup_due())
        SyncRun.objects.filter(status='failed').update(
            started_at=timezone.now() - timedelta(hours=7))
        self.assertTrue(retention_catchup_due())

    def test_catchup_runs_once_and_is_logged(self):
        self._run('success', 27)
        self.assertIsNotNone(run_retention_catchup())
        self.assertIsNone(run_retention_catchup())   # now recent
        self.assertEqual(SyncLog.objects.filter(table_name='retention:catchup').count(), 1)

    def test_lock_busy_leaves_no_run_row(self):
        # PG advisory locks are re-entrant within a session, so hold the lock on a
        # separate raw connection.
        from apps.sync.scheduler_lock import _raw_connection
        conn = _raw_connection()
        self.addCleanup(conn.close)
        with conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_lock(%s)', [RETENTION_LOCK_KEY])
        before = SyncRun.objects.filter(lane='retention').count()
        self.assertIsNone(run_daily_retention())
        self.assertEqual(SyncRun.objects.filter(lane='retention').count(), before)


class MissedRunAlertTests(TestCase):
    def setUp(self):
        _, self.admin, _ = make_admin('mr_admin')

    def _run(self, status, hours_ago, lane='retention'):
        run = SyncRun.objects.create(status=status, lane=lane)
        SyncRun.objects.filter(pk=run.pk).update(
            started_at=timezone.now() - timedelta(hours=hours_ago))
        return run

    def _alerts(self):
        return Notification.objects.filter(notification_type='sync_failure',
                                           title__contains='لم تكتمل').count()

    def test_missed_morning_chain_alerts_once_a_day(self):
        self._run('success', 27, lane='morning_chain')
        self.assertEqual(alert_missed_runs(), ['morning_chain'])
        alert_missed_runs()
        self.assertEqual(self._alerts(), 1)

    def test_recent_success_does_not_alert(self):
        self._run('success', 25, lane='morning_chain')
        self.assertEqual(alert_missed_runs(), [])

    def test_running_lane_does_not_alert(self):
        self._run('success', 27, lane='morning_chain')
        self._run('running', 0, lane='morning_chain')
        self.assertEqual(alert_missed_runs(), [])

    def test_lane_that_never_ran_does_not_alert(self):
        self.assertEqual(alert_missed_runs(), [])

    def test_only_failures_count_from_the_first_attempt(self):
        self._run('failed', 27, lane='morning_chain')
        self.assertEqual(alert_missed_runs(), ['morning_chain'])

    def test_late_wake_successful_catchup_does_not_alert(self):
        self._run('success', 50)                    # retention lane
        retention_watch()
        self.assertEqual(self._alerts(), 0)
        self.assertEqual(SyncRun.objects.filter(lane='retention', status='success').count(), 2)

    def test_failed_catchup_alerts(self):
        self._run('success', 50)
        with mock.patch('apps.sync.maintenance.prune_notifications', side_effect=RuntimeError('x')):
            retention_watch()
        self.assertEqual(self._alerts(), 1)

    def test_watch_alerts_even_if_catchup_raises(self):
        self._run('success', 27, lane='morning_chain')
        with mock.patch('apps.sync.maintenance.run_retention_catchup', side_effect=RuntimeError('x')):
            retention_watch()                       # must not raise
        self.assertEqual(self._alerts(), 1)

    def test_watch_runs_the_morning_chain_catchup_and_still_alerts_if_it_raises(self):
        self._run('success', 27, lane='morning_chain')
        with mock.patch('apps.sync.maintenance.run_morning_chain_catchup',
                        side_effect=RuntimeError('x')) as catchup:
            retention_watch()                       # must not raise
        catchup.assert_called_once()
        self.assertEqual(self._alerts(), 1)


class RetentionLockReleaseTests(TestCase):
    def test_lock_is_released_after_a_normal_run(self):
        # PG advisory locks are re-entrant, so a same-session check can't see a leak;
        # probe from a second connection.
        from apps.sync.scheduler_lock import _raw_connection
        run = run_daily_retention()
        self.assertIsNotNone(run)
        conn = _raw_connection()
        self.addCleanup(conn.close)
        with conn.cursor() as cur:
            cur.execute('SELECT pg_try_advisory_lock(%s)', [RETENTION_LOCK_KEY])
            self.assertTrue(cur.fetchone()[0])
            cur.execute('SELECT pg_advisory_unlock(%s)', [RETENTION_LOCK_KEY])


class StaleFlipTests(TestCase):
    def test_stale_flipped_row_is_not_due_until_six_hours(self):
        from apps.sync.maintenance import mark_stale_runs
        run = SyncRun.objects.create(status='running', lane='retention')
        SyncRun.objects.filter(pk=run.pk).update(
            started_at=timezone.now() - timedelta(minutes=60))
        self.assertEqual(mark_stale_runs(), 1)
        self.assertEqual(SyncRun.objects.get(pk=run.pk).status, 'failed')
        self.assertFalse(retention_catchup_due())     # failed 60 min ago: waits
        SyncRun.objects.filter(pk=run.pk).update(
            started_at=timezone.now() - timedelta(hours=6, minutes=1))
        self.assertTrue(retention_catchup_due())

    def test_run_flipped_to_failed_while_working_ends_as_success(self):
        from apps.sync.maintenance import _run_retention_steps

        def flip():
            SyncRun.objects.filter(lane='retention', status='running').update(status='failed')
            return 3

        run = _run_retention_steps([('retention:flip', flip)])
        self.assertEqual(SyncRun.objects.get(pk=run.pk).status, 'success')


class RetentionRowNotASyncInFlightTests(TestCase):
    def _admin(self):
        from .factories import make_admin
        user, _profile, client = make_admin('inflight_admin')
        user.is_staff = True
        user.save()
        client.force_authenticate(user)
        return client

    def _running(self, lane):
        return SyncRun.objects.create(status='running', lane=lane)

    def test_manual_sync_not_blocked_by_retention_row(self):
        self._running('retention')
        with mock.patch('apps.sync.views.start_thread') as st:
            r = self._admin().post('/api/sync/trigger/', {'lane': 'fast'}, format='json')
        self.assertEqual(r.status_code, 202)
        self.assertEqual(r.data['detail'], 'sync started')
        st.assert_called_once()

    def test_manual_sync_still_blocked_by_other_running_row(self):
        self._running('fast')
        with mock.patch('apps.sync.views.start_thread') as st:
            r = self._admin().post('/api/sync/trigger/', {'lane': 'fast'}, format='json')
        self.assertEqual(r.data['detail'], 'sync already in progress')
        st.assert_not_called()

    def test_supply_refresh_not_blocked_by_retention_row(self):
        self._running('retention')
        with mock.patch('apps.supply.views.start_thread') as st:
            r = self._admin().post('/api/supply/freshness/sync-stock/', {}, format='json')
        self.assertEqual(r.status_code, 202, r.data)
        st.assert_called_once()

    def test_supply_refresh_still_blocked_by_other_running_row(self):
        self._running('slow')
        with mock.patch('apps.supply.views.start_thread') as st:
            r = self._admin().post('/api/supply/freshness/sync-stock/', {}, format='json')
        self.assertEqual(r.status_code, 202, r.data)
        st.assert_not_called()


class MorningChainCatchupTests(TestCase):
    """Owner decision 2026-11-11: a missed 07:30 morning chain catches up too, but only once
    SOFTECH is reachable again (a fast sync succeeded in the last 30 minutes)."""

    # 15:00 Cairo on a fixed day: after the 07:30 slot.
    NOW = timezone.make_aware(datetime(2026, 11, 11, 15, 0))

    def _at(self, status, at, lane='morning_chain'):
        run = SyncRun.objects.create(status=status, lane=lane)
        SyncRun.objects.filter(pk=run.pk).update(started_at=at)
        return run

    def _softech_up(self, minutes_ago=5, status='success'):
        return self._at(status, self.NOW - timedelta(minutes=minutes_ago), lane='fast')

    def test_due_after_a_missed_slot_once_softech_is_back(self):
        self._at('success', self.NOW - timedelta(days=1, hours=7))
        self._softech_up()
        self.assertTrue(morning_chain_catchup_due(self.NOW))

    def test_never_ran_is_due(self):
        self._softech_up()
        self.assertTrue(morning_chain_catchup_due(self.NOW))

    def test_not_due_before_the_slot(self):
        early = timezone.make_aware(datetime(2026, 11, 11, 6, 0))
        self._at('success', early - timedelta(days=1, hours=1))
        self._at('success', early - timedelta(minutes=5), lane='fast')
        self.assertFalse(morning_chain_catchup_due(early))

    def test_not_due_when_todays_run_succeeded(self):
        self._at('success', timezone.make_aware(datetime(2026, 11, 11, 7, 30)))
        self._softech_up()
        self.assertFalse(morning_chain_catchup_due(self.NOW))

    def test_not_due_while_softech_is_unreachable(self):
        self._at('success', self.NOW - timedelta(days=2))
        self._softech_up(status='failed')
        self.assertFalse(morning_chain_catchup_due(self.NOW))

    def test_not_due_when_the_last_fast_sync_is_stale(self):
        self._at('success', self.NOW - timedelta(days=2))
        self._softech_up(minutes_ago=45)
        self.assertFalse(morning_chain_catchup_due(self.NOW))

    def test_not_due_while_a_chain_is_running(self):
        self._at('success', self.NOW - timedelta(days=2))
        self._at('running', self.NOW - timedelta(minutes=10))
        self._softech_up()
        self.assertFalse(morning_chain_catchup_due(self.NOW))

    def test_failed_attempt_waits_six_hours(self):
        self._at('success', self.NOW - timedelta(days=2))
        self._at('failed', self.NOW - timedelta(hours=5))
        self._softech_up()
        self.assertFalse(morning_chain_catchup_due(self.NOW))
        SyncRun.objects.filter(lane='morning_chain', status='failed').update(
            started_at=self.NOW - timedelta(hours=7))
        self.assertTrue(morning_chain_catchup_due(self.NOW))

    def _patched_steps(self):
        return [mock.patch(f'apps.sync.tasks.{name}') for name, _ in tasks.MORNING_CHAIN]

    def test_catchup_runs_the_chain_once_and_is_logged(self):
        patches = self._patched_steps()
        mocks = [p.start() for p in patches]
        self.addCleanup(lambda: [p.stop() for p in patches])
        self._at('success', timezone.now() - timedelta(minutes=2), lane='fast')
        with mock.patch('apps.sync.maintenance.morning_chain_catchup_due', return_value=True):
            run = run_morning_chain_catchup()
        self.assertEqual(run.status, 'success')
        for m in mocks:
            m.assert_called_once()
        self.assertEqual(SyncLog.objects.filter(table_name='chain:catchup').count(), 1)

    def test_catchup_does_nothing_when_not_due(self):
        with mock.patch('apps.sync.maintenance.morning_chain_catchup_due', return_value=False), \
                mock.patch('apps.sync.tasks._run_morning_chain') as chain:
            self.assertIsNone(run_morning_chain_catchup())
        chain.assert_not_called()

    def test_lock_busy_leaves_no_run_row(self):
        from apps.sync.scheduler_lock import _raw_connection
        conn = _raw_connection()
        self.addCleanup(conn.close)
        with conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_lock(%s)', [MORNING_CHAIN_LOCK_KEY])
        patches = self._patched_steps()
        [p.start() for p in patches]
        self.addCleanup(lambda: [p.stop() for p in patches])
        self.assertIsNone(tasks._run_morning_chain())
        self.assertFalse(SyncRun.objects.filter(lane='morning_chain').exists())


class MorningChainRunGuardTests(TestCase):
    """Guards inside the chain lock (review 2026-11-12): one successful chain per day, never
    while SOFTECH is unreachable, and a retry skips the steps already done today. They apply to
    the 07:30 job and to the catch-up alike."""

    def setUp(self):
        self.patches = [mock.patch(f'apps.sync.tasks.{name}') for name, _ in tasks.MORNING_CHAIN]
        self.steps = {name: p.start() for (name, _), p in zip(tasks.MORNING_CHAIN, self.patches)}
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def _fast_ok(self):
        run = SyncRun.objects.create(status='success', lane='fast')
        SyncRun.objects.filter(pk=run.pk).update(started_at=timezone.now() - timedelta(minutes=2))

    def test_softech_down_creates_no_run_and_runs_no_step(self):
        self.assertIsNone(tasks._run_morning_chain())
        self.assertFalse(SyncRun.objects.filter(lane='morning_chain').exists())
        for m in self.steps.values():
            m.assert_not_called()

    def test_a_second_chain_on_the_same_day_does_nothing(self):
        self._fast_ok()
        self.assertEqual(tasks._run_morning_chain().status, 'success')
        self.assertIsNone(tasks._run_morning_chain())
        for m in self.steps.values():
            m.assert_called_once()
        self.assertEqual(SyncRun.objects.filter(lane='morning_chain').count(), 1)

    def test_retry_after_a_killed_run_skips_steps_done_today(self):
        self._fast_ok()
        killed = SyncRun.objects.create(status='failed', lane='morning_chain')
        SyncRun.objects.filter(pk=killed.pk).update(started_at=timezone.now() - timedelta(minutes=1))
        for name in ('_run_ap_reconciliation_sync', '_insights_daily'):
            SyncLog.objects.create(sync_run=killed, table_name=f'chain:{name.lstrip("_")}',
                                   records_processed=1)
        run = tasks._run_morning_chain()
        self.assertEqual(run.status, 'success')
        self.steps['_run_ap_reconciliation_sync'].assert_not_called()
        self.steps['_insights_daily'].assert_not_called()
        self.steps['_run_supply_case_sweep'].assert_called_once()
        self.steps['_run_replacement_check'].assert_called_once()

    def test_lock_is_released_after_a_normal_run(self):
        from apps.sync.scheduler_lock import _raw_connection
        self._fast_ok()
        tasks._run_morning_chain()
        conn = _raw_connection()
        self.addCleanup(conn.close)
        with conn.cursor() as cur:
            cur.execute('SELECT pg_try_advisory_lock(%s)', [MORNING_CHAIN_LOCK_KEY])
            self.assertTrue(cur.fetchone()[0])
            cur.execute('SELECT pg_advisory_unlock(%s)', [MORNING_CHAIN_LOCK_KEY])
