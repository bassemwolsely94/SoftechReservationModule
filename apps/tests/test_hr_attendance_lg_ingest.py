"""
apps/tests/test_hr_attendance_lg_ingest.py

Linked Gates punches/reference ingest: versioned storage, idempotent resends, re-read removal.
"""
import datetime as _dt
import json

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.hr.attendance import agent_auth, lg_ingest
from apps.hr.models import (AttendanceAgent, AttendanceDevice, Employee, LinkedGatesDevice,
                            LinkedGatesEmployee, LinkedGatesPunch)

SECRET = 'test-agent-secret'
HEADER = 'HTTP_X_ELR_ATTENDANCE_AGENT'
PREFIX = '/api/hr-attendance/agent/lg/'
TODAY = _dt.date(2026, 11, 20)


def row(check_id=1, enroll_no=1001, check_time='2026-11-10T09:00:00', device=5, mode=0):
    return {'lg_check_id': check_id, 'enroll_no': enroll_no, 'in_out_mode': mode, 'check_time': check_time,
            'lg_device_id': device, 'created_by': None, 'edit_by': None, 'edit_on': None}


class StoreTests(TestCase):

    def store(self, rows, reread=False):
        return lg_ingest.store_lg_punches(rows, reread, today=TODAY)

    def test_new_rows_inserted(self):
        out = self.store([row(1), row(2, check_time='2026-11-10T17:00:00')])
        self.assertEqual(out, {'new': 2, 'versioned': 0, 'unchanged': 0, 'removed': 0})
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
        out = self.store([row(1), row(3, check_time='2026-11-10T11:00:00')], reread=True)
        self.assertEqual(out['removed'], 1)
        self.assertTrue(LinkedGatesPunch.objects.get(lg_check_id=2).lg_removed)
        self.assertFalse(LinkedGatesPunch.objects.get(lg_check_id=1).lg_removed)

    def test_no_reread_keeps_missing_rows(self):
        self.store([row(1), row(2), row(3)])
        self.assertEqual(self.store([row(1), row(3)])['removed'], 0)

    def test_reread_ignores_rows_outside_range(self):
        self.store([row(1), row(50, check_time='2026-11-12T09:00:00')])
        out = self.store([row(10, check_time='2026-11-10T09:00:00'), row(20, check_time='2026-11-11T09:00:00')],
                         reread=True)
        self.assertEqual(out['removed'], 0)

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
