"""
apps/tests/test_hr_attendance_lg_ingest.py

Linked Gates punches/reference ingest: versioned storage, idempotent resends, re-read removal.
"""
import datetime as _dt
import json

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.hr.attendance import agent_auth, lg_ingest, resolve
from apps.hr.models import (AttendanceAgent, AttendanceDevice, Employee, LinkedGatesDevice,
                            LinkedGatesEmployee, LinkedGatesPunch)
from apps.notifications.models import Notification
from apps.tests.factories import make_user

SECRET = 'test-agent-secret'
HEADER = 'HTTP_X_ELR_ATTENDANCE_AGENT'
PREFIX = '/api/hr-attendance/agent/lg/'
TODAY = _dt.date(2026, 11, 20)


def row(check_id=1, enroll_no=1001, check_time='2026-11-10T09:00:00', device=5, mode=0):
    return {'lg_check_id': check_id, 'enroll_no': enroll_no, 'in_out_mode': mode, 'check_time': check_time,
            'lg_device_id': device, 'created_by': None, 'edit_by': None, 'edit_on': None}


class StoreTests(TestCase):

    def store(self, rows, reread=False, window=None):
        return lg_ingest.store_lg_punches(rows, reread, today=TODAY, window=window)

    @staticmethod
    def win(from_id, to_id, since='2026-10-01T00:00:00'):
        return {'from_id': from_id, 'to_id': to_id, 'since': since}

    def test_new_rows_inserted(self):
        out = self.store([row(1), row(2, check_time='2026-11-10T17:00:00')])
        self.assertEqual(out, {'new': 2, 'versioned': 0, 'unchanged': 0, 'removed': 0, 'skipped': 0})
        p = LinkedGatesPunch.objects.get(lg_check_id=1)
        self.assertEqual((p.version, p.flag), (1, ''))
        self.assertEqual(timezone.localtime(p.check_time).isoformat(), '2026-11-10T09:00:00+02:00')

    def test_employee_resolved_by_enroll_no(self):
        emp = Employee.objects.create(name_ar='م', hr_number='1001')
        self.store([row(1, 1001), row(2, 9999)])
        self.assertEqual(LinkedGatesPunch.objects.get(lg_check_id=1).employee_id, emp.pk)
        self.assertIsNone(LinkedGatesPunch.objects.get(lg_check_id=2).employee_id)

    def test_resend_is_idempotent(self):
        rows = [row(1), row(2), row(3)]
        self.store(rows)
        out = self.store(rows)
        self.assertEqual(out['unchanged'], 3)
        self.assertEqual(out['new'] + out['versioned'], 0)
        self.assertEqual(LinkedGatesPunch.objects.count(), 3)

    def test_edited_row_supersedes(self):
        self.store([row(1)])
        out = self.store([row(1, check_time='2026-11-10T09:30:00')])
        self.assertEqual(out['versioned'], 1)
        versions = list(LinkedGatesPunch.objects.filter(lg_check_id=1).order_by('version'))
        self.assertEqual([v.version for v in versions], [1, 2])
        self.assertIsNotNone(versions[0].superseded_at)
        self.assertIsNone(versions[1].superseded_at)
        self.assertEqual(timezone.localtime(versions[1].check_time).isoformat(), '2026-11-10T09:30:00+02:00')

    def test_reread_marks_removed(self):
        self.store([row(1), row(2, check_time='2026-11-10T10:00:00'), row(3, check_time='2026-11-10T11:00:00')])
        out = self.store([row(1), row(3, check_time='2026-11-10T11:00:00')], reread=True,
                         window=self.win(0, 3))
        self.assertEqual(out['removed'], 1)
        self.assertTrue(LinkedGatesPunch.objects.get(lg_check_id=2).lg_removed)
        self.assertFalse(LinkedGatesPunch.objects.get(lg_check_id=1).lg_removed)

    def test_reread_without_window_is_malformed(self):
        with self.assertRaises(lg_ingest.Malformed):
            self.store([row(1)], reread=True)
        with self.assertRaises(lg_ingest.Malformed):
            self.store([row(1)], reread=True, window={'from_id': 'x', 'to_id': None, 'since': 'y'})

    def test_no_reread_keeps_missing_rows(self):
        self.store([row(1), row(2), row(3)])
        self.assertEqual(self.store([row(1), row(3)])['removed'], 0)

    def test_reread_ignores_rows_outside_window(self):
        self.store([row(1), row(50, check_time='2026-11-12T09:00:00'),
                    row(15, check_time='2026-09-01T09:00:00')])
        out = self.store([row(10, check_time='2026-11-10T09:00:00'), row(20, check_time='2026-11-11T09:00:00')],
                         reread=True, window=self.win(5, 20))
        # 1 is below from_id, 50 above to_id, 15 before `since`: none is touched
        self.assertEqual(out['removed'], 0)

    def test_row_deleted_between_two_reread_batches_is_removed(self):
        self.store([row(i, check_time='2026-11-10T09:00:00') for i in (1, 2, 3, 4, 5, 6)])
        # batch 1 covers ids up to 3, batch 2 ids 3..6 (shared edge); id 3, the edge row, is gone
        first = self.store([row(1), row(2)], reread=True, window=self.win(0, 3))
        second = self.store([row(4), row(5), row(6)], reread=True, window=self.win(3, 6))
        self.assertEqual((first['removed'], second['removed']), (1, 0))
        self.assertEqual(list(LinkedGatesPunch.objects.filter(lg_removed=True)
                              .values_list('lg_check_id', flat=True)), [3])

    def test_row_deleted_after_last_batch_removed_by_empty_final_batch(self):
        self.store([row(1), row(2), row(3)])
        self.store([row(1), row(2)], reread=True, window=self.win(0, 2))
        out = self.store([], reread=True, window=self.win(2, None))
        self.assertEqual(out['removed'], 1)
        self.assertTrue(LinkedGatesPunch.objects.get(lg_check_id=3).lg_removed)

    def test_superseded_versions_never_touched_by_reread(self):
        self.store([row(1)])
        self.store([row(1, check_time='2026-11-10T09:30:00')])
        self.store([], reread=True, window=self.win(0, None))     # row 1 absent: v2 removed, v1 untouched
        v1, v2 = LinkedGatesPunch.objects.filter(lg_check_id=1).order_by('version')
        self.assertFalse(v1.lg_removed)
        self.assertTrue(v2.lg_removed)

    def test_removed_row_reappearing_is_revived(self):
        self.store([row(1)])
        self.store([], reread=True, window=self.win(0, None))
        self.assertTrue(LinkedGatesPunch.objects.get().lg_removed)
        out = self.store([row(1)])
        self.assertEqual(out['unchanged'], 1)
        self.assertFalse(LinkedGatesPunch.objects.get().lg_removed)

    def test_in_out_mode_change_makes_a_new_version(self):
        self.store([row(1, mode=0)])
        out = self.store([row(1, mode=1)])
        self.assertEqual(out['versioned'], 1)
        self.assertEqual(LinkedGatesPunch.objects.filter(lg_check_id=1).count(), 2)

    def test_unreadable_or_null_time_is_skipped_not_fatal(self):
        bad_null, bad_text = row(2), row(3)
        bad_null['check_time'] = None
        bad_text['check_time'] = 'garbage'
        out = self.store([row(1), bad_null, bad_text])
        self.assertEqual((out['new'], out['skipped']), (1, 2))
        self.assertEqual(LinkedGatesPunch.objects.count(), 1)

    def test_wrong_json_type_still_malformed(self):
        wrong = row(2)
        wrong['check_time'] = 12345
        with self.assertRaises(lg_ingest.Malformed):
            self.store([row(1), wrong])
        self.assertEqual(LinkedGatesPunch.objects.count(), 0)

    def test_employee_added_after_punches_is_linked_by_resolver(self):
        self.store([row(1, 1001)])
        self.assertIsNone(LinkedGatesPunch.objects.get().employee_id)
        emp = Employee.objects.create(name_ar='م', hr_number='1001')
        resolve.resolve_user_code('1001')
        self.assertEqual(LinkedGatesPunch.objects.get().employee_id, emp.pk)

    def test_recycled_number_links_only_punches_inside_employment_dates(self):
        emp = Employee.objects.create(name_ar='م', hr_number='1001', start_date=_dt.date(2026, 11, 5),
                                      end_date=_dt.date(2026, 11, 20))
        self.store([
            row(1, check_time='2026-10-20T09:00:00'),     # the previous holder's era
            row(2, check_time='2026-11-04T23:00:00'),     # before start_date
            row(3, check_time='2026-11-05T02:00:00'),     # before the 04:00 boundary: work date 11-04
            row(4, check_time='2026-11-05T09:00:00'),     # first day: in
            row(5, check_time='2026-11-10T09:00:00'),     # in
        ])
        linked = {p.lg_check_id: p.employee_id for p in LinkedGatesPunch.objects.all()}
        self.assertEqual(linked, {1: None, 2: None, 3: None, 4: emp.pk, 5: emp.pk})
        # ending the employment unlinks later punches on the next resolve
        emp.end_date = _dt.date(2026, 11, 8)
        emp.save()
        resolve.resolve_user_code('1001')
        linked = {p.lg_check_id: p.employee_id for p in LinkedGatesPunch.objects.all()}
        self.assertEqual(linked, {1: None, 2: None, 3: None, 4: emp.pk, 5: None})

    def test_bad_date_flagged(self):
        self.store([row(1, check_time='2116-11-10T09:00:00'), row(2, check_time='2010-01-01T09:00:00'), row(3)])
        flags = dict(LinkedGatesPunch.objects.values_list('lg_check_id', 'flag'))
        self.assertEqual(flags, {1: 'bad_date', 2: 'bad_date', 3: ''})

    def test_malformed_row_refused_whole(self):
        with self.assertRaises(lg_ingest.Malformed):
            self.store([row(1), {'lg_check_id': 'x'}])
        self.assertEqual(LinkedGatesPunch.objects.count(), 0)


