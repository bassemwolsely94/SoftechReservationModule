"""
apps/tests/test_hr_attendance_compare.py

The Linked Gates trial comparison: per-punch categories per machine and day, and the employee-days
where Linked Gates' own figures differ from ours, each with its reason codes.
"""
import datetime as dt

from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.hr.attendance import compare
from apps.hr.attendance.days import DayRow
from apps.hr.attendance.lg_rules import LgDay, reason_codes
from apps.hr.attendance.sessions import Stamp
from apps.hr.models import (
    AttendanceDevice, AttendancePunch, Employee, LinkedGatesDevice, LinkedGatesEmployee,
    LinkedGatesPunch,
)


def naive(date, time):
    y, m, d = map(int, date.split('-'))
    h, mi, *s = map(int, time.split(':'))
    return dt.datetime(y, m, d, h, mi, *(s or [0]))


class CompareFixture(TestCase):

    def setUp(self):
        self.hq = AttendanceDevice.objects.create(serial='S1', name='HQ')
        self.other = AttendanceDevice.objects.create(serial='S2', name='Branch')
        LinkedGatesDevice.objects.create(lg_device_id=1, name='LG-HQ', device=self.hq)
        LinkedGatesDevice.objects.create(lg_device_id=2, name='LG-Old')        # not mapped
        self._n = 0

    def employee(self, code, shift_type):
        emp = Employee.objects.create(hr_number=code, name_ar=f'م{code}')
        self._n += 1
        LinkedGatesEmployee.objects.create(lg_employee_id=50000 + self._n, enroll_no=int(code),
                                           shift_type=shift_type)
        return emp

    def machine(self, emp, code, date, time, device=None):
        self._n += 1
        at = naive(date, time)
        return AttendancePunch.objects.create(
            device=device or self.hq, user_code=code, raw_stamp=1000 + self._n, employee=emp,
            punch_date=at.date(), punch_time=at.time())

    def lg(self, emp, code, date, time, device=1, mode=0):
        self._n += 1
        return LinkedGatesPunch.objects.create(
            lg_check_id=9000 + self._n, enroll_no=int(code), in_out_mode=mode,
            check_time=timezone.make_aware(naive(date, time)), lg_device_id=device, employee=emp)

    def both(self, emp, code, date, time):
        self.machine(emp, code, date, time)
        self.lg(emp, code, date, time)


class CompareMonthTests(CompareFixture):

    def test_reason_night_split(self):
        emp = self.employee('3001', 2)
        self.both(emp, '3001', '2026-11-10', '23:00')
        self.both(emp, '3001', '2026-11-11', '08:00')
        rows = {r['date']: r for r in compare.compare_month([emp], 2026, 11)}
        d10 = rows[dt.date(2026, 11, 10)]
        self.assertEqual(d10['employee_id'], emp.id)
        self.assertEqual(d10['ours'], {'in': naive('2026-11-10', '23:00'),
                                       'out': naive('2026-11-11', '08:00'), 'minutes': 540})
        self.assertEqual(d10['lg'], {'in': None, 'out': naive('2026-11-10', '23:00'), 'minutes': 0})
        self.assertIn('lg_night_split', d10['reasons'])
        d11 = rows[dt.date(2026, 11, 11)]
        self.assertEqual(d11['lg']['in'], naive('2026-11-11', '08:00'))
        self.assertIn('lg_night_split', d11['reasons'])

    def test_reason_window_ignored(self):
        emp = self.employee('3002', 1)
        self.both(emp, '3002', '2026-11-10', '06:30')
        self.both(emp, '3002', '2026-11-10', '15:00')
        rows = compare.compare_month([emp], 2026, 11)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['ours']['minutes'], 510)
        self.assertEqual(rows[0]['lg'], {'in': None, 'out': naive('2026-11-10', '15:00'), 'minutes': 0})
        self.assertIn('lg_window_ignored', rows[0]['reasons'])

    def test_identical_day_not_listed(self):
        emp = self.employee('3003', 1)
        self.both(emp, '3003', '2026-11-10', '08:00')
        self.both(emp, '3003', '2026-11-10', '16:00')
        self.assertEqual(compare.compare_month([emp], 2026, 11), [])

    def test_no_shifttype_and_missing_punch(self):
        nost = self.employee('3004', None)
        self.both(nost, '3004', '2026-11-10', '08:00')
        self.both(nost, '3004', '2026-11-10', '16:00')
        rows = compare.compare_month([nost], 2026, 11)
        self.assertEqual([r['reasons'] for r in rows], [['lg_no_shifttype']])
        emp = self.employee('3005', 1)
        self.both(emp, '3005', '2026-11-12', '08:00')
        self.machine(emp, '3005', '2026-11-12', '16:00')      # never reached Linked Gates
        rows = compare.compare_month([emp], 2026, 11)
        self.assertEqual(len(rows), 1)
        self.assertIn('missing_punch', rows[0]['reasons'])

    def test_multi_in(self):
        emp = self.employee('3006', 1)
        self.both(emp, '3006', '2026-11-10', '08:00')
        self.lg(emp, '3006', '2026-11-10', '08:00:30', device=2)     # same moment, another device
        self.both(emp, '3006', '2026-11-10', '16:00')
        rows = compare.compare_month([emp], 2026, 11)
        self.assertEqual(len(rows), 1)
        self.assertIn('lg_multi_in', rows[0]['reasons'])

    def test_compare_query_budget(self):
        def make(n, start):
            emps = []
            for i in range(n):
                code = str(start + i)
                emp = self.employee(code, 1 + i % 2)
                for date in ('2026-11-10', '2026-11-11'):
                    self.both(emp, code, date, '06:30')
                    self.both(emp, code, date, '15:00')
                    self.machine(emp, code, date, '23:30')
                emps.append(emp)
            return emps

        def count(emps):
            with CaptureQueriesContext(connection) as ctx:
                rows = compare.compare_month(emps, 2026, 11)
            self.assertTrue(rows)
            return len(ctx)

        def count_machines():
            with CaptureQueriesContext(connection) as ctx:
                compare.machine_day_counts(2026, 11)
            return len(ctx)

        one = count(make(1, 7000))
        m_one = count_machines()
        many = count(make(12, 7100))
        m_many = count_machines()
        self.assertEqual(one, many)
        self.assertLessEqual(many, 6)
        self.assertEqual(m_one, m_many)
        self.assertLessEqual(m_many, 3)


