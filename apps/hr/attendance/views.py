"""
apps/hr/attendance/views.py — the staff API, mounted at /api/hr-attendance/ (gated in access.py,
not by the module middleware; see EXEMPT_PREFIXES).

Three levels, all checked on the server for every route (a hidden button is no authorization):
  view    month, days, issues, employees, unknown IDs, machines
  manage  edit employees, link review, hold, unknown-ID and name-conflict decisions, collect now
  admin   machines, agent secrets, access grants

Display only: no key here carries pay, deductions or penalties. Every change is audited.
"""
import datetime
import re
from functools import wraps
from io import BytesIO

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.exceptions import ParseError, ValidationError
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.hr.assignments import record_assignment, validate_extensions
from apps.hr.models import (AttendanceAccess, AttendanceAgent, AttendanceDevice, CollectionRun,
                            ConflictConfirmation, DeviceUser, Employee, UnknownIdDecision)
from apps.users.models import StaffProfile
from core.export_safety import neutralise_formulas
from core.sort_ordering import explicit_order_by

from . import days as day_engine
from . import issues as issue_list
from . import export, links, resolve
from .access import Access
from .agent_auth import issue_agent
from .employee_import import normalise_code

_DENIED = {'detail': 'غير مصرح'}
_LEVEL = {'view': 'can_view', 'manage': 'can_manage', 'admin': 'can_admin'}
MAX_ROWS = 1000


def gate(level):
    """Run the view only for callers at `level`; the view receives the resolved Access."""
    flag = _LEVEL[level]

    def decorate(fn):
        @wraps(fn)
        def inner(request, *args, **kwargs):
            acc = Access(request)
            if not getattr(acc, flag):
                return Response(_DENIED, status=403)
            return fn(request, acc, *args, **kwargs)
        return inner
    return decorate


# ── helpers ──────────────────────────────────────────────────────────────────────────────────────

def _body(request) -> dict:
    if not isinstance(request.data, dict):
        raise ParseError('طلب غير صالح')
    return request.data


def _text(body, key, limit, required=False, label=None) -> str:
    value = body.get(key)
    value = '' if value is None else str(value).strip()
    if required and not value:
        raise ValidationError({key: f'{label or key} مطلوب'})
    if len(value) > limit:
        raise ValidationError({key: 'النص أطول من المسموح'})
    return value


def _int(body, key) -> int:
    try:
        return int(body.get(key))
    except (TypeError, ValueError):
        raise ValidationError({key: 'قيمة غير صالحة'})


def _plain(value):
    """A JSON-safe copy of a value for the audit trail."""
    if hasattr(value, 'pk'):
        return value.pk
    if isinstance(value, (datetime.date, datetime.time, datetime.datetime)):
        return value.isoformat()
    if value is None or isinstance(value, (bool, int, str)):
        return value
    return str(value)


def _order(qs, request, allowed, default):
    """Sort by `?ordering=` if it names a whitelisted column; anything else is ignored."""
    try:
        args = explicit_order_by(request.query_params.get('ordering'), allowed, default)
    except ValidationError:
        args = tuple(default)
    return qs.order_by(*args)


def _month(request):
    raw = (request.query_params.get('month') or '').strip()
    if not raw:
        today = timezone.localdate()
        return today.year, today.month
    m = re.fullmatch(r'(\d{4})-(\d{2})', raw)
    if not m or not (2000 <= int(m.group(1)) <= 2100) or not (1 <= int(m.group(2)) <= 12):
        raise ValidationError({'month': 'الشهر بصيغة YYYY-MM'})
    return int(m.group(1)), int(m.group(2))


def _branch_name(branch):
    return (branch.name_ar or branch.name) if branch else None


def _staff_json(staff):
    return {'id': staff.pk, 'name': staff.full_name} if staff else None


def _employee_core(emp):
    return {
        'id': emp.pk, 'hr_number': emp.hr_number, 'name_ar': emp.name_ar, 'department': emp.department,
        'section': emp.section, 'job_title': emp.job_title, 'work_location': emp.work_location,
        'branch': emp.branch_id, 'branch_name': _branch_name(emp.branch), 'daily_hours': emp.daily_hours,
        'status': emp.status, 'employee_type': emp.employee_type, 'start_date': emp.start_date,
        'end_date': emp.end_date, 'day_boundary': emp.day_boundary,
        'hold_resolution': emp.hold_resolution, 'hold_reason': emp.hold_reason,
        'pbx_extensions': emp.pbx_extensions,
    }


