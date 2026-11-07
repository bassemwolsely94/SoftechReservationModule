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