class CategoryTests(CompareFixture):
    NOW = timezone.make_aware(dt.datetime(2026, 11, 12, 12, 0))
    DAY = dt.date(2026, 11, 11)

    def setUp(self):
        super().setUp()
        emp = self.employee('3001', 1)
        self.machine(emp, '3001', '2026-11-11', '08:00:10')
        self.lg(emp, '3001', '2026-11-11', '08:01:30')                   # matched (80 s)
        self.lg(emp, '3001', '2026-11-11', '09:00', device=None)          # lg_manual
        self.lg(emp, '3001', '2026-11-11', '10:00')                       # missing_from_pull
        self.machine(emp, '3001', '2026-11-11', '11:00')                  # 25 h old: missing_in_lg
        self.machine(emp, '3001', '2026-11-11', '13:00')                  # 23 h old: not_yet_in_lg
        self.lg(emp, '3001', '2026-11-11', '14:00')                       # mapped to HQ ...
        self.machine(emp, '3001', '2026-11-11', '14:00', device=self.other)   # ... but read on Branch
        self.lg(emp, '3001', '2026-11-11', '15:00', device=2)            # unmapped LG device

    def test_categories(self):
        hq = compare.punch_categories(self.hq.id, self.DAY, self.NOW)
        self.assertEqual([(i['at'].time().isoformat(), i['category']) for i in hq], [
            ('08:00:10', 'matched'),
            ('10:00:00', 'missing_from_pull'),
            ('11:00:00', 'missing_in_lg'),
            ('13:00:00', 'not_yet_in_lg'),
            ('14:00:00', 'missing_from_pull'),
        ])
        self.assertTrue(all(i['enroll_no'] == 3001 for i in hq))
        self.assertEqual(hq[0]['machine'], 'HQ')
        branch = compare.punch_categories(self.other.id, self.DAY, self.NOW)
        self.assertEqual([i['category'] for i in branch], ['not_yet_in_lg'])
        none = compare.punch_categories(None, self.DAY, self.NOW)
        self.assertEqual([(i['category'], i['machine']) for i in none],
                         [('lg_manual', 'يدوي'), ('missing_from_pull', 'LG-Old')])

    def test_machine_day_counts(self):
        rows = compare.machine_day_counts(2026, 11, now=self.NOW)
        hq = next(r for r in rows if r['device'] == self.hq.id)
        self.assertEqual(hq['date'], self.DAY)
        self.assertEqual({k: hq[k] for k in ('matched', 'lg_manual', 'missing_from_pull',
                                              'not_yet_in_lg', 'missing_in_lg')},
                         {'matched': 1, 'lg_manual': 0, 'missing_from_pull': 2,
                          'not_yet_in_lg': 1, 'missing_in_lg': 1})
        manual = [r for r in rows if r['device'] is None]
        self.assertEqual(sum(r['lg_manual'] for r in manual), 1)
        self.assertEqual(sum(r['missing_from_pull'] for r in manual), 1)

    def test_superseded_lg_rows_ignored(self):
        p = LinkedGatesPunch.objects.get(check_time=timezone.make_aware(naive('2026-11-11', '10:00')))
        p.superseded_at = timezone.now()
        p.save(update_fields=['superseded_at'])
        hq = compare.punch_categories(self.hq.id, self.DAY, self.NOW)
        self.assertNotIn('10:00:00', [i['at'].time().isoformat() for i in hq])


class ReasonCodeTests(SimpleTestCase):
    D = dt.date(2026, 11, 10)

    def stamp(self, date, time, sources=('machine', 'lg')):
        return Stamp(at=naive(date, time), machine='HQ', sources=frozenset(sources))

    def row(self, stamps):
        r = DayRow(work_date=self.D, first_in=stamps[0].at,
                   last_out=stamps[-1].at if len(stamps) > 1 else None,
                   punch_count=len(stamps), needs_review=len(stamps) % 2 == 1)
        r.raw = [{'at': s.at, 'machine': s.machine, 'state': None, 'counted': True} for s in stamps]
        return r

    def test_out_hidden(self):
        stamps = [self.stamp('2026-11-10', '16:00'), self.stamp('2026-11-11', '00:30')]
        lg = LgDay(self.D, [], naive('2026-11-10', '16:00'))
        self.assertIn('lg_out_hidden', reason_codes(self.row(stamps), lg, stamps, 1))

    def test_moved_back_out_is_not_hidden(self):
        stamps = [self.stamp('2026-11-10', '16:00'), self.stamp('2026-11-11', '00:30')]
        lg = LgDay(self.D, [], naive('2026-11-11', '00:30'))
        self.assertNotIn('lg_out_hidden', reason_codes(self.row(stamps), lg, stamps, 1))

    def test_no_shifttype_only(self):
        stamps = [self.stamp('2026-11-10', '08:00')]
        self.assertEqual(reason_codes(self.row(stamps), None, stamps, None), ['lg_no_shifttype'])
