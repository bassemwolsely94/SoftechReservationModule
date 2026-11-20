"""
apps/tests/test_hr_attendance_lg_views.py

The Linked Gates trial on the staff API (design 2026-11-20 §5.4, 5.6, 5.8): the comparison and its
Excel file (view level), the machine mapping (manage level, audited), both totals on the month with
«المعتمد», and the switch: off = no comparison and machine punches only.
"""
import datetime as dt
import json
from io import BytesIO

from django.test import TestCase, override_settings
from django.utils import timezone
from openpyxl import load_workbook

from apps.audit.models import AuditLog
from apps.hr.models import (AttendanceAccess, AttendanceDevice, AttendancePunch, Employee, LinkedGatesDevice,
                            LinkedGatesEmployee, LinkedGatesPunch)
from apps.tests.factories import make_branch, make_user
from apps.tests.perf.budget import assert_budget

URL = '/api/hr-attendance/'
MONTH = '2026-10'


def at(date, time):
    y, m, d = map(int, date.split('-'))
    h, mi = map(int, time.split(':'))
    return dt.datetime(y, m, d, h, mi)


@override_settings(HR_ATTENDANCE_ENABLED=True, HR_ATTENDANCE_LINKEDGATES_ENABLED=True,
                   HR_ATTENDANCE_DAY_SOURCE='linkedgates')
class LgViewsBase(TestCase):

    def setUp(self):
        self.b1 = make_branch('فرع أ', 'B01')
        _, self.admin_p, self.admin = make_user('lgv_admin', role='admin', branch=self.b1)
        _, self.mgr_p, self.mgr = make_user('lgv_mgr', role='pharmacist', branch=self.b1)
        _, self.view_p, self.viewer = make_user('lgv_view', role='pharmacist', branch=self.b1)
        _, self.out_p, self.outsider = make_user('lgv_out', role='branch_manager', branch=self.b1)
        AttendanceAccess.objects.create(staff=self.mgr_p, level='manage', granted_by=self.admin_p)
        AttendanceAccess.objects.create(staff=self.view_p, level='view', granted_by=self.admin_p)
        self.device = AttendanceDevice.objects.create(serial='SN1', name='Balegh', ip='192.168.4.15')
        self.lg_dev = LinkedGatesDevice.objects.create(lg_device_id=7, name='LG Balegh', ip='192.168.4.15',
                                                       device=self.device)
        self.n = 0

    def employee(self, code, shift_type=1, name=None):
        emp = Employee.objects.create(hr_number=code, name_ar=name or f'موظف {code}', daily_hours=8)
        self.n += 1
        LinkedGatesEmployee.objects.create(lg_employee_id=70000 + self.n, enroll_no=int(code),
                                           shift_type=shift_type)
        return emp

    def machine(self, emp, date, time):
        self.n += 1
        moment = at(date, time)
        return AttendancePunch.objects.create(device=self.device, user_code=emp.hr_number, raw_stamp=self.n,
                                              punch_date=moment.date(), punch_time=moment.time(), employee=emp)

    def lg(self, emp, date, time, device=7):
        self.n += 1
        return LinkedGatesPunch.objects.create(
            lg_check_id=500000 + self.n, enroll_no=int(emp.hr_number), check_time=timezone.make_aware(at(date, time)),
            lg_device_id=device, employee=emp)

    def both(self, emp, date, time):
        self.machine(emp, date, time)
        self.lg(emp, date, time)

    def differing_day(self, emp, date='2026-10-05'):
        """06:30 is outside Linked Gates' type-1 windows: ours counts it, Linked Gates ignores it."""
        self.both(emp, date, '06:30')
        self.both(emp, date, '15:00')

    def post(self, client, path, body):
        return client.post(URL + path, json.dumps(body), content_type='application/json')


