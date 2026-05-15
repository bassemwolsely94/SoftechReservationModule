"""
apps/incentives/views.py

API endpoints:
  GET/POST   /api/incentives/programs/
  GET/PATCH  /api/incentives/programs/{id}/
  DELETE     /api/incentives/programs/{id}/
  GET/POST   /api/incentives/rules/
  PATCH/DEL  /api/incentives/rules/{id}/

  POST       /api/incentives/programs/{id}/calculate/
  POST       /api/incentives/programs/{id}/simulate/
  GET        /api/incentives/programs/{id}/report/
  POST       /api/incentives/programs/{id}/finalize/
  GET        /api/incentives/settlements/{id}/receipt/

  -- Multi-item rule management --
  POST       /api/incentives/rules/{id}/add-item/
             Body: { item_code, item_name?, incentive_override? }
             Adds one item to a rule (idempotent: updates name/override if exists)

  POST       /api/incentives/rules/{id}/import-items/
             Body (JSON):  { "items": [...], "mode": "replace"|"append" }
             Body (form):  csv_file=<upload>, mode=replace|append
             CSV columns:  item_code, item_name (opt), incentive_override (opt)
             Bulk-import items; mode=replace deletes existing items first.

  DELETE     /api/incentives/rules/{id}/remove-item/?item_code=XYZ
             Removes one item from a rule.

  DELETE     /api/incentives/rules/{id}/clear-items/
             Removes ALL items from a rule.
"""
import csv
import io
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db.models import Count, Sum, Q
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import (
    IncentiveProgram, IncentiveRule, IncentiveRuleItem,
    IncentiveTransaction, IncentiveSettlement,
)
from .serializers import (
    IncentiveProgramListSerializer,
    IncentiveProgramDetailSerializer,
    IncentiveProgramCreateSerializer,
    IncentiveRuleSerializer,
    IncentiveRuleItemSerializer,
    IncentiveTransactionSerializer,
    IncentiveSettlementSerializer,
)

logger = logging.getLogger('elrezeiky.incentives')


