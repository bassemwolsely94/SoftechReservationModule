"""
apps/payments/views.py

Module 6: Payment Tracking
"""
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import filters, generics, status
from rest_framework.decorators import api_view, parser_classes, permission_classes
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

class ExternalPaymentListView(generics.ListCreateAPIView):
    """
    GET  /api/payments/  — list with filters
    POST /api/payments/  — create new payment record
    """
    permission_classes = [IsAuthenticated]
    filter_backends    = [filters.SearchFilter, filters.OrderingFilter]
    search_fields      = ['customer_name', 'reference_number', 'softech_invoice_code', 'customer_phone']
    ordering_fields    = ['created_at', 'payment_date', 'amount', 'status']
    ordering           = ['-created_at']

    def get_queryset(self):
        qs = ExternalPayment.objects.select_related(
            'branch', 'customer', 'created_by', 'confirmed_by'
        ).prefetch_related('reconciliation_logs')

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


class ExternalPaymentDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET    /api/payments/{id}/
    PATCH  /api/payments/{id}/
    DELETE /api/payments/{id}/
    """
    permission_classes = [IsAuthenticated]
    queryset = ExternalPayment.objects.select_related(
        'branch', 'customer', 'created_by', 'confirmed_by'
    ).prefetch_related('reconciliation_logs')

    def get_serializer_class(self):
        if self.request.method in ('PUT', 'PATCH'):
            return ExternalPaymentCreateSerializer
        return ExternalPaymentSerializer


# ── Action views ──────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def payment_confirm(request, pk):
    """
    POST /api/payments/{id}/confirm/
    Restricted to admin or pharmacist role.
    """
    # Role check
    profile = getattr(request.user, 'staff_profile', None)
    if profile and profile.role not in ('admin', 'pharmacist'):
        return Response(
            {'detail': 'هذا الإجراء مسموح للمدير والصيدلاني فقط.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    payment = get_object_or_404(ExternalPayment, pk=pk)
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
@permission_classes([IsAuthenticated])
def payment_reconcile(request, pk):
    """
    POST /api/payments/{id}/reconcile/
    Body: { notes (optional), variance (optional, default 0) }
    """
    payment = get_object_or_404(ExternalPayment, pk=pk)
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
@permission_classes([IsAuthenticated])
def payment_dispute(request, pk):
    """
    POST /api/payments/{id}/dispute/
    Body: { reason (required) }
    """
    payment = get_object_or_404(ExternalPayment, pk=pk)
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
@permission_classes([IsAuthenticated])
def payment_summary(request):
    """
    GET /api/payments/summary/
    Returns aggregated stats for today's payments.
    """
    today = timezone.localdate()
    today_qs = ExternalPayment.objects.filter(payment_date=today)

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

    total_confirmed = ExternalPayment.objects.filter(
        status=ExternalPayment.STATUS_CONFIRMED,
        payment_date=today,
    ).count()

    total_pending = ExternalPayment.objects.filter(
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
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def payment_upload_screenshot(request, pk):
    """
    POST /api/payments/{id}/screenshot/
    Multipart: file field name = 'screenshot'
    """
    payment = get_object_or_404(ExternalPayment, pk=pk)

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
