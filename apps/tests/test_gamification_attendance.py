"""
apps/tests/test_gamification_attendance.py — attendance points (owner decision 2026-11-22).

On time / late / early leave / missing punch / absent, judged from HR punches against the
person's shift. Guards: no linked HR employee or no shift → no verdict; no machine data through
the next day → no verdict (never a false absence); approved leave skips the day; an approved
permit skips late / early / missing punch; overnight shifts; idempotent re-runs; HR data
untouched; the on-time team-challenge metric.
"""
import datetime as dt
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.gamification import attendance as A
from apps.gamification import challenges as T
from apps.gamification import engine
from apps.gamification.defaults import ensure_defaults
from apps.gamification.models import PointEvent, TeamChallenge
from apps.hr.models import (AttendanceDevice, AttendancePunch, CollectionRun, Employee,
                            LeaveRequest, LeaveType, Permit, ShiftAssignment, ShiftTemplate)
from apps.tests.factories import make_branch, make_user

STAMP = [0]


def _rules(staff):
    return sorted(PointEvent.objects.filter(staff=staff, category='attendance')
                  .values_list('rule_key', flat=True))


@override_settings(GAMIFICATION_ATTENDANCE_GRACE_MINUTES=10)
class AttendancePointsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_defaults()
        cls.b = make_branch()
        cls.day = timezone.localdate() - dt.timedelta(days=1)
        cls.weekday = A.WEEKDAYS[cls.day.weekday()]
        cls.device = AttendanceDevice.objects.create(serial='GAM1', name='جهاز', branch=cls.b)
        cls.shift = ShiftTemplate.objects.create(name='Morning', name_ar='صباحي', branch=cls.b,
                                                 start_time=dt.time(9, 0), end_time=dt.time(17, 0),
                                                 days_of_week=cls.weekday)

    def _person(self, name, shift=None):
        _, staff, _ = make_user(name, role='pharmacist', branch=self.b)
        emp = Employee.objects.create(hr_number=f'HR-{name}', name_ar=name, branch=self.b, staff=staff)
        if shift is not False:
            ShiftAssignment.objects.create(staff=staff, shift=shift or self.shift,
                                           valid_from=self.day - dt.timedelta(days=30))
        return staff, emp

    def _punch(self, emp, hh, mm, day=None):
        STAMP[0] += 1
        return AttendancePunch.objects.create(device=self.device, user_code=emp.hr_number,
                                              raw_stamp=STAMP[0], punch_date=day or self.day,
                                              punch_time=dt.time(hh, mm), employee=emp)

    def _collected(self, through=None):
        CollectionRun.objects.create(device=self.device, started_at=timezone.now(), status='success',
                                     finished_at=timezone.now(),
                                     newest_date=through or self.day + dt.timedelta(days=1))

    def _judge(self):
        return A.judge_day(engine.Scorer(), self.day)

    def test_on_time_late_early_missing(self):
        s1, e1 = self._person('att_ok')
        s2, e2 = self._person('att_late')
        s3, e3 = self._person('att_early')
        s4, e4 = self._person('att_single')
        self._punch(e1, 9, 5); self._punch(e1, 17, 2)
        self._punch(e2, 9, 25); self._punch(e2, 17, 0)
        self._punch(e3, 8, 55); self._punch(e3, 16, 30)
        self._punch(e4, 9, 0)
        self._collected()
        self._judge()
        self.assertEqual(_rules(s1), ['attendance_on_time'])
        self.assertEqual(_rules(s2), ['attendance_late'])
        self.assertEqual(_rules(s3), ['attendance_early_leave'])
        self.assertEqual(_rules(s4), ['attendance_missing_punch'])
        pts = PointEvent.objects.get(staff=s2, rule_key='attendance_late')
        self.assertEqual((pts.points, pts.day, pts.meta['first_in']), (-2, self.day, '09:25'))

    def test_absent_only_when_machine_reported(self):
        s, e = self._person('att_abs')
        self._judge()                                         # no collection run yet
        self.assertEqual(_rules(s), [])
        self._collected(through=self.day)                     # data only up to the day itself
        self._judge()
        self.assertEqual(_rules(s), [])
        self._collected()                                     # data through the next day
        self._judge()
        self.assertEqual(_rules(s), ['attendance_absent'])
        self.assertEqual(PointEvent.objects.get(staff=s).points, -3)

    def test_no_link_or_no_shift_means_no_verdict(self):
        _, unlinked, _ = make_user('att_nolink', role='pharmacist', branch=self.b)
        ShiftAssignment.objects.create(staff=unlinked, shift=self.shift, valid_from=self.day)
        s, e = self._person('att_noshift', shift=False)
        off = ShiftTemplate.objects.create(name='Off', name_ar='راحة', branch=self.b,
                                           start_time=dt.time(9), end_time=dt.time(17),
                                           days_of_week='xxx')
        s2, e2 = self._person('att_offday', shift=off)
        self._collected()
        self._judge()
        self.assertFalse(PointEvent.objects.filter(category='attendance').exists())

    def test_leave_and_permit(self):
        s1, e1 = self._person('att_leave')
        s2, e2 = self._person('att_permit')
        lt = LeaveType.objects.create(code='annual', name='Annual', name_ar='اعتيادية')
        LeaveRequest.objects.create(staff=s1, leave_type=lt, start_date=self.day, end_date=self.day,
                                    days_requested=Decimal('1'), status='approved')
        Permit.objects.create(staff=s2, branch=self.b, permit_type='mission_permit', date=self.day,
                              time_from=dt.time(9, 0), status='approved')
        self._punch(e2, 11, 0); self._punch(e2, 17, 0)        # late, but on an approved permit
        self._collected()
        self._judge()
        self.assertEqual(_rules(s1), [])                      # absent, but on approved leave
        self.assertEqual(_rules(s2), [])

    def test_overnight_shift(self):
        night = ShiftTemplate.objects.create(name='Night', name_ar='ليلي', branch=self.b,
                                             start_time=dt.time(22, 0), end_time=dt.time(6, 0),
                                             days_of_week=self.weekday)
        s, e = self._person('att_night', shift=night)
        self._punch(e, 22, 5)
        self._punch(e, 5, 58, day=self.day + dt.timedelta(days=1))   # before the 04:00 boundary? no
        self._collected(through=self.day + dt.timedelta(days=2))
        self._judge()
        # the 05:58 punch is after the 04:00 work-day boundary → it belongs to the next work day,
        # so this day has a single punch: the HR boundary rule decides, not gamification
        self.assertEqual(_rules(s), ['attendance_missing_punch'])
        Employee.objects.filter(pk=e.pk).update(day_boundary=dt.time(8, 0))
        PointEvent.objects.filter(staff=s).delete()
        self._judge()
        self.assertEqual(_rules(s), ['attendance_on_time'])

    def test_idempotent_and_hr_data_untouched(self):
        s, e = self._person('att_idem')
        p1 = self._punch(e, 9, 40)
        self._punch(e, 17, 0)
        self._collected()
        self._judge()
        self._judge()
        self.assertEqual(PointEvent.objects.filter(staff=s, category='attendance').count(), 1)
        p1.refresh_from_db()
        self.assertEqual(p1.punch_time, dt.time(9, 40))

    def test_engine_run_judges_recent_days_and_challenge_metric(self):
        s1, e1 = self._person('att_r1')
        s2, e2 = self._person('att_r2')
        self._punch(e1, 9, 0); self._punch(e1, 17, 0)
        self._punch(e2, 9, 30); self._punch(e2, 17, 0)
        self._collected()
        engine.run(days=0, finalize=False)
        self.assertEqual(_rules(s1), ['attendance_on_time'])
        self.assertEqual(_rules(s2), ['attendance_late'])
        ch = TeamChallenge.objects.create(name_ar='انضباط', name_en='Punctual', metric='on_time_rate',
                                          target=Decimal('50'), start=self.day, end=self.day)
        T.evaluate(ch)
        res = ch.results.get(branch=self.b)
        self.assertEqual(res.value, Decimal('50.00'))
        self.assertTrue(res.achieved)
