"""
apps/tests/test_hr_attendance_days.py

HR Attendance stage 1: the daily / monthly engine. Display only: no pay, no verdicts.
"""
import dataclasses
import datetime as dt
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase

from apps.hr.attendance import days
from apps.hr.attendance.days import (
    build_days, leave_info, month_totals, punches_for_month, work_date_for,
)
from apps.hr.models import (
    AttendanceDevice, AttendancePunch, Employee, LeaveRequest, LeaveType, Permit,
)
from apps.tests.factories import make_branch, make_user

B4 = dt.time(4, 0)


def P(date, time, machine='HQ', state=0, flag=''):
    """A punch stand-in for the pure functions (no database)."""
    y, m, d = map(int, date.split('-'))
    h, mi, *s = map(int, time.split(':'))
    return SimpleNamespace(punch_date=dt.date(y, m, d), punch_time=dt.time(h, mi, *(s or [0])),
                           device=SimpleNamespace(name=machine), state=state, flag=flag)


def day(rows, iso):
    return next(r for r in rows if r.work_date.isoformat() == iso)


class PureEngineTests(SimpleTestCase):

    def setUp(self):
        p = mock.patch.object(days, '_today', return_value=dt.date(2026, 12, 31))
        p.start()
        self.addCleanup(p.stop)

    def test_0200_belongs_to_previous_day(self):
        self.assertEqual(work_date_for(dt.date(2026, 11, 10), dt.time(2, 0), B4), dt.date(2026, 11, 9))
        self.assertEqual(work_date_for(dt.date(2026, 11, 10), dt.time(4, 0), B4), dt.date(2026, 11, 10))

    def test_0200_on_first_counts_in_previous_month(self):
        punches = [P('2026-11-30', '22:00'), P('2026-12-01', '02:00')]
        nov = build_days(punches, B4, None, 2026, 11)
        dec = build_days(punches, B4, None, 2026, 12)
        self.assertEqual(day(nov, '2026-11-30').punch_count, 2)
        self.assertEqual(sum(r.punch_count for r in dec), 0)
        self.assertEqual(day(dec, '2026-12-01').no_punches, True)

    def test_overnight_shift_is_one_day(self):
        rows = build_days([P('2026-11-10', '22:00'), P('2026-11-11', '03:30')], B4, None, 2026, 11)
        r = day(rows, '2026-11-10')
        self.assertEqual(r.worked_minutes, 330)
        self.assertEqual(r.first_in, dt.datetime(2026, 11, 10, 22, 0))
        self.assertEqual(r.last_out, dt.datetime(2026, 11, 11, 3, 30))
        self.assertTrue(day(rows, '2026-11-11').no_punches)

    def test_custom_boundary(self):
        punches = [P('2026-11-11', '05:00'), P('2026-11-11', '14:00')]
        default = build_days(punches, B4, None, 2026, 11)
        self.assertEqual(day(default, '2026-11-11').punch_count, 2)
        moved = build_days(punches, dt.time(6, 0), None, 2026, 11)
        self.assertEqual(day(moved, '2026-11-10').punch_count, 1)
        self.assertEqual(day(moved, '2026-11-11').punch_count, 1)

    def test_punches_within_two_minutes_count_once(self):
        rows = build_days([P('2026-11-10', '09:00:00'), P('2026-11-10', '09:01:59')], B4, None, 2026, 11)
        r = day(rows, '2026-11-10')
        self.assertEqual(r.punch_count, 1)
        self.assertTrue(r.needs_review)
        self.assertEqual(r.worked_minutes, 0)
        self.assertEqual(len(r.raw), 2)
        self.assertEqual([x['counted'] for x in r.raw], [True, False])

    def test_two_minutes_apart_and_more_are_separate(self):
        rows = build_days([P('2026-11-10', '09:00:00'), P('2026-11-10', '09:02:01')], B4, None, 2026, 11)
        self.assertEqual(day(rows, '2026-11-10').punch_count, 2)

    def test_single_punch_needs_review_no_hours(self):
        r = day(build_days([P('2026-11-10', '09:00')], B4, Decimal('8'), 2026, 11), '2026-11-10')
        self.assertTrue(r.needs_review)
        self.assertEqual(r.worked_minutes, 0)
        self.assertIsNone(r.last_out)
        self.assertFalse(r.no_punches)

    def test_day_with_no_punches_is_no_punches_not_absent(self):
        rows = build_days([], B4, Decimal('8'), 2026, 11)
        self.assertTrue(all(r.no_punches for r in rows))
        self.assertEqual(len(rows), 30)
        blob = repr([dataclasses.asdict(r) for r in rows]) + repr(month_totals(rows))
        self.assertNotIn('absent', blob.lower())
        self.assertNotIn('غياب', blob)
        self.assertNotIn('absent', ' '.join(f.name for f in dataclasses.fields(days.DayRow)))

    def test_future_dates_are_not_no_punches(self):
        with mock.patch.object(days, '_today', return_value=dt.date(2026, 11, 10)):
            rows = build_days([], B4, None, 2026, 11)
        self.assertTrue(day(rows, '2026-11-10').no_punches)
        self.assertFalse(day(rows, '2026-11-11').no_punches)
        self.assertEqual(month_totals(rows).days_no_punches, 10)

    def test_machine_in_out_state_ignored(self):
        # machine says the early one is "out"(1) and the late one is "in"(0)
        rows = build_days([P('2026-11-10', '08:00', state=1), P('2026-11-10', '16:00', state=0)],
                          B4, None, 2026, 11)
        r = day(rows, '2026-11-10')
        self.assertEqual(r.first_in, dt.datetime(2026, 11, 10, 8, 0))
        self.assertEqual(r.last_out, dt.datetime(2026, 11, 10, 16, 0))
        self.assertEqual(r.worked_minutes, 480)

    def test_two_machines_combined(self):
        rows = build_days([P('2026-11-10', '08:00', machine='HQ'), P('2026-11-10', '17:00', machine='Store')],
                          B4, None, 2026, 11)
        r = day(rows, '2026-11-10')
        self.assertEqual(r.worked_minutes, 540)
        self.assertEqual(r.machines, ['HQ', 'Store'])
        self.assertEqual({x['machine'] for x in r.raw}, {'HQ', 'Store'})

    def test_flagged_and_unset_dates_excluded(self):
        rows = build_days([P('2026-11-10', '08:00', flag='bad_date'), P('2026-11-10', '16:00'),
                           SimpleNamespace(punch_date=None, punch_time=None, device=None, state=0, flag='')],
                          B4, None, 2026, 11)
        r = day(rows, '2026-11-10')
        self.assertEqual(r.punch_count, 1)
        self.assertEqual(len(r.raw), 1)

    def test_expected_hours(self):
        punches = [P(f'2026-11-{d:02d}', t) for d in (2, 3, 4, 5) for t in ('09:00', '17:00')]
        rows = build_days(punches, B4, Decimal('8.5'), 2026, 11)
        t = month_totals(rows)
        self.assertEqual(t.days_with_punches, 4)
        self.assertEqual(t.expected_hours, Decimal('34.00'))
        self.assertEqual(t.worked_hours, Decimal('32.00'))
        none_rows = build_days(punches, B4, None, 2026, 11)
        self.assertIsNone(month_totals(none_rows).expected_hours)

    def test_month_totals_counts(self):
        punches = [P('2026-11-02', '09:00'), P('2026-11-02', '17:30'), P('2026-11-03', '09:00')]
        t = month_totals(build_days(punches, B4, Decimal('8'), 2026, 11))
        self.assertEqual((t.days_with_punches, t.days_needing_review, t.days_no_punches), (2, 1, 28))
        self.assertEqual(t.worked_hours, Decimal('8.50'))
        self.assertEqual(t.expected_hours, Decimal('16.00'))

    def test_info_attached_but_totals_unchanged(self):
        info = {dt.date(2026, 11, 5): [{'kind': 'leave', 'label': 'سنوية'}]}
        with_info = build_days([], B4, Decimal('8'), 2026, 11, info)
        without = build_days([], B4, Decimal('8'), 2026, 11)
        self.assertEqual(day(with_info, '2026-11-05').info, [{'kind': 'leave', 'label': 'سنوية'}])
        self.assertTrue(day(with_info, '2026-11-05').no_punches)
        self.assertEqual(month_totals(with_info), month_totals(without))


