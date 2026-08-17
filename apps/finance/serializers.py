"""
apps/finance/serializers.py — DRF serializers for the Finance module.
"""

from rest_framework import serializers

from .models import (
    Account,
    AccountBalance,
    ExpenseRecord,
    FinanceSchemaTable,
    FinanceSyncRun,
    FinancialPeriod,
    FinancialSnapshot,
    JournalEntry,
    JournalLine,
    TreasuryMovement,
)


# ── Phase 0 ───────────────────────────────────────────────────────────────────

class FinanceSchemaTableSerializer(serializers.ModelSerializer):
    class Meta:
        model  = FinanceSchemaTable
        fields = [
            'id', 'table_name', 'inferred_purpose', 'row_count',
            'columns', 'sample_rows', 'is_confirmed', 'sync_enabled',
            'category', 'discovered_at', 'notes',
        ]
        read_only_fields = [
            'table_name', 'inferred_purpose', 'row_count',
            'columns', 'sample_rows', 'discovered_at',
        ]


class FinanceSchemaTableListSerializer(serializers.ModelSerializer):
    """Lightweight list — no sample_rows to save bandwidth."""
    col_count = serializers.SerializerMethodField()

    class Meta:
        model  = FinanceSchemaTable
        fields = [
            'id', 'table_name', 'category', 'inferred_purpose',
            'row_count', 'col_count', 'is_confirmed', 'sync_enabled',
            'discovered_at',
        ]

    def get_col_count(self, obj):
        return len(obj.columns or [])


# ── Accounts ──────────────────────────────────────────────────────────────────

class AccountSerializer(serializers.ModelSerializer):
    parent_code = serializers.CharField(source='parent.code', read_only=True, default=None)
    children_count = serializers.SerializerMethodField()

    class Meta:
        model  = Account
        fields = [
            'id', 'code', 'name', 'name_ar', 'account_type',
            'nature', 'parent', 'parent_code', 'level', 'is_leaf',
            'is_active', 'softech_code', 'description',
            'children_count',
        ]

    def get_children_count(self, obj):
        return obj.children.count()


class AccountTreeSerializer(serializers.ModelSerializer):
    """Recursive tree — use only for small COA trees."""
    children = serializers.SerializerMethodField()

    class Meta:
        model  = Account
        fields = ['id', 'code', 'name', 'name_ar', 'account_type', 'nature', 'level', 'children']

    def get_children(self, obj):
        qs = obj.children.filter(is_active=True).order_by('code')
        return AccountTreeSerializer(qs, many=True).data


# ── Periods ───────────────────────────────────────────────────────────────────

class FinancialPeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model  = FinancialPeriod
        fields = ['id', 'year', 'month', 'period_type', 'period_start', 'period_end', 'label', 'is_closed']


# ── Journal ───────────────────────────────────────────────────────────────────

class JournalLineSerializer(serializers.ModelSerializer):
    account_display = serializers.CharField(source='account.display_name', read_only=True, default='')

    class Meta:
        model  = JournalLine
        fields = [
            'id', 'line_number', 'account', 'account_display',
            'account_code', 'description', 'debit', 'credit',
            'cost_center', 'party_code', 'party_name',
        ]


class JournalEntrySerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name', read_only=True, default='')
    period_label = serializers.CharField(source='period.label', read_only=True, default='')
    lines = JournalLineSerializer(many=True, read_only=True)

    class Meta:
        model  = JournalEntry
        fields = [
            'id', 'softech_number', 'entry_date', 'branch', 'branch_name',
            'description', 'description_ar', 'entry_type', 'reference',
            'total_debit', 'total_credit', 'is_balanced',
            'period', 'period_label', 'source_table', 'synced_at',
            'lines',
        ]


class JournalEntryListSerializer(serializers.ModelSerializer):
    """Lightweight list without lines."""
    branch_name  = serializers.CharField(source='branch.name', read_only=True, default='')
    period_label = serializers.CharField(source='period.label', read_only=True, default='')

    class Meta:
        model  = JournalEntry
        fields = [
            'id', 'softech_number', 'entry_date', 'branch_name',
            'entry_type', 'total_debit', 'total_credit', 'is_balanced',
            'period_label',
        ]


# ── Account Balance ───────────────────────────────────────────────────────────

class AccountBalanceSerializer(serializers.ModelSerializer):
    account_code    = serializers.CharField(source='account.code',    read_only=True)
    account_name    = serializers.CharField(source='account.name_ar', read_only=True)
    account_type    = serializers.CharField(source='account.account_type', read_only=True)
    branch_name     = serializers.CharField(source='branch.name',     read_only=True, default='موحد')
    period_label    = serializers.CharField(source='period.label',    read_only=True)

    class Meta:
        model  = AccountBalance
        fields = [
            'id', 'account', 'account_code', 'account_name', 'account_type',
            'period', 'period_label', 'branch', 'branch_name',
            'opening_balance', 'total_debit', 'total_credit', 'closing_balance',
            'movement_count',
        ]


