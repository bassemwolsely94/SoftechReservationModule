"""
Payment Audit ViewSets
======================
BankStatementImportViewSet  — upload & trigger matching
BankStatementLineViewSet    — browse lines, manual-match action
PaymentExceptionViewSet     — triage exceptions
"""
import logging

from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .audit_serializers import (
    BankStatementImportSerializer,
    BankStatementLineSerializer,
    ManualMatchSerializer,
    PaymentExceptionSerializer,
)
from .audit_service import PaymentAuditService
from .models import BankStatementImport, BankStatementLine, ExternalPayment, PaymentException

logger = logging.getLogger('elrezeiky')

FINANCE_ROLES = {'admin', 'supervisor', 'purchasing'}


def _staff(request):
    return getattr(request.user, 'staff_profile', None)


def _require_role(request, allowed_roles):
    sp = _staff(request)
    if sp and sp.role in allowed_roles:
        return True
    return False


class BankStatementImportViewSet(viewsets.ModelViewSet):
    """Upload CSV/XLSX bank statements and trigger automatic matching."""
    serializer_class    = BankStatementImportSerializer
    parser_classes      = [MultiPartParser, FormParser]
    permission_classes  = [IsAuthenticated]

    def get_queryset(self):
        sp  = _staff(self.request)
        qs  = BankStatementImport.objects.select_related('branch', 'imported_by').order_by('-imported_at')
        if sp and sp.role not in ('admin', 'supervisor'):
            qs = qs.filter(branch=sp.branch)
        branch = self.request.query_params.get('branch')
        if branch:
            qs = qs.filter(branch_id=branch)
        return qs

    def perform_create(self, serializer):
        serializer.save(imported_by=_staff(self.request))

    @action(detail=True, methods=['post'], url_path='run-matching')
    def run_matching(self, request, pk=None):
        """Trigger auto-matching for a statement import."""
        if not _require_role(request, FINANCE_ROLES):
            return Response({'detail': 'غير مصرح'}, status=status.HTTP_403_FORBIDDEN)

        stmt = self.get_object()
        try:
            result = PaymentAuditService.match_statement_to_payments(stmt.pk)
            return Response({'detail': 'تمت المطابقة', **result})
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            logger.exception('run_matching failed for import #%s', stmt.pk)
            return Response({'detail': 'حدث خطأ أثناء المطابقة'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class BankStatementLineViewSet(viewsets.ReadOnlyModelViewSet):
    """Browse statement lines and perform manual matches."""
    serializer_class   = BankStatementLineSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = BankStatementLine.objects.select_related(
            'statement_import', 'matched_payment', 'matched_by'
        )
        import_id    = self.request.query_params.get('import')
        match_method = self.request.query_params.get('match_method')
        if import_id:
            qs = qs.filter(statement_import_id=import_id)
        if match_method:
            qs = qs.filter(match_method=match_method)
        return qs

    @action(detail=True, methods=['post'], url_path='manual-match')
    def manual_match(self, request, pk=None):
        """Manually link this line to an ExternalPayment."""
        if not _require_role(request, FINANCE_ROLES):
            return Response({'detail': 'غير مصرح'}, status=status.HTTP_403_FORBIDDEN)

        line = self.get_object()
        ser  = ManualMatchSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        payment = get_object_or_404(ExternalPayment, pk=ser.validated_data['payment_id'])
        try:
            updated = PaymentAuditService.manual_match(
                line       = line,
                payment    = payment,
                matched_by = _staff(request),
            )
            return Response(BankStatementLineSerializer(updated).data)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class PaymentExceptionViewSet(viewsets.ModelViewSet):
    """Triage, assign, and resolve payment exceptions."""
    serializer_class   = PaymentExceptionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = PaymentException.objects.select_related(
            'payment', 'statement_line', 'assigned_to', 'resolved_by'
        ).order_by('-created_at')

        exc_type = self.request.query_params.get('type')
        sev      = self.request.query_params.get('severity')
        st       = self.request.query_params.get('status')
        if exc_type:
            qs = qs.filter(exception_type=exc_type)
        if sev:
            qs = qs.filter(severity=sev)
        if st:
            qs = qs.filter(status=st)
        return qs

    @action(detail=True, methods=['post'], url_path='resolve')
    def resolve(self, request, pk=None):
        exc  = self.get_object()
        note = request.data.get('resolution_notes', '')
        if exc.status in ('resolved', 'dismissed'):
            return Response({'detail': 'هذا الاستثناء مغلق بالفعل'}, status=status.HTTP_400_BAD_REQUEST)
        from django.utils import timezone
        exc.status           = 'resolved'
        exc.resolution_notes = note
        exc.resolved_by      = _staff(request)
        exc.resolved_at      = timezone.now()
        exc.save(update_fields=['status', 'resolution_notes', 'resolved_by', 'resolved_at'])
        return Response(PaymentExceptionSerializer(exc).data)

    @action(detail=True, methods=['post'], url_path='dismiss')
    def dismiss(self, request, pk=None):
        exc = self.get_object()
        if exc.status in ('resolved', 'dismissed'):
            return Response({'detail': 'هذا الاستثناء مغلق بالفعل'}, status=status.HTTP_400_BAD_REQUEST)
        from django.utils import timezone
        exc.status      = 'dismissed'
        exc.resolved_by = _staff(request)
        exc.resolved_at = timezone.now()
        exc.save(update_fields=['status', 'resolved_by', 'resolved_at'])
        return Response(PaymentExceptionSerializer(exc).data)

    @action(detail=True, methods=['post'], url_path='assign')
    def assign(self, request, pk=None):
        from apps.users.models import StaffProfile
        exc      = self.get_object()
        staff_id = request.data.get('staff_id')
        if not staff_id:
            return Response({'detail': 'staff_id مطلوب'}, status=status.HTTP_400_BAD_REQUEST)
        exc.assigned_to = get_object_or_404(StaffProfile, pk=staff_id)
        exc.status      = 'investigating'
        exc.save(update_fields=['assigned_to', 'status'])
        return Response(PaymentExceptionSerializer(exc).data)
