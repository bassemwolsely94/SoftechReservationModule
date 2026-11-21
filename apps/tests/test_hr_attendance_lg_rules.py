"""
apps/tests/test_hr_attendance_lg_rules.py

Linked Gates' own day rules (its CheckIn / CheckOut SQL views), recomputed by us from the copied
punches. Each test is one of the losses listed in the design (2026-11-20, section 2).
"""
import datetime as dt
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.utils import timezone

from apps.hr.attendance.lg_rules import LgDay, lg_days

D = dt.date(2026, 11, 10)
D1 = dt.date(2026, 11, 11)


def P(date, time, device=1, mode=0, aware=False):
    """A LinkedGatesPunch stand-in."""
    y, m, d = map(int, date.split('-'))
    h, mi, *s = map(int, time.split(':'))
    at = dt.datetime(y, m, d, h, mi, *(s or [0]))
    if aware:
        at = timezone.make_aware(at)
    return SimpleNamespace(check_time=at, lg_device_id=device, in_out_mode=mode)


def at(date, time):
    y, m, d = map(int, date.split('-'))
    h, mi = map(int, time.split(':'))
    return dt.datetime(y, m, d, h, mi)


class LgRulesTests(SimpleTestCase):

    def test_type1_window(self):
        got = lg_days([P('2026-11-10', '06:30'), P('2026-11-10', '08:00'), P('2026-11-10', '16:00')], 1)
        self.assertEqual(got, {D: LgDay(D, [at('2026-11-10', '08:00')], at('2026-11-10', '16:00'))})

    def test_type2_window(self):
        got = lg_days([P('2026-11-10', '09:00'), P('2026-11-10', '22:00')], 2)
        self.assertEqual(got, {D: LgDay(D, [at('2026-11-10', '09:00')], at('2026-11-10', '22:00'))})

    def test_type1_window_edges(self):
        # 07:00 and 14:00:59 are inside the in window (seconds ignored); 14:01 is the first out.
        got = lg_days([P('2026-11-10', '07:00'), P('2026-11-10', '14:00:59')], 1)
        self.assertEqual(got[D].in_times, [at('2026-11-10', '07:00')])
        self.assertIsNone(got[D].out_time)
        got = lg_days([P('2026-11-10', '06:59'), P('2026-11-10', '14:01')], 1)
        self.assertEqual(got[D].in_times, [])
        self.assertEqual(got[D].out_time, at('2026-11-10', '14:01'))

    def test_after_midnight_out_moves_back(self):
        got = lg_days([P('2026-11-10', '16:00'), P('2026-11-11', '00:30')], 1)
        self.assertEqual(got[D].out_time, at('2026-11-11', '00:30'))
        self.assertNotIn(D1, got)

    def test_midnight_exactly_and_two_am_are_not_outs(self):
        got = lg_days([P('2026-11-11', '00:00'), P('2026-11-11', '02:00')], 1)
        self.assertEqual(got, {})

    def test_out_hidden(self):
        # On D+1 the 16:00 / 23:00 punches make the MAX of that date 23:00, so the 00:30 is not moved
        # back: D loses its after-midnight out. (Type 1: D's own 16:00 is then D's out, exactly as the
        # view computes; a type 2 person with D 15:00 has no out at all.)
        punches = [P('2026-11-10', '16:00'), P('2026-11-11', '00:30'),
                   P('2026-11-11', '16:00'), P('2026-11-11', '23:00')]
        got = lg_days(punches, 1)
        self.assertEqual(got[D].out_time, at('2026-11-10', '16:00'))
        self.assertEqual(got[D1].out_time, at('2026-11-11', '23:00'))
        got = lg_days([P('2026-11-10', '15:00'), P('2026-11-11', '00:30'),
                       P('2026-11-11', '16:00'), P('2026-11-11', '23:00')], 2)
        self.assertEqual(got[D].in_times, [at('2026-11-10', '15:00')])
        self.assertIsNone(got[D].out_time)
        self.assertEqual(got[D1].out_time, at('2026-11-11', '23:00'))

    def test_no_shifttype(self):
        self.assertEqual(lg_days([P('2026-11-10', '08:00'), P('2026-11-10', '16:00')], None), {})
        self.assertEqual(lg_days([P('2026-11-10', '08:00')], 3), {})

    def test_multi_in_device_mode(self):
        got = lg_days([P('2026-11-10', '08:00', device=1, mode=0),
                       P('2026-11-10', '08:05', device=2, mode=0)], 1)
        self.assertEqual(got[D].in_times, [at('2026-11-10', '08:00'), at('2026-11-10', '08:05')])
        got = lg_days([P('2026-11-10', '08:00', mode=0), P('2026-11-10', '08:05', mode=1)], 1)
        self.assertEqual(len(got[D].in_times), 2)
        got = lg_days([P('2026-11-10', '08:00'), P('2026-11-10', '08:05')], 1)
        self.assertEqual(got[D].in_times, [at('2026-11-10', '08:00')])

    def test_night_split(self):
        got = lg_days([P('2026-11-10', '23:00'), P('2026-11-11', '08:00')], 2)
        self.assertEqual(got[D], LgDay(D, [], at('2026-11-10', '23:00')))
        self.assertEqual(got[D1], LgDay(D1, [at('2026-11-11', '08:00')], None))

    def test_out_per_device_takes_latest(self):
        got = lg_days([P('2026-11-10', '16:00', device=1), P('2026-11-10', '17:00', device=2)], 1)
        self.assertEqual(got[D].out_time, at('2026-11-10', '17:00'))

    def test_aware_times_read_in_cairo(self):
        got = lg_days([P('2026-11-10', '08:00', aware=True), P('2026-11-11', '00:30', aware=True)], 1)
        self.assertEqual(got[D].in_times, [at('2026-11-10', '08:00')])
        self.assertEqual(got[D].out_time, at('2026-11-11', '00:30'))

    def test_minutes(self):
        self.assertEqual(LgDay(D, [at('2026-11-10', '08:00')], at('2026-11-10', '16:30')).minutes, 510)
        self.assertEqual(LgDay(D, [], at('2026-11-10', '16:30')).minutes, 0)
