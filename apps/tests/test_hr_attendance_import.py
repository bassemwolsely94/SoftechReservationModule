"""
apps/tests/test_hr_attendance_import.py

HR Attendance stage 1, Task 2: the one-time employee import. The workbook is built here with
openpyxl and FAKE data; the real salaries workbook is never used. Only the allowed columns are read.
"""
import os
import tempfile
from io import StringIO

import openpyxl
from django.core.management import call_command
from django.test import TestCase
from openpyxl.utils import column_index_from_string

from apps.audit.models import AuditLog
from apps.hr.attendance import employee_import as imp
from apps.hr.models import Employee
from apps.tests.factories import make_branch, make_user

SECRET_COLS = ['CE', 'Z', 'AE', 'AU', 'Y']


def build_workbook(rows, path):
    """rows: list of dicts keyed by import field; header row 2, data from row 3."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(row=2, column=1, value='header')
    for r, row in enumerate(rows, start=3):
        for col, field in imp.IMPORT_COLUMNS.items():
            if field in row:
                ws.cell(row=r, column=column_index_from_string(col), value=row[field])
        for col in SECRET_COLS:
            ws.cell(row=r, column=column_index_from_string(col), value='SECRET')
    wb.save(path)


def fake_row(i, **kw):
    row = {'hr_number': 1000 + i, 'name_ar': f'موظف {i}', 'department': 'إدارة', 'section': 'قسم',
           'work_location': 'فرع أ', 'job_title': 'صيدلي', 'daily_hours': 8}
    row.update(kw)
    return row


class Base(TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, 'fake.xlsx')
        self.branch = make_branch('فرع أ', 'B01')
        _, self.profile, _ = make_user('imp_admin', role='admin', branch=self.branch)

    def preview(self, rows):
        build_workbook(rows, self.path)
        return imp.read_workbook(self.path)


class ImportTests(Base):

    def test_normalise_code_handles_float_space_text(self):
        for v in (1001.0, ' 1001', '1001', 1001):
            self.assertEqual(imp.normalise_code(v), '1001')
        self.assertEqual(imp.normalise_code(None), '')

    def test_normalise_code_text_float_and_odd_characters(self):
        for v in ('1001.0', ' 1001.0 ', '1001.00', '\xa01001​', '١٠٠١', '١٠٠١.٠'):
            self.assertEqual(imp.normalise_code(v), '1001', repr(v))
        self.assertEqual(imp.normalise_code('1001.5'), '1001.5')

    def test_float_and_text_forms_of_same_code_are_duplicates(self):
        p = self.preview([fake_row(1, hr_number=1001.0), fake_row(2, hr_number=' 1001')])
        self.assertEqual(len(p.rows), 1)
        self.assertEqual(len(p.errors), 1)
        self.assertIn('duplicate', p.errors[0])
        p = self.preview([fake_row(1, hr_number='1001.0'), fake_row(2, hr_number=' 1001')])
        self.assertEqual(len(p.errors), 1)

    def test_reads_only_allowed_columns(self):
        p = self.preview([fake_row(1), fake_row(2)])
        self.assertNotIn('SECRET', repr(p.rows) + repr(p.errors))

    def test_skips_total_row(self):
        p = self.preview([fake_row(1), fake_row(2, name_ar='الاجمالى', hr_number=None)])
        self.assertEqual(len(p.rows), 1)
        self.assertEqual(p.errors, [])

    def test_55_rows_dry_run_writes_nothing(self):
        p = self.preview([fake_row(i) for i in range(55)])
        self.assertEqual(len(p.rows), 55)
        self.assertEqual(Employee.objects.count(), 0)
        out = StringIO()
        call_command('import_attendance_employees', self.path, stdout=out)
        self.assertEqual(Employee.objects.count(), 0)
        self.assertIn('55', out.getvalue())
        self.assertNotIn('موظف', out.getvalue())

    def test_duplicate_code_is_an_error(self):
        p = self.preview([fake_row(1), fake_row(2, hr_number=1001)])
        self.assertEqual(len(p.errors), 1)
        self.assertIn('1001', p.errors[0])
        self.assertNotIn('SECRET', p.errors[0])
        with self.assertRaises(imp.ImportBlocked):
            imp.apply(p, self.profile)
        self.assertEqual(Employee.objects.count(), 0)

    def test_missing_hours_stays_null(self):
        p = self.preview([fake_row(1, daily_hours=None)])
        imp.apply(p, self.profile)
        self.assertIsNone(Employee.objects.get(hr_number='1001').daily_hours)

    def test_branch_set_only_on_clean_map(self):
        p = self.preview([fake_row(1), fake_row(2, work_location='المخازن')])
        imp.apply(p, self.profile)
        self.assertEqual(Employee.objects.get(hr_number='1001').branch, self.branch)
        e = Employee.objects.get(hr_number='1002')
        self.assertEqual(e.work_location, 'المخازن')
        self.assertIsNone(e.branch)

    def test_apply_is_idempotent(self):
        imp.apply(self.preview([fake_row(1)]), self.profile)
        res = imp.apply(self.preview([fake_row(1, job_title='مدير')]), self.profile)
        self.assertEqual(Employee.objects.count(), 1)
        self.assertEqual(Employee.objects.get().job_title, 'مدير')
        self.assertEqual(res['created'], 0)
        self.assertEqual(res['updated'], 1)

    def test_apply_audited(self):
        imp.apply(self.preview([fake_row(1), fake_row(2)]), self.profile)
        entry = AuditLog.objects.get(action='hr_employee_import')
        self.assertEqual(entry.user, self.profile)
        self.assertEqual(entry.extra['created'], 2)
        self.assertNotIn('موظف', repr(entry.extra))

    def test_command_apply_flag_writes(self):
        build_workbook([fake_row(1)], self.path)
        call_command('import_attendance_employees', self.path, '--apply', stdout=StringIO())
        self.assertEqual(Employee.objects.count(), 1)
