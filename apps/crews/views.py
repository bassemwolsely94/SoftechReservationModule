"""
apps/crews/views.py — mounted at /api/crews/ (spec 2026-11-13 §6.5, §6.8)

  GET    ?archived=1                     crews: id, name, type, member_count (today), last_change   view
  POST   ''                              create {name, type, description?}                           edit
  GET    <id>/                           crew + rules + manual rows (all, newest first)              view
  PATCH  <id>/                           {name?, type?, description?}                                edit
  DELETE <id>/                           {'result': 'deleted' | 'archived'}                          edit
  POST   <id>/unarchive/                                                                             edit
  GET    <id>/members/?date=             members on the day (default today)                          view
  GET    <id>/history/?start&end         spans + every audited change (default last 12 months)       view
  POST   <id>/rules/                     add a rule                                                  edit
  POST   <id>/rules/<rid>/end/ {on}      end the day before `on` (void when it never applied)        edit
  POST   <id>/rules/<rid>/replace/       end + new open rule from `on` (valid_from/valid_to → 400)   edit
  POST   <id>/manual/                    add a manual include / exclude                              edit
  POST   <id>/manual/<mid>/end/ {on}                                                                 edit
  POST   preview/ {rules, date?, crew_id?}  who unsaved rules would match; saves nothing            edit
  GET    options/                        picker values from live data                                view
  GET    unattributed-sales/?start&end   «بائع غير محدد» share per branch                            view
  GET|PUT unattributed-sales/config/     the generic-seller rule                                     view | edit

RBAC module `crews` has only view / edit: every write asks edit (the middleware maps it the same way).
Company-level, not branch-scoped (permission_matrix.BRANCH_SCOPE). Writes go through services.py.
No SOFTECH access: only local mirrors.
"""
from datetime import date, timedelta

from django.db.models import Max
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from apps.hr.models import Employee, EmployeeAssignment
from apps.users.models import ErpUserGroup
from core.errors import public_error
from core.permissions import matrix_permission

from . import membership, services, unattributed
from .branches import live_branches
from .models import Crew, CrewManualMember, CrewRule
from .serializers import (CrewInput, EndInput, GenericRuleInput, ManualInput, PreviewInput, RuleInput,
                          manual_out, member_key, member_out, rule_out)

CREWS = [IsAuthenticated, matrix_permission('crews', post=('edit',), delete=('edit',))]
BAD_DATE = 'تاريخ غير صحيح (YYYY-MM-DD).'
REPLACE_DATES = 'التعديل يبدأ القاعدة الجديدة من «on» مفتوحة — لا ترسل valid_from أو valid_to.'
MAX_RANGE_DAYS = 3 * 366


def _staff(request):
    return getattr(request.user, 'staff_profile', None)


def _date(request, name, default):
    raw = request.query_params.get(name)
    if not raw:
        return default
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValidationError({'detail': BAD_DATE})


def _range(request, default_start, default_end):
    start, end = _date(request, 'start', default_start), _date(request, 'end', default_end)
    if end < start or (end - start).days > MAX_RANGE_DAYS:
        raise ValidationError({'detail': 'الفترة غير صحيحة (البداية قبل النهاية، ثلاث سنوات على الأكثر).'})
    return start, end


def _valid(serializer_class, data, **kw):
    s = serializer_class(data=data, **kw)
    s.is_valid(raise_exception=True)
    return s.validated_data


def _branch_labels(ids) -> dict:
    ids = {i for i in ids if i}
    return {b.id: unattributed.branch_label(b) for b in Branch.objects.filter(id__in=ids)} if ids else {}


def _members_out(members) -> list:
    labels = _branch_labels(m.branch_id for m in members)
    return [member_out(m, labels) for m in members]


def _crew_out(crew, today, last_change=None) -> dict:
    return {'id': crew.id, 'name': crew.name, 'type': crew.type, 'type_label': crew.get_type_display(),
            'description': crew.description, 'is_archived': crew.is_archived,
            'member_count': len(membership.members(crew, today)), 'last_change': last_change}