def _employee_rows(employees, with_suggestions=True):
    """Rows for the employees tab: the person, their login link, what the machines call that ID,
    and a name conflict if the machines disagree."""
    employees = list(employees)
    codes = [e.hr_number for e in employees]
    names: dict = {}
    for code, name in DeviceUser.objects.filter(user_code__in=codes).values_list('user_code', 'device_name'):
        if resolve.is_real_name(name, code):
            names.setdefault(code, set()).add(name)
    conflicts = resolve.conflicting_user_codes()
    confirmed = {c.user_code for c in ConflictConfirmation.objects.filter(user_code__in=codes)
                 .select_related('employee') if resolve.confirmation_valid(c)}
    pool = links.pool_for_review() if with_suggestions and any(not e.staff_id for e in employees) else []
    rows = []
    for e in employees:
        row = _employee_core(e)
        row.update({
            'staff': _staff_json(e.staff),
            'machine_names': sorted(names.get(e.hr_number, ())),
            'conflict': e.hr_number in conflicts,
            'conflict_confirmed': e.hr_number in conflicts and e.hr_number in confirmed,
            'suggestions': links.suggest(e, pool) if (with_suggestions and not e.staff_id
                                                      and e.status == 'active') else [],
        })
        rows.append(row)
    return rows


def _one_employee_row(emp):
    emp = Employee.objects.select_related('staff__user', 'branch').get(pk=emp.pk)
    return _employee_rows([emp])[0]


def _link_call(fn, *args):
    try:
        return fn(*args)
    except links.LinkError as exc:
        body = {'detail': str(exc)}
        if exc.code:    # a machine-readable reason, so the screen doesn't guess from the text
            body['code'] = exc.code
        raise ValidationError(body)


def _staff_from(body, key='staff') -> StaffProfile:
    pk = _int(body, key)
    staff = StaffProfile.objects.select_related('user').filter(pk=pk, is_active=True).first()
    if staff is None:
        raise ValidationError({key: 'حساب غير موجود'})
    return staff


# ── view level ───────────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
def me(request):
    """The caller's attendance permissions; 403 unless they may open the module."""
    acc = Access(request)
    if not acc.can_view:
        return Response(_DENIED, status=403)
    return Response(acc.as_dict())


MONTH_SORT = ('hr_number', 'name_ar', 'department', 'days_with_punches', 'worked_hours',
              'expected_hours', 'days_needing_review', 'days_no_punches')


@api_view(['GET'])
@gate('view')
def month(request, acc):
    year, mon = _month(request)
    employees = Employee.objects.select_related('branch')
    if request.query_params.get('status') in ('active', 'left'):
        employees = employees.filter(status=request.query_params['status'])
    employees = list(employees.order_by('hr_number')[:MAX_ROWS])
    rows = []
    for e, _days, totals in day_engine.month_rows(employees, year, mon):
        rows.append({
            'id': e.pk, 'hr_number': e.hr_number, 'name_ar': e.name_ar, 'department': e.department,
            'job_title': e.job_title, 'branch_name': _branch_name(e.branch), 'status': e.status,
            'employee_type': e.employee_type, 'daily_hours': e.daily_hours,
            'days_with_punches': totals.days_with_punches, 'worked_hours': totals.worked_hours,
            'expected_hours': totals.expected_hours, 'days_needing_review': totals.days_needing_review,
            'days_no_punches': totals.days_no_punches,
        })
    raw = (request.query_params.get('ordering') or '').strip()
    key, desc = raw.lstrip('-'), raw.startswith('-')
    if key in MONTH_SORT and key != 'hr_number':
        # empty values last in both directions; the employee id breaks ties
        filled = [r for r in rows if r[key] is not None]
        empty = [r for r in rows if r[key] is None]
        filled.sort(key=lambda r: (r[key], r['id']), reverse=desc)
        rows = filled + empty
    elif key == 'hr_number' and desc:
        rows.reverse()
    return Response({'month': f'{year:04d}-{mon:02d}', 'rows': rows})


