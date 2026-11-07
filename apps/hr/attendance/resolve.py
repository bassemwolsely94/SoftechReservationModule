"""
apps/hr/attendance/resolve.py — which employee a machine ID belongs to.

The HR number is the machine number (owner), so an ID resolves when it equals an employee's HR
number, unless a guard stops it. resolve_user_code recalculates from the current facts, so a punch
can also become unresolved again. Only AttendancePunch.employee changes here, and only through
queryset.update(): the punch's own data is never touched.
"""
from collections import defaultdict

from django.db.models import Q

from apps.hr.models import AttendancePunch, DeviceUser, Employee

# A machine's internal slot, sent when its log holds no clean ID (8-byte logs). It means something
# only on that machine, so it is never an employee and two machines' same slot is no conflict.
UID_PREFIX = 'uid-'


def _normalise_name(value) -> str:
    return ''.join(str(value or '').split()).casefold()


def is_real_name(name, user_code) -> bool:
    """False for what machines hold when nobody typed a name: blank, the ID again, or only digits."""
    normal = _normalise_name(name)
    return (bool(normal) and normal != _normalise_name(user_code)
            and any(ch.isalpha() for ch in normal))


def _real_names(rows):
    """{user_code: set of normalised real names} from (user_code, device_name) pairs."""
    names = defaultdict(set)
    for user_code, device_name in rows:
        if not user_code.startswith(UID_PREFIX) and is_real_name(device_name, user_code):
            names[user_code].add(_normalise_name(device_name))
    return names


def conflicting_user_codes() -> set[str]:
    """IDs that hold different real names on different machines."""
    names = _real_names(DeviceUser.objects.values_list('user_code', 'device_name'))
    return {code for code, found in names.items() if len(found) > 1}


def _is_conflicting(code) -> bool:
    rows = DeviceUser.objects.filter(user_code=code).values_list('user_code', 'device_name')
    return len(_real_names(rows)[code]) > 1


def _employee_for(code):
    if code.startswith(UID_PREFIX) or _is_conflicting(code):
        return None
    return Employee.objects.filter(hr_number=code, hold_resolution=False).first()


def _eligible(employee) -> Q:
    # A flagged punch has no date to trust, so the employment-date guard can't be checked.
    rule = Q(flag='', punch_date__isnull=False)
    if employee.start_date:
        rule &= Q(punch_date__gte=employee.start_date)
    if employee.end_date:
        rule &= Q(punch_date__lte=employee.end_date)
    return rule


def resolve_user_code(code) -> None:
    """Link or unlink every stored punch of this ID. Safe to call any number of times."""
    punches = AttendancePunch.objects.filter(user_code=code)
    employee = _employee_for(code)
    if employee is None:
        punches.filter(employee__isnull=False).update(employee=None)
        return
    eligible = _eligible(employee)
    punches.filter(eligible).exclude(employee=employee).update(employee=employee)
    punches.exclude(eligible).filter(employee__isnull=False).update(employee=None)
