"""Daily and monthly attendance figures, calculated on request from immutable punches.

DISPLAY ONLY (Stage 1): no pay, lateness, overtime or absence verdicts. A day with no punches is
``no_punches`` and never "absent". Everything here except the two query helpers is a pure function.

Rules (design 2026-11-07):
- Work day: a punch earlier than the employee's boundary (default 04:00) belongs to the previous
  date, so a 02:00 punch on the 1st counts in the previous month.
- First punch of the work day = in, last = out. The machine's own in/out state is never trusted.
- Punches within 2 minutes of each other count once for display; ``raw`` keeps all of them.
- A single (de-duplicated) punch needs review and contributes no hours.
- Flagged (bad date) and unresolved (no employee) punches are left out of every total.
- Approved leave / permits are information only; they never change a figure.
"""
import calendar
import datetime
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.db.models import Q
from django.utils import timezone

DUPLICATE_WINDOW_SECONDS = 120
_TWO_PLACES = Decimal('0.01')


def _today() -> datetime.date:
    return timezone.localdate()


DEFAULT_BOUNDARY = datetime.time(4, 0)


def effective_boundary(employee) -> datetime.time:
    """The cut-off used for employment-date eligibility: the employee's own, else 04:00. A null
    ``day_boundary`` means 'no personal cut-off' (Linked Gates sessions need none)."""
    return employee.day_boundary or DEFAULT_BOUNDARY


def work_date_for(punch_date: datetime.date, punch_time: datetime.time,
                  boundary: datetime.time) -> datetime.date:
    """The work date a punch belongs to: before the boundary means the previous calendar day."""
    if punch_time < boundary:
        return punch_date - datetime.timedelta(days=1)
    return punch_date


@dataclass
class DayRow:
    work_date: datetime.date
    first_in: Optional[datetime.datetime] = None
    last_out: Optional[datetime.datetime] = None
    worked_minutes: int = 0
    needs_review: bool = False
    no_punches: bool = False
    punch_count: int = 0                       # after the 2-minute duplicate merge
    machines: list = field(default_factory=list)   # distinct machine names, sorted
    raw: list = field(default_factory=list)        # every punch: {at, machine, state, counted}
    info: list = field(default_factory=list)       # approved leave / permits, display only
    daily_hours: Optional[Decimal] = None          # carried so month_totals(days) needs nothing else
    sessions: list = field(default_factory=list)   # work sessions on this date (session mode only)


@dataclass
class MonthTotals:
    days_with_punches: int
    worked_hours: Decimal
    expected_hours: Optional[Decimal]
    days_needing_review: int
    days_no_punches: int


def _usable(p) -> bool:
    return (not getattr(p, 'flag', '') and p.punch_date is not None and p.punch_time is not None)


def _machine_name(p) -> str:
    device = getattr(p, 'device', None)
    return getattr(device, 'name', '') or ''


def to_stamps(punches) -> list:
    """AttendancePunch-like objects -> Stamps (machine = device name). Flagged punches and punches
    with no date or time are left out. The machine's own in/out state is dropped."""
    from apps.hr.attendance.sessions import Stamp
    return [Stamp(at=datetime.datetime.combine(p.punch_date, p.punch_time), machine=_machine_name(p),
                  sources=frozenset({'machine'}))
            for p in punches if _usable(p)]


def _session_hours() -> tuple:
    """(gap_hours, max_shift_hours) from settings."""
    from django.conf import settings
    return (int(getattr(settings, 'HR_ATTENDANCE_SESSION_GAP_HOURS', 6)),
            int(getattr(settings, 'HR_ATTENDANCE_MAX_SHIFT_HOURS', 16)))


