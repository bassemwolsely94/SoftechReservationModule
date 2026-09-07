from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone

from .models import AuditLog, AbuseFlag
from .serializers import AuditLogSerializer, AbuseFlagSerializer, AbuseFlagListSerializer
from .detector import run_abuse_detection, detect_erp_mismatches


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


def _is_admin(request):
    profile = _profile(request)
    return profile and profile.role in ('admin', 'purchasing')


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only audit log API — admin only."""
    serializer_class   = AuditLogSerializer
    permission_classes = [IsAuthenticated]
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields   = ['action', 'model_name', 'user']
    search_fields      = ['user_name', 'object_repr', 'note']
    ordering_fields    = ['created_at']
    ordering           = ['-created_at']

    def get_queryset(self):
        if not _is_admin(self.request):
            # Non-admins can only see their own audit trail
            profile = _profile(self.request)
            if profile:
                return AuditLog.objects.filter(user=profile)
            return AuditLog.objects.none()
        return AuditLog.objects.select_related('user__user')

    @action(detail=False, methods=['get'], url_path='for-object')
    def for_object(self, request):
        """
        GET /api/audit/logs/for-object/?model=Reservation&id=42
        Returns audit trail for a specific object.
        """
        model = request.query_params.get('model', '').strip()
        obj_id = request.query_params.get('id', '').strip()
        if not model or not obj_id:
            return Response({'detail': 'model و id مطلوبان'}, status=400)

        qs = AuditLog.objects.filter(
            model_name=model, object_id=obj_id
        ).select_related('user__user').order_by('-created_at')
        return Response(AuditLogSerializer(qs, many=True).data)

    @action(detail=False, methods=['get'], url_path='for-user')
    def for_user(self, request):
        """
        GET /api/audit/logs/for-user/?staff_id=5
        Returns audit trail for a specific staff member — admin only.
        """
        if not _is_admin(request):
            return Response({'detail': 'غير مصرح'}, status=403)
        staff_id = request.query_params.get('staff_id')
        if not staff_id:
            return Response({'detail': 'staff_id مطلوب'}, status=400)
        qs = AuditLog.objects.filter(
            user_id=staff_id
        ).order_by('-created_at')[:200]
        return Response(AuditLogSerializer(qs, many=True).data)


class AbuseFlagViewSet(viewsets.ReadOnlyModelViewSet):
    """Abuse flags — admin only."""
    permission_classes = [IsAuthenticated]
    filter_backends    = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields   = ['flag_type', 'severity', 'status', 'staff']
    ordering_fields    = ['detected_at', 'severity']
    ordering           = ['-detected_at']

    def get_queryset(self):
        if not _is_admin(self.request):
            return AbuseFlag.objects.none()
        return AbuseFlag.objects.select_related('staff__user', 'reviewed_by__user')

    def get_serializer_class(self):
        if self.action == 'list':
            return AbuseFlagListSerializer
        return AbuseFlagSerializer

    @action(detail=True, methods=['post'])
    def review(self, request, pk=None):
        """POST /api/audit/flags/{id}/review/ — mark as reviewed."""
        if not _is_admin(request):
            return Response({'detail': 'غير مصرح'}, status=403)
        flag = self.get_object()
        new_status = request.data.get('status', 'reviewed')
        note       = request.data.get('note', '')

        if new_status not in ('reviewed', 'dismissed', 'escalated'):
            return Response({'detail': 'حالة غير صالحة'}, status=400)

        flag.status      = new_status
        flag.review_note = note
        flag.reviewed_by = _profile(request)
        flag.reviewed_at = timezone.now()
        flag.save(update_fields=['status', 'review_note', 'reviewed_by', 'reviewed_at'])

        return Response(AbuseFlagSerializer(flag).data)

    @action(detail=False, methods=['post'], url_path='run-detection')
    def run_detection(self, request):
        """POST /api/audit/flags/run-detection/ — trigger abuse scan."""
        if not _is_admin(request):
            return Response({'detail': 'غير مصرح'}, status=403)

        hours = int(request.data.get('window_hours', 24))
        flags = run_abuse_detection(window_hours=hours)
        erp   = detect_erp_mismatches(days=7)

        return Response({
            'pattern_flags_created': flags,
            'erp_mismatch_flags':    erp,
            'total':                 flags + erp,
        })

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """GET /api/audit/flags/summary/ — open flags by type."""
        if not _is_admin(request):
            return Response({'detail': 'غير مصرح'}, status=403)

        from django.db.models import Count
        data = AbuseFlag.objects.filter(status='open').values(
            'flag_type', 'severity'
        ).annotate(count=Count('id')).order_by('-count')

        return Response({
            'open_flags': list(data),
            'total_open': AbuseFlag.objects.filter(status='open').count(),
        })
