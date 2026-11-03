"""
Admin API for phone alerts (/api/notifications/phone-alerts/...).

Admin + supervisor only (the /api/notifications/ prefix is exempt from the module matrix, so the
check lives here, server-side). Every write writes an AuditLog row with before/after.
"""
import logging

from django.conf import settings
from django.db import transaction
from rest_framework import serializers as drf
from rest_framework import status as http
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from .models import PhoneAlert, PhoneAlertPolicy, WorkOwner
from .serializers import (AlertDetailSerializer, AlertLogSerializer, OwnerSerializer,
                          PolicySerializer, clean_phone)

logger = logging.getLogger('elrezeiky.phone_alerts')


class IsAdminOrSupervisor(BasePermission):
    message = 'هذه الصفحة للمدير والمشرف فقط'

    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated):
            return False
        p = getattr(u, 'staff_profile', None)
        return bool(p and p.is_active and p.role in ('admin', 'supervisor'))


PERMS = [IsAuthenticated, IsAdminOrSupervisor]


def _actor(request):
    return getattr(request.user, 'staff_profile', None)


def _is_admin(request):
    p = _actor(request)
    return bool(request.user.is_superuser or (p and p.role == 'admin'))


def _audit(request, action, obj, before, after, note=''):
    from apps.audit.models import AuditLog
    AuditLog.log(action, user=_actor(request), obj=obj, old_data=before or None,
                 new_data=after or None, note=note, request=request)


# ── policies ─────────────────────────────────────────────────────────────────

def _policy_state(p):
    return {'mode': p.mode, 'remind_after_min': p.remind_after_min,
            'escalate_after_min': p.escalate_after_min, 'max_reminders': p.max_reminders,
            'escalate_to': sorted(p.escalate_to.values_list('pk', flat=True))}


@api_view(['GET', 'PATCH'])
@permission_classes(PERMS)
def policies(request):
    if request.method == 'GET':
        qs = PhoneAlertPolicy.objects.prefetch_related('escalate_to').order_by('pk')
        return Response(PolicySerializer(qs, many=True).data)

    many = isinstance(request.data, list)
    items = request.data if many else [request.data]
    done = []
    with transaction.atomic():
        for item in items:
            item = item if isinstance(item, dict) else {}
            policy = PhoneAlertPolicy.objects.filter(event=item.get('event')).first()
            if policy is None:
                transaction.set_rollback(True)
                return Response({'event': 'حدث غير معروف'}, status=http.HTTP_400_BAD_REQUEST)
            ser = PolicySerializer(policy, data={k: v for k, v in item.items() if k != 'event'},
                                   partial=True)
            if not ser.is_valid():
                transaction.set_rollback(True)
                return Response(ser.errors, status=http.HTTP_400_BAD_REQUEST)
            before = _policy_state(policy)
            escalate_to = ser.validated_data.pop('escalate_to', None)
            policy = ser.save(updated_by=_actor(request))
            if escalate_to is not None:
                policy.escalate_to.set(escalate_to)
            after = _policy_state(policy)
            if before != after:
                _audit(request, 'phone_alert_policy_changed', policy, before, after, note=policy.event)
            done.append(policy)
    return Response(PolicySerializer(done if many else done[0], many=many).data)


# ── owners ───────────────────────────────────────────────────────────────────

def _owner_state(o):
    return {'kind': o.kind, 'staff': o.staff_id, 'branch': o.branch_id,
            'is_escalation': o.is_escalation, 'active': o.active}


@api_view(['GET', 'POST'])
@permission_classes(PERMS)
def owners(request):
    if request.method == 'GET':
        qs = WorkOwner.objects.select_related('staff__user', 'branch').order_by('kind', 'pk')
        kind = request.query_params.get('kind')
        if kind:
            qs = qs.filter(kind=kind)
        return Response(OwnerSerializer(qs, many=True).data)
    ser = OwnerSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    owner = ser.save()
    _audit(request, 'phone_alert_owner_changed', owner, None, _owner_state(owner), note='created')
    return Response(OwnerSerializer(owner).data, status=http.HTTP_201_CREATED)