# ── Treasury ──────────────────────────────────────────────────────────────────

class TreasuryMovementSerializer(serializers.ModelSerializer):
    branch_name  = serializers.CharField(source='branch.name',  read_only=True, default='')
    period_label = serializers.CharField(source='period.label', read_only=True, default='')

    class Meta:
        model  = TreasuryMovement
        fields = [
            'id', 'softech_number', 'movement_date', 'movement_type',
            'direction', 'payment_method', 'account_code',
            'branch', 'branch_name', 'amount', 'description', 'reference',
            'party_code', 'party_name', 'party_type',
            'cheque_number', 'cheque_date', 'bank_name',
            'period', 'period_label', 'source_table', 'synced_at',
        ]


# ── Expenses ──────────────────────────────────────────────────────────────────

class ExpenseRecordSerializer(serializers.ModelSerializer):
    branch_name    = serializers.CharField(source='branch.name',    read_only=True, default='')
    period_label   = serializers.CharField(source='period.label',   read_only=True, default='')
    category_label = serializers.CharField(source='get_category_display', read_only=True)

    class Meta:
        model  = ExpenseRecord
        fields = [
            'id', 'softech_ref', 'expense_date', 'category', 'category_label',
            'sub_category', 'branch', 'branch_name', 'amount',
            'description', 'vendor', 'reference', 'account_code',
            'cost_center', 'is_recurring', 'period', 'period_label',
            'source_table', 'synced_at',
        ]


# ── Financial Snapshot ────────────────────────────────────────────────────────

class FinancialSnapshotSerializer(serializers.ModelSerializer):
    period_label = serializers.CharField(source='period.label',  read_only=True)
    branch_name  = serializers.CharField(source='branch.name',   read_only=True, default='موحد')

    class Meta:
        model  = FinancialSnapshot
        fields = [
            'id', 'period', 'period_label', 'branch', 'branch_name',
            # Revenue
            'gross_revenue', 'returns_value', 'net_revenue',
            # COGS & Gross Profit
            'cogs', 'gross_profit', 'gross_margin_pct',
            # Purchases
            'total_purchases', 'total_purchase_returns', 'net_purchases',
            # Expenses
            'total_expenses', 'payroll_expenses', 'rent_expenses',
            'utility_expenses', 'other_expenses',
            # Profit
            'operating_profit', 'ebitda', 'net_profit', 'net_margin_pct',
            # Cash Flow
            'cash_inflow', 'cash_outflow', 'net_cash_flow',
            # Balance Sheet
            'total_assets', 'total_liabilities', 'equity',
            'working_capital', 'inventory_value',
            'total_receivables', 'total_payables',
            # Ratios
            'current_ratio', 'quick_ratio', 'debt_ratio',
            # Meta
            'data_sources', 'is_complete', 'computed_at',
        ]


class FinancialSnapshotKPISerializer(serializers.ModelSerializer):
    """Compact snapshot for executive dashboard cards."""
    period_label = serializers.CharField(source='period.label', read_only=True)
    branch_name  = serializers.CharField(source='branch.name',  read_only=True, default='موحد')

    class Meta:
        model  = FinancialSnapshot
        fields = [
            'id', 'period', 'period_label', 'branch', 'branch_name',
            'net_revenue', 'gross_profit', 'gross_margin_pct',
            'net_profit', 'net_margin_pct',
            'total_purchases', 'net_purchases',
            'net_cash_flow', 'is_complete', 'computed_at',
        ]


# ── Sync Run ──────────────────────────────────────────────────────────────────

class FinanceSyncRunSerializer(serializers.ModelSerializer):
    class Meta:
        model  = FinanceSyncRun
        fields = [
            'id', 'sync_type', 'status', 'started_at', 'finished_at',
            'duration_seconds', 'records_synced', 'errors', 'triggered_by', 'notes',
        ]
        read_only_fields = fields


# ── Dashboard summary ─────────────────────────────────────────────────────────

class FinanceDashboardSerializer(serializers.Serializer):
    """
    Shape returned by the /api/finance/dashboard/ endpoint.
    Constructed manually in the view — not a ModelSerializer.
    """
    period_label      = serializers.CharField()
    net_revenue       = serializers.DecimalField(max_digits=18, decimal_places=2)
    gross_profit      = serializers.DecimalField(max_digits=18, decimal_places=2)
    gross_margin_pct  = serializers.DecimalField(max_digits=10, decimal_places=2)
    net_profit        = serializers.DecimalField(max_digits=18, decimal_places=2)
    net_margin_pct    = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_purchases   = serializers.DecimalField(max_digits=18, decimal_places=2)
    net_cash_flow     = serializers.DecimalField(max_digits=18, decimal_places=2)
    total_expenses    = serializers.DecimalField(max_digits=18, decimal_places=2)
    branch_snapshots  = FinancialSnapshotKPISerializer(many=True)
    monthly_trend     = serializers.ListField(child=serializers.DictField())
    last_sync         = FinanceSyncRunSerializer(allow_null=True)
