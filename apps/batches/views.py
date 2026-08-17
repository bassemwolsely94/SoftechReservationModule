from rest_framework import viewsets, mixins, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import StockBatch, NearExpiryAlert
from .serializers import (
    StockBatchSerializer, StockBatchListSerializer,
    NearExpiryAlertSerializer, FEFORecommendationSerializer,
)
from .service import BatchService


class StockBatchViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    GET /api/batches/                    — list (filter: item, branch, vendor, expiring_in_days)
    GET /api/batches/{id}/               — full detail with movements
    GET /api/batches/fefo/?item=&branch= — FEFO-ordered list for dispatch
    GET /api/batches/near-expiry/        — near-expiry dashboard summary
    GET /api/batches/alerts/             — NearExpiryAlert list
    POST /api/batches/{id}/quarantine/   — quarantine a batch
    """
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = StockBatch.objects.select_related('item', 'branch', 'vendor', 'received_by')
        p  = self.request.query_params

        if p.get('item'):
            qs = qs.filter(item_id=p['item'])
        if p.get('branch'):
            qs = qs.filter(branch_id=p['branch'])
        if p.get('vendor'):
            qs = qs.filter(vendor_id=p['vendor'])
        if p.get('expiring_in_days'):
            from django.utils import timezone
            from datetime import timedelta
            cutoff = timezone.now().date() + timedelta(days=int(p['expiring_in_days']))
            qs = qs.filter(expiry_date__lte=cutoff, is_expired=False, current_qty__gt=0)
        if p.get('is_quarantined'):
            qs = qs.filter(is_quarantined=p['is_quarantined'].lower() == 'true')
        if p.get('is_expired'):
            qs = qs.filter(is_expired=p['is_expired'].lower() == 'true')

        return qs.order_by('expiry_date', 'id')

    def get_serializer_class(self):
        if self.action in ('list', 'fefo'):
            return StockBatchListSerializer
        return StockBatchSerializer

    @action(detail=False, methods=['get'])
    def fefo(self, request):
        """FEFO-ordered active batches for a given item × branch."""
        item_id   = request.query_params.get('item')
        branch_id = request.query_params.get('branch')
        if not item_id or not branch_id:
            return Response({'detail': 'item و branch مطلوبان.'}, status=status.HTTP_400_BAD_REQUEST)

        batches = BatchService.fefo_batches(int(item_id), int(branch_id))
        serializer = FEFORecommendationSerializer(batches, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='near-expiry')
    def near_expiry(self, request):
        """Near-expiry KPI summary for dashboard."""
        branch_id = request.query_params.get('branch')
        days      = int(request.query_params.get('days', 180))
        data      = BatchService.near_expiry_summary(
            branch_id=int(branch_id) if branch_id else None,
            days=days,
        )
        return Response(data)

    @action(detail=False, methods=['get'])
    def alerts(self, request):
        """Active (unresolved) NearExpiryAlert list."""
        qs = NearExpiryAlert.objects.filter(
            resolved_at__isnull=True
        ).select_related('batch', 'batch__item', 'batch__branch', 'batch__vendor')

        if request.query_params.get('branch'):
            qs = qs.filter(batch__branch_id=request.query_params['branch'])
        if request.query_params.get('threshold'):
            qs = qs.filter(threshold_days=request.query_params['threshold'])

        qs = qs.order_by('batch__expiry_date')
        serializer = NearExpiryAlertSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def quarantine(self, request, pk=None):
        """Put a batch into quarantine (quality hold)."""
        batch  = self.get_object()
        reason = request.data.get('reason', '')
        if not reason:
            return Response({'detail': 'سبب العزل مطلوب.'}, status=status.HTTP_400_BAD_REQUEST)

        # Require approval for quarantine if not admin
        profile = request.user.staff_profile
        if profile.role not in ('admin', 'quality_manager'):
            # Submit approval request first; actual quarantine happens on approval
            from apps.approvals.service import ApprovalService
            ApprovalService.submit(
                workflow_code='batch_quarantine',
                subject_object=batch,
                title=f'عزل دفعة: {batch.item.name} — {batch.batch_number}',
                requested_by=profile,
                context_data={
                    'batch_id': batch.pk,
                    'reason':   reason,
                    'qty':      str(batch.current_qty),
                },
            )
            return Response(
                {'detail': 'تم رفع طلب عزل الدفعة للاعتماد.'},
                status=status.HTTP_202_ACCEPTED,
            )

        BatchService.quarantine(batch=batch, reason=reason, performed_by=profile)
        return Response({'detail': 'تم عزل الدفعة.'}, status=status.HTTP_200_OK)
