"""
apps/payments/views.py

Module 6: Payment Tracking
"""
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import filters, generics, status
from rest_framework.decorators import api_view, parser_classes, permission_classes

from core import branch_scope
from core.permissions import matrix_permission

# External payments sit in the finance module (Batch 4, Z-3): read = view, record = create,
# change = edit, delete = delete; confirm / reconcile = approve; dispute / screenshot = edit.
FINANCE         = matrix_permission('finance')
FINANCE_APPROVE = matrix_permission('finance', post=('approve',))
FINANCE_EDIT    = matrix_permission('finance', post=('edit',))
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import ExternalPayment, PaymentReconciliationLog
from .serializers import (
    ExternalPaymentCreateSerializer,
    ExternalPaymentSerializer,
    PaymentReconciliationLogSerializer,
)


def _log_action(payment, action, user, notes='', variance=0):
    PaymentReconciliationLog.objects.create(
        payment=payment,
        action=action,
        notes=notes,
        variance=variance,
        performed_by=user,
    )


# ── CRUD views ────────────────────────────────────────────────────────────────

class ExternalPaymentListView(branch_scope.BranchScopedMixin, generics.ListCreateAPIView):
    """
    GET  /api/payments/  — list with filters
    POST /api/payments/  — create new payment record
    """
    permission_classes = [IsAuthenticated, FINANCE]
    filter_backends    = [filters.SearchFilter, filters.OrderingFilter]
    search_fields      = ['customer_name', 'reference_number', 'softech_invoice_code', 'customer_phone']
    ordering_fields    = ['created_at', 'payment_date', 'amount', 'status']
    ordering           = ['-created_at']

    def get_queryset(self):
        qs = branch_scope.scope(ExternalPayment.objects.select_related(
            'branch', 'customer', 'created_by', 'confirmed_by'
        ).prefetch_related('reconciliation_logs'), self.request.user)

        method       = self.request.query_params.get('method')
        pay_status   = self.request.query_params.get('status')
        branch       = self.request.query_params.get('branch')
        payment_date = self.request.query_params.get('payment_date')

        if method:
            qs = qs.filter(method=method)
        if pay_status:
            qs = qs.filter(status=pay_status)
        if branch:
            qs = qs.filter(branch_id=branch)
        if payment_date:
            qs = qs.filter(payment_date=payment_date)
        return qs

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return ExternalPaymentCreateSerializer
        return ExternalPaymentSerializer


