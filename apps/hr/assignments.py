"""
apps/hr/assignments.py

Dated employee assignment history (crews design 2026-11-13). The history is written whenever an
employee's tracked placement changes; "apply from D" ends the old row at D - 1 day and starts the
new one at D. All dates are inclusive. No SOFTECH access.
"""
import re
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from .models import EmployeeAssignment

SEED_EPOCH = date(2020, 1, 1)
TRACKED = ('job_title', 'branch_id', 'department', 'section')
_EXT = re.compile(r'^\d{2,8}$')


def _snapshot(employee) -> dict:
    return {f: getattr(employee, f) for f in TRACKED}


@transaction.atomic
def record_assignment(employee, *, on: date, source: str, user=None):
    """Bring the history in line with the employee's current placement. Returns the created or
    updated row, or None when nothing changed."""
    snap = _snapshot(employee)
    open_row = EmployeeAssignment.objects.select_for_update().filter(
        employee=employee, valid_to__isnull=True).first()
    if open_row is None:
        return EmployeeAssignment.objects.create(
            employee=employee, valid_from=employee.start_date or SEED_EPOCH, source=source,
            created_by=user, **snap)
    if all(getattr(open_row, f) == v for f, v in snap.items()):
        return None
    if open_row.valid_from >= on:      # same-day correction (or a back-dated apply): fix in place
        for f, v in snap.items():
            setattr(open_row, f, v)
        open_row.source = source
        open_row.created_by = user
        open_row.save()
        return open_row
    open_row.valid_to = on - timedelta(days=1)
    open_row.save(update_fields=['valid_to'])
    return EmployeeAssignment.objects.create(
        employee=employee, valid_from=on, source=source, created_by=user, **snap)


def assignment_on(employee_id: int, d: date):
    return (EmployeeAssignment.objects
            .filter(employee_id=employee_id, valid_from__lte=d)
            .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=d))
            .order_by('-valid_from').first())


def validate_extensions(values) -> list:
    out = []
    for v in values or []:
        v = str(v).strip()
        if not v or v in out:
            continue
        if not _EXT.match(v):
            raise ValidationError(f'رقم داخلي غير صالح: {v}')
        out.append(v)
    return out
