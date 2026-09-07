"""
apps/finance/views.py — Finance Intelligence Platform API views.

All views require IsAuthenticated.
Trigger endpoints (sync, discover) additionally require admin/pharmacist role.
"""

import threading
from decimal import Decimal

from django.db.models import Count, Sum
from rest_framework import filters, generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import (
    Account,
    AccountBalance,
    ExpenseRecord,
    FinanceSchemaTable,
    FinanceSyncRun,
    FinancialPeriod,
    FinancialSnapshot,
    JournalEntry,
    TreasuryMovement,
)
from .serializers import (
    AccountBalanceSerializer,
    AccountSerializer,
    AccountTreeSerializer,
    ExpenseRecordSerializer,
    FinanceSchemaTableListSerializer,
    FinanceSchemaTableSerializer,
    FinanceSyncRunSerializer,
    FinancialPeriodSerializer,
    FinancialSnapshotKPISerializer,
    FinancialSnapshotSerializer,
    JournalEntryListSerializer,
    JournalEntrySerializer,
    TreasuryMovementSerializer,
)


# ── Permission helpers ────────────────────────────────────────────────────────

def _is_admin_or_pharmacist(user) -> bool:
    try:
        return user.staff_profile.role in ('admin', 'pharmacist') or user.is_superuser
    except Exception:
        return user.is_staff or user.is_superuser


# ── Period helpers ────────────────────────────────────────────────────────────

def _latest_period() -> FinancialPeriod | None:
    return FinancialPeriod.objects.filter(period_type='month').order_by('-year', '-month').first()


def _period_from_params(request) -> FinancialPeriod | None:
    period_id = request.query_params.get('period_id')
    if period_id:
        return FinancialPeriod.objects.filter(pk=period_id).first()
    year  = request.query_params.get('year')
    month = request.query_params.get('month')
    if year and month:
        return FinancialPeriod.objects.filter(year=int(year), month=int(month)).first()
    return _latest_period()


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def finance_dashboard(request):
    """
    Consolidated financial dashboard.
    Returns KPIs for the requested period (default: latest).
    Query params: period_id | year + month | branch_id
    """
    period = _period_from_params(request)
    if not period:
        return Response({'detail': 'No financial data found. Run sync first.'}, status=404)

    branch_id = request.query_params.get('branch_id')

    # Consolidated (branch=None) snapshot
    qs = FinancialSnapshot.objects.filter(period=period)
    consolidated = qs.filter(branch__isnull=True).first()

    # All branch snapshots for this period
    branch_snapshots = qs.filter(branch__isnull=False)
    if branch_id:
        branch_snapshots = branch_snapshots.filter(branch_id=branch_id)

    # YTD monthly trend (current year)
    trend = list(
        FinancialSnapshot.objects.filter(
            period__year=period.year,
            period__period_type='month',
            branch__isnull=True,
        )
        .order_by('period__month')
        .values(
            'period__label', 'period__month',
            'net_revenue', 'gross_profit', 'net_profit', 'total_purchases',
        )
    )

    last_sync = FinanceSyncRun.objects.order_by('-started_at').first()

    snap = consolidated or FinancialSnapshot()

    return Response({
        'period_label':     period.label,
        'period_id':        period.pk,
        'net_revenue':      snap.net_revenue,
        'gross_revenue':    snap.gross_revenue,
        'returns_value':    snap.returns_value,
        'gross_profit':     snap.gross_profit,
        'gross_margin_pct': float(snap.gross_margin_pct),
        'net_profit':       snap.net_profit,
        'net_margin_pct':   float(snap.net_margin_pct),
        'total_purchases':  snap.total_purchases,
        'net_purchases':    snap.net_purchases,
        'total_expenses':   snap.total_expenses,
        'net_cash_flow':    snap.net_cash_flow,
        'inventory_value':  snap.inventory_value,
        'is_complete':      snap.is_complete,
        'branch_snapshots': FinancialSnapshotKPISerializer(branch_snapshots, many=True).data,
        'monthly_trend':    trend,
        'last_sync':        FinanceSyncRunSerializer(last_sync).data if last_sync else None,
    })


# ══════════════════════════════════════════════════════════════════════════════
# PERIODS
# ══════════════════════════════════════════════════════════════════════════════