def _last_changes(ids) -> dict:
    rows = (AuditLog.objects.filter(model_name='Crew', object_id__in=[str(i) for i in ids])
            .values('object_id').annotate(at=Max('created_at')))
    return {int(r['object_id']): r['at'] for r in rows}


def _detail(crew) -> dict:
    today = timezone.localdate()
    rules = (crew.rules.select_related('created_by__user', 'ended_by__user', 'voided_by__user')
             .prefetch_related('branches').order_by('-valid_from', '-id'))
    manual = (crew.manual_members.select_related('employee', 'created_by__user', 'ended_by__user',
                                                 'voided_by__user').order_by('-valid_from', '-id'))
    return {**_crew_out(crew, today, _last_changes([crew.id]).get(crew.id)),
            'rules': [rule_out(r, today) for r in rules],
            'manual': [manual_out(x, today) for x in manual]}


# ── crews ────────────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes(CREWS)
def crew_list(request):
    if request.method == 'POST':
        crew = services.create_crew(_valid(CrewInput, request.data), _staff(request))
        return Response(_detail(crew), status=status.HTTP_201_CREATED)
    archived = request.query_params.get('archived') in ('1', 'true')
    crews = list(Crew.objects.filter(is_archived=archived))
    today = timezone.localdate()
    last = _last_changes([c.id for c in crews])
    return Response([_crew_out(c, today, last.get(c.id)) for c in crews])


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes(CREWS)
def crew_detail(request, pk):
    crew = get_object_or_404(Crew, pk=pk)
    if request.method == 'PATCH':
        data = _valid(CrewInput, request.data, partial=True)
        crew = services.update_crew(crew, data, _staff(request))
    elif request.method == 'DELETE':
        return Response({'result': services.remove_crew(crew, _staff(request))})
    return Response(_detail(crew))


@api_view(['POST'])
@permission_classes(CREWS)
def crew_unarchive(request, pk):
    crew = get_object_or_404(Crew, pk=pk, is_archived=True)
    return Response(_detail(services.unarchive_crew(crew, _staff(request))))


@api_view(['GET'])
@permission_classes(CREWS)
def crew_members(request, pk):
    crew = get_object_or_404(Crew, pk=pk)
    d = _date(request, 'date', timezone.localdate())
    return Response(_members_out(membership.members(crew, d)))


def _span_names(crew, keys) -> dict:
    """key -> (name, off_payroll) for the spans; employees by name, bare codes by the manual row's label."""
    emp_ids = [k[1] for k in keys if k[0] == 'emp']
    names = {('emp', i): (n, False) for i, n in Employee.objects.filter(id__in=emp_ids).values_list('id', 'name_ar')}
    for x in crew.manual_members.filter(employee__isnull=True):
        key = ('code', x.softech_usercode) if x.softech_usercode else ('ext', x.pbx_extension)
        if key in keys and (key not in names or x.label):
            names[key] = (x.label or key[1], True)
    return names


@api_view(['GET'])
@permission_classes(CREWS)
def crew_history(request, pk):
    crew = get_object_or_404(Crew, pk=pk)
    today = timezone.localdate()
    start, end = _range(request, today - timedelta(days=365), today)
    spans = membership.members_between(crew, start, end)
    names = _span_names(crew, set(spans))
    out_spans = sorted(({'key': member_key(k), 'name': names.get(k, (k[1], k[0] != 'emp'))[0],
                         'off_payroll': names.get(k, (k[1], k[0] != 'emp'))[1], 'from': f, 'to': t}
                        for k, lst in spans.items() for f, t in lst),
                       key=lambda s: (s['from'], s['name']))
    logs = AuditLog.objects.filter(model_name='Crew', object_id=str(crew.pk)).order_by('-created_at', '-id')
    changes = [{'at': a.created_at, 'user_name': a.user_name, 'action': a.action,
                'action_label': services.ACTION_LABELS.get(a.action, a.action),
                'old_data': a.old_data, 'new_data': a.new_data, 'note': a.note} for a in logs]
    return Response({'start': start, 'end': end, 'spans': out_spans, 'changes': changes})