@api_view(['GET'])
def month_export(request):
    """The month as an Excel file (summary, day by day, items to review); audited."""
    acc = Access(request)
    if not acc.can_export:
        return Response(_DENIED, status=403)
    year, mon = _month(request)
    status = request.query_params.get('status')
    wb = export.build_workbook(year, mon, status if status in ('active', 'left') else None)
    buf = BytesIO()
    neutralise_formulas(wb).save(buf)       # build_workbook already did; the save site says so
    AuditLog.log('hr_attendance_export', user=acc.profile, request=request,
                 extra={'month': f'{year:04d}-{mon:02d}'}, note='Monthly attendance export')
    resp = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f'attachment; filename="attendance-{year:04d}-{mon:02d}.xlsx"'
    return resp


@api_view(['GET'])
@gate('view')
def employee_days(request, acc, pk):
    emp = get_object_or_404(Employee.objects.select_related('branch', 'staff__user'), pk=pk)
    year, mon = _month(request)
    punches = day_engine.punches_for_month([emp.pk], year, mon).get(emp.pk, [])
    info = day_engine.leave_info([emp], year, mon).get(emp.pk, {})
    rows = day_engine.build_days(punches, emp.day_boundary, emp.daily_hours, year, mon, info)
    totals = day_engine.month_totals(rows)
    days = [{
        'work_date': d.work_date, 'first_in': d.first_in, 'last_out': d.last_out,
        'worked_minutes': d.worked_minutes, 'needs_review': d.needs_review, 'no_punches': d.no_punches,
        'punch_count': d.punch_count, 'machines': d.machines, 'info': d.info,
        'raw': [{'at': r['at'], 'machine': r['machine'], 'state': r['state'], 'counted': r['counted']}
                for r in d.raw],
    } for d in rows]
    return Response({
        'month': f'{year:04d}-{mon:02d}',
        'employee': {**_employee_core(emp), 'staff': _staff_json(emp.staff)},
        'totals': {
            'days_with_punches': totals.days_with_punches, 'worked_hours': totals.worked_hours,
            'expected_hours': totals.expected_hours, 'days_needing_review': totals.days_needing_review,
            'days_no_punches': totals.days_no_punches,
        },
        'days': days,
    })


@api_view(['GET'])
@gate('view')
def issues_view(request, acc):
    rows = issue_list.list_issues()
    counts: dict = {}
    for r in rows:
        counts[r['kind']] = counts.get(r['kind'], 0) + 1
    return Response({'rows': rows, 'counts': counts, 'ignored': issue_list.ignored_ids()})


EMPLOYEE_SORT = {
    'hr_number': 'hr_number', 'name_ar': 'name_ar', 'department': 'department', 'section': 'section',
    'job_title': 'job_title', 'work_location': 'work_location', 'branch': 'branch__name_ar',
    'status': 'status', 'employee_type': 'employee_type', 'start_date': 'start_date',
    'end_date': 'end_date', 'daily_hours': 'daily_hours',
}


@api_view(['GET'])
@gate('view')
def employees(request, acc):
    qs = Employee.objects.select_related('staff__user', 'branch')
    p = request.query_params
    q = (p.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(name_ar__icontains=q) | Q(hr_number__icontains=q))
    if p.get('status') in ('active', 'left'):
        qs = qs.filter(status=p['status'])
    if p.get('type') in ('payroll', 'non_payroll'):
        qs = qs.filter(employee_type=p['type'])
    if p.get('linked') in ('yes', 'no'):
        qs = qs.filter(staff__isnull=(p['linked'] == 'no'))
    qs = _order(qs, request, EMPLOYEE_SORT, ('hr_number',))[:MAX_ROWS]
    return Response({'rows': _employee_rows(qs)})


@api_view(['GET'])
@gate('view')
def unknown_ids(request, acc):
    return Response({'rows': issue_list.unknown_ids(), 'ignored': issue_list.ignored_ids()})


