"""Scheduler registration (doc 30, F7): every job function is scheduled once, and
every job runs under its own telemetry scope."""
from collections import Counter
from unittest import mock

from django.test import SimpleTestCase

from apps.sync import tasks


class _FakeScheduler:
    def __init__(self, *a, **kw):
        self.jobs = []
        self.running = False

    def add_job(self, func, trigger, *args, **kwargs):
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
            return tasks._scheduler.jobs

    def test_no_job_function_registered_twice_on_the_same_cadence(self):
        jobs = self._jobs()
        self.assertGreater(len(jobs), 40)
        ids = Counter(j[1] for j in jobs)
        self.assertEqual([i for i, n in ids.items() if n > 1], [])
        for name in ('_flush_pos_orders', '_reconcile_pos_orders'):
            with self.subTest(job=name):
                self.assertEqual(sum(1 for f, _, _ in jobs if f.__name__ == name), 1)

    def test_pos_jobs_keep_their_ids(self):
        ids = {j[1] for j in self._jobs()}
        self.assertTrue({'pos_orders_flush', 'pos_orders_reconcile'} <= ids)
        self.assertFalse({'pos_flush_queued', 'pos_reconcile'} & ids)

    def test_every_job_runs_under_its_scope(self):
        for real, jid, wrapped in self._jobs():
            with self.subTest(job=jid):
                self.assertIs(wrapped.__wrapped__, real)