class FinancialPeriodListView(generics.ListAPIView):
    permission_classes  = [IsAuthenticated]
    serializer_class    = FinancialPeriodSerializer
    queryset            = FinancialPeriod.objects.all()
    filter_backends     = [filters.OrderingFilter]
    ordering_fields     = ['year', 'month']
    ordering            = ['-year', '-month']


# ══════════════════════════════════════════════════════════════════════════════
# CHART OF ACCOUNTS
# ══════════════════════════════════════════════════════════════════════════════

class AccountListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class   = AccountSerializer
    filter_backends    = [filters.SearchFilter, filters.OrderingFilter]
    search_fields      = ['code', 'name', 'name_ar', 'softech_code']
    ordering_fields    = ['code', 'level', 'account_type']
    ordering           = ['code']

    def get_queryset(self):
        qs = Account.objects.all()
        atype  = self.request.query_params.get('account_type')
        active = self.request.query_params.get('is_active')
        if atype:
            qs = qs.filter(account_type=atype)
        if active is not None:
            qs = qs.filter(is_active=active.lower() == 'true')
        return qs


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def account_tree(request):
    """Return root accounts with their children nested (for small COA trees)."""
    roots = Account.objects.filter(parent__isnull=True, is_active=True).order_by('code')
    return Response(AccountTreeSerializer(roots, many=True).data)


# ══════════════════════════════════════════════════════════════════════════════
# FINANCIAL SNAPSHOTS
# ══════════════════════════════════════════════════════════════════════════════

class FinancialSnapshotListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class   = FinancialSnapshotSerializer
    filter_backends    = [filters.OrderingFilter]
    ordering_fields    = ['period', 'net_revenue', 'gross_profit']
    ordering           = ['-period']

    def get_queryset(self):
        qs = FinancialSnapshot.objects.select_related('period', 'branch')
        period_id = self.request.query_params.get('period_id')
        branch_id = self.request.query_params.get('branch_id')
        year      = self.request.query_params.get('year')
        if period_id:
            qs = qs.filter(period_id=period_id)
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        elif self.request.query_params.get('consolidated') == 'true':
            qs = qs.filter(branch__isnull=True)
        if year:
            qs = qs.filter(period__year=year)
        return qs


# ══════════════════════════════════════════════════════════════════════════════
# P&L STATEMENT
# ══════════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def profit_and_loss(request):
    """
    Profit & Loss statement for a period.
    Returns a structured P&L with revenue, COGS, gross profit, expenses, net profit.
    Query params: period_id | year+month | branch_id
    """
    period = _period_from_params(request)
    if not period:
        return Response({'detail': 'Period not found.'}, status=404)

    branch_id = request.query_params.get('branch_id')
    snap_qs   = FinancialSnapshot.objects.filter(period=period)
    if branch_id:
        snap_qs = snap_qs.filter(branch_id=branch_id)
    else:
        snap_qs = snap_qs.filter(branch__isnull=True)

    snap = snap_qs.first()
    if not snap:
        return Response({'detail': 'No snapshot for this period. Run sync first.'}, status=404)

    D = Decimal

    return Response({
        'period':       period.label,
        'branch':       snap.branch.name if snap.branch else 'موحد',
        'revenue': {
            'gross_revenue':  snap.gross_revenue,
            'returns_value':  snap.returns_value,
            'net_revenue':    snap.net_revenue,
        },
        'cogs': {
            'total_purchases':        snap.total_purchases,
            'total_purchase_returns': snap.total_purchase_returns,
            'net_purchases':          snap.net_purchases,
            'cogs':                   snap.cogs,
        },
        'gross_profit':    snap.gross_profit,
        'gross_margin_pct': float(snap.gross_margin_pct),
        'expenses': {
            'payroll':    snap.payroll_expenses,
            'rent':       snap.rent_expenses,
            'utilities':  snap.utility_expenses,
            'other':      snap.other_expenses,
            'total':      snap.total_expenses,
        },
        'operating_profit':  snap.operating_profit,
        'ebitda':            snap.ebitda,
        'net_profit':        snap.net_profit,
        'net_margin_pct':    float(snap.net_margin_pct),
        'is_complete':       snap.is_complete,
        'computed_at':       snap.computed_at,
    })


# ══════════════════════════════════════════════════════════════════════════════
# JOURNAL ENTRIES
# ══════════════════════════════════════════════════════════════════════════════

class JournalEntryListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    filter_backends    = [filters.SearchFilter, filters.OrderingFilter]
    search_fields      = ['softech_number', 'description', 'reference']
    ordering_fields    = ['entry_date', 'total_debit']
    ordering           = ['-entry_date']

    def get_serializer_class(self):
        if self.request.query_params.get('detail') == 'true':
            return JournalEntrySerializer
        return JournalEntryListSerializer

    def get_queryset(self):
        qs = JournalEntry.objects.select_related('branch', 'period')
        period_id  = self.request.query_params.get('period_id')
        entry_type = self.request.query_params.get('entry_type')
        branch_id  = self.request.query_params.get('branch_id')
        if period_id:
            qs = qs.filter(period_id=period_id)
        if entry_type:
            qs = qs.filter(entry_type=entry_type)
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        return qs


class JournalEntryDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class   = JournalEntrySerializer
    queryset           = JournalEntry.objects.prefetch_related('lines__account')


# ══════════════════════════════════════════════════════════════════════════════
# ACCOUNT BALANCES  (Trial Balance)
# ══════════════════════════════════════════════════════════════════════════════

class AccountBalanceListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class   = AccountBalanceSerializer
    filter_backends    = [filters.OrderingFilter]
    ordering_fields    = ['account__code', 'closing_balance']
    ordering           = ['account__code']

    def get_queryset(self):
        qs = AccountBalance.objects.select_related('account', 'period', 'branch')
        period_id    = self.request.query_params.get('period_id')
        branch_id    = self.request.query_params.get('branch_id')
        account_type = self.request.query_params.get('account_type')
        if period_id:
            qs = qs.filter(period_id=period_id)
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        if account_type:
            qs = qs.filter(account__account_type=account_type)
        return qs


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def trial_balance(request):
    """
    Trial balance for a period.
    Returns grouped totals by account_type.
    """
    period = _period_from_params(request)
    if not period:
        return Response({'detail': 'Period not found.'}, status=404)

    branch_id = request.query_params.get('branch_id')
    qs = AccountBalance.objects.filter(period=period).select_related('account', 'branch')
    if branch_id:
        qs = qs.filter(branch_id=branch_id)

    rows = qs.values(
        'account__code', 'account__name_ar', 'account__account_type',
    ).annotate(
        total_debit     = Sum('total_debit'),
        total_credit    = Sum('total_credit'),
        closing_balance = Sum('closing_balance'),
    ).order_by('account__code')

    totals_debit  = sum(r['total_debit']     or 0 for r in rows)
    totals_credit = sum(r['total_credit']    or 0 for r in rows)

    return Response({
        'period':       period.label,
        'lines':        list(rows),
        'total_debit':  totals_debit,
        'total_credit': totals_credit,
        'is_balanced':  abs(totals_debit - totals_credit) < Decimal('0.01'),
    })


# ══════════════════════════════════════════════════════════════════════════════
# TREASURY / CASH FLOW
# ══════════════════════════════════════════════════════════════════════════════

class TreasuryMovementListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class   = TreasuryMovementSerializer
    filter_backends    = [filters.SearchFilter, filters.OrderingFilter]
    search_fields      = ['softech_number', 'party_name', 'party_code', 'reference']
    ordering_fields    = ['movement_date', 'amount']
    ordering           = ['-movement_date']

    def get_queryset(self):
        qs = TreasuryMovement.objects.select_related('branch', 'period')
        period_id      = self.request.query_params.get('period_id')
        direction      = self.request.query_params.get('direction')
        payment_method = self.request.query_params.get('payment_method')
        branch_id      = self.request.query_params.get('branch_id')
        if period_id:
            qs = qs.filter(period_id=period_id)
        if direction:
            qs = qs.filter(direction=direction)
        if payment_method:
            qs = qs.filter(payment_method=payment_method)
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        return qs


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def cash_flow_summary(request):
    """
    Direct cash flow summary for a period.
    Returns inflow, outflow, net by payment method.
    """
    period = _period_from_params(request)
    if not period:
        return Response({'detail': 'Period not found.'}, status=404)

    snap = FinancialSnapshot.objects.filter(period=period, branch__isnull=True).first()

    by_method = list(
        TreasuryMovement.objects.filter(period=period)
        .values('direction', 'payment_method')
        .annotate(total=Sum('amount'))
        .order_by('payment_method', 'direction')
    )

    return Response({
        'period':        period.label,
        'cash_inflow':   snap.cash_inflow   if snap else 0,
        'cash_outflow':  snap.cash_outflow  if snap else 0,
        'net_cash_flow': snap.net_cash_flow if snap else 0,
        'by_method':     by_method,
    })


