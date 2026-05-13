from rest_framework import viewsets, filters, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from .models import ChronicMedicationProfile, FollowUpTask
from .serializers import (
    ChronicMedicationProfileSerializer, ChronicMedicationProfileWriteSerializer,
    FollowUpTaskListSerializer, FollowUpTaskDetailSerializer,
    FollowUpTaskCreateSerializer, FollowUpActionSerializer,
)
from . import services


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


class ChronicMedicationProfileViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields   = ['is_chronic', 'source']
    search_fields      = ['item__name', 'item__softech_id']

    def get_queryset(self):
        return ChronicMedicationProfile.objects.select_related('item', 'created_by__user')

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return ChronicMedicationProfileWriteSerializer
        return ChronicMedicationProfileSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=_profile(self.request))

    @action(detail=False, methods=['post'], url_path='infer-from-erp')
    def infer_from_erp(self, request):
        """POST /api/followups/chronic/infer-from-erp/ — detect chronic meds from ERP history."""
        min_purchases = int(request.data.get('min_purchase_count', 3))
        min_months    = int(request.data.get('min_months', 2))
        count = services.infer_chronic_profiles_from_erp(
            min_purchase_count=min_purchases,
            min_months=min_months,
        )
        return Response({'profiles_created_or_updated': count})


class FollowUpTaskViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields   = ['status', 'task_type', 'branch', 'assigned_to']
    search_fields      = ['customer__name', 'customer__phone', 'item__name']
    ordering_fields    = ['due_date', 'created_at', 'status']
    ordering           = ['due_date', '-created_at']

    def get_queryset(self):
        qs = FollowUpTask.objects.select_related(
            'customer', 'item', 'branch',
            'assigned_to__user', 'created_by__user',
            'chronic_profile__item',
        )
        profile = _profile(self.request)
        if not profile:
            return qs.none()

        # Branch staff see only their branch tasks
        if profile.role not in ('admin', 'call_center', 'purchasing'):
            if profile.branch:
                return qs.filter(branch=profile.branch)
            return qs.none()

        return qs

    def get_serializer_class(self):
        if self.action == 'list':
            return FollowUpTaskListSerializer
        if self.action == 'create':
            return FollowUpTaskCreateSerializer
        return FollowUpTaskDetailSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=_profile(self.request))

    # ── State machine actions ─────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def call(self, request, pk=None):
        task = self.get_object()
        s    = FollowUpActionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        services.mark_task_called(task, note=s.validated_data.get('note', ''), staff=_profile(request))
        return Response(FollowUpTaskDetailSerializer(task).data)

    @action(detail=True, methods=['post'])
    def done(self, request, pk=None):
        task = self.get_object()
        s    = FollowUpActionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        services.mark_task_done(task, note=s.validated_data.get('note', ''), staff=_profile(request))
        return Response(FollowUpTaskDetailSerializer(task).data)

    @action(detail=True, methods=['post'])
    def missed(self, request, pk=None):
        task = self.get_object()
        s    = FollowUpActionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        services.mark_task_missed(task, note=s.validated_data.get('note', ''), staff=_profile(request))
        return Response(FollowUpTaskDetailSerializer(task).data)

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        profile   = _profile(request)
        branch_id = request.query_params.get('branch')
        days      = int(request.query_params.get('days', 30))

        branch = None
        if branch_id:
            from apps.branches.models import Branch
            branch = Branch.objects.filter(pk=branch_id).first()
        elif profile and profile.branch and profile.role not in ('admin', 'call_center'):
            branch = profile.branch

        return Response(services.get_dashboard_stats(branch=branch, days=days))

    @action(detail=False, methods=['post'], url_path='generate')
    def generate(self, request):
        """
        POST /api/followups/tasks/generate/
        Trigger bulk follow-up task generation from ERP history.
        Body: {"dry_run": true, "branch_id": 5}
        """
        dry_run   = request.data.get('dry_run', False)
        branch_id = request.data.get('branch_id')
        branch    = None
        if branch_id:
            from apps.branches.models import Branch
            branch = Branch.objects.filter(pk=branch_id).first()

        count = services.generate_followup_tasks_bulk(
            branch=branch, dry_run=dry_run
        )
        return Response({
            'tasks_created': count,
            'dry_run':       dry_run,
        })

    @action(detail=False, methods=['post'], url_path='auto-close')
    def auto_close(self, request):
        """POST /api/followups/tasks/auto-close/ — manually trigger ERP auto-close."""
        minutes = int(request.data.get('minutes', 12))
        count   = services.auto_close_followup_tasks_from_erp(since_minutes=minutes)
        return Response({'tasks_auto_closed': count})