def build_days(stamps, boundary, daily_hours, year, month, info_by_date=None):
    """One DayRow for every date of the month (oldest first). ``stamps`` is a list of ``Stamp``.
    A ``boundary`` time cuts work days at that time; ``None`` groups the stamps into work sessions."""
    from apps.hr.attendance import sessions as sess
    info_by_date = info_by_date or {}
    today = _today()
    last_day = calendar.monthrange(year, month)[1]
    first = datetime.date(year, month, 1)
    last = datetime.date(year, month, last_day)

    by_date: dict = {}
    sessions_by_date: dict = {}
    if boundary is None:
        for s in sess.build_sessions(stamps, *_session_hours()):
            if first <= s.work_date <= last:
                sessions_by_date.setdefault(s.work_date, []).append(s)
    else:
        for st in stamps:
            wd = work_date_for(st.at.date(), st.at.time(), boundary)
            if first <= wd <= last:
                by_date.setdefault(wd, []).append(st)

    rows = []
    for offset in range(last_day):
        d = first + datetime.timedelta(days=offset)
        row = DayRow(work_date=d, info=list(info_by_date.get(d, [])), daily_hours=daily_hours)
        if boundary is None:
            day_sessions = sessions_by_date.get(d)
            if not day_sessions:
                row.no_punches = d <= today
            else:
                _fill_from_sessions(row, day_sessions)
            rows.append(row)
            continue

        day_stamps = by_date.get(d)
        if not day_stamps:
            row.no_punches = d <= today
            rows.append(row)
            continue

        counted_at = []
        raw = []
        for st in sorted(day_stamps, key=lambda s: s.at):
            counted = not counted_at or (st.at - counted_at[-1]).total_seconds() > DUPLICATE_WINDOW_SECONDS
            if counted:
                counted_at.append(st.at)
            raw.append({'at': st.at, 'machine': st.machine, 'state': None, 'counted': counted})
        row.raw = raw
        row.punch_count = len(counted_at)
        row.machines = sorted({r['machine'] for r in raw if r['machine']})
        row.first_in = counted_at[0]
        row.last_out = counted_at[-1] if len(counted_at) > 1 else None
        if row.punch_count == 1:
            row.needs_review = True
        else:
            row.worked_minutes = int((counted_at[-1] - counted_at[0]).total_seconds() // 60)
        rows.append(row)
    return rows


def _fill_from_sessions(row, day_sessions):
    """Fill a DayRow from that date's sessions (already ordered by time)."""
    stamps = [st for s in day_sessions for st in s.stamps]
    row.sessions = list(day_sessions)
    row.raw = [{'at': st.at, 'machine': st.machine, 'state': None, 'counted': True} for st in stamps]
    row.punch_count = len(stamps)
    row.machines = sorted({st.machine for st in stamps if st.machine})
    row.first_in = day_sessions[0].first_in
    row.last_out = day_sessions[-1].last_out
    row.worked_minutes = sum(s.worked_minutes for s in day_sessions)
    row.needs_review = any(s.needs_review for s in day_sessions)


def month_totals(days) -> MonthTotals:
    with_punches = [d for d in days if d.punch_count > 0]
    minutes = sum(d.worked_minutes for d in with_punches)
    worked = (Decimal(minutes) / Decimal(60)).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    daily = next((d.daily_hours for d in days if d.daily_hours is not None), None)
    expected = None
    if daily is not None:
        expected = (Decimal(daily) * len(with_punches)).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    return MonthTotals(
        days_with_punches=len(with_punches),
        worked_hours=worked,
        expected_hours=expected,
        days_needing_review=sum(1 for d in days if d.needs_review),
        days_no_punches=sum(1 for d in days if d.no_punches),
    )


MANUAL_MACHINE = 'يدوي'     # a Linked Gates punch typed in by hand (no device)


def default_sources() -> tuple:
    """Machine punches always; Linked Gates only while its switch is on."""
    from django.conf import settings
    if getattr(settings, 'HR_ATTENDANCE_LINKEDGATES_ENABLED', False):
        return ('machine', 'lg')
    return ('machine',)


def punches_for_month(employee_ids, year, month, lead_days: int = 0, sources=None) -> dict:
    """{employee_id: [Stamp]} for resolved, unflagged punches that can fall in the month's work days,
    merged across sources (120 s fold, sources united). A work date is never later than the punch
    date, so the window is the month's first day through the day after its last (a 02:00 punch on the
    1st of next month still belongs here). Callers pass each list to ``build_days``, which drops
    anything outside the month. ``lead_days`` also reads that many days BEFORE the month, so a
    session that began last month and ends in this one is not mistaken for a lone stamp.
    ``sources`` defaults from the Linked Gates switch; Linked Gates rows used are current ones only."""
    from apps.hr.attendance.sessions import Stamp, merge_stamps
    from apps.hr.models import AttendancePunch, LinkedGatesDevice, LinkedGatesPunch

    if sources is None:
        sources = default_sources()
    employee_ids = list(employee_ids)
    first = datetime.date(year, month, 1) - datetime.timedelta(days=lead_days)
    last = datetime.date(year, month, calendar.monthrange(year, month)[1]) + datetime.timedelta(days=1)
    collected: dict = {eid: [] for eid in employee_ids}

    if 'machine' in sources:
        qs = (AttendancePunch.objects
              .filter(employee_id__in=employee_ids, flag='', punch_date__gte=first, punch_date__lte=last,
                      punch_time__isnull=False)
              .select_related('device'))
        for p in qs:
            for st in to_stamps([p]):
                collected[p.employee_id].append(st)

    if 'lg' in sources:
        tz = timezone.get_current_timezone()
        start = timezone.make_aware(datetime.datetime.combine(first, datetime.time.min), tz)
        end = timezone.make_aware(datetime.datetime.combine(last + datetime.timedelta(days=1),
                                                            datetime.time.min), tz)
        devices = {d.lg_device_id: d for d in LinkedGatesDevice.objects.select_related('device')}
        qs = LinkedGatesPunch.objects.filter(
            employee_id__in=employee_ids, superseded_at__isnull=True, lg_removed=False, flag='',
            check_time__gte=start, check_time__lt=end)
        for p in qs:
            dev = devices.get(p.lg_device_id) if p.lg_device_id is not None else None
            if dev is None:
                machine = MANUAL_MACHINE
            else:
                machine = (dev.device.name if dev.device_id else '') or dev.name or MANUAL_MACHINE
            at = timezone.localtime(p.check_time, tz).replace(tzinfo=None)
            collected[p.employee_id].append(Stamp(at=at, machine=machine, sources=frozenset({'lg'})))

    return {eid: merge_stamps(stamps) for eid, stamps in collected.items()}


def month_rows(employees, year, month, with_leave=False):
    """[(employee, [DayRow], MonthTotals)] — the one place the month screen and the Excel export
    take their day and total figures from, so the two cannot disagree. ``with_leave`` fills each
    day's ``info`` with approved leave / permits (display only; totals never change)."""
    employees = list(employees)
    punches = punches_for_month([e.pk for e in employees], year, month, lead_days=1)
    info = leave_info(employees, year, month) if with_leave else {}
    out = []
    for e in employees:
        rows = build_days(punches.get(e.pk, []), e.day_boundary, e.daily_hours, year, month,
                          info.get(e.pk))
        out.append((e, rows, month_totals(rows)))
    return out


def leave_info(employees, year, month) -> dict:
    """{employee_id: {date: [info]}} for APPROVED leave and permits in the month, matched to the
    employee by linked login (``staff``) or by HR code. Information only; pending, draft, rejected
    and cancelled requests are never shown."""
    from apps.hr.models import LeaveRequest, Permit

    employees = list(employees)
    first = datetime.date(year, month, 1)
    last = datetime.date(year, month, calendar.monthrange(year, month)[1])
    by_staff = {e.staff_id: e.id for e in employees if e.staff_id}
    by_code = {e.hr_number: e.id for e in employees if e.hr_number}
    if not by_staff and not by_code:
        return {}

    match = Q()
    if by_staff:
        match |= Q(staff_id__in=list(by_staff))
    if by_code:
        match |= Q(employee_hr_code__in=list(by_code))

    def owner(req):
        return by_staff.get(req.staff_id) or by_code.get(req.employee_hr_code)

    out: dict = {}

    def add(emp_id, day, item):
        out.setdefault(emp_id, {}).setdefault(day, []).append(item)

    leaves = (LeaveRequest.objects
              .filter(match, status='approved', start_date__lte=last, end_date__gte=first)
              .select_related('leave_type'))
    for req in leaves:
        emp_id = owner(req)
        if emp_id is None:
            continue
        day = max(req.start_date, first)
        end = min(req.end_date, last)
        while day <= end:
            add(emp_id, day, {'kind': 'leave', 'label': req.leave_type.name_ar, 'id': req.id})
            day += datetime.timedelta(days=1)

    permits = Permit.objects.filter(match, status='approved', date__gte=first, date__lte=last)
    for req in permits:
        emp_id = owner(req)
        if emp_id is None:
            continue
        add(emp_id, req.date, {'kind': 'permit', 'label': req.get_permit_type_display(), 'id': req.id,
                               'time_from': req.time_from, 'time_to': req.time_to})
    return out
