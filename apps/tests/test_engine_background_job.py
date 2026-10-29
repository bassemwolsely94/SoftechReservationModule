"""
The dashboard's engine buttons run in their own process (owner 2026-10-26) — a web-server
restart used to kill the in-process thread mid-run (apps/purchasing/background.py).
"""
from datetime import timedelta
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.purchasing import background
from apps.purchasing.models import DemandCalculationRun
from apps.purchasing.views import INTERRUPTED_MESSAGE
from apps.tests.factories import make_admin


class ButtonsLaunchSeparateProcessTests(TestCase):
    def setUp(self):
        _u, _p, self.client = make_admin()

    def test_quick_run_creates_run_and_launches_job(self):
        with mock.patch.object(background, 'launch', return_value=123) as launch:
            r = self.client.post('/api/purchasing/trigger/', {}, format='json')
        self.assertEqual(r.status_code, 202)
        run = DemandCalculationRun.objects.get()
        self.assertEqual((r.data['id'], run.status), (run.pk, 'running'))
        launch.assert_called_once_with('quick', run.pk, {})

    def test_full_sync_launches_full_job_with_catalog_phase(self):
        with mock.patch.object(background, 'launch', return_value=123) as launch:
            r = self.client.post('/api/purchasing/trigger/', {'full': True}, format='json')
        self.assertEqual(r.status_code, 202)
        run = DemandCalculationRun.objects.get()
        self.assertEqual(run.progress['phase'], 'catalog')
        launch.assert_called_once_with('full', run.pk, {})

    def test_catchup_launches_catchup_job(self):
        with mock.patch('apps.purchasing.catchup.softech_reachable', return_value=True), \
             mock.patch.object(background, 'launch', return_value=123) as launch:
            r = self.client.post('/api/purchasing/catchup/')
        self.assertEqual(r.status_code, 202)
        launch.assert_called_once_with('catchup', DemandCalculationRun.objects.get().pk, None)

    def test_launch_failure_fails_the_run_instead_of_leaving_it_running(self):
        with mock.patch.object(background, 'launch', side_effect=OSError('no python')):
            r = self.client.post('/api/purchasing/trigger/', {}, format='json')
        self.assertEqual(r.status_code, 503)
        run = DemandCalculationRun.objects.get()
        self.assertEqual(run.status, 'failed')
        self.assertIn('no python', run.error_message)

    def test_second_run_refused_while_one_runs(self):
        DemandCalculationRun.objects.create(status='running')
        with mock.patch.object(background, 'launch') as launch:
            r = self.client.post('/api/purchasing/trigger/', {}, format='json')
        self.assertEqual(r.status_code, 409)
        launch.assert_not_called()


class LaunchTests(TestCase):
    def test_command_line(self):
        with mock.patch('subprocess.Popen') as popen:
            popen.return_value.pid = 77
            self.assertEqual(background.launch('full', 5, {'weight_30d': 0.6}), 77)
        cmd = popen.call_args.args[0]
        self.assertEqual(cmd[2:7], ['run_engine_job', '--mode', 'full', '--run', '5'])
        self.assertEqual(cmd[7:], ['--params', '{"weight_30d": 0.6}'])

    def test_unknown_mode_refused(self):
        with self.assertRaises(ValueError):
            background.launch('rm', 1)


class RunEngineJobCommandTests(TestCase):
    def test_quick_drives_the_existing_run(self):
        run = DemandCalculationRun.objects.create(status='running')
        with mock.patch('apps.purchasing.engine.DemandEngine') as engine:
            call_command('run_engine_job', mode='quick', run=run.pk)
        engine.return_value.run.assert_called_once_with(full_backfill=False, existing_run=mock.ANY)
        self.assertEqual(engine.return_value.run.call_args.kwargs['existing_run'].pk, run.pk)

    def test_error_fails_the_run(self):
        run = DemandCalculationRun.objects.create(status='running')
        with mock.patch('apps.purchasing.engine.DemandEngine') as engine, self.assertRaises(SystemExit):
            engine.return_value.run.side_effect = RuntimeError('boom')
            call_command('run_engine_job', mode='quick', run=run.pk)
        run.refresh_from_db()
        self.assertEqual((run.status, run.error_message), ('failed', 'boom'))

    def test_finished_run_is_left_alone(self):
        run = DemandCalculationRun.objects.create(status='failed')
        with mock.patch('apps.purchasing.engine.DemandEngine') as engine:
            call_command('run_engine_job', mode='quick', run=run.pk)
        engine.assert_not_called()


class WatchdogMessageTests(TestCase):
    def test_silent_run_reported_as_interrupted(self):
        run = DemandCalculationRun.objects.create(status='running')
        DemandCalculationRun.objects.filter(pk=run.pk).update(updated_at=timezone.now() - timedelta(minutes=25))
        _u, _p, client = make_admin()
        self.assertEqual(client.get('/api/purchasing/runs/active/').status_code, 404)
        run.refresh_from_db()
        self.assertEqual((run.status, run.error_message), ('failed', INTERRUPTED_MESSAGE))
        self.assertIn('توقف التشغيل قبل اكتماله', run.error_message)