class ReferenceTests(TestCase):

    def ref(self, devices, employees=(), departments=()):
        return lg_ingest.store_lg_reference(
            {'devices': list(devices), 'employees': list(employees), 'departments': list(departments)})

    @staticmethod
    def dev(i, ip, name='d'):
        return {'lg_device_id': i, 'name': name, 'ip': ip, 'status': True}

    def test_unique_ip_automapped(self):
        ours = AttendanceDevice.objects.create(serial='S1', name='a', ip='192.168.30.15')
        self.ref([self.dev(1, '192.168.30.15')])
        self.assertEqual(LinkedGatesDevice.objects.get(lg_device_id=1).device_id, ours.pk)

    def test_duplicate_ip_not_automapped(self):
        AttendanceDevice.objects.create(serial='S1', name='a', ip='192.168.30.15')
        self.ref([self.dev(1, '192.168.30.15'), self.dev(2, '192.168.30.15')])
        self.assertEqual(list(LinkedGatesDevice.objects.values_list('device', flat=True)), [None, None])

    def test_employees_upserted_with_department_name(self):
        emp = {'lg_employee_id': 7, 'enroll_no': 1001, 'hr_code': 'H1', 'first_name': 'أ', 'last_name': 'ب',
               'department_id': 3, 'shift_type': 1, 'is_manager': False, 'status': True}
        for _ in range(2):
            out = self.ref([], [emp], [{'department_id': 3, 'name': 'الصيدلية'}])
        self.assertEqual(out['employees'], 1)
        self.assertEqual(LinkedGatesEmployee.objects.count(), 1)
        self.assertEqual(LinkedGatesEmployee.objects.get().department_name, 'الصيدلية')

    def test_non_int_shift_type_stored_as_none(self):
        # A portal text/decimal shift type informs only: stored as None, the upload is not refused.
        base = {'lg_employee_id': 7, 'enroll_no': 1001, 'hr_code': 'H1', 'first_name': 'أ', 'last_name': 'ب',
                'department_id': 3, 'is_manager': False, 'status': True}
        out = self.ref([], [dict(base, shift_type='1'), dict(base, lg_employee_id=8, shift_type=None)])
        self.assertEqual(out['employees'], 2)
        self.assertEqual(list(LinkedGatesEmployee.objects.order_by('lg_employee_id')
                              .values_list('shift_type', flat=True)), [None, None])


