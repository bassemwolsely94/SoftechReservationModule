"""
apps/tests/test_hr_attendance_end_to_end.py

HR Attendance stage 1: the whole chain with nothing faked in the middle. The real agent collector
(collect_device, AgentLoop, spool, drain) reads a fake machine, and a real HTTP client carries its
files to the real agent endpoints (ingest.store_run, punch storage), and then the real
check_attendance_health looks at what was stored.

Why this exists: every worker's tests used their own numbers, so the agent's `spool_waiting` (which
counted the run's own files) and the server's alert (which treated any waiting file as a problem)
were each right on their own and wrong together. Here, three healthy hourly runs must raise no
alert, and a file that really stays behind must.

Time is simulated: `timezone.now` moves one hour per pass, and the agent's PC clock follows it.
"""
import datetime as _dt
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.hr.attendance import agent_auth, health
from apps.hr.models import (AttendanceAccess, AttendanceAgent, AttendanceDevice, AttendancePunch,
                            CollectionRun)
from apps.notifications.models import Notification
from apps.tests.factories import make_branch, make_user
from apps.tests.test_attendance_agent_loop import FakeClient
from attendance_agent.collector import AgentLoop
from attendance_agent.spool import Spool
from attendance_agent.uploader import UploadError, Uploader
from attendance_agent.zk_client import DeviceUserRow, LogRow

SECRET = 'e2e-agent-secret'
HEADER = 'HTTP_X_ELR_ATTENDANCE_AGENT'
PREFIX = '/api/hr-attendance/agent/'
HOUR = _dt.timedelta(hours=1)


class InProcessUploader:
    """The agent's Uploader interface, carried by the Django test client to the real endpoints.
    Refusals map to UploadError exactly as the real Uploader maps them."""

    def __init__(self, api):
        self.api = api

    def get_config(self):
        response = self.api.get(f'{PREFIX}config/')
        if response.status_code != 200:
            raise UploadError(f'HTTP {response.status_code}')
        return response.json()

    def send(self, kind, payload):
        response = self.api.post(f'{PREFIX}{kind}/', json.dumps(payload), content_type='application/json')
        code = response.status_code
        if code >= 300:
            raise UploadError(f'HTTP {code}', permanent=400 <= code < 500 and code not in (401, 408, 429))
        answer = response.json()
        if kind == 'punches':
            Uploader._check_counts(answer, len(payload['punches']))


class ClockedClient(FakeClient):
    """A machine whose own clock is exactly the true (simulated) time."""

    def __init__(self, truth, **kw):
        super().__init__(**kw)
        self._truth = truth

    def read_time(self):
        self.calls.append('time')
        return self._truth()


@override_settings(HR_ATTENDANCE_ENABLED=True)
class EndToEndBase(TestCase):
    pc_skew = _dt.timedelta(0)      # how far behind the true time the agent PC's clock runs

    def setUp(self):
        # The agent sends naive local time and the server reads it in its current zone, so both
        # sides use the machine's own zone here; the offset arithmetic is then exact anywhere.
        timezone.activate(_dt.datetime.now().astimezone().tzinfo)
        self.addCleanup(timezone.deactivate)

        self.sim = timezone.now().replace(microsecond=0) - _dt.timedelta(hours=1)
        patch = mock.patch('django.utils.timezone.now', side_effect=lambda: self.sim)
        patch.start()
        self.addCleanup(patch.stop)

        branch = make_branch('فرع أ', 'B01')
        _, self.admin_p, _ = make_user('e2e_admin', role='admin', branch=branch)
        _, self.mgr_p, _ = make_user('e2e_mgr', role='pharmacist', branch=branch)
        _, self.viewer_p, _ = make_user('e2e_view', role='pharmacist', branch=branch)
        AttendanceAccess.objects.create(staff=self.mgr_p, level='manage', granted_by=self.admin_p)
        AttendanceAccess.objects.create(staff=self.viewer_p, level='view', granted_by=self.admin_p)

        self.agent = AttendanceAgent.objects.create(name='PC الإدارة', token_hash=agent_auth.hash_secret(SECRET))
        self.device = AttendanceDevice.objects.create(
            serial='SN1', name='ماكينة الفرع', ip='192.168.3.15', agent=self.agent)
        api = APIClient()
        api.credentials(**{HEADER: SECRET})
        self.uploader = InProcessUploader(api)

        self.root = Path(tempfile.mkdtemp(prefix='attendance-e2e-'))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.spool = Spool(self.root / 'spool')
        self.monotonic = 0
        self.log = []
        self.loop = AgentLoop(
            uploader=self.uploader, spool=self.spool, client_factory=self.client_factory,
            now=self.pc_now, clock=lambda: self.monotonic, cache_path=self.root / 'devices.json')

    # the agent PC's naive local clock, as datetime.now() would give it
    def pc_now(self):
        return (self.sim - self.pc_skew).astimezone().replace(tzinfo=None)

    def true_naive_now(self):
        return self.sim.astimezone().replace(tzinfo=None)

    def client_factory(self, target):
        return ClockedClient(
            self.true_naive_now, serial=target['serial'], logs=list(self.log),
            users=[DeviceUserRow('1001', 'SamerSami', False)])

    def punch_now(self, code='1001'):
        """The machine records a punch at the simulated time."""
        local = self.sim.astimezone()
        self.log.append(LogRow(code, int(self.sim.timestamp()), local.date(), local.time().replace(microsecond=0),
                               4, 1))

    def hour(self):
        """One hourly pass: time moves on, the machine takes a punch, the agent runs."""
        self.sim += HOUR
        self.monotonic += 3600
        self.punch_now()
        self.loop.tick()

    def alerts(self):
        return health.check_attendance_health(now=self.sim)['alerts']

    def kinds(self):
        return sorted(a['kind'] for a in self.alerts())

    def notifications(self):
        return Notification.objects.filter(notification_type='attendance_alert')