class ExternalPaymentDetailView(branch_scope.BranchScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    """
    GET    /api/payments/{id}/
    PATCH  /api/payments/{id}/
    DELETE /api/payments/{id}/
    """
    permission_classes = [IsAuthenticated, FINANCE]
    queryset = ExternalPayment.objects.select_related(
        'branch', 'customer', 'created_by', 'confirmed_by'
    ).prefetch_related('reconciliation_logs')

    def get_serializer_class(self):
        if self.request.method in ('PUT', 'PATCH'):
            return ExternalPaymentCreateSerializer
        return ExternalPaymentSerializer

    # Batch 4, Z-10a: a payment is corrected only while pending or disputed — once confirmed,
    # reconciled or cancelled its amount, branch and SOFTECH references are closed — and only a
    # pending payment can be deleted. Status itself moves only through confirm / reconcile / dispute.
    EDITABLE = (ExternalPayment.STATUS_PENDING, ExternalPayment.STATUS_DISPUTED)

    def update(self, request, *args, **kwargs):
        payment = self.get_object()
        if payment.status not in self.EDITABLE:
            return Response({'detail': f'لا يمكن تعديل دفعة بحالة "{payment.get_status_display()}".'},
                            status=status.HTTP_409_CONFLICT)
        return super().update(request, *args, **kwargs)

    def perform_update(self, serializer):
        self.check_branch_value(serializer)
        # each correction lands in the payment's log, before → after (Batch 4, Z-10c)
        before = {f: getattr(serializer.instance, f) for f in serializer.validated_data}
        payment = serializer.save()
        changes = '، '.join(f'{f}: {before[f]} → {getattr(payment, f)}'
                           for f in before if before[f] != getattr(payment, f))
        if changes:
            _log_action(payment, 'edited', self.request.user, notes=changes)

    def destroy(self, request, *args, **kwargs):
        payment = self.get_object()
        if payment.status != ExternalPayment.STATUS_PENDING:
            return Response({'detail': f'لا يمكن حذف دفعة بحالة "{payment.get_status_display()}".'},
                            status=status.HTTP_409_CONFLICT)
        return super().destroy(request, *args, **kwargs)


# ── Action views ──────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated, FINANCE_APPROVE])
def payment_confirm(request, pk):
    """
    POST /api/payments/{id}/confirm/
    Needs finance approve (FINANCE_APPROVE: admin, purchasing). A hard-coded admin / pharmacist list
    used to sit here too — pharmacists hold finance view only, so in practice only admin could
    confirm, against the matrix and the help (Batch 4, Z-11d — overblock review decision 2).
    """
    payment = branch_scope.get_or_404(ExternalPayment, request.user, pk=pk)
    if payment.status not in (ExternalPayment.STATUS_PENDING, ExternalPayment.STATUS_DISPUTED):
        return Response(
            {'detail': f'لا يمكن تأكيد دفعة بحالة "{payment.get_status_display()}".'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    notes = request.data.get('notes', '')
    payment.status       = ExternalPayment.STATUS_CONFIRMED
    payment.confirmed_by = request.user
    payment.confirmed_at = timezone.now()
    payment.save(update_fields=['status', 'confirmed_by', 'confirmed_at', 'updated_at'])

    _log_action(payment, 'confirmed', request.user, notes=notes)

    return Response(ExternalPaymentSerializer(payment).data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated, FINANCE_APPROVE])
def payment_reconcile(request, pk):
    """
    POST /api/payments/{id}/reconcile/
    Body: { notes (optional), variance (optional, default 0) }
    """
    payment = branch_scope.get_or_404(ExternalPayment, request.user, pk=pk)
    if payment.status not in (ExternalPayment.STATUS_CONFIRMED, ExternalPayment.STATUS_DISPUTED):
        return Response(
            {'detail': f'لا يمكن تسوية دفعة بحالة "{payment.get_status_display()}".'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    notes    = request.data.get('notes', '')
    variance = request.data.get('variance', 0)

    try:
        variance = float(variance)
    except (TypeError, ValueError):
        variance = 0.0

    payment.status = ExternalPayment.STATUS_RECONCILED
    payment.save(update_fields=['status', 'updated_at'])

    _log_action(payment, 'reconciled', request.user, notes=notes, variance=variance)

    return Response(ExternalPaymentSerializer(payment).data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated, FINANCE_EDIT])
def payment_dispute(request, pk):
    """
    POST /api/payments/{id}/dispute/
    Body: { reason (required) }
    """
    payment = branch_scope.get_or_404(ExternalPayment, request.user, pk=pk)
    if payment.status in (ExternalPayment.STATUS_CANCELLED, ExternalPayment.STATUS_RECONCILED):
        return Response(
            {'detail': f'لا يمكن الاعتراض على دفعة بحالة "{payment.get_status_display()}".'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    reason = request.data.get('reason', '').strip()
    if not reason:
        return Response({'detail': 'سبب الاعتراض مطلوب.'}, status=status.HTTP_400_BAD_REQUEST)

    payment.status = ExternalPayment.STATUS_DISPUTED
    payment.save(update_fields=['status', 'updated_at'])

    _log_action(payment, 'disputed', request.user, notes=reason)

    return Response(ExternalPaymentSerializer(payment).data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated, FINANCE])
def payment_summary(request):
    """
    GET /api/payments/summary/
    Returns aggregated stats for today's payments.
    """
    today = timezone.localdate()
    mine = branch_scope.scope(ExternalPayment.objects.all(), request.user)
    today_qs = mine.filter(payment_date=today)

    total_today = today_qs.count()

    # Breakdown by method
    method_agg = today_qs.values('method').annotate(
        count=Count('id'),
        total=Sum('amount'),
    )
    by_method = {
        ExternalPayment.METHOD_CASH:          {'count': 0, 'total': 0.0},
        ExternalPayment.METHOD_INSTAPAY:      {'count': 0, 'total': 0.0},
        ExternalPayment.METHOD_VODAFONE_CASH: {'count': 0, 'total': 0.0},
        ExternalPayment.METHOD_BANK_TRANSFER: {'count': 0, 'total': 0.0},
        ExternalPayment.METHOD_OTHER:         {'count': 0, 'total': 0.0},
    }
    for row in method_agg:
        m = row['method']
        if m in by_method:
            by_method[m] = {
                'count': row['count'],
                'total': float(row['total'] or 0),
            }

    total_confirmed = mine.filter(
        status=ExternalPayment.STATUS_CONFIRMED,
        payment_date=today,
    ).count()

    total_pending = mine.filter(
        status=ExternalPayment.STATUS_PENDING,
        payment_date=today,
    ).count()

    total_value_today = today_qs.aggregate(t=Sum('amount'))['t'] or 0

    return Response({
        'total_today':       total_today,
        'by_method':         by_method,
        'total_confirmed':   total_confirmed,
        'total_pending':     total_pending,
        'total_value_today': float(total_value_today),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated, FINANCE_EDIT])
@parser_classes([MultiPartParser, FormParser])
def payment_upload_screenshot(request, pk):
    """
    POST /api/payments/{id}/screenshot/
    Multipart: file field name = 'screenshot'
    """
    payment = branch_scope.get_or_404(ExternalPayment, request.user, pk=pk)

    screenshot = request.FILES.get('screenshot')
    if not screenshot:
        return Response({'detail': 'لم يتم إرفاق ملف.'}, status=status.HTTP_400_BAD_REQUEST)

    payment.screenshot = screenshot
    payment.save(update_fields=['screenshot', 'updated_at'])

    _log_action(payment, 'screenshot_uploaded', request.user,
                notes=f'رُفع ملف: {screenshot.name}')

    return Response(
        {'screenshot_url': request.build_absolute_uri(payment.screenshot.url)},
        status=status.HTTP_200_OK,
    )
