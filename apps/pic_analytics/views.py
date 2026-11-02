"""
apps/pic_analytics/views.py — mounted at /api/pic-analytics/ (doc 33)

  GET|POST grants/                 named branch managers (admin only)
  POST     grants/<id>/revoke/
  GET      grants/candidates/?q=   staff to grant

Every rule is enforced here; the screen only hides what the user cannot do.
"""
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .access import Access
from .models import PicAnalyticsAccess


def _deny(msg='ليس لديك صلاحية — Not allowed'):
    return Response({'detail': msg}, status=status.HTTP_403_FORBIDDEN)


def _bad(msg):
    return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)


def _grant_json(g):
    return {'id': g.id, 'staff_id': g.staff_id, 'staff_name': g.staff.full_name,
            'role': g.staff.role, 'branch': g.staff.branch_name, 'note': g.note,
            'granted_by': g.granted_by.full_name if g.granted_by_id else '', 'granted_at': g.granted_at,
            'revoked_by': g.revoked_by.full_name if g.revoked_by_id else '', 'revoked_at': g.revoked_at}


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def grants(request):
    acc = Access(request)
    if not acc.can_manage_access:
        return _deny()
    if request.method == 'GET':
        qs = PicAnalyticsAccess.objects.select_related('staff__user', 'staff__branch', 'granted_by__user',
                                                       'revoked_by__user')[:200]
        return Response({'rows': [_grant_json(g) for g in qs]})
    from apps.users.models import StaffProfile
    staff = StaffProfile.objects.filter(pk=request.data.get('staff_id'), is_active=True).first()
    if staff is None:
        return _bad('موظف غير موجود — unknown staff')
    if PicAnalyticsAccess.objects.filter(staff=staff, revoked_at__isnull=True).exists():
        return _bad('لديه الصلاحية بالفعل — already granted')
    g = PicAnalyticsAccess.objects.create(staff=staff, granted_by=acc.profile,
                                          note=str(request.data.get('note') or '')[:255])
    from apps.audit.models import AuditLog
    AuditLog.log('pic_analytics_access_granted', user=acc.profile, obj=g, note=g.note, request=request,
                 extra={'staff_id': staff.pk, 'staff': staff.full_name})
    return Response(_grant_json(g), status=201)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def grant_revoke(request, pk):
    acc = Access(request)
    if not acc.can_manage_access:
        return _deny()
    g = PicAnalyticsAccess.objects.filter(pk=pk, revoked_at__isnull=True).select_related('staff__user').first()
    if g is None:
        return Response({'detail': 'غير موجود — Not found'}, status=404)
    g.revoked_at, g.revoked_by = timezone.now(), acc.profile
    g.save(update_fields=['revoked_at', 'revoked_by'])
    from apps.audit.models import AuditLog
    AuditLog.log('pic_analytics_access_revoked', user=acc.profile, obj=g, request=request,
                 note=str(request.data.get('note') or '')[:255], extra={'staff_id': g.staff_id})
    return Response(_grant_json(g))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def grant_candidates(request):
    acc = Access(request)
    if not acc.can_manage_access:
        return _deny()
    from apps.users.models import StaffProfile
    q = (request.query_params.get('q') or '').strip()
    granted = set(PicAnalyticsAccess.objects.filter(revoked_at__isnull=True).values_list('staff_id', flat=True))
    qs = StaffProfile.objects.filter(is_active=True).exclude(role='admin').select_related('user', 'branch')
    if q:
        qs = qs.filter(Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q) |
                       Q(user__username__icontains=q) | Q(softech_username__icontains=q) |
                       Q(softech_user_id=q))
    rows = [{'id': p.id, 'name': p.full_name, 'role': p.role, 'branch': p.branch_name,
             'granted': p.id in granted} for p in qs.order_by('branch__softech_branch_id')[:30]]
    return Response({'rows': rows})
