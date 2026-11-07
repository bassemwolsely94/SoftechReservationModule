"""
apps/tests/test_hr_attendance_export.py

HR Attendance stage 1, Task 8: the monthly Excel export. Same day and total figures as the month
screen (one shared function), three RTL sheets, typed text never runs as a formula, no money.
"""
import datetime as _dt
from io import BytesIO

from django.test import TestCase, override_settings
from openpyxl import load_workbook

from apps.audit.models import AuditLog
from apps.hr.attendance import export
from apps.hr.models import (AttendanceAccess, AttendanceDevice, AttendancePunch, Employee, LeaveRequest,
                            LeaveType)
from apps.tests.factories import make_branch, make_user

URL = '/api/hr-attendance/'
SHEETS = ['الملخص الشهري', 'يوم بيوم', 'بنود للمراجعة']


def cells(ws):
    return [[c.value for c in row] for row in ws.iter_rows()]


@override_settings(HR_ATTENDANCE_ENABLED=True)
class ExportTests(TestCase):

    def setUp(self):
        self.b1 = make_branch('فرع أ', 'B01')
        _, self.admin_p, self.admin = make_user('hx_admin', role='admin', branch=self.b1)
        _, self.view_p, self.viewer = make_user('hx_view', role='pharmacist', branch=self.b1)
        _, self.out_p, self.outsider = make_user('hx_out', role='branch_manager', branch=self.b1)
        AttendanceAccess.objects.create(staff=self.view_p, level='view', granted_by=self.admin_p)
        self.device = AttendanceDevice.objects.create(serial='SN1', name='جهاز ١', ip='192.168.3.15')
        self.emp = Employee.objects.create(hr_number='1001', name_ar='سامر سامي', branch=self.b1,
                                           daily_hours=8)
        self.n = 0

    def punch(self, date, time, code='1001', flag='', employee='default'):
        self.n += 1
        emp = self.emp if employee == 'default' else employee
        return AttendancePunch.objects.create(
            device=self.device, user_code=code, raw_stamp=self.n, punch_date=date, punch_time=time,
            flag=flag, employee=emp)

    def fixture(self):
        d = _dt.date
        self.punch(d(2026, 10, 1), _dt.time(9, 0))
        self.punch(d(2026, 10, 1), _dt.time(17, 30))
        self.punch(d(2026, 10, 2), _dt.time(9, 0))          # single punch: needs review
        self.punch(d(2026, 11, 1), _dt.time(2, 0))          # before 04:00 -> 31 Oct work day
        self.punch(d(2026, 10, 31), _dt.time(10, 0))

    def book(self, month='2026-10'):
        r = self.admin.get(URL + f'month/export/?month={month}')
        self.assertEqual(r.status_code, 200, r.content[:200])
        return load_workbook(BytesIO(r.content)), r

    def test_three_sheets(self):
        wb = export.build_workbook(2026, 10)
        self.assertEqual(wb.sheetnames, SHEETS)
        for ws in wb.worksheets:
            self.assertTrue(ws.sheet_view.rightToLeft)

    def test_summary_matches_month_api(self):
        self.fixture()
        api = self.admin.get(URL + 'month/?month=2026-10').json()['rows'][0]
        wb, _ = self.book()
        rows = cells(wb[SHEETS[0]])
        got = dict(zip(rows[0], rows[1]))
        self.assertEqual(got['رقم الموظف'], api['hr_number'])
        self.assertEqual(got['أيام بها بصمات'], api['days_with_punches'])
        self.assertEqual(float(got['ساعات العمل']), float(api['worked_hours']))
        self.assertEqual(float(got['الساعات المتوقعة']), float(api['expected_hours']))
        self.assertEqual(got['أيام تحتاج مراجعة'], api['days_needing_review'])
        self.assertEqual(got['بدون بصمات'], api['days_no_punches'])

    def test_formula_name_is_neutralised(self):
        Employee.objects.filter(pk=self.emp.pk).update(name_ar='=1+1')
        wb = export.build_workbook(2026, 10)
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    self.assertNotEqual(c.data_type, 'f', (ws.title, c.coordinate))
        wb2, _ = self.book()
        values = [v for row in cells(wb2[SHEETS[0]]) for v in row]
        self.assertIn('=1+1', values)

    def test_no_bare_branch_code(self):
        self.fixture()
        wb, _ = self.book()
        every = [v for ws in wb.worksheets for row in cells(ws) for v in row]
        self.assertIn('فرع أ', every)
        self.assertNotIn('B01', every)

    def test_unresolved_and_flagged_are_listed(self):
        self.punch(_dt.date(2026, 10, 3), _dt.time(9, 0), code='7777', employee=None)
        self.punch(_dt.date(1999, 1, 1), _dt.time(9, 0), flag='bad_date')
        wb, _ = self.book()
        rows = cells(wb[SHEETS[2]])
        text = ' '.join(str(v) for row in rows for v in row if v is not None)
        self.assertIn('7777', text)
        self.assertIn('جهاز ١', text)
        self.assertGreaterEqual(len(rows), 3)

    def test_no_money_columns(self):
        self.fixture()
        wb, _ = self.book()
        heads = ' '.join(str(v).lower() for ws in wb.worksheets for v in cells(ws)[0] if v)
        for word in ('salary', 'amount', 'deduct', 'penalty', 'net', 'راتب', 'خصم', 'جزاء', 'صافي', 'مبلغ'):
            self.assertNotIn(word, heads)

    def test_month_boundary_matches_screen(self):
        self.fixture()
        api = self.admin.get(URL + f'employees/{self.emp.pk}/days/?month=2026-10').json()['days']
        wb, _ = self.book()
        rows = cells(wb[SHEETS[1]])
        head = rows[0]
        di, wi, ci = head.index('التاريخ'), head.index('دقائق العمل'), head.index('عدد البصمات')
        by_date = {str(r[di])[:10]: r for r in rows[1:]}
        self.assertEqual(len(by_date), 31)
        for d in api:
            self.assertEqual(by_date[d['work_date']][wi], d['worked_minutes'], d['work_date'])
        # the 02:00 punch of 1 Nov belongs to 31 Oct (two punches there), not to November
        self.assertEqual(by_date['2026-10-31'][ci], 2)
        nov = cells(export.build_workbook(2026, 11)[SHEETS[1]])
        self.assertEqual(nov[1][ci], 0)

    def test_leave_listed_pending_not_and_totals_unchanged(self):
        self.fixture()
        lt = LeaveType.objects.create(code='annual', name='Annual', name_ar='سنوية')
        before = cells(export.build_workbook(2026, 10)[SHEETS[0]])
        for status, day in (('approved', _dt.date(2026, 10, 5)), ('pending', _dt.date(2026, 10, 6))):
            LeaveRequest.objects.create(leave_type=lt, start_date=day, end_date=day, days_requested=1,
                                        status=status, employee_hr_code='1001')
        wb = export.build_workbook(2026, 10)
        rows = cells(wb[SHEETS[1]])
        head = rows[0]
        di, li = head.index('التاريخ'), head.index('إجازة / إذن')
        by_date = {str(r[di])[:10]: r for r in rows[1:]}
        self.assertEqual(by_date['2026-10-05'][li], 'سنوية')
        self.assertFalse(by_date['2026-10-06'][li])
        self.assertEqual(cells(wb[SHEETS[0]]), before)

    def test_status_is_arabic(self):
        rows = cells(export.build_workbook(2026, 10)[SHEETS[0]])
        self.assertEqual(rows[1][rows[0].index('الحالة')], 'على رأس العمل')

    def test_export_is_audited(self):
        self.book()
        log = AuditLog.objects.filter(action='hr_attendance_export').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.extra['month'], '2026-10')

    def test_outsider_refused_and_view_grant_may_export(self):
        self.assertEqual(self.outsider.get(URL + 'month/export/?month=2026-10').status_code, 403)
        self.assertEqual(self.viewer.get(URL + 'month/export/?month=2026-10').status_code, 200)

    def test_bad_month_rejected(self):
        self.assertEqual(self.admin.get(URL + 'month/export/?month=2026-13').status_code, 400)