@api_view(['GET'])
@gate('view')
def devices(request, acc):
    rows = []
    for dev in AttendanceDevice.objects.select_related('agent', 'branch').order_by('name'):
        run = CollectionRun.objects.filter(device=dev).order_by('-started_at', '-pk').first()
        row = {
            'id': dev.pk, 'serial': dev.serial, 'name': dev.name, 'model_name': dev.model_name,
            'location_label': dev.location_label, 'branch': dev.branch_id,
            'branch_name': _branch_name(dev.branch), 'is_active': dev.is_active,
            'agent': dev.agent_id, 'agent_name': dev.agent.name if dev.agent else None,
            'last_contact_at': dev.last_contact_at, 'last_status': dev.last_status,
            'last_drift_seconds': dev.last_drift_seconds, 'last_log_count': dev.last_log_count,
            'last_run': None if run is None else {
                'status': run.status, 'started_at': run.started_at, 'finished_at': run.finished_at,
                'records_read': run.records_read, 'new_count': run.new_count,
                'spool_waiting': run.spool_waiting},
        }
        if acc.can_admin:      # network details (the error text may name an IP) are for the admin
            row.update({'ip': dev.ip, 'port': dev.port})
            if run is not None:
                row['last_run']['error'] = run.error
        rows.append(row)
    agents = AttendanceAgent.objects.filter(revoked_at__isnull=True).order_by('name')
    return Response({'rows': rows, 'agents': [
        {'id': a.pk, 'name': a.name, 'last_seen_at': a.last_seen_at,
         'collect_requested_at': a.collect_requested_at} for a in agents]})


# ── manage level ─────────────────────────────────────────────────────────────────────────────────

class _DatesMixin:
    """An end date before the start date would put every punch of the employee outside their
    employment. On a partial edit the other date comes from the stored employee."""

    def validate(self, attrs):
        attrs = super().validate(attrs)
        current = self.instance
        start = attrs['start_date'] if 'start_date' in attrs else getattr(current, 'start_date', None)
        end = attrs['end_date'] if 'end_date' in attrs else getattr(current, 'end_date', None)
        if start and end and end < start:
            raise serializers.ValidationError({'end_date': 'تاريخ النهاية قبل تاريخ البداية'})
        return attrs