# ══════════════════════════════════════════════════════════════════════════════
# EXPENSES
# ══════════════════════════════════════════════════════════════════════════════

class ExpenseRecordListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class   = ExpenseRecordSerializer
    filter_backends    = [filters.SearchFilter, filters.OrderingFilter]
    search_fields      = ['softech_ref', 'description', 'vendor', 'reference']
    ordering_fields    = ['expense_date', 'amount']
    ordering           = ['-expense_date']

    def get_queryset(self):
        qs = ExpenseRecord.objects.select_related('branch', 'period')
        p  = self.request.query_params

        period_id    = p.get('period_id')
        year         = p.get('year')
        month        = p.get('month')
        date_from    = p.get('date_from')   # YYYY-MM-DD free-range start
        date_to      = p.get('date_to')     # YYYY-MM-DD free-range end
        category     = p.get('category')
        branch_id    = p.get('branch_id')
        sub_category = p.get('sub_category')

        # Period filtering — prefer free date range when supplied
        if date_from:
            qs = qs.filter(expense_date__gte=date_from)
        if date_to:
            qs = qs.filter(expense_date__lte=date_to)
        if not (date_from or date_to):
            # Fall back to period/year+month
            if period_id:
                qs = qs.filter(period_id=period_id)
            elif year and month:
                qs = qs.filter(
                    period__year=int(year),
                    period__month=int(month),
                )
            elif year:
                qs = qs.filter(period__year=int(year))

        if category:
            qs = qs.filter(category=category)
        if sub_category:
            qs = qs.filter(sub_category__icontains=sub_category)
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        return qs


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def expense_breakdown(request):
    """
    Expense breakdown by category for a period.
    """
    period = _period_from_params(request)
    if not period:
        return Response({'detail': 'Period not found.'}, status=404)

    p         = request.query_params
    branch_id = p.get('branch_id')
    date_from = p.get('date_from')
    date_to   = p.get('date_to')
    category  = p.get('category')

    # Build the base queryset — use free date range when supplied
    if date_from or date_to:
        qs = ExpenseRecord.objects.all()
        if date_from:
            qs = qs.filter(expense_date__gte=date_from)
        if date_to:
            qs = qs.filter(expense_date__lte=date_to)
        period_label = f"{date_from or '?'} — {date_to or '?'}"
    else:
        qs = ExpenseRecord.objects.filter(period=period)
        period_label = period.label

    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    if category:
        qs = qs.filter(category=category)

    by_category = list(
        qs.values('category')
          .annotate(total=Sum('amount'), count=Count('id'))
          .order_by('-total')
    )
    total = sum(r['total'] or 0 for r in by_category)

    by_sub_category = list(
        qs.exclude(sub_category='')
          .values('sub_category', 'category')
          .annotate(total=Sum('amount'), count=Count('id'))
          .order_by('-total')[:50]
    )

    return Response({
        'period':           period_label,
        'total':            total,
        'by_category':      by_category,
        'by_sub_category':  by_sub_category,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def expense_subcategories(request):
    """
    Return distinct sub_category values with totals.
    Accepts the same period / date-range / category / branch_id params as the list view.
    Used to populate the subcategory filter dropdown.
    """
    p         = request.query_params
    date_from = p.get('date_from')
    date_to   = p.get('date_to')
    year      = p.get('year')
    month     = p.get('month')
    period_id = p.get('period_id')
    category  = p.get('category')
    branch_id = p.get('branch_id')

    if date_from or date_to:
        qs = ExpenseRecord.objects.all()
        if date_from:
            qs = qs.filter(expense_date__gte=date_from)
        if date_to:
            qs = qs.filter(expense_date__lte=date_to)
    else:
        period = _period_from_params(request)
        if period:
            qs = ExpenseRecord.objects.filter(period=period)
        elif year and month:
            qs = ExpenseRecord.objects.filter(
                period__year=int(year), period__month=int(month)
            )
        elif year:
            qs = ExpenseRecord.objects.filter(period__year=int(year))
        else:
            qs = ExpenseRecord.objects.all()

    if category:
        qs = qs.filter(category=category)
    if branch_id:
        qs = qs.filter(branch_id=branch_id)

    result = list(
        qs.exclude(sub_category='')
          .values('sub_category', 'category')
          .annotate(total=Sum('amount'), count=Count('id'))
          .order_by('-total')
    )
    return Response(result)


# ══════════════════════════════════════════════════════════════════════════════
# SCHEMA DISCOVERY
# ══════════════════════════════════════════════════════════════════════════════

class FinanceSchemaTableListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class   = FinanceSchemaTableListSerializer
    filter_backends    = [filters.SearchFilter, filters.OrderingFilter]
    search_fields      = ['table_name', 'inferred_purpose', 'category']
    ordering_fields    = ['table_name', 'row_count', 'category']
    ordering           = ['category', 'table_name']

    def get_queryset(self):
        qs = FinanceSchemaTable.objects.all()
        cat       = self.request.query_params.get('category')
        confirmed = self.request.query_params.get('is_confirmed')
        enabled   = self.request.query_params.get('sync_enabled')
        if cat:
            qs = qs.filter(category=cat)
        if confirmed is not None:
            qs = qs.filter(is_confirmed=confirmed.lower() == 'true')
        if enabled is not None:
            qs = qs.filter(sync_enabled=enabled.lower() == 'true')
        return qs


class FinanceSchemaTableDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class   = FinanceSchemaTableSerializer
    queryset           = FinanceSchemaTable.objects.all()

    def update(self, request, *args, **kwargs):
        if not _is_admin_or_pharmacist(request.user):
            return Response({'detail': 'Not authorized.'}, status=403)
        return super().update(request, *args, **kwargs)


# ══════════════════════════════════════════════════════════════════════════════
# SYNC TRIGGERS
# ══════════════════════════════════════════════════════════════════════════════

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def trigger_discover(request):
    """
    Phase 0 — trigger schema discovery in a background thread.
    Requires admin/pharmacist role.
    """
    if not _is_admin_or_pharmacist(request.user):
        return Response({'detail': 'Not authorized.'}, status=403)

    from apps.finance.management.commands.discover_finance_schema import Command

    def _run():
        cmd = Command()
        cmd.stdout = type('S', (), {'write': lambda s, x, **k: None, 'flush': lambda s: None})()
        cmd.stderr = cmd.stdout
        cmd.style  = type('S', (), {
            'HTTP_INFO': str, 'WARNING': str, 'SUCCESS': str, 'ERROR': str
        })()
        try:
            cmd.handle(table=None, min_score=3, dry_run=False)
        except Exception:
            pass

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return Response({'detail': 'Schema discovery started in background.'}, status=202)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def trigger_sync(request):
    """
    Phase 9 — trigger financial sync for a period.
    Body (optional): { "year": 2024, "month": 3 } or { "months": 6 }
    Requires admin/pharmacist role.
    """
    if not _is_admin_or_pharmacist(request.user):
        return Response({'detail': 'Not authorized.'}, status=403)

    import datetime
    from apps.finance.engine.sync_engine import FinanceSyncEngine
    from django.utils import timezone

    body  = request.data or {}
    today = datetime.date.today()

    months_back = int(body.get('months', 0))
    if months_back > 0:
        pairs = []
        cur = today
        for _ in range(months_back):
            pairs.append((cur.year, cur.month))
            if cur.month == 1:
                cur = cur.replace(year=cur.year - 1, month=12)
            else:
                cur = cur.replace(month=cur.month - 1)
        pairs.reverse()
    else:
        year  = int(body.get('year',  today.year))
        month = int(body.get('month', today.month))
        pairs = [(year, month)]

    sync_run = FinanceSyncRun.objects.create(
        sync_type='incremental',
        status='running',
        started_at=timezone.now(),
        triggered_by=str(request.user),
    )

    def _run():
        for yr, mo in pairs:
            try:
                FinanceSyncEngine(year=yr, month=mo, sync_run=sync_run).run()
            except Exception:
                pass

    threading.Thread(target=_run, daemon=True).start()

    return Response({
        'detail':    f'Sync started for {len(pairs)} period(s).',
        'sync_run':  sync_run.pk,
        'periods':   [f'{yr}-{mo:02d}' for yr, mo in pairs],
    }, status=202)


# ══════════════════════════════════════════════════════════════════════════════
# SYNC RUN HISTORY
# ══════════════════════════════════════════════════════════════════════════════

class FinanceSyncRunListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class   = FinanceSyncRunSerializer
    queryset           = FinanceSyncRun.objects.order_by('-started_at')[:50]
    filter_backends    = [filters.OrderingFilter]
    ordering           = ['-started_at']
