"""
Payment Audit ViewSets
======================
BankStatementImportViewSet  — upload & trigger matching
BankStatementLineViewSet    — browse lines, manual-match action
PaymentExceptionViewSet     — triage exceptions
"""
import logging

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from django.db.models import Q

from core import branch_scope
from core.stable_ordering import StableOrderingMixin
from core.permissions import MatrixPermission

from .audit_serializers import (
    BankStatementImportSerializer,
    BankStatementLineSerializer,
    ManualMatchSerializer,
    PaymentExceptionSerializer,
)
from .audit_service import PaymentAuditService
from .statement_parser import UNREADABLE_FILE, StatementParseError, parse_statement
from .models import BankStatementImport, BankStatementLine, ExternalPayment, PaymentException
from core.permissions import RouteModuleDeletePermission  # round 2, owner answers 2026-11-05

logger = logging.getLogger('elrezeiky')

FINANCE_ROLES = {'admin', 'supervisor', 'purchasing'}


def _staff(request):
    return getattr(request.user, 'staff_profile', None)


def _require_role(request, allowed_roles):
    sp = _staff(request)
    if sp and sp.role in allowed_roles:
        return True
    return False


class BankStatementImportViewSet(StableOrderingMixin, viewsets.ModelViewSet):
    """Upload CSV/XLSX bank statements and trigger automatic matching."""
    serializer_class    = BankStatementImportSerializer
    parser_classes      = [MultiPartParser, FormParser]
    permission_classes  = [IsAuthenticated, MatrixPermission, RouteModuleDeletePermission]
    rbac_module         = 'finance'
    rbac_actions        = {'run_matching': ('edit',)}
    rbac_delete         = ('delete', 'approve')
    # sortable headers of the statements grid (ordering=<field> / -<field>; the list is paged, so the server sorts)
    ordering_fields     = ['id', 'bank_name', 'total_lines', 'matched_lines', 'status', 'imported_at']

    def get_queryset(self):
        qs  = branch_scope.scope(
            BankStatementImport.objects.select_related('branch', 'imported_by').order_by('-imported_at'),
            self.request.user)
        branch = self.request.query_params.get('branch')
        if branch:
            qs = qs.filter(branch_id=branch)
        return qs

    def create(self, request, *args, **kwargs):
        """Save the import, then read its file into lines (all or none). A file that cannot be
        read keeps the import as «فشل» with its message and answers 400 with that message."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        stmt = serializer.instance
        data = {**self.get_serializer(stmt).data, 'warnings': getattr(stmt, '_parse_warnings', [])}
        if stmt.status == BankStatementImport.STATUS_FAILED:
            return Response({**data, 'detail': stmt.error_message}, status=status.HTTP_400_BAD_REQUEST)
        return Response(data, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        from apps.audit.models import AuditLog

        branch_scope.check_branch_value(self.request.user, serializer)
        stmt = serializer.save(imported_by=_staff(self.request))
        file_name = serializer.validated_data['raw_file'].name
        warnings = []
        try:
            with transaction.atomic():
                with stmt.raw_file.open('rb') as fh:
                    lines, warnings = parse_statement(fh, file_name, stmt.statement_from, stmt.statement_to)
                BankStatementLine.objects.bulk_create(
                    [BankStatementLine(statement_import=stmt, **ln) for ln in lines], batch_size=1000)
                stmt.total_lines     = len(lines)
                stmt.unmatched_lines = len(lines)
                stmt.save(update_fields=['total_lines', 'unmatched_lines'])
        except StatementParseError as exc:
            stmt.status        = BankStatementImport.STATUS_FAILED
            stmt.error_message = str(exc).replace('\x00', '')
            stmt.save(update_fields=['status', 'error_message'])
        except Exception:
            logger.exception('statement import #%s: reading %s failed', stmt.pk, file_name)
            warnings = []
            stmt.status          = BankStatementImport.STATUS_FAILED
            stmt.error_message   = UNREADABLE_FILE
            stmt.total_lines     = 0
            stmt.unmatched_lines = 0
            stmt.save(update_fields=['status', 'error_message', 'total_lines', 'unmatched_lines'])
        stmt._parse_warnings = warnings
        AuditLog.log('bank_statement_uploaded', user=_staff(self.request), obj=stmt, request=self.request,
                     note=f'{file_name} — {stmt.total_lines} سطر'[:255],
                     extra={'file_name': file_name, 'lines': stmt.total_lines, 'status': stmt.status,
                            'branch_id': stmt.branch_id, 'bank_name': stmt.bank_name,
                            'payment_method': stmt.payment_method,
                            'statement_from': str(stmt.statement_from), 'statement_to': str(stmt.statement_to),
                            'warnings': warnings, 'error': stmt.error_message})

    @action(detail=False, methods=['get'], url_path='form-options')
    def form_options(self, request):
        """What the upload form offers: the user's branches, payment methods, bank names used."""
        from apps.branches.models import Branch

        branches = branch_scope.scope(Branch.objects.live(), request.user, 'id').order_by('name')
        rows = [{'id': b.pk, 'name': b.name_ar or b.name} for b in branches]
        ids = {r['id'] for r in rows}
        home = getattr(_staff(request), 'branch_id', None)
        default = home if home in ids else (rows[0]['id'] if len(rows) == 1 else None)
        banks = (self.get_queryset().order_by().exclude(bank_name='')
                 .values_list('bank_name', flat=True).distinct())
        return Response({
            'branches':        rows,
            'default_branch':  default,
            'payment_methods': [{'value': v, 'label': l} for v, l in ExternalPayment.METHOD_CHOICES],
            'bank_names':      sorted(set(banks)),
        })

    @action(detail=True, methods=['post'], url_path='run-matching')
    def run_matching(self, request, pk=None):
        """Trigger auto-matching for a statement import."""
        if not _require_role(request, FINANCE_ROLES):
            return Response({'detail': 'غير مصرح'}, status=status.HTTP_403_FORBIDDEN)

        stmt = self.get_object()
        if not stmt.lines.exists():
            return Response({'detail': 'لا توجد سطور في هذا الكشف — ارفع الملف مرة أخرى.'},
                            status=status.HTTP_400_BAD_REQUEST)
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
    permission_classes = [IsAuthenticated, MatrixPermission]
    rbac_module        = 'finance'
    rbac_actions       = {'manual_match': ('edit',)}

    def get_queryset(self):
        qs = branch_scope.scope(BankStatementLine.objects.select_related(
            'statement_import', 'matched_payment', 'matched_by'
        ), self.request.user, 'statement_import__branch')
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

        payment = branch_scope.get_or_404(ExternalPayment, request.user, pk=ser.validated_data['payment_id'])
        try:
            updated = PaymentAuditService.manual_match(
                line       = line,
                payment    = payment,
                matched_by = _staff(request),
            )
            return Response(BankStatementLineSerializer(updated).data)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class PaymentExceptionViewSet(StableOrderingMixin, viewsets.ReadOnlyModelViewSet):
    """Triage, assign, and resolve payment exceptions.

    Read-only apart from resolve / dismiss / assign (Batch 4, Z-10a): exceptions are raised by the
    matching engine, and a generic PATCH set status / resolved_by without the approve grant (a
    generic DELETE erased them)."""
    serializer_class   = PaymentExceptionSerializer
    permission_classes = [IsAuthenticated, MatrixPermission]
    rbac_module        = 'finance'
    rbac_actions       = {'resolve': ('approve',), 'dismiss': ('approve',), 'assign': ('assign', 'approve')}
    # sortable headers of the exceptions grid (paged list: the server sorts all rows)
    ordering_fields    = ['exception_type', 'payment__amount', 'payment__reference_number', 'status', 'created_at']

    def get_queryset(self):
        qs = PaymentException.objects.select_related(
            'payment', 'statement_line', 'assigned_to', 'resolved_by'
        ).order_by('-created_at')
        ids = branch_scope.branch_ids(self.request.user)
        if ids is not None:
            qs = qs.filter(Q(payment__branch_id__in=ids)
                           | Q(payment__isnull=True, statement_line__statement_import__branch_id__in=ids))

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