class QueryHelperTests(TestCase):

    def setUp(self):
        self.branch = make_branch('فرع أ', 'B01')
        self.dev = AttendanceDevice.objects.create(serial='S1', name='HQ')
        self.emp = Employee.objects.create(hr_number='1001', name_ar='أحمد')
        self.other = Employee.objects.create(hr_number='1002', name_ar='سعيد')
        self._n = 0

    def punch(self, emp, date, time, **kw):
        self._n += 1
        y, m, d = map(int, date.split('-'))
        h, mi = map(int, time.split(':'))
        return AttendancePunch.objects.create(
            device=self.dev, user_code='1001', raw_stamp=1000 + self._n, employee=emp,
            punch_date=dt.date(y, m, d), punch_time=dt.time(h, mi), **kw)

    def test_flagged_and_unresolved_excluded(self):
        self.punch(self.emp, '2026-11-10', '09:00')
        self.punch(self.emp, '2026-11-10', '10:00', flag='bad_date')
        self.punch(None, '2026-11-10', '11:00')
        AttendancePunch.objects.create(device=self.dev, user_code='1001', raw_stamp=5, employee=self.emp,
                                       punch_date=None, punch_time=None, flag='bad_date')
        got = punches_for_month([self.emp.id, self.other.id], 2026, 11)
        self.assertEqual(len(got[self.emp.id]), 1)
        self.assertEqual(got[self.other.id], [])

    def test_month_window_includes_next_month_first_early_morning(self):
        self.punch(self.emp, '2026-11-30', '22:00')
        self.punch(self.emp, '2026-12-01', '02:00')
        self.punch(self.emp, '2026-12-02', '09:00')     # cannot belong to November
        self.punch(self.emp, '2026-10-31', '23:00')     # cannot belong to November
        got = punches_for_month([self.emp.id], 2026, 11)[self.emp.id]
        self.assertEqual(len(got), 2)
        rows = build_days(got, dt.time(4, 0), None, 2026, 11)
        self.assertEqual(day(rows, '2026-11-30').worked_minutes, 240)
        self.assertEqual(month_totals(rows).days_with_punches, 1)

    def test_query_count_is_constant(self):
        for i in range(5):
            self.punch(self.emp, f'2026-11-{i + 1:02d}', '09:00')
        with self.assertNumQueries(1):
            for p in punches_for_month([self.emp.id], 2026, 11)[self.emp.id]:
                p.device.name


