"""Retention job dependability (data lifecycle stage 1): overlap lock + catch-up."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.sync.maintenance import (RETENTION_LOCK_KEY, retention_catchup_due,
                                   run_daily_retention, run_retention_catchup)
from apps.sync.models import SyncLog, SyncRun


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
