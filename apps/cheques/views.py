"""
apps/cheques/views.py
"""
import logging
from datetime import date
from decimal import Decimal, ROUND_DOWN

from django.db import transaction
from django.db.models import Sum, Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.users.models import StaffProfile
from .engine import preview_plan, compute_instalment_dates
from .models import EgyptianHoliday, ChequePlan, ChequeInstalment
from .serializers import (
    HolidaySerializer,
    ChequePlanListSerializer,
    ChequePlanDetailSerializer,
    ChequePlanCreateSerializer,
    ChequeInstalmentSerializer,
    ChequeInstalmentUpdateSerializer,
    PlanPreviewRequestSerializer,
    PlanPreviewItemSerializer,
)

logger = logging.getLogger(__name__)


def _get_staff(request):
    try:
        return StaffProfile.objects.get(user=request.user)
    except StaffProfile.DoesNotExist:
        return None


# ── Holidays ─────────────────────────────────────────────────────────────────

class HolidayListView(generics.ListAPIView):
    """GET /api/cheques/holidays/?year=2025"""
    permission_classes = [IsAuthenticated]
    serializer_class   = HolidaySerializer

    def get_queryset(self):
        qs = EgyptianHoliday.objects.all()
        year = self.request.query_params.get('year')
        if year:
            qs = qs.filter(date__year=year)
        return qs


# ── Preview (no DB write) ─────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def preview_cheque_plan(request):
    """
    POST /api/cheques/preview/
    Body: { first_due_date, count, total_amount, interval_value, interval_unit }
    Returns list of instalment rows with banking-day-adjusted dates.
    """
    req_ser = PlanPreviewRequestSerializer(data=request.data)
    req_ser.is_valid(raise_exception=True)
    d = req_ser.validated_data

    rows = preview_plan(
        first_due=d['first_due_date'],
        count=d['count'],
        total_amount=d['total_amount'],
        interval_value=d['interval_value'],
        interval_unit=d['interval_unit'],
    )
    return Response(PlanPreviewItemSerializer(rows, many=True).data)


# ── Plans CRUD ────────────────────────────────────────────────────────────────

class PlanListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        return ChequePlanCreateSerializer if self.request.method == 'POST' else ChequePlanListSerializer

    def get_queryset(self):
        qs = ChequePlan.objects.select_related(
            'created_by__user', 'branch',
        ).prefetch_related('instalments')

        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        branch = self.request.query_params.get('branch')
        if branch:
            qs = qs.filter(branch_id=branch)

        payee_q = self.request.query_params.get('q', '').strip()
        if payee_q:
            qs = qs.filter(
                Q(title__icontains=payee_q) |
                Q(payee_name__icontains=payee_q) |
                Q(reference_doc__icontains=payee_q)
            )

        return qs

    @transaction.atomic
    def perform_create(self, serializer):
        staff = _get_staff(self.request)
        plan  = serializer.save(status='draft', created_by=staff)
        _generate_instalments(plan)


class PlanDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method in ('PUT', 'PATCH'):
            return ChequePlanCreateSerializer
        return ChequePlanDetailSerializer

    def get_queryset(self):
        return ChequePlan.objects.select_related(
            'created_by__user', 'branch',
        ).prefetch_related('instalments')

    def update(self, request, *args, **kwargs):
        plan = self.get_object()
        if plan.status not in ('draft',):
            return Response(
                {'detail': 'يمكن تعديل الخطة فقط في حالة المسودة.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        with transaction.atomic():
            response = super().update(request, *args, **kwargs)
            plan.refresh_from_db()
            # Regenerate instalments if schedule params changed
            plan.instalments.all().delete()
            _generate_instalments(plan)
        return response

    def destroy(self, request, *args, **kwargs):
        plan = self.get_object()
        if plan.status not in ('draft', 'cancelled'):
            return Response(
                {'detail': 'لا يمكن حذف خطة نشطة أو مكتملة.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)


# ── Plan workflow actions ─────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def activate_plan(request, pk):
    """draft → active"""
    plan = get_object_or_404(ChequePlan, pk=pk)
    if plan.status != 'draft':
        return Response({'detail': 'الخطة ليست في حالة مسودة.'}, status=400)
    plan.status = 'active'
    plan.save(update_fields=['status', 'updated_at'])
    return Response(ChequePlanDetailSerializer(
        ChequePlan.objects.prefetch_related('instalments').get(pk=pk)
    ).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_plan(request, pk):
    """any → cancelled (if no cleared cheques)"""
    plan = get_object_or_404(ChequePlan, pk=pk)
    if plan.instalments.filter(status='cleared').exists():
        return Response(
            {'detail': 'لا يمكن إلغاء خطة تحتوي على شيكات صُرفت.'},
            status=400,
        )
    plan.status = 'cancelled'
    plan.save(update_fields=['status', 'updated_at'])
    return Response({'status': 'cancelled'})


# ── Instalment update ─────────────────────────────────────────────────────────

@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def update_instalment(request, plan_pk, inst_pk):
    """PATCH /api/cheques/plans/{pk}/instalments/{inst_pk}/"""
    inst = get_object_or_404(ChequeInstalment, pk=inst_pk, plan_id=plan_pk)
    serializer = ChequeInstalmentUpdateSerializer(inst, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()

    # Auto-complete plan if all instalments cleared or cancelled
    plan = inst.plan
    outstanding = plan.instalments.exclude(status__in=['cleared', 'cancelled']).count()
    if outstanding == 0 and plan.status == 'active':
        plan.status = 'completed'
        plan.save(update_fields=['status', 'updated_at'])

    return Response(ChequeInstalmentSerializer(inst).data)


# ── Treasury dashboard ────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def treasury_dashboard(request):
    """
    GET /api/cheques/treasury/
    Returns summary KPIs + upcoming cheques (next 30 days) + overdue.
    """
    today = date.today()
    in_30 = today.replace(day=today.day) if False else \
        (today.replace(month=today.month + 1) if today.month < 12
         else today.replace(year=today.year + 1, month=1))
    # Simpler: just use timedelta
    from datetime import timedelta
    in_30 = today + timedelta(days=30)

    active_plans = ChequePlan.objects.filter(status='active')

    total_outstanding = ChequeInstalment.objects.filter(
        plan__status='active',
        status__in=['pending', 'issued'],
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

    upcoming = ChequeInstalment.objects.filter(
        plan__status='active',
        status__in=['pending', 'issued'],
        due_date__gte=today,
        due_date__lte=in_30,
    ).select_related('plan').order_by('due_date')

    overdue = ChequeInstalment.objects.filter(
        plan__status='active',
        status__in=['pending', 'issued'],
        due_date__lt=today,
    ).select_related('plan').order_by('due_date')

    def _ser(inst):
        return {
            'id':           inst.id,
            'plan_id':      inst.plan_id,
            'plan_title':   inst.plan.title,
            'payee_name':   inst.plan.payee_name,
            'instalment_no': inst.instalment_no,
            'amount':       str(inst.amount),
            'due_date':     inst.due_date,
            'cheque_number': inst.cheque_number,
            'status':       inst.status,
            'adjusted':     inst.due_date != inst.nominal_date,
        }

    return Response({
        'active_plans_count':  active_plans.count(),
        'total_outstanding':   str(total_outstanding),
        'upcoming_30d_count':  upcoming.count(),
        'upcoming_30d_amount': str(upcoming.aggregate(t=Sum('amount'))['t'] or 0),
        'overdue_count':       overdue.count(),
        'overdue_amount':      str(overdue.aggregate(t=Sum('amount'))['t'] or 0),
        'upcoming_cheques':    [_ser(i) for i in upcoming[:20]],
        'overdue_cheques':     [_ser(i) for i in overdue[:10]],
    })


# ── Helper ────────────────────────────────────────────────────────────────────

def _generate_instalments(plan: ChequePlan):
    """Build ChequeInstalment rows from a plan's schedule parameters."""
    total   = plan.total_amount
    n       = plan.cheque_count
    unit_amt = (total / n).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    remainder = total - unit_amt * n

    dates = compute_instalment_dates(
        first_due=plan.first_due_date,
        count=n,
        interval_value=plan.interval_value,
        interval_unit=plan.interval_unit,
    )

    instalments = []
    for i, (nominal, banking) in enumerate(dates, start=1):
        amt = unit_amt + (remainder if i == n else Decimal('0'))
        instalments.append(ChequeInstalment(
            plan=plan,
            instalment_no=i,
            amount=amt,
            nominal_date=nominal,
            due_date=banking,
            status='pending',
        ))

    ChequeInstalment.objects.bulk_create(instalments)
    logger.info('Generated %d instalments for ChequePlan %d', len(instalments), plan.pk)