# ── rule and manual rows ─────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes(CREWS)
def rule_add(request, pk):
    crew = get_object_or_404(Crew, pk=pk)
    rule = services.add_rule(crew, _valid(RuleInput, request.data), _staff(request))
    return Response(rule_out(rule), status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes(CREWS)
def rule_end(request, pk, rid):
    rule = get_object_or_404(CrewRule, pk=rid, crew_id=pk)
    on = _valid(EndInput, request.data)['on']
    return Response(rule_out(services.end_rule(rule, on, _staff(request))))


@api_view(['POST'])
@permission_classes(CREWS)
def rule_replace(request, pk, rid):
    rule = get_object_or_404(CrewRule, pk=rid, crew_id=pk)
    on = _valid(EndInput, request.data)['on']
    if {'valid_from', 'valid_to'} & set(request.data):
        # the new rule starts on `on` and stays open; dates in the body would be silently dropped
        raise ValidationError({'detail': REPLACE_DATES})
    new = services.replace_rule(rule, _valid(RuleInput, request.data), on, _staff(request))
    return Response(rule_out(new), status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes(CREWS)
def manual_add(request, pk):
    crew = get_object_or_404(Crew, pk=pk)
    row = services.add_manual(crew, _valid(ManualInput, request.data), _staff(request))
    return Response(manual_out(row), status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes(CREWS)
def manual_end(request, pk, mid):
    row = get_object_or_404(CrewManualMember, pk=mid, crew_id=pk)
    on = _valid(EndInput, request.data)['on']
    return Response(manual_out(services.end_manual(row, on, _staff(request))))


# ── pickers and preview ──────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes(CREWS)
def preview(request):
    data = _valid(PreviewInput, request.data)
    crew = get_object_or_404(Crew, pk=data['crew_id']) if data['crew_id'] else None
    d = data['date'] or timezone.localdate()
    return Response(_members_out(membership.preview(data['rules'], d, crew=crew)))


def _distinct(field) -> list:
    values = set(EmployeeAssignment.objects.filter(valid_to__isnull=True).values_list(field, flat=True))
    values |= set(Employee.objects.values_list(field, flat=True))
    return sorted({(v or '').strip() for v in values} - {''})


@api_view(['GET'])
@permission_classes(CREWS)
def options(request):
    branches = sorted(live_branches(), key=lambda b: unattributed.branch_label(b))
    employees = Employee.objects.order_by('name_ar', 'id').values(
        'id', 'hr_number', 'name_ar', 'job_title', 'branch_id', 'softech_usercode', 'pbx_extensions', 'status')
    return Response({
        'job_titles': _distinct('job_title'), 'departments': _distinct('department'),
        'sections': _distinct('section'),
        'branches': [{'id': b.id, 'code': b.code or b.softech_branch_id, 'label': unattributed.branch_label(b)}
                     for b in branches],
        'employees': [{**{k: v for k, v in e.items() if k != 'name_ar'}, 'name': e['name_ar']} for e in employees],
    })


# ── «بائع غير محدد» ──────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes(CREWS)
def unattributed_sales(request):
    today = timezone.localdate()
    start, end = _range(request, today.replace(day=1), today)
    try:
        return Response(unattributed.unattributed_by_branch(start, end))
    except Exception as exc:          # a report failure must not leak internals (core/errors)
        return Response({'detail': public_error(request, exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'PUT'])
@permission_classes(CREWS)
def unattributed_config(request):
    if request.method == 'PUT':
        data = _valid(GenericRuleInput, request.data)
        rule = unattributed.set_generic_rule(data['groups'], data['usercodes'], _staff(request))
    else:
        rule = unattributed.generic_rule()
    groups = [{'code': str(g), 'name': n} for g, n in ErpUserGroup.objects.values_list('usergroup', 'name')]
    return Response({'rule': rule, 'groups': groups})