def _parse_date(value, field_name='date') -> date:
    """Parse an ISO date string from request data, raise ValueError on failure."""
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

    # ── shared period-parse helper ────────────────────────────────────────────

    def _parse_period(self, data):
        """
        Parse period_start / period_end from request data.
        Returns (period_start, period_end) or raises ValueError.
        """
        period_start = _parse_date(data.get('period_start'), 'period_start')
        period_end   = _parse_date(data.get('period_end'),   'period_end')
        if period_start > period_end:
            raise ValueError('period_start يجب أن يسبق period_end')
        return period_start, period_end

    def _parse_user_ids(self, data):
        """Return list[int] or None."""
        raw = data.get('user_ids') or None
        if raw is None:
            return None
        try:
            return [int(x) for x in raw]
        except (TypeError, ValueError):
            raise ValueError('user_ids يجب أن تكون قائمة أرقام صحيحة')

    # ── POST .../programs/{id}/calculate/ ─────────────────────────────────────

    @action(detail=True, methods=['post'])
    def calculate(self, request, pk=None):
        """
        Trigger incentive calculation for a period.

        Body (JSON):
          {
            "period_start": "2025-01-01",
            "period_end":   "2025-01-31",
            "user_ids":     [1, 2, 3],   # optional — omit for all staff
            "force":        false        # true to recalculate even if finalized
          }

        Returns 409 if any settlement for this period is already finalized
        and force is not true.
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
            )
        except ValueError as exc:
            # Finalization lock: period already finalized, force not set
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
            'skipped_person_codes': result.skipped_person_codes,
            'simulated':            result.simulated,
        })

    # ── POST .../programs/{id}/simulate/ ─────────────────────────────────────

    @action(detail=True, methods=['post'])
    def simulate(self, request, pk=None):
        """
        Dry-run: compute incentives without writing any transactions.

        Body (JSON):
          {
            "period_start": "2025-01-01",
            "period_end":   "2025-01-31",
            "user_ids":     [1, 2, 3]   # optional
          }

        Returns same shape as calculate with simulated=true.
        Safe to call at any time — never modifies the database.
        """
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
            'skipped_person_codes': result.skipped_person_codes,
            'simulated':            result.simulated,
        })

    # ── GET .../programs/{id}/report/ ─────────────────────────────────────────

    @action(detail=True, methods=['get'])
    def report(self, request, pk=None):
        """
        Aggregate incentive totals per user for a calculated period.

        Params:
          period_start  — required
          period_end    — required
          user_id       — optional StaffProfile.id
          page / page_size — optional pagination (default 50)

        Returns:
          {
            "period_start": "...", "period_end": "...",
            "rows": [
              {
                "user_id": 1, "user_name": "...", "person_code": "...",
                "total_incentive": 120.00,
                "sale_count": 15, "return_count": 2,
                "is_finalized": false,
                "settlement_id": null,
                "transactions": [ ... ]   # included if user_id filter is given
              }
            ]
          }
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

        # Aggregate per user
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

        # Build settlement lookup for this period
        settlements = {
            s.user_id: s
            for s in IncentiveSettlement.objects.filter(
                program=program,
                period_start=period_start,
                period_end=period_end,
            )
        }

        rows = []
        for a in agg:
            uid = a['user_id']
            fn  = a.get('user__user__first_name') or ''
            ln  = a.get('user__user__last_name') or ''
            name = f'{fn} {ln}'.strip()
            settlement = settlements.get(uid)

            row = {
                'user_id':         uid,
                'user_name':       name,
                'person_code':     a.get('user__softech_user_id') or '',
                'total_incentive': float(a['total_incentive'] or 0),
                'sale_count':      a['sale_count'],
                'return_count':    a['return_count'],
                'is_finalized':    settlement.is_finalized if settlement else False,
                'settlement_id':   settlement.id if settlement else None,
            }
            # Include transaction detail when filtering by single user
            if user_id_filter:
                txns = base_qs.filter(user_id=uid).order_by('-erp_date', 'doc_no')
                row['transactions'] = IncentiveTransactionSerializer(txns, many=True).data

            rows.append(row)

        return Response({
            'program_id':   program.id,
            'program_name': program.name,
            'period_start': period_start.isoformat(),
            'period_end':   period_end.isoformat(),
            'rows':         rows,
        })

    # ── POST .../programs/{id}/finalize/ ──────────────────────────────────────

    @action(detail=True, methods=['post'])
    def finalize(self, request, pk=None):
        """
        Finalize (lock) incentive settlements for a period.

        Body:
          { "period_start": "...", "period_end": "...", "notes": "..." }

        Creates one IncentiveSettlement per user that has transactions,
        marks each as is_finalized=True.  Already-finalized settlements
        are skipped (no double-finalization).
        """
        program = self.get_object()

        try:
            period_start = _parse_date(request.data.get('period_start'), 'period_start')
            period_end   = _parse_date(request.data.get('period_end'),   'period_end')
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        notes   = (request.data.get('notes') or '').strip()
        profile = getattr(request.user, 'staff_profile', None)

        # Aggregate per user
        agg = (
            IncentiveTransaction.objects
            .filter(program=program, period_start=period_start, period_end=period_end)
            .values('user_id')
            .annotate(
                total=Sum('incentive_amount'),
                count=Count('id'),
            )
        )

        if not agg:
            return Response(
                {'detail': 'لا توجد حركات لهذه الفترة — قم بتشغيل الاحتساب أولاً'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        finalized = []
        skipped   = []
        now       = timezone.now()

        for row in agg:
            uid   = row['user_id']
            total = row['total'] or Decimal('0')
            count = row['count']

            sett, created = IncentiveSettlement.objects.get_or_create(
                program=program, user_id=uid,
                period_start=period_start, period_end=period_end,
                defaults={
                    'total_incentive':   total,
                    'transaction_count': count,
                    'notes':             notes,
                },
            )

            if sett.is_finalized:
                skipped.append(uid)
                continue

            # Update totals in case calculate() was re-run since draft
            sett.total_incentive   = total
            sett.transaction_count = count
            sett.is_finalized      = True
            sett.finalized_at      = now
            sett.finalized_by      = profile
            if notes:
                sett.notes = notes
            sett.save(update_fields=[
                'total_incentive', 'transaction_count',
                'is_finalized', 'finalized_at', 'finalized_by', 'notes',
            ])
            finalized.append(uid)

        return Response({
            'finalized_count': len(finalized),
            'skipped_count':   len(skipped),
            'period_start':    period_start.isoformat(),
            'period_end':      period_end.isoformat(),
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
        return qs.order_by('-priority', 'item_code')

    # ── POST .../rules/{id}/add-item/ ─────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='add-item')
    def add_item(self, request, pk=None):
        """
        Add (or update) one item in a rule.

        Body: { "item_code": "123", "item_name": "...", "incentive_override": null }

        Idempotent: if item_code already exists for this rule, updates
        item_name and incentive_override.
        """
        rule = self.get_object()
        item_code = (request.data.get('item_code') or '').strip()
        if not item_code:
            return Response({'detail': 'item_code مطلوب'}, status=status.HTTP_400_BAD_REQUEST)

        item_name = (request.data.get('item_name') or '').strip()
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
            rule=rule,
            item_code=item_code,
            defaults={
                'item_name':          item_name,
                'incentive_override': incentive_override,
            },
        )
        return Response(
            IncentiveRuleItemSerializer(ri).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    # ── POST .../rules/{id}/import-items/ ─────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='import-items')
    def import_items(self, request, pk=None):
        """
        Bulk-import items into a rule.

        Accepts two input formats:
          1. JSON body:
             {
               "items": [
                 { "item_code": "123", "item_name": "...", "incentive_override": 5.0 },
                 ...
               ],
               "mode": "replace"   // "replace" (default) or "append"
             }

          2. Multipart form upload:
             csv_file=<CSV file>
             mode=replace|append
             CSV expected columns (header row required):
               item_code, item_name (optional), incentive_override (optional)

        mode=replace: deletes ALL existing rule items before importing.
        mode=append:  merges; existing item_codes are updated, new ones added.

        Returns: { created, updated, deleted, total }
        """
        rule = self.get_object()
        mode = (request.data.get('mode') or 'replace').strip().lower()
        if mode not in ('replace', 'append'):
            return Response(
                {'detail': 'mode يجب أن يكون replace أو append'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Parse input ───────────────────────────────────────────────────────
        raw_items = []

        # Check for CSV file upload
        csv_file = request.FILES.get('csv_file')
        if csv_file:
            try:
                text = csv_file.read().decode('utf-8-sig')   # handle BOM
                reader = csv.DictReader(io.StringIO(text))
                for row in reader:
                    code = (row.get('item_code') or row.get('كود الصنف') or '').strip()
                    if not code:
                        continue
                    name = (row.get('item_name') or row.get('اسم الصنف') or '').strip()
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
            # JSON body
            items_data = request.data.get('items')
            if not isinstance(items_data, list):
                return Response(
                    {'detail': 'يجب إرسال items كمصفوفة JSON أو رفع ملف csv_file'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            for entry in items_data:
                code = (entry.get('item_code') or '').strip()
                if not code:
                    continue
                name = (entry.get('item_name') or '').strip()
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
                {'detail': 'لم يتم العثور على بنود صالحة في البيانات المُرسَلة'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Apply to DB ───────────────────────────────────────────────────────
        deleted_count = 0
        if mode == 'replace':
            deleted_count, _ = IncentiveRuleItem.objects.filter(rule=rule).delete()

        created_count = 0
        updated_count = 0
        for item in raw_items:
            _, created = IncentiveRuleItem.objects.update_or_create(
                rule=rule,
                item_code=item['item_code'],
                defaults={
                    'item_name':          item['item_name'],
                    'incentive_override': item['incentive_override'],
                },
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

        return Response({
            'created': created_count,
            'updated': updated_count,
            'deleted': deleted_count,
            'total':   total,
        })

    # ── DELETE .../rules/{id}/remove-item/?item_code=XYZ ─────────────────────

    @action(detail=True, methods=['delete'], url_path='remove-item')
    def remove_item(self, request, pk=None):
        """Remove a single item from the rule. Pass ?item_code=XYZ as query param."""
        rule = self.get_object()
        item_code = (request.query_params.get('item_code') or '').strip()
        if not item_code:
            return Response({'detail': 'item_code مطلوب'}, status=status.HTTP_400_BAD_REQUEST)
        deleted, _ = IncentiveRuleItem.objects.filter(rule=rule, item_code=item_code).delete()
        if not deleted:
            return Response({'detail': 'الصنف غير موجود في هذه القاعدة'}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ── DELETE .../rules/{id}/clear-items/ ────────────────────────────────────

    @action(detail=True, methods=['delete'], url_path='clear-items')
    def clear_items(self, request, pk=None):
        """Remove ALL items from a rule."""
        rule = self.get_object()
        deleted, _ = IncentiveRuleItem.objects.filter(rule=rule).delete()
        return Response({'deleted': deleted})


# ─────────────────────────────────────────────────────────────────────────────
# Transactions (read-only — written only by engine)
# ─────────────────────────────────────────────────────────────────────────────

class IncentiveTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class   = IncentiveTransactionSerializer

    def get_queryset(self):
        qs = IncentiveTransaction.objects.select_related('program', 'rule', 'user')
        program     = self.request.query_params.get('program')
        user_id     = self.request.query_params.get('user_id')
        period_start = self.request.query_params.get('period_start')
        period_end   = self.request.query_params.get('period_end')
        if program:
            qs = qs.filter(program_id=program)
        if user_id:
            qs = qs.filter(user_id=user_id)
        if period_start:
            qs = qs.filter(period_start__gte=period_start)
        if period_end:
            qs = qs.filter(period_end__lte=period_end)
        return qs.order_by('-erp_date', 'doc_no')


# ─────────────────────────────────────────────────────────────────────────────
# Settlements
# ─────────────────────────────────────────────────────────────────────────────

class IncentiveSettlementViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class   = IncentiveSettlementSerializer

    def get_queryset(self):
        qs = IncentiveSettlement.objects.select_related(
            'program', 'user', 'finalized_by',
        )
        program      = self.request.query_params.get('program')
        user_id      = self.request.query_params.get('user_id')
        is_finalized = self.request.query_params.get('is_finalized')
        if program:
            qs = qs.filter(program_id=program)
        if user_id:
            qs = qs.filter(user_id=user_id)
        if is_finalized is not None:
            qs = qs.filter(is_finalized=(is_finalized.lower() == 'true'))
        return qs.order_by('-period_end')

    @action(detail=True, methods=['get'])
    def receipt(self, request, pk=None):
        """
        Return settlement detail enriched with per-item breakdown
        for printable receipt rendering.
        """
        sett = self.get_object()
        txns = (
            IncentiveTransaction.objects
            .filter(
                program=sett.program,
                user=sett.user,
                period_start=sett.period_start,
                period_end=sett.period_end,
            )
            .select_related('rule')
            .order_by('-erp_date', 'doc_no')
        )

        # Group by item_code for the item summary table
        from collections import defaultdict
        item_summary = defaultdict(lambda: {
            'item_code': '', 'item_name': '', 'rule_name': '',
            'net_qty': Decimal('0'), 'total_incentive': Decimal('0'), 'line_count': 0,
        })
        for t in txns:
            s = item_summary[t.item_code]
            s['item_code']       = t.item_code
            s['item_name']       = t.item_name
            s['rule_name']       = t.rule.rule_name if t.rule else ''
            s['net_qty']         += t.quantity
            s['total_incentive'] += t.incentive_amount
            s['line_count']      += 1

        return Response({
            'settlement': IncentiveSettlementSerializer(sett).data,
            'item_summary': [
                {
                    **{k: (float(v) if isinstance(v, Decimal) else v) for k, v in s.items()}
                }
                for s in sorted(item_summary.values(), key=lambda x: x['item_name'])
            ],
            'transactions': IncentiveTransactionSerializer(txns, many=True).data,
        })
