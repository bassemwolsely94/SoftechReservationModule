"""
apps/tests/test_hr_attendance_health.py

HR Attendance stage 1, Task 9: alerts to the HR head when a machine or the collection agent goes
quiet, a clock drifts, or a machine's log count falls (evidence that logs were cleared).
"""
import datetime as _dt
import hashlib

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.hr.attendance import health
from apps.hr.models import AttendanceAccess, AttendanceAgent, AttendanceDevice, CollectionRun
from apps.notifications.models import Notification
from apps.tests.factories import make_branch, make_user

NOW = timezone.make_aware(_dt.datetime(2026, 11, 7, 12, 0))


def ago(**kw):
    return NOW - _dt.timedelta(**kw)


@override_settings(HR_ATTENDANCE_ENABLED=True)
class HealthBase(TestCase):

    def setUp(self):
        b = make_branch('فرع أ', 'B01')
        _, self.admin_p, _ = make_user('hh_admin', role='admin', branch=b)
        _, self.mgr_p, _ = make_user('hh_mgr', role='pharmacist', branch=b)
        _, self.viewer_p, _ = make_user('hh_view', role='pharmacist', branch=b)
        AttendanceAccess.objects.create(staff=self.mgr_p, level='manage', granted_by=self.admin_p)
        AttendanceAccess.objects.create(staff=self.viewer_p, level='view', granted_by=self.admin_p)
        self.agent = AttendanceAgent.objects.create(
            name='PC الإدارة', token_hash=hashlib.sha256(b'x').hexdigest(), last_seen_at=ago(minutes=5))
        self.dev = AttendanceDevice.objects.create(
            serial='SN1', name='ماكينة الفرع', agent=self.agent, last_contact_at=ago(minutes=30))

    def alerts(self, who=None):
        qs = Notification.objects.filter(notification_type='attendance_alert')
        return qs.filter(recipient=who) if who else qs

    def run_rec(self, count, status='success', **kw):
        return CollectionRun.objects.create(
            device=self.dev, agent=self.agent, started_at=kw.pop('started_at', ago(minutes=1)),
            device_log_count=count, status=status, **kw)


class SilenceTests(HealthBase):

    def test_machine_silent_24h_alerts(self):
        self.dev.last_contact_at = ago(hours=24, minutes=1)
        self.dev.save()
        health.check_attendance_health(now=NOW)
        self.assertEqual(self.alerts(self.admin_p).count(), 1)

    def test_machine_silent_not_at_23h(self):
        self.dev.last_contact_at = ago(hours=23)
        self.dev.save()
        health.check_attendance_health(now=NOW)
        self.assertEqual(self.alerts().count(), 0)

    def test_agent_silent_3h_alerts(self):
        self.agent.last_seen_at = ago(hours=3, minutes=1)
        self.agent.save()
        health.check_attendance_health(now=NOW)
        self.assertEqual(self.alerts(self.admin_p).count(), 1)

    def test_agent_silent_not_at_2h59(self):
        self.agent.last_seen_at = ago(hours=2, minutes=59)
        self.agent.save()
        health.check_attendance_health(now=NOW)
        self.assertEqual(self.alerts().count(), 0)

    def test_revoked_agent_no_alert(self):
        self.agent.last_seen_at = ago(hours=9)
        self.agent.revoked_at = ago(hours=1)
        self.agent.save()
        health.check_attendance_health(now=NOW)
        self.assertEqual(self.alerts().count(), 0)

    def test_inactive_device_no_alert(self):
        self.dev.last_contact_at = ago(days=5)
        self.dev.last_drift_seconds = 9000
        self.dev.is_active = False
        self.dev.save()
        health.check_attendance_health(now=NOW)
        self.assertEqual(self.alerts().count(), 0)