class LeaveInfoTests(TestCase):

    def setUp(self):
        self.branch = make_branch('فرع أ', 'B01')
        _, self.profile, _ = make_user('lv_staff', role='pharmacist', branch=self.branch)
        self.by_staff = Employee.objects.create(hr_number='2001', name_ar='أ', staff=self.profile)
        self.by_code = Employee.objects.create(hr_number='2002', name_ar='ب')
        self.stranger = Employee.objects.create(hr_number='2003', name_ar='ج')
        self.ltype = LeaveType.objects.create(code='annual', name='Annual', name_ar='سنوية')

    def leave(self, status, start, end, **kw):
        return LeaveRequest.objects.create(
            leave_type=self.ltype, start_date=start, end_date=end, days_requested=1,
            status=status, **kw)

    def test_approved_leave_and_permit_shown_as_info_only(self):
        self.leave('approved', dt.date(2026, 10, 30), dt.date(2026, 11, 2), staff=self.profile)
        self.leave('approved', dt.date(2026, 11, 20), dt.date(2026, 11, 20), employee_hr_code='2002')
        Permit.objects.create(branch=self.branch, permit_type='mamoriya', date=dt.date(2026, 11, 9),
                              time_from=dt.time(10, 0), status='approved', employee_hr_code='2001')
        info = leave_info([self.by_staff, self.by_code, self.stranger], 2026, 11)
        a = info[self.by_staff.id]
        self.assertEqual(sorted(a), [dt.date(2026, 11, 1), dt.date(2026, 11, 2), dt.date(2026, 11, 9)])
        self.assertEqual(a[dt.date(2026, 11, 1)][0]['label'], 'سنوية')
        self.assertEqual(a[dt.date(2026, 11, 9)][0]['kind'], 'permit')
        self.assertEqual(list(info[self.by_code.id]), [dt.date(2026, 11, 20)])
        self.assertNotIn(self.stranger.id, info)

        # info never changes the figures
        rows = build_days([], dt.time(4, 0), Decimal('8'), 2026, 11, a)
        with mock.patch.object(days, '_today', return_value=dt.date(2026, 12, 31)):
            plain = build_days([], dt.time(4, 0), Decimal('8'), 2026, 11)
            rows = build_days([], dt.time(4, 0), Decimal('8'), 2026, 11, a)
        self.assertEqual(month_totals(rows), month_totals(plain))

    def test_pending_and_other_states_not_shown(self):
        for st in ('draft', 'submitted', 'rejected', 'cancelled'):
            self.leave(st, dt.date(2026, 11, 3), dt.date(2026, 11, 3), staff=self.profile)
        Permit.objects.create(branch=self.branch, permit_type='shift_change', date=dt.date(2026, 11, 4),
                              time_from=dt.time(10, 0), status='submitted', staff=self.profile)
        self.assertEqual(leave_info([self.by_staff], 2026, 11), {})

    def test_leave_outside_month_not_shown_and_no_double_listing(self):
        self.leave('approved', dt.date(2026, 12, 1), dt.date(2026, 12, 5), staff=self.profile)
        self.leave('approved', dt.date(2026, 11, 6), dt.date(2026, 11, 6), staff=self.profile,
                   employee_hr_code='2001')    # matches by login AND code: listed once
        info = leave_info([self.by_staff], 2026, 11)[self.by_staff.id]
        self.assertEqual(list(info), [dt.date(2026, 11, 6)])
        self.assertEqual(len(info[dt.date(2026, 11, 6)]), 1)
