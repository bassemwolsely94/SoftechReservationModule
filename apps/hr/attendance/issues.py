"""
apps/hr/attendance/issues.py — everything on the attendance "issues" tab, one flat list.

Read-only and company-level (see access.py). Each row has a `kind`:

  unknown_id  an ID on the machines that is not on the employee list, ONE row per ID (so a hundred
              punches from one visitor don't swamp the tab), minus IDs the HR head set aside
  conflict    an ID whose machines hold different real names, not yet confirmed by the HR head
  held        an employee whose punches are held back on purpose (hold_resolution)
  bad_date    punches with a date no machine could have written (kept, but left out of totals)
  drift       a machine whose clock is off by more than five minutes

No money, no verdicts, no names beyond what the machines and the employee list already hold.
"""
from django.db.models import Count, Max, Min, Q

from apps.hr.models import (AttendanceDevice, AttendancePunch, ConflictConfirmation, DeviceUser,
                            Employee, UnknownIdDecision)

from . import resolve
from .health import DRIFT_WARNING_SECONDS


def _iso(value):
    return value.isoformat() if value else None


def unknown_ids() -> list[dict]:
    """One row per ID with punches but no employee, not ignored; most punches first."""
    hidden = UnknownIdDecision.objects.filter(decision='ignored').values('user_code')
    known = Employee.objects.values('hr_number')
    groups = list(AttendancePunch.objects
                  .exclude(user_code__in=known).exclude(user_code__in=hidden)
                  .values('user_code')
                  .annotate(count=Count('id'), last_punch=Max('punch_date', filter=Q(flag=''))))
    codes = [g['user_code'] for g in groups]
    machines: dict = {}
    for code, name in (AttendancePunch.objects.filter(user_code__in=codes)
                       .values_list('user_code', 'device__name').distinct()):
        machines.setdefault(code, set()).add(name)
    names: dict = {}
    for code, name in DeviceUser.objects.filter(user_code__in=codes).values_list('user_code', 'device_name'):
        if resolve.is_real_name(name, code):
            names.setdefault(code, set()).add(name)
    rows = [{
        'kind': 'unknown_id', 'user_code': g['user_code'], 'count': g['count'],
        'last_punch': _iso(g['last_punch']), 'machines': sorted(machines.get(g['user_code'], ())),
        'roster_names': sorted(names.get(g['user_code'], ())),
        'slot_only': g['user_code'].startswith(resolve.UID_PREFIX),
    } for g in groups]
    return sorted(rows, key=lambda r: (-r['count'], r['user_code']))


def ignored_ids() -> list[dict]:
    rows = UnknownIdDecision.objects.filter(decision='ignored').order_by('-decided_at')
    return [{'user_code': r.user_code, 'reason': r.reason, 'decided_at': _iso(r.decided_at)} for r in rows]


def _conflicts() -> list[dict]:
    confirmed = {c.user_code for c in ConflictConfirmation.objects.select_related('employee')
                 if resolve.confirmation_valid(c)}
    codes = sorted(resolve.conflicting_user_codes() - confirmed)
    if not codes:
        return []
    by_code: dict = {c: [] for c in codes}
    rows = (DeviceUser.objects.filter(user_code__in=codes).select_related('device')
            .order_by('device__name', 'id'))
    for du in rows:
        if resolve.is_real_name(du.device_name, du.user_code):
            by_code[du.user_code].append({'machine': du.device.name, 'name': du.device_name})
    employees = {e.hr_number: e for e in Employee.objects.filter(hr_number__in=codes)}
    return [{
        'kind': 'conflict', 'user_code': code, 'by_machine': by_code[code],
        'names': sorted({m['name'] for m in by_code[code]}),
        'employee': employees[code].pk if code in employees else None,
        'employee_name': employees[code].name_ar if code in employees else '',
    } for code in codes]


def _held() -> list[dict]:
    out = []
    for emp in Employee.objects.filter(hold_resolution=True):
        count = AttendancePunch.objects.filter(user_code=emp.hr_number, flag='', employee__isnull=True).count()
        out.append({'kind': 'held', 'employee': emp.pk, 'user_code': emp.hr_number,
                    'name': emp.name_ar, 'reason': emp.hold_reason, 'count': count})
    return out


def _bad_dates() -> list[dict]:
    groups = (AttendancePunch.objects.exclude(flag='').values('device__name')
              .annotate(count=Count('id'), oldest=Min('punch_date'), newest=Max('punch_date'))
              .order_by('device__name'))
    return [{'kind': 'bad_date', 'machine': g['device__name'], 'count': g['count'],
             'oldest': _iso(g['oldest']), 'newest': _iso(g['newest'])} for g in groups]


def _drift() -> list[dict]:
    out = []
    for dev in AttendanceDevice.objects.filter(is_active=True, last_drift_seconds__isnull=False):
        if abs(dev.last_drift_seconds) > DRIFT_WARNING_SECONDS:
            out.append({'kind': 'drift', 'machine': dev.name, 'device': dev.pk,
                        'seconds': dev.last_drift_seconds})
    return out


def list_issues() -> list[dict]:
    return [*_conflicts(), *unknown_ids(), *_held(), *_bad_dates(), *_drift()]