class CompareAccessTests(LgViewsBase):

    def test_compare_requires_view_grant(self):
        self.differing_day(self.employee('1001'))
        self.assertEqual(self.outsider.get(URL + f'linkedgates/compare/?month={MONTH}').status_code, 403)
        r = self.viewer.get(URL + f'linkedgates/compare/?month={MONTH}')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body['enabled'])
        self.assertEqual(body['day_source'], 'linkedgates')
        self.assertEqual(body['official'], 'lg')
        self.assertEqual(len(body['days']), 1)
        day = body['days'][0]
        self.assertEqual((day['hr_number'], day['date']), ('1001', '2026-10-05'))
        self.assertIn('lg_window_ignored', day['reasons'])
        self.assertEqual(day['minutes_diff'], 510)
        self.assertIn('lg_window_ignored', body['reasons'])        # plain words travel with the codes
        self.assertEqual(sum(m['matched'] for m in body['machines']), 2)

    def test_year_and_month_params(self):
        self.differing_day(self.employee('1001'))
        r = self.viewer.get(URL + 'linkedgates/compare/?year=2026&month=10')
        self.assertEqual(r.json()['month'], MONTH)
        self.assertEqual(len(r.json()['days']), 1)

    def test_devices_list_is_view_level_and_hides_the_ip(self):
        self.assertEqual(self.outsider.get(URL + 'linkedgates/devices/').status_code, 403)
        row = self.viewer.get(URL + 'linkedgates/devices/').json()['rows'][0]
        self.assertEqual((row['lg_device_id'], row['device'], row['device_name']), (7, self.device.pk, 'Balegh'))
        self.assertNotIn('ip', row)
        self.assertEqual(self.admin.get(URL + 'linkedgates/devices/').json()['rows'][0]['ip'], '192.168.4.15')


class DeviceMapTests(LgViewsBase):

    def test_device_map_requires_manage(self):
        path = 'linkedgates/devices/7/map/'
        self.assertEqual(self.post(self.outsider, path, {'device_id': None}).status_code, 403)
        self.assertEqual(self.post(self.viewer, path, {'device_id': None}).status_code, 403)
        self.lg_dev.refresh_from_db()
        self.assertEqual(self.lg_dev.device_id, self.device.pk)
        r = self.post(self.mgr, path, {'device_id': None})
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.lg_dev.refresh_from_db()
        self.assertIsNone(self.lg_dev.device_id)

    def test_device_map_audited(self):
        other = AttendanceDevice.objects.create(serial='SN2', name='Zahar', ip='192.168.5.15')
        r = self.post(self.mgr, 'linkedgates/devices/7/map/', {'device_id': other.pk})
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.assertEqual(r.json()['device_name'], 'Zahar')
        entry = AuditLog.objects.get(action='hr_attendance_lg_device_map')
        self.assertEqual(entry.changes['device'], [self.device.pk, other.pk])
        self.assertEqual(entry.changes['device_name'], ['Balegh', 'Zahar'])
        self.assertEqual(entry.user_id, self.mgr_p.pk)
        self.assertEqual(entry.extra['lg_device_id'], 7)
        # the same mapping again changes nothing and writes no second row
        self.post(self.mgr, 'linkedgates/devices/7/map/', {'device_id': other.pk})
        self.assertEqual(AuditLog.objects.filter(action='hr_attendance_lg_device_map').count(), 1)

    def test_device_map_rejects_unknown_machine_and_missing_key(self):
        self.assertEqual(self.post(self.mgr, 'linkedgates/devices/7/map/', {'device_id': 99999}).status_code, 400)
        self.assertEqual(self.post(self.mgr, 'linkedgates/devices/7/map/', {}).status_code, 400)
        self.assertEqual(self.post(self.mgr, 'linkedgates/devices/404/map/', {'device_id': None}).status_code, 404)


class ExportTests(LgViewsBase):

    def test_export_safe(self):
        self.differing_day(self.employee('1001', name='=1+1'))
        self.assertEqual(self.outsider.get(URL + f'linkedgates/compare/export/?month={MONTH}').status_code, 403)
        r = self.viewer.get(URL + f'linkedgates/compare/export/?month={MONTH}')
        self.assertEqual(r.status_code, 200, r.content[:200])
        wb = load_workbook(BytesIO(r.content))
        values = []
        for ws in wb.worksheets:
            self.assertTrue(ws.sheet_view.rightToLeft)
            for row in ws.iter_rows():
                for c in row:
                    self.assertNotEqual(c.data_type, 'f', (ws.title, c.coordinate))
                    values.append(c.value)
        self.assertIn('=1+1', values)
        self.assertTrue(any('المعتمد' in str(v) for v in values))
        self.assertTrue(AuditLog.objects.filter(action='hr_attendance_lg_compare_export').exists())


