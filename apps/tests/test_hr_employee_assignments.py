"""
apps/tests/test_hr_employee_assignments.py

Crews piece 2a, Task 1: dated employee assignment history + PBX extensions.
"""
from datetime import date, timedelta
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase

from apps.audit.models import AuditLog
from apps.hr import assignments as asg
from apps.hr.attendance import employee_import as imp
from apps.hr.models import Employee, EmployeeAssignment
from apps.tests.factories import make_branch, make_user


def row(i=1, **kw):
    r = {'row': 3, 'hr_number': str(1000 + i), 'name_ar': f'موظف {i}', 'department': 'إدارة',
         'section': 'قسم', 'work_location': 'فرع أ', 'job_title': 'صيدلي', 'daily_hours': None}
    r.update(kw)
    return r


def preview(*rows):
    return imp.ImportPreview(rows=list(rows))


class AssignmentTests(TestCase):
    def setUp(self):
        self.branch = make_branch('فرع أ', 'B01')
        self.branch2 = make_branch('فرع ب', 'B02')
        _, self.profile, _ = make_user('asg_admin', role='admin', branch=self.branch)

    def rows(self, code='1001'):
        return list(EmployeeAssignment.objects.filter(employee__hr_number=code).order_by('valid_from'))

    def test_first_import_opens_row_from_start_date_or_epoch(self):
        Employee.objects.create(hr_number='1001', name_ar='أ', start_date=date(2023, 5, 1))
        imp.apply(preview(row(1)), self.profile, on=date(2026, 11, 13))
        imp.apply(preview(row(2)), self.profile, on=date(2026, 11, 13))
        a, b = self.rows('1001'), self.rows('1002')
        self.assertEqual((len(a), a[0].valid_from, a[0].valid_to), (1, date(2023, 5, 1), None))
        # a new hire with no start date starts on the import day, never back in 2020 (final review F1)
        self.assertEqual((len(b), b[0].valid_from, b[0].valid_to), (1, date(2026, 11, 13), None))
        self.assertEqual(a[0].source, 'import')
        # only the seed (the go-live backfill of people already here) reaches back to the epoch
        seeded = Employee.objects.create(hr_number='1003', name_ar='ج')
        asg.record_assignment(seeded, on=date(2026, 11, 13), source='seed')
        self.assertEqual(self.rows('1003')[0].valid_from, asg.SEED_EPOCH)

    def test_new_hire_import_after_go_live_leaves_last_month_unchanged(self):
        from django.utils import timezone

        from apps.crews import membership
        from apps.crews.models import Crew, CrewRule
        today = timezone.localdate()
        last_end = today.replace(day=1) - timedelta(days=1)
        last_start = last_end.replace(day=1)
        imp.apply(preview(row(1)), self.profile, on=date(2020, 1, 1))     # an employee already here
        crew = Crew.objects.create(name='صيادلة', type='job')
        CrewRule.objects.create(crew=crew, job_titles=['صيدلي'], valid_from=date(2020, 1, 1))
        before = membership.members_between(crew, last_start, last_end)
        self.assertEqual(len(before), 1)
        imp.apply(preview(row(1), row(2)), self.profile, on=today)        # a new hire, no start date
        self.assertEqual(membership.members_between(crew, last_start, last_end), before)
        new = Employee.objects.get(hr_number='1002')
        self.assertIn(('emp', new.id), {x.key for x in membership.members(crew, today)})

    def test_go_live_migration_seeds_open_rows_for_employees_without_history(self):
        import importlib

        from django.apps import apps as django_apps
        mig = importlib.import_module('apps.hr.migrations.0014_seed_employee_assignments')
        a = Employee.objects.create(hr_number='1001', name_ar='أ', job_title='صيدلي', branch=self.branch,
                                    department='د', section='س', softech_usercode='55',
                                    pbx_extensions=['201'], start_date=date(2024, 3, 1))
        b = Employee.objects.create(hr_number='1002', name_ar='ب', job_title='كاشير')
        c = Employee.objects.create(hr_number='1003', name_ar='ج', job_title='مدير')
        asg.record_assignment(c, on=date(2026, 1, 1), source='manual')      # already has history
        mig.seed(django_apps, None)
        mig.seed(django_apps, None)                                          # idempotent
        ra, rb, rc = self.rows('1001'), self.rows('1002'), self.rows('1003')
        self.assertEqual(len(ra), 1)
        self.assertEqual((ra[0].valid_from, ra[0].valid_to, ra[0].source, ra[0].job_title, ra[0].branch_id,
                          ra[0].department, ra[0].section, ra[0].softech_usercode, ra[0].pbx_extensions),
                         (date(2024, 3, 1), None, 'seed', 'صيدلي', self.branch.id, 'د', 'س', '55', ['201']))
        self.assertEqual((len(rb), rb[0].valid_from, rb[0].source), (1, date(2020, 1, 1), 'seed'))
        self.assertEqual((len(rc), rc[0].source), (1, 'manual'))
        self.assertEqual(a.assignments.count() + b.assignments.count(), 2)

    def test_reimport_unchanged_writes_nothing(self):
        p = preview(row(1))
        first = imp.apply(p, self.profile, on=date(2026, 11, 13))
        second = imp.apply(p, self.profile, on=date(2026, 12, 1))
        self.assertEqual(first['assignments_changed'], 1)
        self.assertEqual(second['assignments_changed'], 0)
        self.assertEqual(len(self.rows()), 1)

    def test_job_change_closes_previous_day_and_opens_new(self):
        imp.apply(preview(row(1, job_title='A')), self.profile, on=date(2026, 11, 13))
        imp.apply(preview(row(1, job_title='B')), self.profile, on=date(2026, 12, 1))
        a, b = self.rows()
        self.assertEqual((a.job_title, a.valid_to), ('A', date(2026, 11, 30)))
        self.assertEqual((b.job_title, b.valid_from, b.valid_to), ('B', date(2026, 12, 1), None))

    def test_branch_change_and_section_change_each_open_row(self):
        imp.apply(preview(row(1)), self.profile, on=date(2026, 1, 1))
        imp.apply(preview(row(1, work_location='فرع ب')), self.profile, on=date(2026, 2, 1))
        imp.apply(preview(row(1, work_location='فرع ب', section='قسم 2')), self.profile,
                  on=date(2026, 3, 1))
        rows = self.rows()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1].branch_id, self.branch2.pk)
        self.assertEqual(rows[2].section, 'قسم 2')
        self.assertEqual(rows[1].valid_to, date(2026, 2, 28))

    def test_usercode_and_extension_change_open_row_with_snapshot(self):
        emp = Employee.objects.create(hr_number='1001', name_ar='أ', start_date=date(2026, 1, 1),
                                      softech_usercode='55', pbx_extensions=['201'])
        asg.record_assignment(emp, on=date(2026, 1, 1), source='seed')
        emp.pbx_extensions = ['201']          # same list again → nothing changes
        self.assertIsNone(asg.record_assignment(emp, on=date(2026, 2, 1), source='manual'))
        emp.softech_usercode = '66'
        asg.record_assignment(emp, on=date(2026, 3, 1), source='manual')
        emp.pbx_extensions = ['201', '202']
        asg.record_assignment(emp, on=date(2026, 4, 1), source='manual')
        rows = self.rows()
        self.assertEqual([(r.softech_usercode, r.pbx_extensions, r.valid_from, r.valid_to) for r in rows], [
            ('55', ['201'], date(2026, 1, 1), date(2026, 2, 28)),
            ('66', ['201'], date(2026, 3, 1), date(2026, 3, 31)),
            ('66', ['201', '202'], date(2026, 4, 1), None)])

    def test_same_day_change_corrects_in_place(self):
        d = date(2026, 11, 13)
        # the first row starts at start_date; a same-day fix applies when that equals `on`
        Employee.objects.create(hr_number='1001', name_ar='أ', start_date=d)
        imp.apply(preview(row(1, job_title='A')), self.profile, on=d)
        imp.apply(preview(row(1, job_title='B')), self.profile, on=d)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].job_title, 'B')
        self.assertIsNone(rows[0].valid_to)

    def test_assignment_on_picks_row_covering_date(self):
        imp.apply(preview(row(1, job_title='A')), self.profile, on=date(2026, 11, 13))
        imp.apply(preview(row(1, job_title='B')), self.profile, on=date(2026, 12, 1))
        emp = Employee.objects.get(hr_number='1001')
        self.assertEqual(asg.assignment_on(emp.pk, date(2026, 11, 30)).job_title, 'A')
        self.assertEqual(asg.assignment_on(emp.pk, date(2026, 12, 1)).job_title, 'B')
        self.assertEqual(asg.assignment_on(emp.pk, date(2030, 1, 1)).job_title, 'B')
        self.assertIsNone(asg.assignment_on(emp.pk, date(2019, 1, 1)))

    def test_seed_command_idempotent(self):
        for i in range(3):
            Employee.objects.create(hr_number=f'9{i}', name_ar='x', job_title='ص')
        call_command('seed_employee_assignments', '--dry-run', stdout=StringIO())
        self.assertEqual(EmployeeAssignment.objects.count(), 0)
        call_command('seed_employee_assignments', stdout=StringIO())
        call_command('seed_employee_assignments', stdout=StringIO())
        self.assertEqual(EmployeeAssignment.objects.count(), 3)
        self.assertEqual(set(EmployeeAssignment.objects.values_list('source', flat=True)), {'seed'})

    def test_validate_extensions(self):
        self.assertEqual(asg.validate_extensions([' 201', '201', '', '33']), ['201', '33'])
        with self.assertRaises(ValidationError):
            asg.validate_extensions(['12a'])
        with self.assertRaises(ValidationError):
            asg.validate_extensions(['1'])
        self.assertEqual(asg.validate_extensions(['٢٠١', '۳۳']), ['201', '33'])
        for bad in ('201', 5, {'a': 1}):
            with self.assertRaises(ValidationError):
                asg.validate_extensions(bad)

    def test_back_dated_apply_rewrites_open_row_in_place(self):
        Employee.objects.create(hr_number='1001', name_ar='أ', start_date=date(2026, 5, 1))
        imp.apply(preview(row(1, job_title='A')), self.profile, on=date(2026, 5, 1))
        imp.apply(preview(row(1, job_title='B')), self.profile, on=date(2026, 4, 1))
        rows = self.rows()
        self.assertEqual((len(rows), rows[0].job_title, rows[0].valid_from), (1, 'B', date(2026, 5, 1)))

    def test_import_audit_extra_has_assignments_changed(self):
        imp.apply(preview(row(1)), self.profile, on=date(2026, 11, 13))
        log = AuditLog.objects.filter(action='hr_employee_import').latest('pk')
        self.assertEqual(log.extra['assignments_changed'], 1)