class ClosedMachineAlertTests(TestCase):
    """New Linked Gates punches from a portal machine tied to one of ours marked closed alert HR once
    a day, the same alert a ZK punch from that machine raises."""

    TITLE = 'جهاز مغلق أرسل بصمات'

    def setUp(self):
        make_user('lg_alert_admin', role='admin')
        self.ours = AttendanceDevice.objects.create(serial='S1', name='a', ip='192.168.30.15', is_active=False)
        LinkedGatesDevice.objects.create(lg_device_id=5, name='d', ip='192.168.30.15', device=self.ours)

    def alerts(self):
        return Notification.objects.filter(notification_type='attendance_alert', title=self.TITLE)

    def store(self, rows):
        return lg_ingest.store_lg_punches(rows, False, today=TODAY)

    def test_new_punch_from_closed_machine_alerts_once_a_day(self):
        self.assertEqual(self.store([row(1)])['new'], 1)                 # stored, never refused
        self.assertEqual(self.alerts().count(), 1)
        self.store([row(2, check_time='2026-11-10T17:00:00')])           # same day: still one
        self.assertEqual(self.alerts().count(), 1)

    def test_resend_does_not_alert(self):
        AttendanceDevice.objects.filter(pk=self.ours.pk).update(is_active=True)
        self.store([row(1)])
        AttendanceDevice.objects.filter(pk=self.ours.pk).update(is_active=False)
        self.store([row(1)])                                             # unchanged: not a new punch
        self.assertFalse(self.alerts().exists())

    def test_open_or_unmapped_machine_does_not_alert(self):
        AttendanceDevice.objects.filter(pk=self.ours.pk).update(is_active=True)
        self.store([row(1), row(2, device=99)])
        self.assertFalse(self.alerts().exists())


