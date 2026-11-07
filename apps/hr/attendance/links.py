"""
apps/hr/attendance/links.py — Employee <-> system login (StaffProfile) link review.

A link is only ever made by a person (confirm). Suggestions come from NAMES alone; a number that
happens to equal a SOFTECH user id never creates or suggests a link (design 2026-11-07). Confirming
writes the HR number to StaffProfile.hr_code, which is unique among non-blank values, so a
confirm that would clash is refused before anything is written. Every change is audited.
"""
import re

from django.db import IntegrityError, transaction

from apps.audit.models import AuditLog
from apps.hr.models import Employee, EmployeeLinkRejection, GenericLogin
from apps.users.models import StaffProfile

GENERIC_PATTERN = re.compile(r'cash|كاشير|test|branch|فرع', re.IGNORECASE)
MAX_SUGGESTIONS = 5

_DIACRITICS = re.compile('[ً-ٰٟـ]')   # harakat, dagger alef, tatweel
_LETTERS = str.maketrans({'أ': 'ا', 'إ': 'ا', 'آ': 'ا',   # alef forms
                          'ى': 'ي', 'ة': 'ه'})                      # ya, ta marbuta


class LinkError(ValueError):
    """A refused link action. The message is shown to the HR head."""


def _tokens(name) -> list[str]:
    text = _DIACRITICS.sub('', str(name or '')).translate(_LETTERS).casefold()
    return [t for t in re.split(r'[\s_.\-]+', text) if t]


def _names(staff) -> list[str]:
    return [n for n in (staff.full_name, staff.softech_username) if n]


def _generic_by_name(staff) -> bool:
    return any(GENERIC_PATTERN.search(n) for n in [staff.user.username, *_names(staff)])


def is_generic_login(staff) -> bool:
    """A shared login (cashier, test, branch account): a GenericLogin row, or a telltale name."""
    return GenericLogin.objects.filter(staff=staff).exists() or _generic_by_name(staff)


def _match_reason(emp_tokens, staff_tokens):
    """Why the two names look alike, or '' if they don't. Needs two or more words on the login."""
    if len(staff_tokens) < 2 or not emp_tokens:
        return ''
    if emp_tokens == staff_tokens:
        return 'الاسم مطابق'
    if set(staff_tokens) <= set(emp_tokens) or set(emp_tokens[:2]) <= set(staff_tokens):
        return 'تشابه في الاسم'
    return ''


def _candidates(exclude_employee=None):
    """Active, single-person logins not already tied to an employee."""
    taken = Employee.objects.filter(staff__isnull=False)
    if exclude_employee is not None:
        taken = taken.exclude(pk=exclude_employee.pk)
    generic = set(GenericLogin.objects.values_list('staff_id', flat=True))
    pool = (StaffProfile.objects.filter(is_active=True, alerts_only=False)
            .exclude(pk__in=taken.values('staff_id')).select_related('user'))
    return [s for s in pool if s.pk not in generic and not _generic_by_name(s)]


def suggest(employee, pool=None) -> list[dict]:
    """[{staff_id, name, reason}] — name matches only. `pool` lets a list screen share one lookup."""
    if employee.staff_id:
        return []
    pool = _candidates() if pool is None else pool
    rejected = set(EmployeeLinkRejection.objects.filter(employee=employee).values_list('staff_id', flat=True))
    emp_tokens = _tokens(employee.name_ar)
    found = []
    for staff in pool:
        if staff.pk in rejected:
            continue
        reason = next((r for r in (_match_reason(emp_tokens, _tokens(n)) for n in _names(staff)) if r), '')
        if reason:
            found.append({'staff_id': staff.pk, 'name': staff.full_name, 'reason': reason})
    found.sort(key=lambda s: (s['reason'] != 'الاسم مطابق', s['staff_id']))
    return found[:MAX_SUGGESTIONS]


def pool_for_review():
    return _candidates()


def confirm(employee, staff, user):
    with transaction.atomic():
        employee = Employee.objects.select_for_update().get(pk=employee.pk)
        staff = StaffProfile.objects.select_for_update().get(pk=staff.pk)
        if is_generic_login(staff):
            raise LinkError('هذا حساب مشترك ولا يُربط بموظف')
        if employee.staff_id:
            raise LinkError('الموظف مرتبط بحساب بالفعل، فُك الربط أولاً')
        if Employee.objects.filter(staff=staff).exists():
            raise LinkError('هذا الحساب مرتبط بموظف آخر')
        if staff.hr_code and staff.hr_code != employee.hr_number:
            raise LinkError('للحساب كود موارد بشرية مختلف')
        if StaffProfile.objects.filter(hr_code=employee.hr_number).exclude(pk=staff.pk).exists():
            raise LinkError('كود الموارد البشرية مستخدم لحساب آخر')
        try:
            with transaction.atomic():
                employee.staff = staff
                employee.save(update_fields=['staff'])
                staff.hr_code = employee.hr_number
                staff.save(update_fields=['hr_code'])
        except IntegrityError:
            raise LinkError('تعذّر الربط: الكود أو الحساب مستخدم')
        EmployeeLinkRejection.objects.filter(employee=employee, staff=staff).delete()
        AuditLog.log('hr_attendance_link_confirm', user=user, obj=employee,
                     changes={'staff': [None, staff.pk], 'hr_code': ['', employee.hr_number]},
                     note='Employee linked to a system login by a person')
    return employee


def reject(employee, staff, user):
    if employee.staff_id == staff.pk:
        raise LinkError('الحساب مرتبط بهذا الموظف بالفعل')
    _, created = EmployeeLinkRejection.objects.get_or_create(
        employee=employee, staff=staff, defaults={'decided_by': user})
    if created:
        AuditLog.log('hr_attendance_link_reject', user=user, obj=employee,
                     extra={'staff': staff.pk}, note='Suggested link rejected')
    return created


def mark_generic(staff, user):
    if Employee.objects.filter(staff=staff).exists():
        raise LinkError('الحساب مرتبط بموظف، فُك الربط أولاً')
    row, created = GenericLogin.objects.get_or_create(staff=staff, defaults={'marked_by': user})
    if created:
        AuditLog.log('hr_attendance_generic_login', user=user, obj=staff,
                     note='Login marked as shared (never linked to one employee)')
    return row


def unlink(employee, user):
    with transaction.atomic():
        employee = Employee.objects.select_for_update().get(pk=employee.pk)
        staff = employee.staff
        if staff is None:
            raise LinkError('الموظف غير مرتبط بحساب')
        cleared = staff.hr_code == employee.hr_number
        employee.staff = None
        employee.save(update_fields=['staff'])
        if cleared:
            staff.hr_code = ''
            staff.save(update_fields=['hr_code'])
        AuditLog.log('hr_attendance_link_unlink', user=user, obj=employee,
                     changes={'staff': [staff.pk, None]},
                     extra={'hr_code_cleared': cleared},
                     note='Employee unlinked from a system login')
    return employee
