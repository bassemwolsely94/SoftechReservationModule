"""
apps/crews/services.py

Every crew write (spec 2026-11-13 §6.5). Each runs in one transaction and writes one AuditLog row
with obj=crew, extra={'crew_id', 'row': 'rule' | 'manual' | None, 'row_id'} and the changed row
before / after. Rule and manual rows are never edited in place: they are ended ("apply from D" =
valid_to D - 1) or, when they never applied, voided. No change may take effect before the first
day of the current month (past months are closed). No SOFTECH access.
"""
from datetime import date, timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.hr.assignments import validate_extensions
from apps.hr.attendance.employee_import import normalise_code
from apps.hr.models import Employee

from .branches import live_branches
from .models import Crew, CrewManualMember, CrewRule

ONE_DAY = timedelta(days=1)

MONTH_LOCKED = 'لا يمكن تطبيق تغيير قبل أول الشهر الحالي — الشهور السابقة مقفلة.'
NAME_TAKEN = 'يوجد طاقم آخر بنفس الاسم.'
ARCHIVED = 'الطاقم مؤرشف — أعده أولًا ثم عدّل أفراده.'

# Labels for the history tab (the actions are not in AuditLog.ACTION_CHOICES, like hr_attendance_*)
ACTION_LABELS = {
    'crew_created': 'إنشاء الطاقم',
    'crew_updated': 'تعديل بيانات الطاقم',
    'crew_deleted': 'حذف الطاقم',
    'crew_archived': 'أرشفة الطاقم',
    'crew_unarchived': 'إعادة الطاقم من الأرشيف',
    'crew_rule_added': 'إضافة قاعدة',
    'crew_rule_ended': 'إنهاء قاعدة',
    'crew_rule_voided': 'إلغاء قاعدة لم تُطبق',
    'crew_rule_replaced': 'استبدال قاعدة',
    'crew_member_added': 'إضافة / استبعاد فرد يدويًا',
    'crew_member_ended': 'إنهاء إضافة / استبعاد يدوي',
    'crew_member_voided': 'إلغاء إضافة / استبعاد لم تُطبق',
    'crew_generic_sellers_set': 'تعديل حسابات «بائع غير محدد»',
}


def _refuse(msg):
    raise ValidationError({'detail': msg})


def check_effective(d: date):
    if d < timezone.localdate().replace(day=1):
        _refuse(MONTH_LOCKED)


# ── snapshots for the audit log ──────────────────────────────────────────────

def crew_data(crew) -> dict:
    return {'name': crew.name, 'type': crew.type, 'description': crew.description,
            'is_archived': crew.is_archived}


def _d(v):
    return v.isoformat() if v else None


def rule_data(rule) -> dict:
    return {'job_titles': list(rule.job_titles or []), 'branch_ids': sorted(b.id for b in rule.branches.all()),
            'departments': list(rule.departments or []), 'sections': list(rule.sections or []),
            'note': rule.note, 'valid_from': _d(rule.valid_from), 'valid_to': _d(rule.valid_to),
            'voided': rule.voided_at is not None}


def manual_data(row) -> dict:
    return {'mode': row.mode, 'employee_id': row.employee_id, 'softech_usercode': row.softech_usercode,
            'pbx_extension': row.pbx_extension, 'label': row.label, 'reason': row.reason,
            'valid_from': _d(row.valid_from), 'valid_to': _d(row.valid_to), 'voided': row.voided_at is not None}


def _audit(action, crew, user, *, row=None, row_id=None, old=None, new=None, note=''):
    AuditLog.log(action, user=user, obj=crew, old_data=old, new_data=new, note=note,
                 extra={'crew_id': crew.pk, 'row': row, 'row_id': row_id})


# ── crew ─────────────────────────────────────────────────────────────────────

def _name_taken(name, exclude_pk=None) -> bool:
    qs = Crew.objects.filter(is_archived=False, name__iexact=name)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.exists()


def _save_unique(crew):
    try:
        with transaction.atomic():
            crew.save()
    except IntegrityError:          # the live-name constraint, raced past the check
        _refuse(NAME_TAKEN)


@transaction.atomic
def create_crew(data: dict, user) -> Crew:
    if _name_taken(data['name']):
        _refuse(NAME_TAKEN)
    crew = Crew(name=data['name'], type=data['type'], description=data.get('description', ''),
                created_by=user, updated_by=user)
    _save_unique(crew)
    _audit('crew_created', crew, user, new=crew_data(crew))
    return crew


@transaction.atomic
def update_crew(crew, data: dict, user) -> Crew:
    old = crew_data(crew)
    for f in ('name', 'type', 'description'):
        if f in data:
            setattr(crew, f, data[f])
    if not crew.is_archived and _name_taken(crew.name, exclude_pk=crew.pk):
        _refuse(NAME_TAKEN)
    crew.updated_by = user
    _save_unique(crew)
    new = crew_data(crew)
    if new != old:
        _audit('crew_updated', crew, user, old=old, new=new)
    return crew


@transaction.atomic
def remove_crew(crew, user) -> str:
    """'deleted' when the crew never had a member before today, else 'archived' (hidden from pickers,
    name kept in past reports)."""
    old = crew_data(crew)
    if not crew.has_history():
        _audit('crew_deleted', crew, user, old={**old, 'rules': [rule_data(r) for r in crew.rules.all()],
                                                'manual': [manual_data(x) for x in crew.manual_members.all()]})
        crew.delete()
        return 'deleted'
    crew.is_archived = True
    crew.updated_by = user
    crew.save(update_fields=['is_archived', 'updated_by', 'updated_at'])
    _audit('crew_archived', crew, user, old=old, new=crew_data(crew))
    return 'archived'