class MonthTests(LgViewsBase):

    def test_month_has_both_totals_and_official(self):
        self.differing_day(self.employee('1001'))
        row = self.viewer.get(URL + f'month/?month={MONTH}').json()['rows'][0]
        self.assertEqual(row['official'], 'lg')
        self.assertEqual(float(row['ours']['worked_hours']), 8.5)          # 06:30 → 15:00
        self.assertEqual(row['ours']['days_with_punches'], 1)
        self.assertEqual(row['lg']['days_with_punches'], 1)                # out only, no in → 0 minutes
        self.assertEqual(float(row['lg']['worked_hours']), 0.0)
        with override_settings(HR_ATTENDANCE_DAY_SOURCE='sessions'):
            body = self.viewer.get(URL + f'month/?month={MONTH}').json()
            self.assertEqual((body['official'], body['rows'][0]['official']), ('ours', 'ours'))

    def test_month_file_puts_official_first(self):
        self.differing_day(self.employee('1001'))
        r = self.viewer.get(URL + f'month/export/?month={MONTH}')
        ws = load_workbook(BytesIO(r.content)).worksheets[0]
        head = [c.value for c in ws[1]]
        first_figure = head[6]
        self.assertTrue(first_figure.startswith('المعتمد'), head)
        self.assertIn('لينكد جيتس', first_figure)
        self.assertIn('ساعات لينكد جيتس', head)
        self.assertIn('ساعات العمل', head)

    @override_settings(HR_ATTENDANCE_LINKEDGATES_ENABLED=False)
    def test_switch_off_hides_lg(self):
        emp = self.employee('1001')
        self.machine(emp, '2026-10-05', '08:00')
        self.lg(emp, '2026-10-05', '16:00')                   # Linked Gates only
        self.assertEqual(self.viewer.get(URL + f'linkedgates/compare/?month={MONTH}').json(), {'enabled': False})
        body = self.viewer.get(URL + f'month/?month={MONTH}').json()
        row = body['rows'][0]
        self.assertFalse(body['lg_enabled'])
        self.assertIsNone(row['lg'])
        self.assertEqual(row['official'], 'ours')
        self.assertEqual(float(row['worked_hours']), 0.0)      # the 16:00 from Linked Gates is not used
        self.assertEqual(row['days_needing_review'], 1)
        head = [c.value for c in load_workbook(BytesIO(self.viewer.get(
            URL + f'month/export/?month={MONTH}').content)).worksheets[0][1]]
        self.assertFalse(any('لينكد' in str(h) or 'المعتمد' in str(h) for h in head))

    def test_switch_on_merges_lg_into_ours(self):
        emp = self.employee('1001')
        self.machine(emp, '2026-10-05', '08:00')
        self.lg(emp, '2026-10-05', '16:00')
        row = self.viewer.get(URL + f'month/?month={MONTH}').json()['rows'][0]
        self.assertEqual(float(row['ours']['worked_hours']), 8.0)


class BudgetTests(LgViewsBase):

    def _grow(self, n=12):
        for i in range(n):
            self.n += 1
            emp = self.employee(str(2000 + self.n), shift_type=1 + i % 2)
            self.differing_day(emp, f'2026-10-{1 + i % 20:02d}')

    def test_compare_budget(self):
        self._grow(2)
        assert_budget(self, 'hr-attendance-lg-compare', self.admin, URL + f'linkedgates/compare/?month={MONTH}',
                      grow=self._grow, min_rows=12, rows_of=lambda r: len(r.json()['days']))

    def test_devices_budget(self):
        def grow():
            for i in range(12):
                LinkedGatesDevice.objects.create(lg_device_id=100 + i + self.n, name=f'LG {i}', device=self.device)
            self.n += 100
        assert_budget(self, 'hr-attendance-lg-devices', self.admin, URL + 'linkedgates/devices/',
                      grow=grow, min_rows=12, rows_of=lambda r: len(r.json()['rows']))