@override_settings(HR_ATTENDANCE_ENABLED=True, HR_ATTENDANCE_LINKEDGATES_ENABLED=True)
class ViewTests(TestCase):

    def setUp(self):
        AttendanceAgent.objects.create(name='office', token_hash=agent_auth.hash_secret(SECRET))
        self.api = APIClient()
        self.api.credentials(**{HEADER: SECRET})

    def post(self, endpoint, body, client=None):
        return (client or self.api).post(f'{PREFIX}{endpoint}/', json.dumps(body), content_type='application/json')

    def test_punches_endpoint(self):
        r = self.post('punches', {'rows': [row(1, check_time='2026-11-10T09:00:00')], 'reread': False})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['new'], 1)

    def test_reread_endpoint_needs_window(self):
        self.assertEqual(self.post('punches', {'rows': [], 'reread': True}).status_code, 400)
        ok = self.post('punches', {'rows': [], 'reread': True,
                                   'window': {'from_id': 0, 'to_id': None, 'since': '2026-10-01T00:00:00'}})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()['skipped'], 0)

    def test_reference_endpoint(self):
        r = self.post('reference', {'devices': [], 'employees': [], 'departments': []})
        self.assertEqual(r.status_code, 200)

    def test_config_reports_switch(self):
        r = self.api.get('/api/hr-attendance/agent/config/')
        self.assertIs(r.json()['linkedgates'], True)

    def test_switch_off_returns_503(self):
        with override_settings(HR_ATTENDANCE_LINKEDGATES_ENABLED=False):
            self.assertEqual(self.post('punches', {'rows': [], 'reread': False}).status_code, 503)
            self.assertEqual(self.post('reference', {}).status_code, 503)
            self.assertIs(self.api.get('/api/hr-attendance/agent/config/').json()['linkedgates'], False)

    def test_wrong_agent_secret_401(self):
        bad = APIClient()
        bad.credentials(**{HEADER: 'nope'})
        self.assertEqual(self.post('punches', {'rows': [], 'reread': False}, client=bad).status_code, 401)

    def test_over_limit_413(self):
        rows = [row(i) for i in range(lg_ingest.MAX_LG_ROWS_PER_REQUEST + 1)]
        self.assertEqual(self.post('punches', {'rows': rows, 'reread': False}).status_code, 413)