@transaction.atomic
def unarchive_crew(crew, user) -> Crew:
    if _name_taken(crew.name, exclude_pk=crew.pk):
        _refuse(NAME_TAKEN)
    old = crew_data(crew)
    crew.is_archived = False
    crew.updated_by = user
    _save_unique(crew)
    _audit('crew_unarchived', crew, user, old=old, new=crew_data(crew))
    return crew


# ── rule and manual rows ─────────────────────────────────────────────────────

def _live(crew):
    if crew.is_archived:
        _refuse(ARCHIVED)


def _check_range(valid_from, valid_to):
    check_effective(valid_from)
    if valid_to is not None and valid_to < valid_from:
        _refuse('تاريخ النهاية قبل تاريخ البداية.')


def _end_or_void(row, on: date, user) -> bool:
    """End the row the day before `on`; a row that starts on or after `on` never applied and is
    voided. Returns True when voided."""
    check_effective(on)
    if row.voided_at is not None:
        _refuse('هذا السطر ملغى بالفعل.')
    if row.valid_to is not None and row.valid_to < on:
        _refuse('هذا السطر منتهٍ قبل هذا التاريخ.')
    now = timezone.now()
    if row.valid_from >= on:
        row.voided_at, row.voided_by = now, user
        row.save(update_fields=['voided_at', 'voided_by'])
        return True
    row.valid_to, row.ended_at, row.ended_by = on - ONE_DAY, now, user
    row.save(update_fields=['valid_to', 'ended_at', 'ended_by'])
    return False


def _clean_texts(values) -> list:
    out = []
    for v in values or []:
        v = str(v).strip()
        if v and v not in out:
            out.append(v)
    return out


def _new_rule(crew, data: dict, user, valid_from: date) -> CrewRule:
    valid_to = data.get('valid_to')
    _check_range(valid_from, valid_to)
    branch_ids = sorted(set(data.get('branch_ids') or []))
    if branch_ids:
        found = set(live_branches().filter(id__in=branch_ids).values_list('id', flat=True))
        if found != set(branch_ids):
            _refuse('فرع غير موجود أو غير نشط في القاعدة.')
    fields = {k: _clean_texts(data.get(k)) for k in ('job_titles', 'departments', 'sections')}
    if not (branch_ids or any(fields.values())):
        _refuse('القاعدة فارغة — اختر وظيفة أو فرعًا أو إدارة أو قسمًا واحدًا على الأقل.')
    rule = CrewRule.objects.create(crew=crew, note=(data.get('note') or '').strip(), valid_from=valid_from,
                                   valid_to=valid_to, created_by=user, **fields)
    rule.branches.set(branch_ids)
    return rule


@transaction.atomic
def add_rule(crew, data: dict, user) -> CrewRule:
    _live(crew)
    rule = _new_rule(crew, data, user, data.get('valid_from') or timezone.localdate())
    _audit('crew_rule_added', crew, user, row='rule', row_id=rule.pk, new=rule_data(rule))
    return rule


@transaction.atomic
def end_rule(rule, on: date, user) -> CrewRule:
    crew = rule.crew
    _live(crew)
    old = rule_data(rule)
    voided = _end_or_void(rule, on, user)
    _audit('crew_rule_voided' if voided else 'crew_rule_ended', crew, user, row='rule', row_id=rule.pk,
           old=old, new=rule_data(rule))
    return rule


@transaction.atomic
def replace_rule(rule, data: dict, on: date, user) -> CrewRule:
    """End (or void) `rule` and start the new one on `on`, in one transaction and one audit row."""
    crew = rule.crew
    _live(crew)
    old = rule_data(rule)
    voided = _end_or_void(rule, on, user)
    new_rule = _new_rule(crew, {**data, 'valid_to': None}, user, on)
    _audit('crew_rule_replaced', crew, user, row='rule', row_id=new_rule.pk,
           old={**old, 'id': rule.pk, 'voided': voided}, new={**rule_data(new_rule), 'id': new_rule.pk})
    return new_rule


@transaction.atomic
def add_manual(crew, data: dict, user) -> CrewManualMember:
    _live(crew)
    valid_from = data.get('valid_from') or timezone.localdate()
    valid_to = data.get('valid_to')
    _check_range(valid_from, valid_to)
    employee = data.get('employee')
    code = normalise_code(data.get('softech_usercode'))
    try:
        ext = (validate_extensions([data.get('pbx_extension')]) or [''])[0]
    except DjangoValidationError as exc:
        _refuse(exc.messages[0])
    if employee is None and code:
        # a bare code an employee carries is that person (Review Focus 3): store the employee
        matches = list(Employee.objects.filter(softech_usercode=code).values_list('id', flat=True)[:2])
        if len(matches) == 1:
            employee = Employee.objects.get(pk=matches[0])
    if employee is None and not (code or ext):
        _refuse('حدد موظفًا أو كود مستخدم SOFTECH أو رقمًا داخليًا.')
    reason = (data.get('reason') or '').strip()
    if not reason:
        _refuse('السبب مطلوب.')
    row = CrewManualMember.objects.create(
        crew=crew, mode=data['mode'], employee=employee, softech_usercode=code, pbx_extension=ext,
        label=(data.get('label') or '').strip(), reason=reason, valid_from=valid_from, valid_to=valid_to,
        created_by=user)
    _audit('crew_member_added', crew, user, row='manual', row_id=row.pk, new=manual_data(row))
    return row


@transaction.atomic
def end_manual(row, on: date, user) -> CrewManualMember:
    crew = row.crew
    _live(crew)
    old = manual_data(row)
    voided = _end_or_void(row, on, user)
    _audit('crew_member_voided' if voided else 'crew_member_ended', crew, user, row='manual', row_id=row.pk,
           old=old, new=manual_data(row))
    return row