class HealthyChainTests(EndToEndBase):

    def test_three_healthy_hourly_runs_raise_no_alert(self):
        for _ in range(3):
            self.hour()
            self.assertEqual(self.kinds(), [], 'a healthy run must not alert')
        self.assertEqual(self.notifications().count(), 0)

        runs = list(CollectionRun.objects.filter(device=self.device).order_by('started_at'))
        self.assertEqual(len(runs), 3)
        self.assertEqual([r.status for r in runs], ['success'] * 3)
        self.assertEqual([r.spool_waiting for r in runs], [0, 0, 0])
        self.assertEqual([r.drift_seconds for r in runs], [0, 0, 0])
        self.assertEqual([r.device_log_count for r in runs], [1, 2, 3])
        self.assertEqual(AttendancePunch.objects.filter(device=self.device).count(), 3)
        self.assertEqual(self.spool.pending(), [])
        self.device.refresh_from_db()
        self.assertEqual(self.device.last_status, 'success')

    def test_the_machine_lists_the_same_after_many_hours(self):
        for _ in range(6):
            self.hour()
        self.assertEqual(self.kinds(), [])
        self.assertEqual(AttendancePunch.objects.filter(device=self.device).count(), 6)


class StuckFileTests(EndToEndBase):
    """One punch file the server refuses for good (a code longer than any machine writes) stays on
    the agent's disk while every run still looks healthy."""

    def test_a_file_that_stays_stuck_alerts_after_three_hours(self):
        self.sim += HOUR
        self.monotonic += 3600
        self.punch_now(code='9' * 40)          # the server refuses this whole batch
        self.punch_now(code='1001')
        self.loop.tick()
        self.assertEqual(len(self.spool.pending()), 1, 'the refused punch file stays on disk')
        self.assertEqual(self.kinds(), [])
        seen = {}
        for step in range(1, 5):
            self.hour()
            seen[step] = self.kinds()
        # the first run left nothing behind; the file shows from the second run on
        self.assertEqual([seen[1], seen[2], seen[3]], [[], [], []])     # waiting for under 3 hours
        self.assertEqual(seen[4], ['spool_waiting'])                    # 3 hours
        runs = list(CollectionRun.objects.filter(device=self.device).order_by('started_at'))
        self.assertEqual([r.spool_waiting for r in runs], [0, 1, 1, 1, 1])
        self.assertGreaterEqual(self.notifications().filter(recipient=self.admin_p).count(), 1)
        self.assertEqual(self.notifications().filter(recipient=self.viewer_p).count(), 0)
        # the other punches still arrived, so only the refused file is behind
        self.assertEqual(AttendancePunch.objects.filter(device=self.device).count(), 4)

    def test_another_machines_stuck_file_does_not_alert_this_one(self):
        other = AttendanceDevice.objects.create(serial='SN2', name='ماكينة أخرى', ip='192.168.3.16',
                                              agent=self.agent)
        # SN2's agent files are refused; SN1's are not
        original = self.uploader.send

        def refuse_sn2(kind, payload):
            if kind == 'punches' and payload['device_serial'] == 'SN2':
                raise UploadError('HTTP 400', permanent=True)
            return original(kind, payload)

        self.uploader.send = refuse_sn2
        self.loop._uploader = self.uploader
        for _ in range(5):
            self.hour()
        by_device = {}
        for run in CollectionRun.objects.order_by('started_at'):
            by_device.setdefault(run.device.serial, []).append(run.spool_waiting)
        self.assertEqual(by_device['SN1'], [0] * 5)
        self.assertEqual(by_device['SN2'], [0, 1, 2, 3, 4])    # a new refused file each hour
        self.assertEqual(self.kinds(), ['spool_waiting'])
        # the alert names SN2's machine only
        titles = ' '.join(self.notifications().values_list('title', flat=True))
        self.assertIn(other.name, titles)
        self.assertNotIn(self.device.name, titles)


class PcClockChainTests(EndToEndBase):
    pc_skew = _dt.timedelta(hours=2)

    def test_a_wrong_pc_clock_is_reported_as_the_pc_not_as_every_machine(self):
        for _ in range(2):
            self.hour()
        runs = list(CollectionRun.objects.filter(device=self.device).order_by('started_at'))
        self.assertEqual([r.pc_offset_seconds for r in runs], [7200, 7200])
        # times are the server's, and the (correct) machine clock shows no drift
        self.assertEqual([r.drift_seconds for r in runs], [0, 0])
        self.assertEqual(runs[-1].started_at, self.sim)
        self.device.refresh_from_db()
        self.assertEqual(self.device.last_drift_seconds, 0)
        self.assertEqual(self.kinds(), ['pc_clock'])
