"""The Linked Gates trial comparison (design 2026-11-20 §5.4). Read-only; display only.

Two views of the same month:
- per machine and day, how each punch compares across the two sources (``machine_day_counts`` and
  ``punch_categories``);
- per employee-day, our session figures next to Linked Gates' own figures (recomputed by
  ``lg_rules`` from the copied punches), listed only where they differ, with reason codes
  (``compare_month``).

Matching a punch across sources: same person (``AttendancePunch.user_code`` ==
``str(LinkedGatesPunch.enroll_no)``) and at most 120 s apart; when the Linked Gates machine is mapped
to one of ours, the machine must match too. Each machine punch matches at most one Linked Gates
punch (the closest). Times and dates are Cairo local throughout. Every function bulk-loads the whole
window, so the query count does not grow with the number of rows.

Categories: ``matched``; Linked Gates only -> ``lg_manual`` (no machine) or ``missing_from_pull``;
ours only -> ``not_yet_in_lg`` (under 24 h old at ``now``) or ``missing_in_lg``.
"""
import bisect
import calendar
import datetime

from django.utils import timezone

from apps.hr.attendance import lg_rules
from apps.hr.attendance.days import MANUAL_MACHINE, build_days, punches_for_month

CATEGORIES = ('matched', 'lg_manual', 'missing_from_pull', 'not_yet_in_lg', 'missing_in_lg')
NOT_YET_HOURS = 24
_ONE_DAY = datetime.timedelta(days=1)


def _month_bounds(year, month):
    return (datetime.date(year, month, 1),
            datetime.date(year, month, calendar.monthrange(year, month)[1]))


def _aware_range(first, last):
    """[first 00:00, last + 1 day 00:00) as aware Cairo times."""
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.datetime.combine(first, datetime.time.min), tz)
    end = timezone.make_aware(datetime.datetime.combine(last + _ONE_DAY, datetime.time.min), tz)
    return start, end


def _current_lg(qs):
    return qs.filter(superseded_at__isnull=True, lg_removed=False, flag='')


# ---------------------------------------------------------------- per-punch categories

def _code_value(code: str):
    return int(code) if code.isdigit() else code


def _categorize(first, last, now) -> list:
    """Every punch of both sources from ``first`` to ``last`` (inclusive), each with its category.
    Punches one day either side are read too, so a match across midnight is not lost."""
    from apps.hr.models import AttendancePunch, LinkedGatesDevice, LinkedGatesPunch

    lo, hi = first - _ONE_DAY, last + _ONE_DAY
    machine = [(datetime.datetime.combine(p.punch_date, p.punch_time), p)
               for p in (AttendancePunch.objects
                         .filter(flag='', punch_date__gte=lo, punch_date__lte=hi, punch_time__isnull=False)
                         .select_related('device'))]
    start, end = _aware_range(lo, hi)
    lg = sorted(((lg_rules.local_naive(p.check_time), p) for p in _current_lg(
        LinkedGatesPunch.objects.filter(check_time__gte=start, check_time__lt=end))),
        key=lambda t: (t[0], t[1].pk))
    lg_devices = {d.lg_device_id: d for d in LinkedGatesDevice.objects.select_related('device')}

    by_code: dict = {}
    for i, (at, p) in enumerate(machine):
        by_code.setdefault(p.user_code, []).append((at, i))
    times: dict = {}
    for code, items in by_code.items():
        items.sort()
        times[code] = [at for at, _ in items]
    used = [False] * len(machine)
    window = datetime.timedelta(seconds=lg_rules.MATCH_SECONDS)
    tz = timezone.get_current_timezone()
    out = []

    for at, p in lg:
        lg_dev = lg_devices.get(p.lg_device_id) if p.lg_device_id is not None else None
        mapped = lg_dev.device_id if lg_dev is not None and lg_dev.device_id else None
        code = str(p.enroll_no)
        best, best_gap = None, None
        items = by_code.get(code, [])
        ats = times.get(code, [])
        for j in range(bisect.bisect_left(ats, at - window), bisect.bisect_right(ats, at + window)):
            m_at, i = items[j]
            if used[i] or (mapped is not None and machine[i][1].device_id != mapped):
                continue
            gap = abs((m_at - at).total_seconds())
            if best is None or gap < best_gap:
                best, best_gap = i, gap
        if best is not None:
            used[best] = True
            m_at, mp = machine[best]
            out.append({'at': m_at, 'enroll_no': p.enroll_no, 'machine': mp.device.name,
                        'device': mp.device_id, 'category': 'matched'})
            continue
        if p.lg_device_id is None:
            name, category = MANUAL_MACHINE, 'lg_manual'
        else:
            category = 'missing_from_pull'
            if mapped is not None:
                name = lg_dev.device.name
            elif lg_dev is not None:
                name = lg_dev.name or f'LG {p.lg_device_id}'
            else:
                name = f'LG {p.lg_device_id}'
        out.append({'at': at, 'enroll_no': p.enroll_no, 'machine': name, 'device': mapped,
                    'category': category})

    young = datetime.timedelta(hours=NOT_YET_HOURS)
    for i, (at, p) in enumerate(machine):
        if used[i]:
            continue
        age = now - timezone.make_aware(at, tz)
        out.append({'at': at, 'enroll_no': _code_value(p.user_code), 'machine': p.device.name,
                    'device': p.device_id, 'category': 'not_yet_in_lg' if age < young else 'missing_in_lg'})

    out = [item for item in out if first <= item['at'].date() <= last]
    out.sort(key=lambda item: (item['at'], item['machine']))
    return out