class EmployeeEditSerializer(_DatesMixin, serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ['hr_number', 'name_ar', 'department', 'section', 'job_title', 'work_location',
                  'branch', 'daily_hours', 'status', 'employee_type', 'start_date', 'end_date',
                  'day_boundary', 'pbx_extensions']

    def validate_pbx_extensions(self, value):
        try:
            return validate_extensions(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)

    def validate_hr_number(self, value):
        value = normalise_code(value)
        if not value or value.startswith(resolve.UID_PREFIX):
            raise serializers.ValidationError('رقم وظيفي غير صالح')
        return value


class EmployeeCreateSerializer(_DatesMixin, serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ['name_ar', 'department', 'section', 'job_title', 'work_location', 'branch',
                  'daily_hours', 'employee_type', 'start_date', 'end_date']


# What a resolve needs to be re-run for when it changes.
_RESOLVE_FIELDS = {'hr_number', 'start_date', 'end_date', 'day_boundary'}


@api_view(['PATCH'])
@gate('manage')
def employee_edit(request, acc, pk):
    emp = get_object_or_404(Employee.objects.select_related('staff__user', 'branch'), pk=pk)
    ser = EmployeeEditSerializer(emp, data=_body(request), partial=True)
    ser.is_valid(raise_exception=True)
    new = ser.validated_data
    old_code = emp.hr_number
    changes = {f: [_plain(getattr(emp, f)), _plain(v)] for f, v in new.items() if getattr(emp, f) != v}
    if not changes:
        return Response(_one_employee_row(emp))
    code_changes = 'hr_number' in changes
    if code_changes and emp.staff_id:
        clash = StaffProfile.objects.filter(hr_code=new['hr_number']).exclude(pk=emp.staff_id).exists()
        if clash:
            raise ValidationError({'hr_number': 'الرقم مستخدم ككود موارد بشرية لحساب آخر'})
    try:
        with transaction.atomic():
            ser.save()
            if {'job_title', 'branch', 'department', 'section', 'softech_usercode',
                    'pbx_extensions'} & set(changes):
                record_assignment(emp, on=timezone.localdate(), source='manual', user=acc.profile)
            if code_changes and emp.staff_id and emp.staff.hr_code == old_code:
                emp.staff.hr_code = new['hr_number']
                emp.staff.save(update_fields=['hr_code'])
            if _RESOLVE_FIELDS & set(changes):
                for code in {old_code, emp.hr_number}:
                    resolve.resolve_user_code(code)
    except IntegrityError:
        raise ValidationError({'detail': 'تعذّر الحفظ: الرقم مستخدم'})
    AuditLog.log('hr_attendance_employee_edit', user=acc.profile, obj=emp, changes=changes, request=request,
                 note='Employee edited')
    if 'status' in changes:
        AuditLog.log('hr_attendance_employee_status', user=acc.profile, obj=emp, request=request,
                     changes={'status': changes['status']}, note='Employee status changed')
    return Response(_one_employee_row(emp))


@api_view(['POST'])
@gate('manage')
def employee_link(request, acc, pk):
    emp = get_object_or_404(Employee, pk=pk)
    staff = _staff_from(_body(request))
    _link_call(links.confirm, emp, staff, acc.profile)
    return Response(_one_employee_row(emp))


@api_view(['POST'])
@gate('manage')
def employee_reject_link(request, acc, pk):
    emp = get_object_or_404(Employee, pk=pk)
    staff = _staff_from(_body(request))
    _link_call(links.reject, emp, staff, acc.profile)
    return Response(_one_employee_row(emp))


@api_view(['POST'])
@gate('manage')
def employee_unlink(request, acc, pk):
    emp = get_object_or_404(Employee, pk=pk)
    _link_call(links.unlink, emp, acc.profile)
    return Response(_one_employee_row(emp))


@api_view(['POST'])
@gate('manage')
def employee_hold(request, acc, pk):
    emp = get_object_or_404(Employee, pk=pk)
    body = _body(request)
    hold = body.get('hold') is True
    reason = _text(body, 'reason', 255, required=hold, label='السبب') if hold else ''
    before = [emp.hold_resolution, emp.hold_reason]
    with transaction.atomic():
        emp.hold_resolution, emp.hold_reason = hold, reason
        emp.save(update_fields=['hold_resolution', 'hold_reason'])
        resolve.resolve_user_code(emp.hr_number)
    AuditLog.log('hr_attendance_employee_hold', user=acc.profile, obj=emp, request=request,
                 changes={'hold_resolution': [before[0], hold], 'hold_reason': [before[1], reason]},
                 note='Punch resolution held' if hold else 'Punch resolution released')
    return Response(_one_employee_row(emp))


@api_view(['POST'])
@gate('manage')
def generic_login(request, acc):
    staff = _staff_from(_body(request))
    _link_call(links.mark_generic, staff, acc.profile)
    return Response({'staff': staff.pk, 'generic': True})


@api_view(['POST'])
@gate('manage')
def not_generic_login(request, acc):
    """The login is one person after all (or a generic mark was a mistake). Reason required."""
    body = _body(request)
    staff = _staff_from(body)
    reason = _text(body, 'reason', 255, required=True, label='السبب')
    _link_call(links.mark_not_generic, staff, acc.profile, reason)
    return Response({'staff': staff.pk, 'generic': False})


def _seen_code(code) -> bool:
    from apps.hr.models import AttendancePunch
    return (AttendancePunch.objects.filter(user_code=code).exists()
            or DeviceUser.objects.filter(user_code=code).exists())


@api_view(['POST'])
@gate('manage')
def unknown_create_employee(request, acc, code):
    code = code.strip()
    if not code or code.startswith(resolve.UID_PREFIX) or len(code) > 30:
        raise ValidationError({'detail': 'هذا الرقم لا يصلح كرقم وظيفي'})
    if Employee.objects.filter(hr_number=code).exists():
        raise ValidationError({'detail': 'الرقم موجود في قائمة الموظفين'})
    if not _seen_code(code):
        raise ValidationError({'detail': 'الرقم لم يظهر على أي ماكينة'})
    ser = EmployeeCreateSerializer(data={'employee_type': 'non_payroll', **_body(request)})
    ser.is_valid(raise_exception=True)
    try:
        with transaction.atomic():
            emp = ser.save(hr_number=code)
            # the dated history starts now (or at start_date), never back in 2020 (crews F1)
            record_assignment(emp, on=timezone.localdate(), source='manual', user=acc.profile)
            resolve.resolve_user_code(code)
    except IntegrityError:
        raise ValidationError({'detail': 'الرقم موجود في قائمة الموظفين'})
    AuditLog.log('hr_attendance_employee_create', user=acc.profile, obj=emp, request=request,
                 extra={'hr_number': code, 'employee_type': emp.employee_type},
                 note='Employee created from an unknown fingerprint ID')
    return Response(_one_employee_row(emp), status=201)


@api_view(['POST'])
@gate('manage')
def unknown_ignore(request, acc, code):
    code = code.strip()
    reason = _text(_body(request), 'reason', 255, required=True, label='السبب')
    if Employee.objects.filter(hr_number=code).exists():
        raise ValidationError({'detail': 'الرقم على قائمة الموظفين وليس مجهولاً'})
    if not _seen_code(code):
        raise ValidationError({'detail': 'الرقم لم يظهر على أي ماكينة'})
    UnknownIdDecision.objects.update_or_create(
        user_code=code, defaults={'decision': 'ignored', 'reason': reason, 'decided_by': acc.profile})
    AuditLog.log('hr_attendance_unknown_ignore', user=acc.profile, request=request, note=reason,
                 extra={'user_code': code})
    return Response({'user_code': code, 'ignored': True})


@api_view(['POST'])
@gate('manage')
def unknown_unignore(request, acc, code):
    """Undo «ignore»: the ID shows again among the unknown IDs. Audited."""
    code = code.strip()
    decision = UnknownIdDecision.objects.filter(user_code=code, decision='ignored').first()
    if decision is None:
        raise ValidationError({'detail': 'الرقم ليس في قائمة المستبعدين'})
    reason = decision.reason
    decision.delete()
    AuditLog.log('hr_attendance_unknown_unignore', user=acc.profile, request=request,
                 extra={'user_code': code, 'was_ignored_because': reason},
                 note='Ignored fingerprint ID restored to the unknown list')
    return Response({'user_code': code, 'ignored': False})


@api_view(['POST'])
@gate('manage')
def conflict_confirm(request, acc, code):
    """The HR head's decision that an ID whose machines hold different names is this employee."""
    code = code.strip()
    body = _body(request)
    reason = _text(body, 'reason', 255, required=True, label='السبب')
    emp = Employee.objects.filter(pk=_int(body, 'employee')).first()
    if emp is None or emp.hr_number != code:
        raise ValidationError({'employee': 'يجب أن يكون الموظف صاحب هذا الرقم الوظيفي'})
    if code not in resolve.conflicting_user_codes():
        raise ValidationError({'detail': 'لا يوجد تعارض أسماء على هذا الرقم'})
    with transaction.atomic():
        ConflictConfirmation.objects.update_or_create(
            user_code=code, defaults={'employee': emp, 'reason': reason, 'decided_by': acc.profile,
                                      'names': sorted(resolve.current_names(code))})
        resolve.resolve_user_code(code)
    AuditLog.log('hr_attendance_conflict_confirm', user=acc.profile, obj=emp, request=request, note=reason,
                 extra={'user_code': code})
    return Response(_one_employee_row(emp))


@api_view(['POST'])
@gate('manage')
def collect_now(request, acc):
    """Ask every working agent that has an active machine to collect on its next poll."""
    agents = AttendanceAgent.objects.filter(revoked_at__isnull=True,
                                            devices__is_active=True).distinct()
    ids = list(agents.values_list('pk', flat=True))
    if not ids:
        raise ValidationError({'detail': 'لا يوجد برنامج تجميع مرتبط بماكينة فعّالة'})
    AttendanceAgent.objects.filter(pk__in=ids).update(collect_requested_at=timezone.now())
    AuditLog.log('hr_attendance_collect_now', user=acc.profile, request=request,
                 extra={'agents': ids}, note='Collect now requested')
    return Response({'agents': len(ids)})


# ── admin level ──────────────────────────────────────────────────────────────────────────────────

class DeviceEditSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttendanceDevice
        fields = ['name', 'ip', 'port', 'model_name', 'location_label', 'branch', 'agent', 'is_active']

    def validate_agent(self, value):
        if value is not None and value.revoked_at is not None:
            raise serializers.ValidationError('برنامج التجميع ملغى')
        return value


@api_view(['PATCH'])
@gate('admin')
def device_edit(request, acc, pk):
    dev = get_object_or_404(AttendanceDevice, pk=pk)
    ser = DeviceEditSerializer(dev, data=_body(request), partial=True)
    ser.is_valid(raise_exception=True)
    changes = {f: [_plain(getattr(dev, f)), _plain(v)] for f, v in ser.validated_data.items()
               if getattr(dev, f) != v}
    if changes:
        ser.save()
        AuditLog.log('hr_attendance_device_edit', user=acc.profile, obj=dev, changes=changes,
                     request=request, note='Machine edited')
    return Response({'id': dev.pk, 'changed': sorted(changes)})


@api_view(['GET'])
@gate('admin')
def agents(request, acc):
    rows = []
    for a in AttendanceAgent.objects.prefetch_related('devices').order_by('-pk'):
        rows.append({
            'id': a.pk, 'name': a.name, 'last_seen_at': a.last_seen_at, 'revoked_at': a.revoked_at,
            'collect_requested_at': a.collect_requested_at,
            'devices': [d.name for d in a.devices.all()],
        })
    return Response({'rows': rows})


@api_view(['POST'])
@gate('admin')
def agent_issue(request, acc):
    name = _text(_body(request), 'name', 120, required=True, label='الاسم')
    agent, secret = issue_agent(name, created_by=acc.profile)
    # the secret is in this response only, and never in the audit trail
    AuditLog.log('hr_attendance_agent_issue', user=acc.profile, obj=agent, request=request,
                 note='Agent secret issued (shown once)')
    response = Response({'id': agent.pk, 'name': agent.name, 'secret': secret}, status=201)
    response['Cache-Control'] = 'no-store'
    return response


@api_view(['POST'])
@gate('admin')
def agent_revoke(request, acc, pk):
    agent = get_object_or_404(AttendanceAgent, pk=pk)
    if agent.revoked_at is not None:
        raise ValidationError({'detail': 'ملغى بالفعل'})
    agent.revoked_at = timezone.now()
    agent.save(update_fields=['revoked_at'])
    AuditLog.log('hr_attendance_agent_revoke', user=acc.profile, obj=agent, request=request,
                 note='Agent revoked')
    return Response({'id': agent.pk, 'revoked': True})


def _grant_json(g):
    return {'id': g.pk, 'staff': _staff_json(g.staff), 'level': g.level, 'granted_at': g.granted_at,
            'granted_by': g.granted_by.full_name if g.granted_by else None, 'revoked_at': g.revoked_at}


@api_view(['GET', 'POST'])
@gate('admin')
def grants(request, acc):
    if request.method == 'GET':
        qs = AttendanceAccess.objects.select_related('staff__user', 'granted_by__user')[:200]
        out = {'rows': [_grant_json(g) for g in qs]}
        q = (request.query_params.get('q') or '').strip()
        if q:    # who can be picked: active logins matching the text
            found = (StaffProfile.objects.filter(is_active=True).select_related('user')
                     .filter(Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q)
                             | Q(user__username__icontains=q) | Q(softech_username__icontains=q))[:30])
            out['candidates'] = [_staff_json(s) for s in found]
        return Response(out)
    body = _body(request)
    staff = _staff_from(body)
    level = body.get('level')
    if level not in dict(AttendanceAccess.LEVEL_CHOICES):
        raise ValidationError({'level': 'مستوى غير صالح'})
    try:
        with transaction.atomic():
            if AttendanceAccess.objects.filter(staff=staff, revoked_at__isnull=True).exists():
                raise ValidationError({'detail': 'لديه صلاحية بالفعل'})
            grant = AttendanceAccess.objects.create(staff=staff, level=level, granted_by=acc.profile)
    except IntegrityError:
        raise ValidationError({'detail': 'لديه صلاحية بالفعل'})
    AuditLog.log('hr_attendance_grant_create', user=acc.profile, obj=grant, request=request,
                 extra={'staff': staff.pk, 'level': level}, note='Attendance access granted')
    return Response(_grant_json(grant), status=201)


@api_view(['POST'])
@gate('admin')
def grant_revoke(request, acc, pk):
    grant = get_object_or_404(AttendanceAccess.objects.select_related('staff__user'), pk=pk)
    if grant.revoked_at is not None:
        raise ValidationError({'detail': 'ملغاة بالفعل'})
    grant.revoked_at = timezone.now()
    grant.save(update_fields=['revoked_at'])
    AuditLog.log('hr_attendance_grant_revoke', user=acc.profile, obj=grant, request=request,
                 extra={'staff': grant.staff_id, 'level': grant.level}, note='Attendance access revoked')
    return Response(_grant_json(grant))
