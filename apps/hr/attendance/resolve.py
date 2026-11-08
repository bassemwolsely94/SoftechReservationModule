"""
apps/hr/attendance/resolve.py — which employee a machine ID belongs to.

The HR number is the machine number (owner), so an ID resolves when it equals an employee's HR
number, unless a guard stops it. resolve_user_code recalculates from the current facts, so a punch
can also become unresolved again. Only AttendancePunch.employee changes here, and only through
queryset.update(): the punch's own data is never touched.
"""
import datetime
from collections import defaultdict

from django.db.models import Q

from apps.hr.models import AttendancePunch, ConflictConfirmation, DeviceUser, Employee

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


def current_names(code) -> set:
    """The normalised real names the machines hold for this ID right now."""
    rows = DeviceUser.objects.filter(user_code=code).values_list('user_code', 'device_name')
    return _real_names(rows)[code]


def _is_conflicting(code) -> bool:
    return len(current_names(code)) > 1


def confirmation_valid(confirmation) -> bool:
    """A confirmation holds only while every current real name was among those it confirmed, and
    the confirmed employee still holds the ID."""
    return (confirmation.employee.hr_number == confirmation.user_code
            and current_names(confirmation.user_code) <= set(confirmation.names))


def _employee_for(code):
    if code.startswith(UID_PREFIX):
        return None
    employee = Employee.objects.filter(hr_number=code, hold_resolution=False).first()
    if employee is None:
        return None
    # A name conflict keeps the ID unresolved until the HR head confirms this employee for it.
    if _is_conflicting(code):
        conf = ConflictConfirmation.objects.filter(user_code=code, employee=employee).first()
        if conf is None or not confirmation_valid(conf):
            return None
    return employee


def eligible_q(employee) -> Q:
    return _eligible(employee)


def _eligible(employee) -> Q:
    """Which punches may belong to this employee. Employment dates are compared with the WORK date
    (days.work_date_for): a punch before the day boundary belongs to the previous calendar day, so
    02:00 the morning after end_date is still end_date's, and 02:00 on start_date is not."""
    # A flagged punch has no date to trust, so the employment-date guard can't be checked.
    rule = Q(flag='', punch_date__isnull=False, punch_time__isnull=False)
    early = Q(punch_time__lt=employee.day_boundary)     # work date = punch date - 1 day
    if employee.start_date:
        rule &= (~early & Q(punch_date__gte=employee.start_date)) | (
            early & Q(punch_date__gt=employee.start_date))
    if employee.end_date:
        rule &= (~early & Q(punch_date__lte=employee.end_date)) | (
            early & Q(punch_date__lte=employee.end_date + datetime.timedelta(days=1)))
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