class DriftTests(HealthBase):

    def test_drift_over_5_min_alerts(self):
        self.dev.last_drift_seconds = 301
        self.dev.save()
        health.check_attendance_health(now=NOW)
        self.assertEqual(self.alerts(self.admin_p).count(), 1)

    def test_negative_drift_over_5_min_alerts(self):
        self.dev.last_drift_seconds = -400
        self.dev.save()
        health.check_attendance_health(now=NOW)
        self.assertEqual(self.alerts(self.admin_p).count(), 1)

    def test_silent_machine_does_not_repeat_its_stale_drift(self):
        self.dev.last_drift_seconds = 900
        self.dev.last_contact_at = ago(days=2)
        self.dev.save()
        result = health.check_attendance_health(now=NOW)
        self.assertEqual([a['kind'] for a in result['alerts']], ['silent_device'])

    def test_drift_not_at_300_seconds_exactly(self):
        self.dev.last_drift_seconds = 300
        self.dev.save()
        health.check_attendance_health(now=NOW)
        self.assertEqual(self.alerts().count(), 0)


class LogCountTests(HealthBase):

    def test_log_count_fall_alerts(self):
        self.run_rec(3906, started_at=ago(hours=2))
        self.run_rec(120, started_at=ago(hours=1))
        health.check_attendance_health(now=NOW)
        self.assertEqual(self.alerts(self.admin_p).count(), 1)

    def test_log_count_rise_does_not_alert(self):
        self.run_rec(3906, started_at=ago(hours=2))
        self.run_rec(3950, started_at=ago(hours=1))
        health.check_attendance_health(now=NOW)
        self.assertEqual(self.alerts().count(), 0)

    def test_failed_run_does_not_count_as_fall(self):
        self.run_rec(3906, started_at=ago(hours=3))
        self.run_rec(0, status='failed', started_at=ago(hours=2))
        self.run_rec(3920, started_at=ago(hours=1))
        health.check_attendance_health(now=NOW)
        self.assertEqual(self.alerts().count(), 0)

    def test_run_without_count_is_skipped(self):
        self.run_rec(3906, started_at=ago(hours=3))
        self.run_rec(None, started_at=ago(hours=2))
        self.run_rec(3910, started_at=ago(hours=1))
        health.check_attendance_health(now=NOW)
        self.assertEqual(self.alerts().count(), 0)

    def test_one_fall_alerts_once_even_if_checked_again_next_day(self):
        self.run_rec(3906, started_at=ago(hours=2))
        self.run_rec(120, started_at=ago(hours=1))
        health.check_attendance_health(now=NOW)
        health.check_attendance_health(now=NOW + _dt.timedelta(days=1))
        self.assertEqual(self.alerts(self.admin_p).filter(title__contains='سجلات').count(), 1)


class DeliveryTests(HealthBase):

    def test_alert_deduped_per_day(self):
        self.dev.last_drift_seconds = 900
        self.dev.save()
        health.check_attendance_health(now=NOW)
        health.check_attendance_health(now=NOW + _dt.timedelta(hours=1))
        self.assertEqual(self.alerts(self.admin_p).count(), 1)

    def test_alert_repeats_next_day(self):
        self.dev.last_drift_seconds = 900
        self.dev.save()
        health.check_attendance_health(now=NOW)
        tomorrow = NOW + _dt.timedelta(days=1)
        self.dev.last_contact_at = tomorrow - _dt.timedelta(minutes=5)   # still talking, still drifting
        self.dev.save()
        self.agent.last_seen_at = tomorrow - _dt.timedelta(minutes=5)
        self.agent.save()
        health.check_attendance_health(now=tomorrow)
        self.assertEqual(self.alerts(self.admin_p).count(), 2)

    def test_only_managers_receive(self):
        self.dev.last_drift_seconds = 900
        self.dev.save()
        health.check_attendance_health(now=NOW)
        self.assertEqual(self.alerts(self.admin_p).count(), 1)
        self.assertEqual(self.alerts(self.mgr_p).count(), 1)
        self.assertEqual(self.alerts(self.viewer_p).count(), 0)

    def test_alert_text_has_no_employee_names(self):
        from apps.hr.models import DeviceUser, Employee
        Employee.objects.create(hr_number='1001', name_ar='محمد علي الشريف')
        DeviceUser.objects.create(device=self.dev, user_code='1001', device_name='Mohamed Ali')
        self.dev.last_drift_seconds = 900
        self.dev.last_contact_at = ago(days=3)
        self.dev.save()
        health.check_attendance_health(now=NOW)
        text = ' '.join(f'{n.title} {n.body}' for n in self.alerts())
        self.assertTrue(text)
        self.assertNotIn('محمد', text)
        self.assertNotIn('Mohamed', text)
        self.assertIn('ماكينة الفرع', text)

    def test_switch_off_no_alerts(self):
        self.dev.last_drift_seconds = 900
        self.dev.save()
        with override_settings(HR_ATTENDANCE_ENABLED=False):
            result = health.check_attendance_health(now=NOW)
        self.assertEqual(self.alerts().count(), 0)
        self.assertEqual(result['alerts'], [])

    def test_result_lists_alerts(self):
        self.dev.last_drift_seconds = 900
        self.dev.save()
        result = health.check_attendance_health(now=NOW)
        self.assertEqual([a['kind'] for a in result['alerts']], ['drift'])