def punch_categories(device_id, day, now) -> list:
    """The punches of one machine (our AttendanceDevice id; None = Linked Gates punches with no machine
    of ours: typed by hand, or on an unmapped Linked Gates machine) on one date, oldest first."""
    return [{k: item[k] for k in ('at', 'enroll_no', 'machine', 'category')}
            for item in _categorize(day, day, now) if item['device'] == device_id]


def machine_day_counts(year, month, now=None) -> list:
    """One row per machine per date with any punch: the count in each category."""
    now = now or timezone.now()
    first, last = _month_bounds(year, month)
    rows: dict = {}
    for item in _categorize(first, last, now):
        key = (item['device'], item['machine'], item['at'].date())
        row = rows.get(key)
        if row is None:
            row = rows[key] = {'device': item['device'], 'name': item['machine'], 'date': key[2],
                               **{c: 0 for c in CATEGORIES}}
        row[item['category']] += 1
    return sorted(rows.values(), key=lambda r: (r['date'], r['name']))


# ---------------------------------------------------------------- employee-day comparison

def _canonical_enroll(hr_number):
    """The Linked Gates EnrollNo for an HR code, only when the code is its canonical number
    ('01001' is not 1001)."""
    code = (hr_number or '').strip()
    if code.isdigit() and str(int(code)) == code:
        return int(code)
    return None


def shift_types(employees) -> dict:
    """{employee_id: Linked Gates ShiftType or None}, from LinkedGatesEmployee by EnrollNo."""
    from apps.hr.models import LinkedGatesEmployee

    enroll = {e.pk: _canonical_enroll(e.hr_number) for e in employees}
    numbers = {n for n in enroll.values() if n is not None}
    by_number: dict = {}
    if numbers:
        for number, shift in (LinkedGatesEmployee.objects.filter(enroll_no__in=numbers)
                              .order_by('lg_employee_id').values_list('enroll_no', 'shift_type')):
            by_number.setdefault(number, shift)
    return {pk: by_number.get(n) for pk, n in enroll.items()}


def _figures(first_in, last_out, minutes):
    return {'in': first_in, 'out': last_out, 'minutes': minutes}


def compare_month(employees, year, month) -> list:
    """Employee-days of the month where Linked Gates' own figures differ from ours, oldest first per
    employee. Ours = session rules on machine + Linked Gates punches (whatever the switch says);
    Linked Gates' = its own rules on its punches only."""
    from apps.hr.models import LinkedGatesPunch

    employees = list(employees)
    if not employees:
        return []
    ids = [e.pk for e in employees]
    first, last = _month_bounds(year, month)
    stamps = punches_for_month(ids, year, month, lead_days=1, sources=('machine', 'lg'))
    start, end = _aware_range(first, last + _ONE_DAY)       # an out on the 1st of next month moves back
    lg_by_emp: dict = {pk: [] for pk in ids}
    for p in _current_lg(LinkedGatesPunch.objects.filter(employee_id__in=ids, check_time__gte=start,
                                                         check_time__lt=end)):
        lg_by_emp[p.employee_id].append(p)
    shifts = shift_types(employees)

    out = []
    for e in employees:
        emp_stamps = stamps.get(e.pk, [])
        shift = shifts.get(e.pk)
        lg_map = lg_rules.lg_days(lg_by_emp[e.pk], shift)
        for row in build_days(emp_stamps, e.day_boundary, e.daily_hours, year, month):
            lg = lg_map.get(row.work_date)
            if row.punch_count == 0 and lg is None:
                continue
            if lg_rules.same_day(row, lg):
                continue
            ours_at = {r['at'] for r in row.raw}
            lg_times = ([*lg.in_times, lg.out_time] if lg is not None else [])
            day_stamps = [st for st in emp_stamps
                          if st.at in ours_at or any(lg_rules.near(st.at, t) for t in lg_times)]
            out.append({
                'employee_id': e.pk,
                'date': row.work_date,
                'ours': _figures(row.first_in, row.last_out, row.worked_minutes),
                'lg': (_figures(lg.first_in, lg.out_time, lg.minutes) if lg is not None
                       else _figures(None, None, 0)),
                'reasons': lg_rules.reason_codes(row, lg, day_stamps, shift),
            })
    return out
