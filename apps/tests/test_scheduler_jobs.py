"""Scheduler registration (doc 30, F7): every job function is scheduled once, and
every job runs under its own telemetry scope."""
from collections import Counter
from unittest import mock

from django.test import SimpleTestCase

from apps.sync import tasks


class _FakeScheduler:
    def __init__(self, *a, **kw):
        self.jobs = []
        self.cfg = {}
        self.tz = kw.get('timezone')
        self.running = False

    def add_job(self, func, trigger, *args, **kwargs):
        self.cfg[kwargs.get('id')] = (trigger, kwargs)
        self.jobs.append((getattr(func, '__wrapped__', func), kwargs.get('id'), func))

    def add_listener(self, *a, **kw):
        pass

    def start(self):
        self.running = True

    def shutdown(self, *a, **kw):
        self.running = False


class SchedulerRegistrationTests(SimpleTestCase):

    def _jobs(self):
        with mock.patch.object(tasks, 'BackgroundScheduler', _FakeScheduler), \
             mock.patch.object(tasks, '_patch_apscheduler_for_python312', lambda: None), \
             mock.patch.object(tasks, '_scheduler', None):
            tasks.start_scheduler()
            self._cfg, self._tz = tasks._scheduler.cfg, tasks._scheduler.tz
            return tasks._scheduler.jobs

    def test_no_job_function_registered_twice_on_the_same_cadence(self):
        jobs = self._jobs()
        self.assertGreater(len(jobs), 40)
        ids = Counter(j[1] for j in jobs)
        self.assertEqual([i for i, n in ids.items() if n > 1], [])
        for name in ('_flush_pos_orders', '_reconcile_pos_orders'):
            with self.subTest(job=name):
                self.assertEqual(sum(1 for f, _, _ in jobs if f.__name__ == name), 1)

    def test_morning_brief_registered_daily_at_0900_cairo(self):
        jobs = [j for j in self._jobs() if j[1] == 'morning_brief']
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0][0].__name__, '_run_morning_brief')
        self.assertEqual(self._cfg['morning_brief'][0], 'cron')
        self.assertEqual((self._cfg['morning_brief'][1]['hour'], self._cfg['morning_brief'][1]['minute']), (9, 0))
        self.assertEqual(self._tz, 'Africa/Cairo')

    def test_phone_alerts_tick_registered_every_minute(self):
        jobs = [j for j in self._jobs() if j[1] == 'phone_alerts_tick']
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0][0].__name__, '_run_phone_alerts_tick')
        trigger, kw = self._cfg['phone_alerts_tick']
        self.assertEqual((trigger, kw['minutes'], kw['max_instances']), ('interval', 1, 1))

    def test_pos_jobs_keep_their_ids(self):
        ids = {j[1] for j in self._jobs()}
        self.assertTrue({'pos_orders_flush', 'pos_orders_reconcile'} <= ids)
        self.assertFalse({'pos_flush_queued', 'pos_reconcile'} & ids)

    def test_every_job_runs_under_its_scope(self):
        for real, jid, wrapped in self._jobs():
            with self.subTest(job=jid):
                self.assertIs(wrapped.__wrapped__, real)


class SlowLaneFirstRunTests(SimpleTestCase):
    """A restart must not push the hourly slow lane another full hour away (2026-11-19:
    13 restarts in 10 h, so it never fired)."""

    def setUp(self):
        import datetime as d
        from django.utils import timezone
        self.d = d
        self.now = timezone.now()

    def _first(self, last=None, exc=None):
        side = exc if exc else (lambda: last)
        with mock.patch.object(tasks, '_last_slow_run_start', side_effect=side):
            return tasks._slow_lane_first_run(60, now=self.now)

    def test_overdue_runs_shortly_after_start(self):
        first = self._first(last=self.now - self.d.timedelta(hours=10))
        self.assertEqual(first, self.now + self.d.timedelta(minutes=tasks.SLOW_LANE_START_DELAY_MIN))

    def test_recent_run_keeps_its_hourly_rhythm(self):
        last = self.now - self.d.timedelta(minutes=20)
        self.assertEqual(self._first(last=last), last + self.d.timedelta(minutes=60))

    def test_never_run_starts_shortly(self):
        self.assertEqual(self._first(last=None),
                         self.now + self.d.timedelta(minutes=tasks.SLOW_LANE_START_DELAY_MIN))

    def test_database_error_falls_back_to_one_interval(self):
        self.assertEqual(self._first(exc=RuntimeError('db down')), self.now + self.d.timedelta(minutes=60))

    def test_registered_with_a_first_run_time(self):
        with mock.patch.object(tasks, 'BackgroundScheduler', _FakeScheduler), \
             mock.patch.object(tasks, '_patch_apscheduler_for_python312', lambda: None), \
             mock.patch.object(tasks, '_scheduler', None), \
             mock.patch.object(tasks, '_last_slow_run_start', return_value=None):
            tasks.start_scheduler()
            kw = tasks._scheduler.cfg['softech_sync_slow'][1]
        self.assertIn('next_run_time', kw)
        self.assertGreater(kw['next_run_time'], self.now)