class SpoolWaitingTests(HealthBase):
    """The agent reports files left behind on its disk (CollectionRun.spool_waiting). A file the
    ERP refuses can sit there while every run looks healthy. The stored field is read as it is."""

    def kinds(self):
        return [a['kind'] for a in health.check_attendance_health(now=NOW)['alerts']]

    def test_waiting_for_3_hours_alerts(self):
        self.run_rec(100, started_at=ago(hours=3, minutes=5), spool_waiting=2)
        self.run_rec(100, started_at=ago(hours=2), spool_waiting=2)
        self.run_rec(100, started_at=ago(hours=1), spool_waiting=2)
        self.assertEqual(self.kinds(), ['spool_waiting'])
        self.assertEqual(self.alerts(self.admin_p).count(), 1)

    def test_cleared_field_clears_the_alert(self):
        self.run_rec(100, started_at=ago(hours=3, minutes=5), spool_waiting=2)
        self.run_rec(100, started_at=ago(hours=1), spool_waiting=2)
        self.assertEqual(self.kinds(), ['spool_waiting'])
        CollectionRun.objects.update(spool_waiting=0)
        self.assertEqual(self.kinds(), [])

    def test_waiting_for_under_3_hours_no_alert(self):
        self.run_rec(100, started_at=ago(hours=2, minutes=50), spool_waiting=2)
        self.run_rec(100, started_at=ago(hours=1), spool_waiting=2)
        self.assertEqual(self.kinds(), [])

    def test_cleared_spool_breaks_the_streak(self):
        self.run_rec(100, started_at=ago(hours=5), spool_waiting=3)
        self.run_rec(100, started_at=ago(hours=4), spool_waiting=0)
        self.run_rec(100, started_at=ago(hours=1), spool_waiting=3)
        self.assertEqual(self.kinds(), [])

    def test_agent_not_reporting_the_field_is_not_an_alarm(self):
        self.run_rec(100, started_at=ago(hours=5))
        self.run_rec(100, started_at=ago(hours=1))
        self.assertEqual(self.kinds(), [])

    def test_inactive_device_spool_no_alert(self):
        self.dev.is_active = False
        self.dev.save()
        self.run_rec(100, started_at=ago(hours=5), spool_waiting=2)
        self.run_rec(100, started_at=ago(hours=1), spool_waiting=2)
        self.assertEqual(self.kinds(), [])

    def test_healthy_hourly_runs_report_zero_and_never_alert(self):
        for hours in (6, 5, 4, 3, 2, 1):
            self.run_rec(100, started_at=ago(hours=hours), spool_waiting=0)
        self.assertEqual(self.kinds(), [])


