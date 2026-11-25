"""
apps/gamification/attendance.py — attendance points (الحضور والانصراف).

Owner decision 2026-11-22: gamification applies lateness rules ("full lateness rules"). The HR
attendance screens stay DISPLAY ONLY as designed (apps/hr/attendance/days.py, 2026-11-07); the
verdicts live here, reuse the HR day logic and never change a punch or an HR figure.

A person's day is judged only when ALL hold:
  • an HR Employee is linked to their staff account (Employee.staff), active on that date;
  • a ShiftAssignment covers that date (valid range + days_of_week, shift active) — no shift,
    no verdict;
  • a machine of their branch reported data THROUGH the next day (a successful CollectionRun with
    newest_date > day), so an upload that has not happened yet is never an absence;
  • no approved leave that day (an approved permit skips late / early / missing-punch checks).
Day rows come from apps.hr.attendance.days.build_days (work-day boundary, 2-minute duplicate
merge, single punch = needs review); approved leave / permits from days.leave_info.

  attendance_on_time       first in ≤ start + grace and last out ≥ end − grace
  attendance_late          first in > start + grace
  attendance_early_leave   last out < end − grace
  attendance_missing_punch a single punch (in or out missing)
  attendance_absent        scheduled, no punches, machine data present, no approved leave
Grace = GAMIFICATION_ATTENDANCE_GRACE_MINUTES (10). Punches are immutable, so unlike open-item
penalties these are re-checked for the last GAMIFICATION_ATTENDANCE_LOOKBACK_DAYS (3) days on
every run (late machine uploads still count); one event per person, day and rule.
"""
import datetime
import logging

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']


def grace():
    return datetime.timedelta(minutes=int(getattr(settings, 'GAMIFICATION_ATTENDANCE_GRACE_MINUTES', 10)))


def lookback_days():
    return int(getattr(settings, 'GAMIFICATION_ATTENDANCE_LOOKBACK_DAYS', 3))


def shift_covers(assignment, day):
    """Pure: does this assignment's shift apply on `day`?"""
    shift = assignment.shift
    if not shift.is_active or assignment.valid_from > day:
        return False
    if assignment.valid_until is not None and assignment.valid_until < day:
        return False
    days = [d.strip().lower() for d in (shift.days_of_week or '').split(',') if d.strip()]
    return WEEKDAYS[day.weekday()] in days


def shift_window(shift, day):
    """(start, end) as aware datetimes; an overnight shift ends on the next day."""
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.datetime.combine(day, shift.start_time), tz)
    end_day = day if shift.end_time > shift.start_time else day + datetime.timedelta(days=1)
    end = timezone.make_aware(datetime.datetime.combine(end_day, shift.end_time), tz)
    return start, end


def verdict(row, start, end, info):
    """Pure: the rule keys earned for one DayRow. `info` = approved leave / permits that day."""
    if any(i.get('kind') == 'leave' for i in info):
        return []
    permit = any(i.get('kind') == 'permit' for i in info)
    if row.no_punches:
        return ['attendance_absent']
    if row.needs_review:
        return [] if permit else ['attendance_missing_punch']
    tz = timezone.get_current_timezone()
    first_in = timezone.make_aware(row.first_in, tz)
    last_out = timezone.make_aware(row.last_out, tz)
    late = first_in > start + grace()
    early = last_out < end - grace()
    if permit and (late or early):
        return []
    out = []
    if late:
        out.append('attendance_late')
    if early:
        out.append('attendance_early_leave')
    return out or ['attendance_on_time']


def judge_day(sc, day, judged=None):
    """Award / deduct attendance points for `day` (idempotent: source key per person and day).
    Adds (staff_id, day) to `judged` for every new event, so the caller can refresh DailyScore."""
    judged = set() if judged is None else judged
    from apps.hr.attendance.days import build_days, leave_info, punches_for_month
    from apps.hr.models import CollectionRun, Employee, ShiftAssignment
    from .engine import _at

    employees = [e for e in Employee.objects.filter(staff__isnull=False, status='active')
                 .filter(Q(start_date__isnull=True) | Q(start_date__lte=day))
                 .filter(Q(end_date__isnull=True) | Q(end_date__gte=day))
                 .select_related('staff')
                 if e.staff_id in sc.staff]
    if not employees:
        return 0
    shifts = {}
    for a in (ShiftAssignment.objects.filter(staff_id__in=[e.staff_id for e in employees],
                                             valid_from__lte=day)
              .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=day))
              .select_related('shift').order_by('valid_from', 'id')):
        if shift_covers(a, day):
            shifts[a.staff_id] = a.shift             # the latest covering assignment wins
    employees = [e for e in employees if e.staff_id in shifts]
    if not employees:
        return 0
    covered = set(CollectionRun.objects.filter(status='success', newest_date__gt=day,
                                               device__is_active=True)
                  .values_list('device__branch_id', flat=True))
    employees = [e for e in employees if (e.branch_id or e.staff.branch_id) in covered]
    if not employees:
        return 0
    punches = punches_for_month([e.id for e in employees], day.year, day.month)
    leave = leave_info(employees, day.year, day.month)
    n = 0
    for e in employees:
        rows = build_days(punches.get(e.id, []), e.day_boundary, e.daily_hours, day.year, day.month)
        row = rows[day.day - 1]
        start, end = shift_window(shifts[e.staff_id], day)
        for rule in verdict(row, start, end, leave.get(e.id, {}).get(day, [])):
            meta = {'shift_start': start.strftime('%H:%M'), 'shift_end': end.strftime('%H:%M')}
            if row.first_in:
                meta['first_in'] = row.first_in.strftime('%H:%M')
            if row.last_out:
                meta['last_out'] = row.last_out.strftime('%H:%M')
            if sc.award(e.staff, rule, f'att:{day}', _at(day), branch_id=e.branch_id, meta=meta):
                n += 1
                judged.add((e.staff_id, day))
    return n


def judge_recent(sc, today=None):
    """Called from engine.run: re-check the last few closed days as machine data arrives.
    Returns {(staff_id, day)} that got a new event."""
    today = today or timezone.localdate()
    judged = set()
    for i in range(1, lookback_days() + 1):
        try:
            judge_day(sc, today - datetime.timedelta(days=i), judged)
        except Exception as exc:          # attendance must never break the rest of the run
            logger.exception('gamification attendance failed for %s: %s',
                             today - datetime.timedelta(days=i), exc)
    return judged
