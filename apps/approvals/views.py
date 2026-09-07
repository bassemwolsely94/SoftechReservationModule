from rest_framework import viewsets, mixins, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import ApprovalWorkflowDefinition, ApprovalRequest
from .permissions import CanViewApprovals
from .serializers import (
    ApprovalWorkflowDefinitionSerializer,
    ApprovalRequestSerializer,
    ApprovalRequestListSerializer,
    DecideSerializer,
    CancelSerializer,
)
from .service import ApprovalService, ApprovalError


class ApprovalWorkflowViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    Read-only for non-admins.  Admins can manage workflows via Django admin.
    GET /api/approvals/workflows/
    GET /api/approvals/workflows/{id}/
    """
    serializer_class   = ApprovalWorkflowDefinitionSerializer
    permission_classes = [CanViewApprovals]
    queryset           = ApprovalWorkflowDefinition.objects.filter(is_active=True).prefetch_related('steps')


class ApprovalRequestViewSet(
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    GET  /api/approvals/requests/          — all requests (admin/supervisor see all; others see own)
    GET  /api/approvals/requests/pending/  — requests awaiting MY action
    GET  /api/approvals/requests/mine/     — requests I submitted
    GET  /api/approvals/requests/{id}/     — full detail
    POST /api/approvals/requests/{id}/decide/  — approve / reject / delegate / return
    POST /api/approvals/requests/{id}/cancel/  — cancel
    """
    permission_classes = [CanViewApprovals]

    def get_queryset(self):
        profile = self.request.user.staff_profile
        qs = ApprovalRequest.objects.select_related(
            'workflow', 'requested_by', 'requested_by__branch',
        ).prefetch_related('decisions', 'escalations')

        if profile.role in ('admin', 'supervisor'):
            qs = qs.all()
        else:
            qs = qs.filter(requested_by=profile)

        # Optional filters
        wf = self.request.query_params.get('workflow')
        if wf:
            qs = qs.filter(workflow__code=wf)

        st = self.request.query_params.get('status')
        if st:
            statuses = [s.strip() for s in st.split(',') if s.strip()]
            qs = qs.filter(status__in=statuses) if len(statuses) > 1 else qs.filter(status=statuses[0])

        return qs.order_by('-requested_at')

    def get_serializer_class(self):
        if self.action == 'list':
            return ApprovalRequestListSerializer
        return ApprovalRequestSerializer

    @action(detail=False, methods=['get'], url_path='pending')
    def pending(self, request):
        """Requests that are waiting for MY decision.
        Optional ?category=operational|hr|finance filters by workflow category
        (used by the mobile operational approvals inbox to exclude HR)."""
        profile = request.user.staff_profile
        requests = ApprovalService.pending_for(profile)
        category = request.query_params.get('category')
        if category:
            requests = [r for r in requests if r.workflow.category == category]
        serializer = ApprovalRequestListSerializer(requests, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='mine')
    def mine(self, request):
        """Requests I submitted."""
        profile = request.user.staff_profile
        qs = ApprovalRequest.objects.filter(
            requested_by=profile
        ).select_related('workflow').order_by('-requested_at')
        serializer = ApprovalRequestListSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='decide')
    def decide(self, request, pk=None):
        approval_request = self.get_object()
        serializer = DecideSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data    = serializer.validated_data
        profile = request.user.staff_profile

        delegated_to = None
        if data.get('delegated_to'):
            from apps.users.models import StaffProfile
            try:
                delegated_to = StaffProfile.objects.get(pk=data['delegated_to'])
            except StaffProfile.DoesNotExist:
                return Response({'detail': 'المستخدم المفوَّض إليه غير موجود.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            decision = ApprovalService.decide(
                request=approval_request,
                decision=data['decision'],
                decided_by=profile,
                notes=data.get('notes', ''),
                delegated_to=delegated_to,
            )
        except ApprovalError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            ApprovalRequestSerializer(approval_request).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel(self, request, pk=None):
        approval_request = self.get_object()
        serializer = CancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            ApprovalService.cancel(
                request=approval_request,
                cancelled_by=request.user.staff_profile,
                reason=serializer.validated_data.get('reason', ''),
            )
        except ApprovalError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({'detail': 'تم الإلغاء.'}, status=status.HTTP_200_OK)
