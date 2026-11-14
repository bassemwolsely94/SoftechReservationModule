"""
apps/hr/attendance/employee_import.py

One-time import of the HR employee list from the payroll workbook (design 2026-11-07).

Privacy: the workbook also holds salaries and other payroll data. Only the columns named in
IMPORT_COLUMNS are ever read; nothing else is loaded, kept, logged or printed. Error messages name
a row number and an HR code, never a value from any other column.
"""
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from apps.hr import assignments
from apps.hr.models import Employee

from . import resolve

IMPORT_COLUMNS = {
    'AV': 'hr_number', 'BC': 'name_ar', 'AX': 'department', 'AY': 'section',
    'AZ': 'work_location', 'BA': 'job_title', 'AT': 'daily_hours',
}
MAX_DAILY_HOURS = Decimal(24)
HEADER_ROW = 2
FIRST_DATA_ROW = 3
TOTAL_NAMES = {'الاجمالى', 'الإجمالى', 'الاجمالي', 'الإجمالي'}

_COL_INDEX = {field_: column_index_from_string(col) - 1 for col, field_ in IMPORT_COLUMNS.items()}
_LAST_COL = max(_COL_INDEX.values()) + 1


class ImportBlocked(Exception):
    """apply() refused because the preview has errors."""


@dataclass
class ImportPreview:
    rows: list = field(default_factory=list)      # dicts keyed by import field + 'row'
    errors: list = field(default_factory=list)    # strings naming row and code only


_CODE_TRANSLATE = {ord(c): None for c in '\xa0\u200b\u200c\u200d\u200e\u200f\u2060\ufeff'}
_CODE_TRANSLATE.update({0x0660 + i: ord(str(i)) for i in range(10)})   # Arabic-Indic digits
_CODE_TRANSLATE.update({0x06F0 + i: ord(str(i)) for i in range(10)})   # Eastern Arabic-Indic digits
_FLOAT_TEXT = re.compile(r'^(\d+)\.0+$')


def normalise_code(value) -> str:
    """1001.0 / ' 1001' / '1001' / '1001.0' / 1001 -> '1001'."""
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).translate(_CODE_TRANSLATE).strip()
    m = _FLOAT_TEXT.match(text)
    return m.group(1) if m else text


def _text(value) -> str:
    return '' if value is None else str(value).strip()


def _hours(value):
    if value is None or str(value).strip() == '':
        return None
    hours = Decimal(str(value).strip())
    # NaN and Infinity parse as Decimals but are no hours (and NaN breaks month sorting).
    if not hours.is_finite() or not 0 < hours <= MAX_DAILY_HOURS:
        raise ValueError('daily hours out of range')
    return hours


def read_workbook(path) -> ImportPreview:
    preview = ImportPreview()
    wb = load_workbook(path, data_only=True, read_only=True)
    seen = set()
    try:
        ws = wb.worksheets[0]
        for offset, cells in enumerate(ws.iter_rows(min_row=FIRST_DATA_ROW, max_col=_LAST_COL,
                                                    values_only=True)):
            rownum = FIRST_DATA_ROW + offset

            def cell(name):
                i = _COL_INDEX[name]
                return cells[i] if i < len(cells) else None

            code = normalise_code(cell('hr_number'))
            name = _text(cell('name_ar'))
            if name in TOTAL_NAMES or (not code and not name):
                continue
            if not code:
                preview.errors.append(f'row {rownum}: missing HR code')
                continue
            if not name:
                preview.errors.append(f'row {rownum} code {code}: missing name')
                continue
            if code in seen:
                preview.errors.append(f'row {rownum} code {code}: duplicate HR code')
                continue
            try:
                hours = _hours(cell('daily_hours'))
            except (InvalidOperation, ValueError):
                preview.errors.append(
                    f'row {rownum} code {code}: daily hours must be a number above 0 and up to 24')
                continue
            seen.add(code)
            preview.rows.append({
                'row': rownum, 'hr_number': code, 'name_ar': name,
                'department': _text(cell('department')), 'section': _text(cell('section')),
                'work_location': _text(cell('work_location')), 'job_title': _text(cell('job_title')),
                'daily_hours': hours,
            })
    finally:
        wb.close()
    return preview


def _branch_map(locations):
    """work_location -> Branch, only where exactly one Branch has that exact name."""
    out = {}
    for loc in locations:
        if not loc:
            continue
        found = list(Branch.objects.filter(name=loc)[:2]) or list(Branch.objects.filter(name_ar=loc)[:2])
        if len(found) == 1:
            out[loc] = found[0]
    return out


@transaction.atomic
def apply(preview, user=None, on=None) -> dict:
    """Upsert Employee rows by hr_number. Idempotent. `user` is a StaffProfile (or None); `on` is the
    date placement changes take effect (default today)."""
    if preview.errors:
        raise ImportBlocked(f'{len(preview.errors)} error(s); fix the workbook first')
    branches = _branch_map({r['work_location'] for r in preview.rows})
    on = on or timezone.localdate()
    created = updated = changed = 0
    new_codes = []
    for r in preview.rows:
        defaults = {k: r[k] for k in ('name_ar', 'department', 'section', 'work_location',
                                      'job_title', 'daily_hours')}
        branch = branches.get(r['work_location'])
        if branch is not None:     # a branch set by hand stays when the workbook doesn't match one
            defaults['branch'] = branch
        emp, was_created = Employee.objects.update_or_create(hr_number=r['hr_number'], defaults=defaults)
        changed += assignments.record_assignment(emp, on=on, source='import', user=user) is not None
        created += was_created
        updated += not was_created
        if was_created:
            new_codes.append(r['hr_number'])
    # Punches may have arrived before the employee existed; they attach now, not on the next resend.
    for code in new_codes:
        resolve.resolve_user_code(code)
    result = {'created': created, 'updated': updated, 'total': len(preview.rows),
              'assignments_changed': changed,
              'branch_matched': sum(1 for r in preview.rows if r['work_location'] in branches)}
    AuditLog.log('hr_employee_import', user=user, extra=result,
                 note='One-time HR employee import (counts only)')
    return result
