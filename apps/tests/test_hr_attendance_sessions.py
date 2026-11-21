"""
apps/tests/test_hr_attendance_sessions.py

HR Attendance: work-session day grouping (Linked Gates design 2026-11-20 §5.3). Pure functions.
"""
import datetime as dt
from unittest import mock

from django.test import SimpleTestCase

from apps.hr.attendance import days
from apps.hr.attendance.sessions import Stamp, build_sessions, merge_stamps

D = dt.date(2026, 11, 10)


def S(day_offset, hhmm, machine='A', sources=('machine',), base=D):
    h, m, *sec = map(int, hhmm.split(':'))
    at = dt.datetime.combine(base + dt.timedelta(days=day_offset), dt.time(h, m, *(sec or [0])))
    return Stamp(at, machine, frozenset(sources))


class SessionTests(SimpleTestCase):

    def one(self, stamps):
        sessions = build_sessions(stamps)
        self.assertEqual(len(sessions), 1)
        return sessions[0]

    def test_morning(self):
        s = self.one([S(0, '08:00'), S(0, '16:00')])
        self.assertEqual((s.work_date, s.worked_minutes, s.needs_review), (D, 480, False))

    def test_evening_past_midnight(self):
        s = self.one([S(0, '16:00'), S(1, '00:30')])
        self.assertEqual((s.work_date, s.worked_minutes), (D, 510))

    def test_night_shift(self):
        s = self.one([S(0, '23:00'), S(1, '08:00')])
        self.assertEqual((s.work_date, s.worked_minutes), (D, 540))

    def test_lone_after_midnight(self):
        s = self.one([S(1, '00:40')])
        self.assertEqual(s.work_date, D)
        self.assertTrue(s.needs_review)
        self.assertEqual(s.worked_minutes, 0)
        self.assertIsNone(s.last_out)

    def test_manager_pairs(self):
        s = self.one([S(0, '09:00'), S(0, '12:00'), S(0, '13:00'), S(0, '18:00')])
        self.assertEqual(s.worked_minutes, 480)
        self.assertFalse(s.needs_review)

    def test_odd_punches(self):
        s = self.one([S(0, '09:00'), S(0, '12:00'), S(0, '13:00')])
        self.assertEqual(s.worked_minutes, 180)
        self.assertTrue(s.needs_review)

    def test_split_shift_gap(self):
        sessions = build_sessions([S(0, '08:00'), S(0, '12:00'), S(0, '19:00'), S(0, '23:00')])
        self.assertEqual(len(sessions), 2)
        self.assertEqual([s.work_date for s in sessions], [D, D])
        self.assertEqual(sum(s.worked_minutes for s in sessions), 480)

    def test_gap_of_exactly_six_hours_stays_together(self):
        self.assertEqual(len(build_sessions([S(0, '08:00'), S(0, '14:00')])), 1)

    def test_forgotten_checkout_next_day(self):
        sessions = build_sessions([S(0, '08:00'), S(1, '08:00'), S(1, '16:00')])
        self.assertEqual(len(sessions), 2)
        self.assertEqual((sessions[0].work_date, sessions[0].needs_review, sessions[0].worked_minutes),
                         (D, True, 0))
        self.assertEqual((sessions[1].work_date, sessions[1].worked_minutes), (dt.date(2026, 11, 11), 480))

    def test_double_shift_16h(self):
        s = self.one([S(0, '08:00'), S(1, '00:00')])
        self.assertEqual(s.worked_minutes, 960)

    def test_duplicate_window(self):
        merged = merge_stamps([S(0, '08:00:00'), S(0, '08:01:30')])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].at, dt.datetime(2026, 11, 10, 8, 0))

    def test_duplicate_unites_sources(self):
        merged = merge_stamps([S(0, '08:00:00', sources=('machine',)), S(0, '08:01:00', sources=('lg',))])
        self.assertEqual(merged[0].sources, frozenset({'machine', 'lg'}))

    def test_two_machines(self):
        s = self.one([S(0, '08:00', machine='A'), S(0, '16:00', machine='B')])
        self.assertEqual([st.machine for st in s.stamps], ['A', 'B'])


    def test_long_pair_needs_review(self):
        # A forgotten check-out at 16:30 pairs with the next morning: 15.5 h is no real pair.
        s = self.one([S(0, '08:00'), S(0, '16:00'), S(0, '16:30'), S(1, '08:00')])
        self.assertTrue(s.needs_review)
        self.assertEqual(s.worked_minutes, 480 + 930)

    def test_long_pair_threshold(self):
        twelve = self.one([S(0, '08:00'), S(0, '20:00')])               # exactly 12 h: fine
        self.assertFalse(twelve.needs_review)
        longer = self.one([S(0, '08:00'), S(0, '20:01')])
        self.assertTrue(longer.needs_review)
        relaxed = build_sessions([S(0, '08:00'), S(0, '20:01')], long_pair_hours=13)
        self.assertFalse(relaxed[0].needs_review)

    def test_long_pair_setting_reaches_days(self):
        with self.settings(HR_ATTENDANCE_LONG_PAIR_HOURS=20):
            self.assertEqual(days._session_hours()[2], 20)

class SessionDaysTests(SimpleTestCase):

    def setUp(self):
        p = mock.patch.object(days, '_today', return_value=dt.date(2026, 12, 31))
        p.start()
        self.addCleanup(p.stop)

    def test_month_edge_night_session(self):
        stamps = [S(0, '23:00', base=dt.date(2026, 11, 30)), S(1, '08:00', base=dt.date(2026, 11, 30))]
        nov = days.build_days(stamps, None, None, 2026, 11)
        dec = days.build_days(stamps, None, None, 2026, 12)
        r = nov[-1]
        self.assertEqual((r.work_date, r.worked_minutes, r.needs_review), (dt.date(2026, 11, 30), 540, False))
        self.assertEqual(len(r.sessions), 1)
        self.assertEqual(sum(d.punch_count for d in dec), 0)
        self.assertTrue(dec[0].no_punches)

    def test_row_aggregates_sessions(self):
        rows = days.build_days([S(0, '08:00'), S(0, '12:00'), S(0, '19:00')], None, None, 2026, 11)
        r = rows[9]
        self.assertEqual(r.worked_minutes, 240)
        self.assertTrue(r.needs_review)
        self.assertEqual(r.first_in, dt.datetime(2026, 11, 10, 8, 0))
        self.assertEqual(len(r.sessions), 2)

    def test_fixed_boundary_still_works(self):
        stamps = [S(0, '22:00'), S(1, '03:30')]
        rows = days.build_days(stamps, dt.time(6, 0), None, 2026, 11)
        self.assertEqual(rows[9].worked_minutes, 330)
        self.assertEqual(rows[9].sessions, [])
        self.assertTrue(rows[10].no_punches)