class NeverSucceededTests(HealthBase):
    """A machine that never had a successful collection counts from its oldest run."""

    def setUp(self):
        super().setUp()
        self.dev.last_contact_at = None
        self.dev.save()

    def kinds(self):
        return [a['kind'] for a in health.check_attendance_health(now=NOW)['alerts']]

    def test_failing_for_over_24_hours_from_day_one_alerts(self):
        self.run_rec(None, status='failed', started_at=ago(hours=25))
        self.run_rec(None, status='failed', started_at=ago(hours=1))
        self.assertEqual(self.kinds(), ['silent_device'])
        self.assertEqual(self.alerts(self.admin_p).count(), 1)
        self.assertIn('لم ينجح أي تجميع', self.alerts(self.admin_p).get().body)

    def test_failing_for_under_24_hours_is_quiet(self):
        self.run_rec(None, status='failed', started_at=ago(hours=23))
        self.assertEqual(self.kinds(), [])

    def test_no_run_at_all_stays_quiet(self):
        self.assertEqual(self.kinds(), [])

    def test_unassigned_machine_stays_quiet(self):
        self.run_rec(None, status='failed', started_at=ago(hours=30))
        AttendanceDevice.objects.filter(pk=self.dev.pk).update(agent=None)
        self.assertEqual(self.kinds(), [])

    def test_inactive_machine_stays_quiet(self):
        self.run_rec(None, status='failed', started_at=ago(hours=30))
        AttendanceDevice.objects.filter(pk=self.dev.pk).update(is_active=False)
        self.assertEqual(self.kinds(), [])

    def test_once_it_succeeds_the_contact_time_governs(self):
        self.run_rec(None, status='failed', started_at=ago(hours=30))
        AttendanceDevice.objects.filter(pk=self.dev.pk).update(last_contact_at=ago(minutes=10))
        self.assertEqual(self.kinds(), [])


class LogFallBacklogTests(HealthBase):

    def test_a_fall_in_the_middle_of_a_backlog_is_seen(self):
        # after an outage, hours of runs arrive together: 100, 100, 5 (cleared), 8, 12
        for hours, count in ((5, 100), (4, 100), (3, 5), (2, 8), (1, 12)):
            self.run_rec(count, started_at=ago(hours=hours))
        result = health.check_attendance_health(now=NOW)
        self.assertEqual([a['kind'] for a in result['alerts']], ['log_fall'])
        self.assertEqual(self.alerts(self.admin_p).count(), 1)

    def test_every_fall_alerts_once(self):
        for hours, count in ((6, 100), (5, 50), (4, 60), (3, 20), (2, 25), (1, 25)):
            self.run_rec(count, started_at=ago(hours=hours))
        health.check_attendance_health(now=NOW)
        health.check_attendance_health(now=NOW + _dt.timedelta(hours=2))
        self.assertEqual(self.alerts(self.admin_p).count(), 2)

    def test_only_the_last_30_successful_runs_are_examined(self):
        self.run_rec(100, started_at=ago(hours=40))
        self.run_rec(1, started_at=ago(hours=39))     # a fall, but beyond the window
        for hours in range(30, 0, -1):
            self.run_rec(1, started_at=ago(hours=hours))
        self.assertEqual(health.check_attendance_health(now=NOW)['alerts'], [])


class PcClockTests(HealthBase):

    def kinds(self):
        return [a['kind'] for a in health.check_attendance_health(now=NOW)['alerts']]

    def test_pc_off_by_more_than_5_minutes_alerts_the_managers(self):
        self.run_rec(100, pc_offset_seconds=-3600)
        self.assertEqual(self.kinds(), ['pc_clock'])
        self.assertEqual(self.alerts(self.admin_p).count(), 1)
        self.assertEqual(self.alerts(self.mgr_p).count(), 1)
        self.assertEqual(self.alerts(self.viewer_p).count(), 0)
        self.assertIn(self.agent.name, self.alerts(self.admin_p).get().title)

    def test_pc_offset_of_5_minutes_exactly_is_fine(self):
        self.run_rec(100, pc_offset_seconds=300)
        self.assertEqual(self.kinds(), [])

    def test_runs_without_an_offset_say_nothing(self):
        self.run_rec(100)
        self.assertEqual(self.kinds(), [])

    def test_the_newest_report_decides(self):
        self.run_rec(100, started_at=ago(hours=3), pc_offset_seconds=-3600)
        self.run_rec(100, started_at=ago(hours=1), pc_offset_seconds=2)
        self.assertEqual(self.kinds(), [])

    def test_alert_repeats_daily_not_hourly(self):
        self.run_rec(100, pc_offset_seconds=900)
        health.check_attendance_health(now=NOW)
        health.check_attendance_health(now=NOW + _dt.timedelta(hours=1))
        self.assertEqual(self.alerts(self.admin_p).count(), 1)

    def test_silent_agent_reports_only_the_silence(self):
        self.run_rec(100, pc_offset_seconds=900)
        self.agent.last_seen_at = ago(hours=5)
        self.agent.save()
        self.assertEqual(self.kinds(), ['silent_agent'])