@api_view(['PATCH', 'DELETE'])
@permission_classes(PERMS)
def owner_detail(request, pk):
    owner = WorkOwner.objects.filter(pk=pk).first()
    if owner is None:
        return Response({'error': 'غير موجود'}, status=http.HTTP_404_NOT_FOUND)
    before = _owner_state(owner)
    if request.method == 'DELETE':
        _audit(request, 'phone_alert_owner_changed', owner, before, None, note='deleted')
        owner.delete()
        return Response(status=http.HTTP_204_NO_CONTENT)
    ser = OwnerSerializer(owner, data=request.data, partial=True)
    ser.is_valid(raise_exception=True)
    owner = ser.save()
    _audit(request, 'phone_alert_owner_changed', owner, before, _owner_state(owner), note='updated')
    return Response(OwnerSerializer(owner).data)


# ── branch mobiles ───────────────────────────────────────────────────────────

def _mobile_rows(branch_ids=None):
    from apps.branches.models import Branch, BranchSettings
    branches = Branch.objects.filter(is_active=True).order_by('name')
    if branch_ids is not None:
        branches = branches.filter(pk__in=branch_ids)
    mobiles = dict(BranchSettings.objects.values_list('branch_id', 'alert_mobile'))
    return [{'branch_id': b.pk, 'branch_name': b.name_ar or b.name,
             'alert_mobile': mobiles.get(b.pk, '') or ''} for b in branches]


@api_view(['GET', 'PATCH'])
@permission_classes(PERMS)
def branch_mobiles(request):
    if request.method == 'GET':
        return Response(_mobile_rows())
    from apps.branches.models import Branch, BranchSettings
    data = request.data if isinstance(request.data, dict) else {}
    try:
        branch = Branch.objects.filter(pk=int(data.get('branch_id'))).first()
    except (TypeError, ValueError):
        branch = None
    if branch is None:
        return Response({'branch_id': 'الفرع غير موجود'}, status=http.HTTP_400_BAD_REQUEST)
    try:
        phone = clean_phone(data.get('alert_mobile'))
    except drf.ValidationError as exc:
        return Response({'alert_mobile': exc.detail[0]}, status=http.HTTP_400_BAD_REQUEST)
    row = BranchSettings.for_branch(branch)
    before = row.alert_mobile
    if before != phone:
        row.alert_mobile = phone
        row.save(update_fields=['alert_mobile'])
        _audit(request, 'phone_alert_mobile_changed', branch, {'alert_mobile': before},
               {'alert_mobile': phone}, note=branch.name)
    return Response(_mobile_rows([branch.pk])[0])


@api_view(['POST'])
@permission_classes(PERMS)
def branch_mobile_test(request, branch_id):
    """Send one test alert to the branch mobile. Dry-run unless the send switch is on."""
    from apps.branches.models import Branch, BranchSettings
    from .recipients import is_plausible_phone
    from .sender import deliver
    branch = Branch.objects.filter(pk=branch_id).first()
    if branch is None:
        return Response({'error': 'الفرع غير موجود'}, status=http.HTTP_404_NOT_FOUND)
    row = BranchSettings.objects.filter(branch=branch).first()
    phone = (row.alert_mobile if row else '') or ''
    if not is_plausible_phone(phone):
        return Response({'error': 'لا يوجد موبايل تنبيهات صحيح لهذا الفرع'},
                        status=http.HTTP_400_BAD_REQUEST)
    alert = PhoneAlert.objects.create(event='test', kind='alert', phone=phone)
    variables = [{'type': 'text', 'text': t} for t in ('تنبيه تجريبي', branch.name or '—',
                                                         'اختبار موبايل التنبيهات', '—')]
    attempt = deliver(alert, variables=variables, payloads=[f'alert:{alert.token}:ack'])
    result = getattr(attempt, 'result', None)
    _audit(request, 'phone_alert_test_sent', branch, None,
           {'alert_id': alert.pk, 'result': result}, note=branch.name)
    alert.refresh_from_db()
    return Response({'alert_id': alert.pk, 'status': alert.status, 'result': result,
                     'dry_run': result == 'dry_run'})


# ── channel ──────────────────────────────────────────────────────────────────

def _channel_payload():
    from apps.omni.models import ChannelAccount
    from .sender import staff_account
    current = staff_account()
    accounts = [{'id': a.pk, 'name': a.name, 'phone_or_handle': a.phone_or_handle,
                 'is_active': a.is_active, 'is_staff_alerts': a.is_staff_alerts}
                for a in ChannelAccount.objects.filter(channel='whatsapp').order_by('name')]
    return {'channel_account_id': current.pk if current else None, 'accounts': accounts}


