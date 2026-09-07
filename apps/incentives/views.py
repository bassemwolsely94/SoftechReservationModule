"""
apps/incentives/views.py  —  v4

API endpoints:
  GET/POST   /api/incentives/programs/
  GET/PATCH  /api/incentives/programs/{id}/
  DELETE     /api/incentives/programs/{id}/

  POST       /api/incentives/programs/{id}/calculate/
  POST       /api/incentives/programs/{id}/simulate/
  GET        /api/incentives/programs/{id}/report/
  POST       /api/incentives/programs/{id}/finalize/

  GET/POST   /api/incentives/rules/
  PATCH/DEL  /api/incentives/rules/{id}/
  POST       /api/incentives/rules/{id}/add-item/
  POST       /api/incentives/rules/{id}/import-items/
  DELETE     /api/incentives/rules/{id}/remove-item/?item_code=XYZ
  DELETE     /api/incentives/rules/{id}/clear-items/

  GET/POST   /api/incentives/adjustments/
  PATCH/DEL  /api/incentives/adjustments/{id}/

  GET        /api/incentives/transactions/

  GET        /api/incentives/settlements/
  GET        /api/incentives/settlements/{id}/receipt/

  GET        /api/incentives/logs/
"""
import csv
import io
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.db.models import Count, Sum, Q, Avg
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    IncentiveProgram, IncentiveRule, IncentiveRuleItem,
    IncentiveTransaction, IncentiveSettlement,
    AdjustmentEntry, IncentiveCalculationLog,
)
from .serializers import (
    IncentiveProgramListSerializer,
    IncentiveProgramDetailSerializer,
    IncentiveProgramCreateSerializer,
    IncentiveRuleSerializer,
    IncentiveRuleItemSerializer,
    IncentiveTransactionSerializer,
    IncentiveSettlementSerializer,
    AdjustmentEntrySerializer,
    IncentiveCalculationLogSerializer,
)

logger = logging.getLogger('elrezeiky.incentives')

_EXPIRY_BUCKETS = ['0-30', '31-60', '61-90', '91-180', '181+']


def _days_to_bucket(days: int | None) -> str:
    if days is None:
        return 'unknown'
    if days <= 30:
        return '0-30'
    if days <= 60:
        return '31-60'
    if days <= 90:
        return '61-90'
    if days <= 180:
        return '91-180'
    return '181+'


def _parse_date(value, field_name='date') -> date:
    if not value:
        raise ValueError(f'{field_name} مطلوب')
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
    except ValueError:
        raise ValueError(f'{field_name} غير صالح — المتوقع: YYYY-MM-DD')


# ─────────────────────────────────────────────────────────────────────────────
# Programs
# ─────────────────────────────────────────────────────────────────────────────

class IncentiveProgramViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = IncentiveProgram.objects.annotate(rule_count=Count('rules'))
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            qs = qs.filter(is_active=(is_active.lower() == 'true'))
        return qs.order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'create':
            return IncentiveProgramCreateSerializer
        if self.action in ('retrieve', 'update', 'partial_update'):
            return IncentiveProgramDetailSerializer
        return IncentiveProgramListSerializer

    def perform_create(self, serializer):
        profile = getattr(self.request.user, 'staff_profile', None)
        serializer.save(created_by=profile)

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _parse_period(self, data):
        period_start = _parse_date(data.get('period_start'), 'period_start')
        period_end   = _parse_date(data.get('period_end'),   'period_end')
        if period_start > period_end:
            raise ValueError('period_start يجب أن يسبق period_end')
        return period_start, period_end

    def _parse_user_ids(self, data):
        raw = data.get('user_ids') or None
        if raw is None:
            return None
        try:
            return [int(x) for x in raw]
        except (TypeError, ValueError):
            raise ValueError('user_ids يجب أن تكون قائمة أرقام صحيحة')

    def _get_profile(self):
        return getattr(self.request.user, 'staff_profile', None)

    # ── POST .../programs/{id}/calculate/ ─────────────────────────────────────

    @action(detail=True, methods=['post'])
    def calculate(self, request, pk=None):
        """
        Run the incentive calculation engine.

        Body (JSON):
          {
            "period_start": "2025-01-01",
            "period_end":   "2025-01-31",
            "user_ids":     [1, 2, 3],   # optional
            "force":        false
          }

        Returns 409 if period is finalized and force is not set.
        """
        program = self.get_object()
        try:
            period_start, period_end = self._parse_period(request.data)
            user_ids = self._parse_user_ids(request.data)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        force = bool(request.data.get('force', False))

        try:
            from .engine import calculate as run_calculate
            result = run_calculate(
                program.id, period_start, period_end,
                user_ids=user_ids, simulate=False, force=force,
                triggered_by=self._get_profile(),
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
        except Exception as exc:
            logger.exception('calculate action failed for program %d', program.id)
            return Response(
                {'detail': f'فشل الاحتساب: {exc}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({
            'program_id':           program.id,
            'period_start':         period_start.isoformat(),
            'period_end':           period_end.isoformat(),
            'created':              result.created,
            'total_by_user':        result.total_by_user,
            'user_summaries':       result.user_summaries,
            'skipped_person_codes': result.skipped_person_codes,
            'simulated':            result.simulated,
            'log_id':               result.log_id,
        })

    # ── POST .../programs/{id}/simulate/ ─────────────────────────────────────

    @action(detail=True, methods=['post'])
    def simulate(self, request, pk=None):
        """Dry-run: compute without writing transactions."""
        program = self.get_object()
        try:
            period_start, period_end = self._parse_period(request.data)
            user_ids = self._parse_user_ids(request.data)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from .engine import calculate as run_calculate
            result = run_calculate(
                program.id, period_start, period_end,
                user_ids=user_ids, simulate=True, force=True,
                triggered_by=self._get_profile(),
            )
        except Exception as exc:
            logger.exception('simulate action failed for program %d', program.id)
            return Response(
                {'detail': f'فشل المحاكاة: {exc}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({
            'program_id':           program.id,
            'period_start':         period_start.isoformat(),
            'period_end':           period_end.isoformat(),
            'created':              result.created,
            'total_by_user':        result.total_by_user,
            'user_summaries':       result.user_summaries,
            'skipped_person_codes': result.skipped_person_codes,
            'simulated':            result.simulated,
            'log_id':               result.log_id,
        })

    # ── GET .../programs/{id}/report/ ─────────────────────────────────────────

    @action(detail=True, methods=['get'])
    def report(self, request, pk=None):
        """
        Aggregated incentive report per user for a calculated period.

        Params:
          period_start, period_end — required
          user_id                  — optional: include transaction detail for one user

        Returns each user row with:
          total_incentive, total_adjustments, final_total,
          sale_count, return_count, is_finalized, transactions (when user_id given)
        """
        program = self.get_object()
        try:
            period_start = _parse_date(request.query_params.get('period_start'), 'period_start')
            period_end   = _parse_date(request.query_params.get('period_end'),   'period_end')
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        user_id_filter = request.query_params.get('user_id')

        base_qs = IncentiveTransaction.objects.filter(
            program=program,
            period_start=period_start,
            period_end=period_end,
        )
        if user_id_filter:
            base_qs = base_qs.filter(user_id=user_id_filter)

        # Per-user aggregation
        agg = (
            base_qs
            .values('user_id', 'user__user__first_name', 'user__user__last_name',
                    'user__softech_user_id')
            .annotate(
                total_incentive=Sum('incentive_amount'),
                sale_count=Count('id', filter=Q(doc_type='sale', is_reversed=False)),
                return_count=Count('id', filter=Q(doc_type='return')),
            )
            .order_by('user__user__first_name')
        )

        # Settlement & adjustment lookups
        settlements = {
            s.user_id: s
            for s in IncentiveSettlement.objects.filter(
                program=program, period_start=period_start, period_end=period_end,
            )
        }
        adj_totals = {
            row['user_id']: row['adj_sum'] or Decimal('0')
            for row in AdjustmentEntry.objects.filter(
                program=program, period_start=period_start, period_end=period_end,
            ).values('user_id').annotate(adj_sum=Sum('amount'))
        }
        # Adjustment entries for detail view
        adj_entries = {}
        if user_id_filter:
            adj_entries = {
                user_id_filter: list(
                    AdjustmentEntrySerializer(
                        AdjustmentEntry.objects.filter(
                            program=program, user_id=user_id_filter,
                            period_start=period_start, period_end=period_end,
                        ).select_related('created_by'),
                        many=True,
                    ).data
                )
            }

        rows = []
        for a in agg:
            uid  = a['user_id']
            fn   = a.get('user__user__first_name') or ''
            ln   = a.get('user__user__last_name') or ''
            name = f'{fn} {ln}'.strip()
            settlement  = settlements.get(uid)
            adj_total   = adj_totals.get(uid, Decimal('0'))
            txn_total   = a['total_incentive'] or Decimal('0')
            final_total = float(txn_total) + float(adj_total)

            row = {
                'user_id':           uid,
                'user_name':         name,
                'person_code':       a.get('user__softech_user_id') or '',
                'total_incentive':   float(txn_total),
                'total_adjustments': float(adj_total),
                'final_total':       final_total,
                'sale_count':        a['sale_count'],
                'return_count':      a['return_count'],
                'is_finalized':      settlement.is_finalized if settlement else False,
                'settlement_id':     settlement.id if settlement else None,
                'final_payout':      float(settlement.final_payout) if settlement else None,
            }

            if user_id_filter:
                txns = base_qs.filter(user_id=uid).select_related('rule').order_by('-erp_date', 'doc_no')
                row['transactions'] = IncentiveTransactionSerializer(txns, many=True).data
                row['adjustments']  = adj_entries.get(str(uid), [])

            rows.append(row)

        grand_total_incentive   = sum(r['total_incentive']   for r in rows)
        grand_total_adjustments = sum(r['total_adjustments'] for r in rows)
        grand_final             = sum(r['final_total']       for r in rows)

        return Response({
            'program_id':             program.id,
            'program_name':           program.name,
            'period_start':           period_start.isoformat(),
            'period_end':             period_end.isoformat(),
            'grand_total_incentive':  grand_total_incentive,
            'grand_total_adjustments': grand_total_adjustments,
            'grand_final':            grand_final,
            'rows':                   rows,
        })

    # ── POST .../programs/{id}/finalize/ ──────────────────────────────────────

    @action(detail=True, methods=['post'])
    def finalize(self, request, pk=None):
        """
        Lock incentive settlements for a period.
        Final payout = transaction total + adjustment total.
        Already-finalized settlements are skipped.
        """
        program = self.get_object()
        try:
            period_start = _parse_date(request.data.get('period_start'), 'period_start')
            period_end   = _parse_date(request.data.get('period_end'),   'period_end')
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        notes   = (request.data.get('notes') or '').strip()
        profile = self._get_profile()

        # Aggregate transactions per user
        agg = (
            IncentiveTransaction.objects
            .filter(program=program, period_start=period_start, period_end=period_end)
            .values('user_id')
            .annotate(txn_total=Sum('incentive_amount'), count=Count('id'))
        )

        if not agg:
            return Response(
                {'detail': 'لا توجد حركات لهذه الفترة — قم بتشغيل الاحتساب أولاً'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Adjustment sums per user
        adj_by_user = {
            row['user_id']: row['adj_sum'] or Decimal('0')
            for row in AdjustmentEntry.objects.filter(
                program=program, period_start=period_start, period_end=period_end,
            ).values('user_id').annotate(adj_sum=Sum('amount'))
        }

        finalized = []
        skipped   = []
        now       = timezone.now()

        for row in agg:
            uid       = row['user_id']
            txn_total = row['txn_total'] or Decimal('0')
            count     = row['count']
            adj_total = adj_by_user.get(uid, Decimal('0'))
            final     = txn_total + adj_total

            sett, _ = IncentiveSettlement.objects.get_or_create(
                program=program, user_id=uid,
                period_start=period_start, period_end=period_end,
                defaults={
                    'total_incentive':   txn_total,
                    'total_adjustments': adj_total,
                    'final_payout':      final,
                    'transaction_count': count,
                    'notes':             notes,
                },
            )

            if sett.is_finalized:
                skipped.append(uid)
                continue

            sett.total_incentive   = txn_total
            sett.total_adjustments = adj_total
            sett.final_payout      = final
            sett.transaction_count = count
            sett.is_finalized      = True
            sett.finalized_at      = now
            sett.finalized_by      = profile
            if notes:
                sett.notes = notes
            sett.save(update_fields=[
                'total_incentive', 'total_adjustments', 'final_payout',
                'transaction_count', 'is_finalized', 'finalized_at',
                'finalized_by', 'notes',
            ])
            finalized.append(uid)

        return Response({
            'finalized_count': len(finalized),
            'skipped_count':   len(skipped),
            'period_start':    period_start.isoformat(),
            'period_end':      period_end.isoformat(),
        })

    # ── GET .../programs/{id}/near-expiry-report/ ─────────────────────────────

    @action(detail=True, methods=['get'], url_path='near-expiry-report')
    def near_expiry_report(self, request, pk=None):
        """
        Near-expiry incentive analytics for a calculated period.

        Shows only transactions linked to near-expiry rules
        (where expiry_days_remaining IS NOT NULL).

        Query params:
          period_start, period_end  — required
          user_id                   — optional, filter to one employee

        Returns:
          grand_totals
          expiry_bucket_breakdown   — incentive per bucket (0-30, 31-60, ...)
          employee_ranking          — top employees by near-expiry incentive
          branch_ranking            — top branches
          item_ranking              — most cleared near-expiry items
        """
        program = self.get_object()
        try:
            period_start = _parse_date(
                request.query_params.get('period_start'), 'period_start'
            )
            period_end = _parse_date(
                request.query_params.get('period_end'), 'period_end'
            )
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        user_id_filter = request.query_params.get('user_id')

        # Only transactions earned under a NEAR-EXPIRY rule (a rule with
        # expiry_within_days set). NOTE: the engine stamps expiry_days_remaining
        # on every line that has a batch expiry date (~84% of items), so filtering
        # on expiry_days_remaining alone would return almost all transactions.
        # The correct scope is "matched by a near-expiry rule".
        base_qs = IncentiveTransaction.objects.filter(
            program=program,
            period_start=period_start,
            period_end=period_end,
            rule__expiry_within_days__isnull=False,
            expiry_days_remaining__isnull=False,
        )
        if user_id_filter:
            base_qs = base_qs.filter(user_id=user_id_filter)

        if not base_qs.exists():
            return Response({
                'program_id':   program.id,
                'program_name': program.name,
                'period_start': period_start.isoformat(),
                'period_end':   period_end.isoformat(),
                'note':         'لا توجد حركات قريبة من الصلاحية في هذه الفترة',
                'grand_totals': {},
                'expiry_bucket_breakdown': [],
                'employee_ranking': [],
                'branch_ranking': [],
                'item_ranking': [],
            })

        # ── Grand totals ──────────────────────────────────────────────────────
        from django.db.models import Count
        totals = base_qs.aggregate(
            total_incentive=Sum('incentive_amount'),
            sale_count=Count('id', filter=Q(doc_type='sale')),
            return_count=Count('id', filter=Q(doc_type='return')),
            qty_sold=Sum('quantity', filter=Q(doc_type='sale')),
            qty_returned=Sum('quantity', filter=Q(doc_type='return')),
        )

        # ── Expiry bucket breakdown ───────────────────────────────────────────
        bucket_data = defaultdict(lambda: {
            'incentive': Decimal('0'), 'sale_count': 0, 'qty': Decimal('0')
        })
        for txn in base_qs.only(
            'expiry_days_remaining', 'incentive_amount', 'doc_type', 'quantity'
        ):
            bucket = _days_to_bucket(txn.expiry_days_remaining)
            bucket_data[bucket]['incentive'] += txn.incentive_amount
            if txn.doc_type == 'sale':
                bucket_data[bucket]['sale_count'] += 1
                bucket_data[bucket]['qty'] += txn.quantity

        bucket_breakdown = []
        for b in _EXPIRY_BUCKETS:
            d = bucket_data.get(b, {})
            bucket_breakdown.append({
                'bucket':     b,
                'incentive':  float(d.get('incentive', 0)),
                'sale_count': d.get('sale_count', 0),
                'qty_sold':   float(d.get('qty', 0)),
            })

        # ── Employee ranking ──────────────────────────────────────────────────
        emp_agg = (
            base_qs
            .values('user_id', 'user__user__first_name', 'user__user__last_name',
                    'user__softech_user_id')
            .annotate(
                total=Sum('incentive_amount'),
                txn_count=Count('id'),
            )
            .order_by('-total')[:20]
        )
        employee_ranking = [
            {
                'user_id':     r['user_id'],
                'user_name':   f"{r['user__user__first_name'] or ''} {r['user__user__last_name'] or ''}".strip(),
                'person_code': r['user__softech_user_id'] or '',
                'total':       float(r['total'] or 0),
                'txn_count':   r['txn_count'],
            }
            for r in emp_agg
        ]

        # ── Branch ranking ────────────────────────────────────────────────────
        branch_agg = (
            base_qs
            .values('branch_code')
            .annotate(
                total=Sum('incentive_amount'),
                txn_count=Count('id'),
            )
            .order_by('-total')[:10]
        )
        branch_ranking = [
            {
                'branch_code': r['branch_code'],
                'total':       float(r['total'] or 0),
                'txn_count':   r['txn_count'],
            }
            for r in branch_agg
        ]

        # ── Item ranking ──────────────────────────────────────────────────────
        item_agg = (
            base_qs
            .filter(doc_type='sale')
            .values('item_code', 'item_name')
            .annotate(
                total_incentive=Sum('incentive_amount'),
                qty_sold=Sum('quantity'),
                avg_expiry_days=Avg('expiry_days_remaining'),
            )
            .order_by('-total_incentive')[:20]
        )
        item_ranking = [
            {
                'item_code':       r['item_code'],
                'item_name':       r['item_name'],
                'total_incentive': float(r['total_incentive'] or 0),
                'qty_sold':        float(r['qty_sold'] or 0),
                'avg_expiry_days': round(float(r['avg_expiry_days'] or 0), 1),
            }
            for r in item_agg
        ]

        return Response({
            'program_id':   program.id,
            'program_name': program.name,
            'period_start': period_start.isoformat(),
            'period_end':   period_end.isoformat(),
            'grand_totals': {
                'total_incentive': float(totals['total_incentive'] or 0),
                'sale_count':      totals['sale_count'] or 0,
                'return_count':    totals['return_count'] or 0,
                'qty_sold':        float(totals['qty_sold'] or 0),
                'qty_returned':    float(abs(totals['qty_returned'] or 0)),
            },
            'expiry_bucket_breakdown': bucket_breakdown,
            'employee_ranking':        employee_ranking,
            'branch_ranking':          branch_ranking,
            'item_ranking':            item_ranking,
        })


    # ── POST .../programs/{id}/clone/ ─────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def clone(self, request, pk=None):
        """
        Feature 4 — Program Clone / Template.

        Deep-copies a program (all rules + rule_items) to a new date range.

        Body:
          { "new_start_date": "2026-07-01",
            "new_end_date":   "2026-07-31",
            "new_name":       "يوليو 2026"   (optional)
          }
        """
        source = self.get_object()
        try:
            new_start = _parse_date(request.data.get('new_start_date'), 'new_start_date')
            new_end   = _parse_date(request.data.get('new_end_date'),   'new_end_date')
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        new_name = (request.data.get('new_name') or '').strip() or f'نسخة من {source.name}'
        profile  = self._get_profile()

        # Clone program
        cloned = source.__class__.objects.create(
            name=new_name,
            description=source.description,
            start_date=new_start,
            end_date=new_end,
            calculation_period=source.calculation_period,
            is_active=source.is_active,
            sponsor_name=source.sponsor_name,
            sponsor_contribution_pct=source.sponsor_contribution_pct,
            created_by=profile,
        )

        # Clone rules + rule_items
        for rule in source.rules.prefetch_related('rule_items').all():
            from .models import IncentiveRule, IncentiveRuleItem
            new_rule = IncentiveRule.objects.create(
                program=cloned,
                rule_name=rule.rule_name,
                item_code=rule.item_code,
                item_name=rule.item_name,
                category_code=rule.category_code,
                incentive_type=rule.incentive_type,
                incentive_value=rule.incentive_value,
                slab_config=rule.slab_config,
                target_qty=rule.target_qty,
                target_tiers=rule.target_tiers,
                min_qty=rule.min_qty,
                min_total_qty_in_period=rule.min_total_qty_in_period,
                person_code_filter=rule.person_code_filter,
                branch_filter=rule.branch_filter,
                time_window_start=rule.time_window_start,
                time_window_end=rule.time_window_end,
                expiry_within_days=rule.expiry_within_days,
                is_imported_filter=rule.is_imported_filter,
                origin_codes=rule.origin_codes,
                margin_min=rule.margin_min,
                margin_max=rule.margin_max,
                pack_price_min=rule.pack_price_min,
                pack_price_max=rule.pack_price_max,
                priority=rule.priority,
                is_active=rule.is_active,
            )
            IncentiveRuleItem.objects.bulk_create([
                IncentiveRuleItem(
                    rule=new_rule,
                    item_code=ri.item_code,
                    item_name=ri.item_name,
                    incentive_override=ri.incentive_override,
                )
                for ri in rule.rule_items.all()
            ])

        from .serializers import IncentiveProgramListSerializer
        return Response(
            IncentiveProgramListSerializer(cloned).data,
            status=status.HTTP_201_CREATED,
        )

    # ── GET .../programs/{id}/export-settlements/ ─────────────────────────────

    @action(detail=True, methods=['get'], url_path='export-settlements')
    def export_settlements(self, request, pk=None):
        """
        Feature 6 — Excel Settlement Export.

        Params: period_start, period_end (required)

        Returns an .xlsx file with:
          Sheet 1 — Summary per employee (payroll-ready)
          Sheet 2 — Full transaction detail
        """
        program = self.get_object()
        try:
            period_start = _parse_date(request.query_params.get('period_start'), 'period_start')
            period_end   = _parse_date(request.query_params.get('period_end'),   'period_end')
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        except ImportError:
            return Response({'detail': 'openpyxl not installed'}, status=500)

        wb  = openpyxl.Workbook()
        ws1 = wb.active
        ws1.title = 'ملخص التسويات'
        ws2 = wb.create_sheet('تفاصيل الحركات')

        header_font  = Font(bold=True, color='FFFFFF')
        header_fill  = PatternFill('solid', fgColor='1F4E79')
        sub_fill     = PatternFill('solid', fgColor='D6E4F0')
        center       = Alignment(horizontal='center', vertical='center', wrap_text=True)
        right        = Alignment(horizontal='right')
        thin         = Side(style='thin', color='CCCCCC')
        border       = Border(left=thin, right=thin, top=thin, bottom=thin)

        def hcell(ws, row, col, value, fill=None):
            c = ws.cell(row=row, column=col, value=value)
            c.font = header_font
            c.fill = fill or header_fill
            c.alignment = center
            c.border = border
            return c

        def dcell(ws, row, col, value, align=None):
            c = ws.cell(row=row, column=col, value=value)
            c.alignment = align or right
            c.border = border
            return c

        # ── Sheet 1: Summary ──────────────────────────────────────────────────
        sponsor_pct = program.sponsor_contribution_pct or Decimal('0')
        pharmacy_pct = Decimal('100') - sponsor_pct

        ws1.merge_cells('A1:H1')
        title_cell = ws1['A1']
        title_cell.value = f'{program.name}  |  {period_start} → {period_end}'
        title_cell.font  = Font(bold=True, size=14, color='1F4E79')
        title_cell.alignment = center

        if program.sponsor_name:
            ws1.merge_cells('A2:H2')
            s2 = ws1['A2']
            s2.value = f'الراعي: {program.sponsor_name}  |  مساهمة الراعي: {sponsor_pct}%  |  مساهمة الصيدلية: {pharmacy_pct}%'
            s2.font  = Font(bold=True, color='7F6000')
            s2.fill  = PatternFill('solid', fgColor='FFF2CC')
            s2.alignment = center
            hrow = 4
        else:
            hrow = 3

        headers1 = ['#', 'اسم المندوب', 'كود المندوب', 'إجمالي الحوافز',
                    'التسويات اليدوية', 'الصافي للصرف',
                    'تكلفة الصيدلية', 'تكلفة الراعي']
        for ci, h in enumerate(headers1, 1):
            hcell(ws1, hrow, ci, h)

        # Aggregate transactions
        agg = (
            IncentiveTransaction.objects
            .filter(program=program, period_start=period_start, period_end=period_end)
            .values('user_id', 'user__user__first_name', 'user__user__last_name',
                    'user__softech_user_id')
            .annotate(txn_total=Sum('incentive_amount'))
            .order_by('user__user__first_name')
        )
        adj_by_user = {
            r['user_id']: r['adj_sum'] or Decimal('0')
            for r in AdjustmentEntry.objects.filter(
                program=program, period_start=period_start, period_end=period_end,
            ).values('user_id').annotate(adj_sum=Sum('amount'))
        }

        grand_total = Decimal('0')
        for i, row in enumerate(agg, 1):
            uid        = row['user_id']
            name       = f"{row['user__user__first_name'] or ''} {row['user__user__last_name'] or ''}".strip()
            person_code= row['user__softech_user_id'] or ''
            txn_total  = row['txn_total'] or Decimal('0')
            adj_total  = adj_by_user.get(uid, Decimal('0'))
            net        = txn_total + adj_total
            ph_cost    = (net * pharmacy_pct / Decimal('100')).quantize(Decimal('0.01'))
            sp_cost    = (net * sponsor_pct  / Decimal('100')).quantize(Decimal('0.01'))
            grand_total += net

            r = hrow + i
            dcell(ws1, r, 1, i)
            dcell(ws1, r, 2, name)
            dcell(ws1, r, 3, person_code)
            dcell(ws1, r, 4, float(txn_total))
            dcell(ws1, r, 5, float(adj_total))
            dcell(ws1, r, 6, float(net))
            dcell(ws1, r, 7, float(ph_cost))
            dcell(ws1, r, 8, float(sp_cost))

        # Grand total row
        total_row = hrow + len(list(agg)) + 1
        for ci in range(1, 9):
            ws1.cell(row=total_row, column=ci).fill = sub_fill
        ws1.cell(row=total_row, column=2, value='الإجمالي').font = Font(bold=True)
        ws1.cell(row=total_row, column=6, value=float(grand_total)).font = Font(bold=True)

        ws1.column_dimensions['B'].width = 30
        ws1.column_dimensions['A'].width = 5
        for col in 'CDEFGH':
            ws1.column_dimensions[col].width = 18

        # ── Sheet 2: Transaction Detail ───────────────────────────────────────
        headers2 = ['المندوب', 'كود المندوب', 'كود الصنف', 'اسم الصنف',
                    'نوع الحركة', 'رقم الفاتورة', 'تاريخ الحركة',
                    'الكمية', 'سعر الوحدة', 'مبلغ الحافز',
                    'القاعدة', 'الفرع', 'تاريخ الصلاحية', 'أيام الصلاحية']
        for ci, h in enumerate(headers2, 1):
            hcell(ws2, 1, ci, h)

        txns = (
            IncentiveTransaction.objects
            .filter(program=program, period_start=period_start, period_end=period_end)
            .select_related('user', 'rule')
            .order_by('user__user__first_name', '-erp_date')
        )
        for i, txn in enumerate(txns, 2):
            vals = [
                txn.user.full_name, txn.user.softech_user_id,
                txn.item_code, txn.item_name,
                'بيع' if txn.doc_type == 'sale' else 'مرتجع',
                txn.doc_no,
                txn.erp_date.isoformat() if txn.erp_date else '',
                float(txn.quantity), float(txn.unit_price),
                float(txn.incentive_amount),
                txn.rule.rule_name if txn.rule else '',
                txn.branch_code,
                txn.expiry_date.isoformat() if txn.expiry_date else '',
                txn.expiry_days_remaining,
            ]
            for ci, v in enumerate(vals, 1):
                dcell(ws2, i, ci, v)

        for col in ['A', 'B', 'D', 'K']:
            ws2.column_dimensions[col].width = 25
        for col in ['C', 'E', 'F', 'G', 'H', 'I', 'J', 'L', 'M', 'N']:
            ws2.column_dimensions[col].width = 16

        # Return as HTTP response
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        filename = f'incentives_{program.id}_{period_start}_{period_end}.xlsx'
        response = HttpResponse(
            buf.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    # ── GET .../programs/{id}/roi-report/ ─────────────────────────────────────

    @action(detail=True, methods=['get'], url_path='roi-report')
    def roi_report(self, request, pk=None):
        """
        Feature 10 — Multi-Period ROI Report.

        Compares sales velocity of incentivized items before, during, and after
        the incentive period using SalesTransactionLine (PostgreSQL).

        Params:
          period_start, period_end — the incentive period
          comparison_days          — look-back / look-forward window (default: 30)
        """
        from apps.purchasing.models import SalesTransactionLine

        program = self.get_object()
        try:
            period_start = _parse_date(request.query_params.get('period_start'), 'period_start')
            period_end   = _parse_date(request.query_params.get('period_end'),   'period_end')
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        comp_days = int(request.query_params.get('comparison_days', 30))

        # Dates for before/after windows
        before_start = period_start - timedelta(days=comp_days)
        before_end   = period_start - timedelta(days=1)
        after_start  = period_end   + timedelta(days=1)
        after_end    = period_end   + timedelta(days=comp_days)

        # Collect all incentivized item codes from this program
        incentivized_codes = set()
        for rule in program.rules.filter(is_active=True).prefetch_related('rule_items'):
            if rule.item_code:
                incentivized_codes.add(rule.item_code)
            for ri in rule.rule_items.all():
                incentivized_codes.add(ri.item_code)

        if not incentivized_codes:
            return Response({'detail': 'لا توجد أصناف محددة في هذا البرنامج'}, status=400)

        def velocity(start, end):
            """Net qty sold per day for incentivized items in a date window."""
            days = (end - start).days + 1
            if days <= 0:
                return Decimal('0'), {}
            rows = (
                SalesTransactionLine.objects
                .filter(
                    softech_itemcode__in=incentivized_codes,
                    doc_date__gte=start,
                    doc_date__lte=end,
                )
                .values('softech_itemcode')
                .annotate(
                    net_qty=Sum('net_qty'),
                    net_rev=Sum('net_revenue'),
                )
            )
            total_qty = sum(r['net_qty'] or Decimal('0') for r in rows)
            total_rev = sum(r['net_rev'] or Decimal('0') for r in rows)
            per_item  = {r['softech_itemcode']: {
                'net_qty': float(r['net_qty'] or 0),
                'net_rev': float(r['net_rev'] or 0),
                'daily_qty': float(r['net_qty'] or 0) / days,
            } for r in rows}
            return total_qty / days, total_rev, per_item

        before_daily_qty, before_revenue, before_items = velocity(before_start, before_end)
        during_days = (period_end - period_start).days + 1
        during_rows = (
            SalesTransactionLine.objects
            .filter(
                softech_itemcode__in=incentivized_codes,
                doc_date__gte=period_start,
                doc_date__lte=period_end,
            )
            .values('softech_itemcode')
            .annotate(net_qty=Sum('net_qty'), net_rev=Sum('net_revenue'))
        )
        during_total_qty = sum(r['net_qty'] or Decimal('0') for r in during_rows)
        during_total_rev = sum(r['net_rev'] or Decimal('0') for r in during_rows)
        during_daily_qty = during_total_qty / during_days if during_days > 0 else Decimal('0')
        during_items     = {r['softech_itemcode']: {
            'net_qty': float(r['net_qty'] or 0),
            'net_rev': float(r['net_rev'] or 0),
            'daily_qty': float(r['net_qty'] or 0) / during_days,
        } for r in during_rows}

        after_daily_qty, after_revenue, after_items = velocity(after_start, after_end)

        # Incentive cost from transactions
        incentive_cost = (
            IncentiveTransaction.objects
            .filter(program=program, period_start=period_start, period_end=period_end)
            .aggregate(total=Sum('incentive_amount'))['total'] or Decimal('0')
        )

        # Revenue uplift vs before period (annualized daily rate)
        revenue_uplift = float(during_total_rev) - float(before_revenue) * during_days / comp_days if comp_days > 0 else 0
        roi = revenue_uplift / float(incentive_cost) if incentive_cost > 0 else None

        # Per-item breakdown
        item_breakdown = []
        for code in incentivized_codes:
            b = before_items.get(code, {})
            d = during_items.get(code, {})
            a = after_items.get(code, {})
            item_breakdown.append({
                'item_code':         code,
                'before_daily_qty':  round(b.get('daily_qty', 0), 2),
                'during_daily_qty':  round(d.get('daily_qty', 0), 2),
                'after_daily_qty':   round(a.get('daily_qty', 0), 2),
                'velocity_uplift':   round(d.get('daily_qty', 0) - b.get('daily_qty', 0), 2),
                'during_revenue':    round(d.get('net_rev', 0), 2),
            })
        item_breakdown.sort(key=lambda x: -x['during_revenue'])

        return Response({
            'program_id':   program.id,
            'program_name': program.name,
            'period_start': period_start.isoformat(),
            'period_end':   period_end.isoformat(),
            'comparison_days': comp_days,
            'windows': {
                'before': {'start': before_start.isoformat(), 'end': before_end.isoformat()},
                'during': {'start': period_start.isoformat(), 'end': period_end.isoformat()},
                'after':  {'start': after_start.isoformat(),  'end': after_end.isoformat()},
            },
            'velocity': {
                'before_daily_qty': round(float(before_daily_qty), 2),
                'during_daily_qty': round(float(during_daily_qty), 2),
                'after_daily_qty':  round(float(after_daily_qty),  2),
                'uplift_vs_before': round(float(during_daily_qty - before_daily_qty), 2),
            },
            'financials': {
                'incentive_cost':   round(float(incentive_cost), 2),
                'revenue_uplift':   round(revenue_uplift, 2),
                'roi_multiple':     round(roi, 2) if roi is not None else None,
            },
            'item_breakdown': item_breakdown[:20],
        })


# ─────────────────────────────────────────────────────────────────────────────
# Rules
# ─────────────────────────────────────────────────────────────────────────────

class IncentiveRuleViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class   = IncentiveRuleSerializer

    def get_queryset(self):
        qs = IncentiveRule.objects.select_related('program').prefetch_related('rule_items')
        program_id = self.request.query_params.get('program')
        is_active  = self.request.query_params.get('is_active')
        if program_id:
            qs = qs.filter(program_id=program_id)
        if is_active is not None:
            qs = qs.filter(is_active=(is_active.lower() == 'true'))
        return qs.order_by('priority', 'item_code')

    # ── POST .../rules/{id}/add-item/ ─────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='add-item')
    def add_item(self, request, pk=None):
        """Add (or update) one item in a rule — idempotent."""
        rule = self.get_object()
        item_code = (request.data.get('item_code') or '').strip()
        if not item_code:
            return Response({'detail': 'item_code مطلوب'}, status=status.HTTP_400_BAD_REQUEST)

        item_name    = (request.data.get('item_name') or '').strip()
        override_raw = request.data.get('incentive_override')
        incentive_override = None
        if override_raw not in (None, ''):
            try:
                incentive_override = Decimal(str(override_raw))
            except InvalidOperation:
                return Response(
                    {'detail': 'incentive_override قيمة غير صالحة'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        ri, created = IncentiveRuleItem.objects.update_or_create(
            rule=rule, item_code=item_code,
            defaults={'item_name': item_name, 'incentive_override': incentive_override},
        )
        return Response(
            IncentiveRuleItemSerializer(ri).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    # ── POST .../rules/{id}/import-items/ ─────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='import-items')
    def import_items(self, request, pk=None):
        """
        Bulk import items into a rule.

        JSON:  { "items": [{item_code, item_name?, incentive_override?},...], "mode": "replace"|"append" }
        Form:  csv_file=<file>, mode=replace|append
        CSV:   columns item_code, item_name (opt), incentive_override (opt)
        """
        rule = self.get_object()
        mode = (request.data.get('mode') or 'replace').strip().lower()
        if mode not in ('replace', 'append'):
            return Response(
                {'detail': 'mode يجب أن يكون replace أو append'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        raw_items = []
        csv_file = request.FILES.get('csv_file')
        if csv_file:
            try:
                text   = csv_file.read().decode('utf-8-sig')
                reader = csv.DictReader(io.StringIO(text))
                for row in reader:
                    code = (row.get('item_code') or row.get('كود الصنف') or '').strip()
                    if not code:
                        continue
                    name   = (row.get('item_name') or row.get('اسم الصنف') or '').strip()
                    ov_raw = (row.get('incentive_override') or row.get('قيمة الحافز') or '').strip()
                    ov = None
                    if ov_raw:
                        try:
                            ov = Decimal(ov_raw)
                        except InvalidOperation:
                            pass
                    raw_items.append({'item_code': code, 'item_name': name, 'incentive_override': ov})
            except Exception as exc:
                return Response(
                    {'detail': f'فشل قراءة ملف CSV: {exc}'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            items_data = request.data.get('items')
            if not isinstance(items_data, list):
                return Response(
                    {'detail': 'أرسل items كمصفوفة أو ارفع csv_file'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            for entry in items_data:
                code = (entry.get('item_code') or '').strip()
                if not code:
                    continue
                name   = (entry.get('item_name') or '').strip()
                ov_raw = entry.get('incentive_override')
                ov = None
                if ov_raw not in (None, ''):
                    try:
                        ov = Decimal(str(ov_raw))
                    except InvalidOperation:
                        pass
                raw_items.append({'item_code': code, 'item_name': name, 'incentive_override': ov})

        if not raw_items:
            return Response(
                {'detail': 'لم يتم العثور على بنود صالحة'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        deleted_count = 0
        if mode == 'replace':
            deleted_count, _ = IncentiveRuleItem.objects.filter(rule=rule).delete()

        created_count = updated_count = 0
        for item in raw_items:
            _, created = IncentiveRuleItem.objects.update_or_create(
                rule=rule, item_code=item['item_code'],
                defaults={'item_name': item['item_name'], 'incentive_override': item['incentive_override']},
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        total = IncentiveRuleItem.objects.filter(rule=rule).count()
        logger.info(
            'import_items: rule=%d mode=%s created=%d updated=%d deleted=%d total=%d',
            rule.id, mode, created_count, updated_count, deleted_count, total,
        )
        return Response({'created': created_count, 'updated': updated_count,
                         'deleted': deleted_count, 'total': total})

    # ── DELETE .../rules/{id}/remove-item/?item_code=XYZ ─────────────────────

    @action(detail=True, methods=['delete'], url_path='remove-item')
    def remove_item(self, request, pk=None):
        rule = self.get_object()
        item_code = (request.query_params.get('item_code') or '').strip()
        if not item_code:
            return Response({'detail': 'item_code مطلوب'}, status=status.HTTP_400_BAD_REQUEST)
        deleted, _ = IncentiveRuleItem.objects.filter(rule=rule, item_code=item_code).delete()
        if not deleted:
            return Response({'detail': 'الصنف غير موجود'}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ── DELETE .../rules/{id}/clear-items/ ────────────────────────────────────

    @action(detail=True, methods=['delete'], url_path='clear-items')
    def clear_items(self, request, pk=None):
        rule = self.get_object()
        deleted, _ = IncentiveRuleItem.objects.filter(rule=rule).delete()
        return Response({'deleted': deleted})


# ─────────────────────────────────────────────────────────────────────────────
# Adjustment Entries
# ─────────────────────────────────────────────────────────────────────────────

class AdjustmentEntryViewSet(viewsets.ModelViewSet):
    """
    Manual +/- adjustments to incentive totals.
    Any authenticated user can view; only admin/manager can create/update/delete.
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = AdjustmentEntrySerializer

    def get_queryset(self):
        qs = AdjustmentEntry.objects.select_related('program', 'user', 'created_by')
        program      = self.request.query_params.get('program')
        user_id      = self.request.query_params.get('user_id')
        period_start = self.request.query_params.get('period_start')
        period_end   = self.request.query_params.get('period_end')
        if program:
            qs = qs.filter(program_id=program)
        if user_id:
            qs = qs.filter(user_id=user_id)
        if period_start:
            qs = qs.filter(period_start=period_start)
        if period_end:
            qs = qs.filter(period_end=period_end)
        return qs.order_by('-created_at')

    def perform_create(self, serializer):
        profile = getattr(self.request.user, 'staff_profile', None)
        serializer.save(created_by=profile)

    def destroy(self, request, *args, **kwargs):
        """Block deletion if the related settlement is already finalized."""
        instance = self.get_object()
        if IncentiveSettlement.objects.filter(
            program=instance.program,
            user=instance.user,
            period_start=instance.period_start,
            period_end=instance.period_end,
            is_finalized=True,
        ).exists():
            return Response(
                {'detail': 'لا يمكن حذف التسوية — التسوية النهائية مُعتمدة بالفعل'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# Transactions (read-only)
# ─────────────────────────────────────────────────────────────────────────────

class IncentiveTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class   = IncentiveTransactionSerializer

    def get_queryset(self):
        qs = IncentiveTransaction.objects.select_related('program', 'rule', 'user')
        params = self.request.query_params
        if params.get('program'):
            qs = qs.filter(program_id=params['program'])
        if params.get('user_id'):
            qs = qs.filter(user_id=params['user_id'])
        if params.get('period_start'):
            qs = qs.filter(period_start__gte=params['period_start'])
        if params.get('period_end'):
            qs = qs.filter(period_end__lte=params['period_end'])
        if params.get('doc_type'):
            qs = qs.filter(doc_type=params['doc_type'])
        return qs.order_by('-erp_date', 'doc_no')


# ─────────────────────────────────────────────────────────────────────────────
# Settlements
# ─────────────────────────────────────────────────────────────────────────────

class IncentiveSettlementViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class   = IncentiveSettlementSerializer

    def get_queryset(self):
        qs = IncentiveSettlement.objects.select_related('program', 'user', 'finalized_by')
        params = self.request.query_params
        if params.get('program'):
            qs = qs.filter(program_id=params['program'])
        if params.get('user_id'):
            qs = qs.filter(user_id=params['user_id'])
        if params.get('is_finalized') is not None:
            qs = qs.filter(is_finalized=(params['is_finalized'].lower() == 'true'))
        return qs.order_by('-period_end')

    @action(detail=True, methods=['get'])
    def receipt(self, request, pk=None):
        """
        Full settlement receipt with:
          • Header (user, period, program, dates)
          • Per-item summary (net_qty, rule, incentive)
          • Manual adjustments list
          • Final payout
        """
        sett = self.get_object()
        txns = (
            IncentiveTransaction.objects
            .filter(
                program=sett.program, user=sett.user,
                period_start=sett.period_start, period_end=sett.period_end,
            )
            .select_related('rule')
            .order_by('-erp_date', 'doc_no')
        )
        adjustments = AdjustmentEntry.objects.filter(
            program=sett.program, user=sett.user,
            period_start=sett.period_start, period_end=sett.period_end,
        ).select_related('created_by')

        # Group transactions by item
        from collections import defaultdict
        item_summary = defaultdict(lambda: {
            'item_code': '', 'item_name': '', 'rule_name': '',
            'qty_sold': Decimal('0'), 'qty_returned': Decimal('0'),
            'net_qty': Decimal('0'), 'total_incentive': Decimal('0'),
            'line_count': 0,
        })
        for t in txns:
            s = item_summary[t.item_code]
            s['item_code']  = t.item_code
            s['item_name']  = t.item_name
            s['rule_name']  = t.rule.rule_name if t.rule else ''
            if t.doc_type == 'sale':
                s['qty_sold'] += t.quantity
            else:
                s['qty_returned'] += abs(t.quantity)
            s['net_qty']          += t.quantity
            s['total_incentive']  += t.incentive_amount
            s['line_count']       += 1

        return Response({
            'settlement': IncentiveSettlementSerializer(sett).data,
            'item_summary': [
                {k: (float(v) if isinstance(v, Decimal) else v) for k, v in s.items()}
                for s in sorted(item_summary.values(), key=lambda x: x['item_name'])
            ],
            'adjustments': AdjustmentEntrySerializer(adjustments, many=True).data,
            'transactions': IncentiveTransactionSerializer(txns, many=True).data,
        })


# ─────────────────────────────────────────────────────────────────────────────
# Calculation Log (read-only audit trail)
# ─────────────────────────────────────────────────────────────────────────────

class IncentiveCalculationLogViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class   = IncentiveCalculationLogSerializer

    def get_queryset(self):
        qs = IncentiveCalculationLog.objects.select_related('program', 'triggered_by')
        params = self.request.query_params
        if params.get('program'):
            qs = qs.filter(program_id=params['program'])
        if params.get('mode'):
            qs = qs.filter(mode=params['mode'])
        return qs.order_by('-started_at')


# ─────────────────────────────────────────────────────────────────────────────
# Near-Expiry Stock  (live query from SOFTECH stkbalexpiry)
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# My Progress  (Feature 1 — Employee Live Progress Dashboard)
# ─────────────────────────────────────────────────────────────────────────────

class MyProgressView(APIView):
    """
    GET /api/incentives/my-progress/

    Returns incentive progress for the currently-authenticated employee
    across all active programs that cover today.
    Silent simulation — does NOT write to IncentiveCalculationLog.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = getattr(request.user, 'staff_profile', None)
        if not profile:
            return Response({'detail': 'لا يوجد ملف موظف مرتبط بهذا الحساب'},
                            status=status.HTTP_404_NOT_FOUND)
        if not profile.softech_user_id:
            return Response({'detail': 'كود المندوب في SOFTECH غير محدد — راجع المسؤول'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            from .engine import get_my_progress
            data = get_my_progress(profile)
        except Exception as exc:
            logger.exception('my_progress: failed for user %d', profile.id)
            return Response({'detail': f'فشل الاحتساب: {exc}'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            'employee': {
                'id':          profile.id,
                'name':        profile.full_name,
                'person_code': profile.softech_user_id,
            },
            'as_of_date': date.today().isoformat(),
            'programs':   data,
        })


# ─────────────────────────────────────────────────────────────────────────────
# Suggest Items  (Feature 3 — Smart Item Suggestions)
# ─────────────────────────────────────────────────────────────────────────────

class SuggestItemsView(APIView):
    """
    GET /api/incentives/suggest-items/

    Returns items that are candidates for incentive programs based on:
      1. Near-expiry stock (stkbalexpiry — live query)
      2. High stock + low velocity (ItemDemandMetrics)
      3. High margin items with slow movement

    Query params:
      expiry_within_days   int   default=90
      branch_code          str   optional
      max_results          int   default=30
      include_tags         str   comma-separated: near_expiry,slow_moving,high_margin
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        params = request.query_params
        expiry_days = int(params.get('expiry_within_days', 90))
        branch_code = params.get('branch_code', '').strip() or None
        max_results = int(params.get('max_results', 30))
        tag_filter  = set(t.strip() for t in params.get('include_tags', '').split(',') if t.strip())

        scored: dict = {}  # item_code → {item_code, item_name, score, tags, ...}

        # ── Source 1: Near-expiry from SOFTECH stkbalexpiry ───────────────────
        if not tag_filter or 'near_expiry' in tag_filter:
            try:
                from .engine import fetch_near_expiry_stock
                # Don't filter by store here — we want every sellable near-expiry
                # item as a candidate. Quarantine stores are excluded by default.
                expiry_items = fetch_near_expiry_stock(
                    expiry_within_days=expiry_days,
                )
                for item in expiry_items:
                    code = item['itemcode']
                    if code not in scored:
                        scored[code] = {
                            'item_code':   code,
                            'item_name':   item['item_name'],
                            'score':       0.0,
                            'tags':        [],
                            'expiry_date': item['itemexpirydate'],
                            'expiry_days': item['days_remaining'],
                            'expiry_qty':  item['itemqty'],
                            'monthly_avg': None,
                            'pack_price':  None,
                            'margin_pct':  None,
                        }
                    # Urgency score: closer to expiry = higher score
                    days = item['days_remaining'] or expiry_days
                    urgency = max(0.0, 1.0 - days / expiry_days) * 50
                    scored[code]['score'] += urgency
                    if 'near_expiry' not in scored[code]['tags']:
                        scored[code]['tags'].append('near_expiry')
            except Exception as exc:
                logger.warning('suggest_items: near_expiry query failed — %s', exc)

        # ── Source 2: Slow-moving / overstocked from ItemDemandMetrics ────────
        if not tag_filter or 'slow_moving' in tag_filter:
            try:
                from apps.purchasing.models import ItemDemandMetrics
                slow_qs = ItemDemandMetrics.objects.filter(
                    coverage_months__gte=3,   # more than 3 months of stock
                    monthly_avg__gt=0,        # has some sales history
                )
                if branch_code:
                    from apps.branches.models import Branch
                    try:
                        br = Branch.objects.get(softech_branch_id=branch_code)
                        slow_qs = slow_qs.filter(branch=br)
                    except Exception:
                        pass

                slow_qs = slow_qs.select_related('item').order_by('-coverage_months')[:100]

                for m in slow_qs:
                    if m.item is None:
                        continue
                    code = m.item.softech_id
                    if code not in scored:
                        scored[code] = {
                            'item_code':   code,
                            'item_name':   m.item.name,
                            'score':       0.0,
                            'tags':        [],
                            'expiry_date': None,
                            'expiry_days': None,
                            'expiry_qty':  None,
                            'monthly_avg': float(m.monthly_avg),
                            'pack_price':  float(m.pack_price),
                            'margin_pct':  None,
                        }
                    else:
                        scored[code]['monthly_avg'] = float(m.monthly_avg)
                        scored[code]['pack_price']  = float(m.pack_price)

                    # Overstock score: more coverage months = higher score
                    overstock_score = min(float(m.coverage_months or 0) / 12 * 30, 30)
                    scored[code]['score'] += overstock_score
                    if 'slow_moving' not in scored[code]['tags']:
                        scored[code]['tags'].append('slow_moving')
            except Exception as exc:
                logger.warning('suggest_items: slow_moving query failed — %s', exc)

        # ── Source 3: High-margin items from catalog ───────────────────────────
        if not tag_filter or 'high_margin' in tag_filter:
            try:
                from apps.catalog.models import Item
                high_margin_qs = Item.objects.filter(
                    is_active=True,
                    pack_price__gt=0,
                    cost_price__gt=0,
                ).extra(
                    where=['(pack_price - cost_price) / pack_price * 100 >= 20']
                ).values('softech_id', 'name', 'pack_price', 'cost_price')[:200]

                for item in high_margin_qs:
                    code = item['softech_id']
                    pp   = float(item['pack_price'] or 0)
                    cp   = float(item['cost_price'] or 0)
                    margin = (pp - cp) / pp * 100 if pp > 0 else 0
                    if code not in scored:
                        continue  # only enrich existing candidates, don't flood
                    scored[code]['margin_pct']  = round(margin, 1)
                    scored[code]['pack_price']  = pp
                    margin_score = min(margin / 50 * 20, 20)
                    scored[code]['score'] += margin_score
                    if 'high_margin' not in scored[code]['tags']:
                        scored[code]['tags'].append('high_margin')
            except Exception as exc:
                logger.warning('suggest_items: high_margin query failed — %s', exc)

        # Sort by composite score, return top N
        results = sorted(scored.values(), key=lambda x: -x['score'])[:max_results]
        return Response({
            'count':   len(results),
            'items':   results,
            'filters': {
                'expiry_within_days': expiry_days,
                'branch_code':        branch_code,
            },
        })


class NearExpiryStockView(viewsets.ViewSet):
    """
    GET /api/incentives/near-expiry-stock/

    Live query of SOFTECHDB9.dbo.stkbalexpiry for items expiring within N days.

    NOTE: stkbalexpiry.branchcode is always 0 in SOFTECH — the real physical
    location is `storecode`. Quarantine stores (102/103/105) are excluded by
    default since their stock is not sellable.

    Query params:
      expiry_within_days   int, default=90
      store_codes          comma-separated store codes, e.g. '100,110,160'
      item_codes           comma-separated item codes (optional filter)
      include_quarantine   'true'/'false' (default false)

    Returns:
      items              — list of near-expiry batch rows
      summary_by_bucket  — aggregated counts per expiry bucket
      summary_by_store   — aggregated qty per store
      total_items        — total distinct item codes
      total_qty          — total quantity across all batches
    """
    permission_classes = [IsAuthenticated]

    def list(self, request):
        params = request.query_params

        try:
            expiry_within_days = int(params.get('expiry_within_days', 90))
            if expiry_within_days < 1 or expiry_within_days > 730:
                raise ValueError
        except (ValueError, TypeError):
            return Response(
                {'detail': 'expiry_within_days يجب أن يكون رقماً بين 1 و 730'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Accept both store_codes (correct) and branch_codes (legacy alias)
        store_raw = (params.get('store_codes') or params.get('branch_codes') or '').strip()
        store_codes = [c.strip() for c in store_raw.split(',') if c.strip()] or None

        item_codes_raw = params.get('item_codes', '').strip()
        item_codes = [c.strip() for c in item_codes_raw.split(',') if c.strip()] or None

        include_quarantine = params.get('include_quarantine', '').lower() == 'true'

        try:
            from .engine import fetch_near_expiry_stock
            items = fetch_near_expiry_stock(
                expiry_within_days=expiry_within_days,
                store_codes=store_codes,
                item_codes=item_codes,
                include_quarantine=include_quarantine,
            )
        except Exception as exc:
            logger.exception('near_expiry_stock: SOFTECH query failed')
            return Response(
                {'detail': f'فشل الاستعلام من قاعدة بيانات ERP: {exc}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # ── Aggregations ──────────────────────────────────────────────────────
        bucket_counts: dict = {b: {'count': 0, 'qty': 0.0} for b in _EXPIRY_BUCKETS}
        store_summary: dict = defaultdict(float)
        total_qty = 0.0

        for item in items:
            b = item['expiry_bucket']
            if b in bucket_counts:
                bucket_counts[b]['count'] += 1
                bucket_counts[b]['qty']   += item['itemqty']
            store_summary[item['storecode']] += item['itemqty']
            total_qty += item['itemqty']

        summary_by_bucket = [
            {'bucket': b, **bucket_counts[b]}
            for b in _EXPIRY_BUCKETS
        ]
        summary_by_store = [
            {'store_code': sc, 'total_qty': round(qty, 3)}
            for sc, qty in sorted(store_summary.items(), key=lambda x: -x[1])
        ]

        distinct_items = len({i['itemcode'] for i in items})

        return Response({
            'expiry_within_days':  expiry_within_days,
            'include_quarantine':  include_quarantine,
            'total_items':         distinct_items,
            'total_batches':       len(items),
            'total_qty':           round(total_qty, 3),
            'summary_by_bucket':   summary_by_bucket,
            'summary_by_store':    summary_by_store,
            'items':               items,
        })


# ── Sales Targets & Goals ────────────────────────────────────────────────────────

from rest_framework import viewsets as _viewsets   # noqa: E402
from rest_framework.permissions import IsAuthenticated as _IsAuth  # noqa: E402
from rest_framework.exceptions import PermissionDenied as _PermDenied  # noqa: E402
from .models import SalesTarget  # noqa: E402
from .serializers import SalesTargetSerializer  # noqa: E402

_TARGET_EDIT_ROLES = {'admin', 'supervisor', 'purchasing'}


class SalesTargetViewSet(_viewsets.ModelViewSet):
    """CRUD for sales targets with live attainment. Filters: ?active=true, ?scope=branch."""
    serializer_class   = SalesTargetSerializer
    permission_classes = [_IsAuth]

    def get_queryset(self):
        qs = SalesTarget.objects.select_related('branch', 'category').all()
        if self.request.query_params.get('active') == 'true':
            from datetime import date
            t = date.today()
            qs = qs.filter(period_start__lte=t, period_end__gte=t)
        scope = self.request.query_params.get('scope')
        if scope:
            qs = qs.filter(scope_type=scope)
        return qs

    def _guard(self):
        p = getattr(self.request.user, 'staff_profile', None)
        if not (p and p.role in _TARGET_EDIT_ROLES):
            raise _PermDenied('لا تملك صلاحية إدارة الأهداف')
        return p

    def perform_create(self, serializer):
        serializer.save(created_by=self._guard())

    def perform_update(self, serializer):
        self._guard()
        serializer.save()

    def perform_destroy(self, instance):
        self._guard()
        instance.delete()