@api_view(['GET', 'PUT'])
@permission_classes(PERMS)
def channel(request):
    if request.method == 'GET':
        return Response(_channel_payload())
    from apps.config.models import SystemSetting
    from apps.omni.models import ChannelAccount
    from .sender import ACCOUNT_SETTING, staff_account
    raw = request.data.get('channel_account_id') if isinstance(request.data, dict) else None
    old = staff_account()
    with transaction.atomic():
        if raw in (None, ''):
            new = None
        else:
            try:
                new = ChannelAccount.objects.filter(pk=int(raw), channel='whatsapp').first()
            except (TypeError, ValueError):
                new = None
            if new is None:
                return Response({'channel_account_id': 'اختر حساب واتساب صحيحاً'},
                                status=http.HTTP_400_BAD_REQUEST)
            # Persistent: keeps this number's threads out of the customer inbox. Never auto-cleared.
            if not new.is_staff_alerts:
                ChannelAccount.objects.filter(pk=new.pk).update(is_staff_alerts=True)
        SystemSetting.objects.update_or_create(
            key=ACCOUNT_SETTING,
            defaults={'value': str(new.pk) if new else '', 'value_type': 'string',
                      'label': 'حساب واتساب لتنبيهات الموظفين', 'category': 'notifications'})
        _audit(request, 'phone_alert_channel_changed', new or old,
               {'channel_account_id': old.pk if old else None},
               {'channel_account_id': new.pk if new else None})
    return Response(_channel_payload())


# ── log ──────────────────────────────────────────────────────────────────────

class LogPagination(CursorPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200
    ordering = '-id'


@api_view(['GET'])
@permission_classes(PERMS)
def log(request):
    from django.db.models import Q
    from apps.branches.models import BranchSettings
    qs = PhoneAlert.objects.select_related('recipient_staff__user').prefetch_related('source')
    p = request.query_params
    ints = {}
    for key in ('staff', 'branch'):
        if p.get(key):
            try:
                ints[key] = int(p[key])
            except ValueError:
                return Response({key: 'قيمة الفلتر غير صحيحة'}, status=http.HTTP_400_BAD_REQUEST)
    day = None
    if p.get('date'):
        from django.utils.dateparse import parse_date
        try:
            day = parse_date(p['date'])
        except ValueError:
            day = None
        if day is None:
            return Response({'date': 'التاريخ غير صحيح — اكتبه بالشكل 2026-11-03'},
                            status=http.HTTP_400_BAD_REQUEST)
    if p.get('status'):
        qs = qs.filter(status=p['status'])
    if p.get('event'):
        qs = qs.filter(event=p['event'])
    if 'staff' in ints:
        qs = qs.filter(recipient_staff_id=ints['staff'])
    if 'branch' in ints:
        # a branch's alerts: its staff, plus whatever went to the branch's shared mobile
        mobiles = list(BranchSettings.objects.filter(branch_id=ints['branch'])
                       .exclude(alert_mobile='').values_list('alert_mobile', flat=True))
        qs = qs.filter(Q(recipient_staff__branch_id=ints['branch']) | Q(phone__in=mobiles))
    if day is not None:
        qs = qs.filter(created_at__date=day)
    paginator = LogPagination()
    page = paginator.paginate_queryset(qs, request)
    data = AlertLogSerializer(page, many=True, context={'mask_phone': not _is_admin(request)}).data
    return paginator.get_paginated_response(data)


@api_view(['GET'])
@permission_classes(PERMS)
def log_detail(request, pk):
    alert = (PhoneAlert.objects.select_related('recipient_staff__user')
             .prefetch_related('attempts').filter(pk=pk).first())
    if alert is None:
        return Response({'error': 'غير موجود'}, status=http.HTTP_404_NOT_FOUND)
    return Response(AlertDetailSerializer(alert, context={'mask_phone': not _is_admin(request)}).data)


# ── switches ─────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes(PERMS)
def switches(request):
    from .sender import staff_account
    return Response({'send_enabled': bool(getattr(settings, 'PHONE_ALERTS_SEND_ENABLED', False)),
                     'brief_enabled': bool(getattr(settings, 'MORNING_BRIEF_SEND_ENABLED', False)),
                     'account_set': staff_account() is not None})
