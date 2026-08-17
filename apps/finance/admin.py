"""
apps/finance/admin.py — Django admin for the Finance Intelligence Platform.
"""

from django.contrib import admin
from django.utils.html import format_html

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


# ── Phase 0 ──────────────────────────────────────────────────────────────────

@admin.register(FinanceSchemaTable)
class FinanceSchemaTableAdmin(admin.ModelAdmin):
    list_display  = ['table_name', 'category', 'row_count', 'is_confirmed', 'sync_enabled', 'discovered_at']
    list_filter   = ['category', 'is_confirmed', 'sync_enabled']
    search_fields = ['table_name', 'inferred_purpose', 'notes']
    list_editable = ['is_confirmed', 'sync_enabled']
    ordering      = ['category', 'table_name']
    readonly_fields = ['discovered_at', 'columns', 'sample_rows', 'inferred_purpose', 'row_count']

    fieldsets = (
        ('Table Info', {
            'fields': ('table_name', 'inferred_purpose', 'row_count', 'discovered_at')
        }),
        ('Classification', {
            'fields': ('category', 'is_confirmed', 'sync_enabled', 'notes')
        }),
        ('Schema Details', {
            'fields': ('columns', 'sample_rows'),
            'classes': ('collapse',),
        }),
    )


# ── Chart of Accounts ─────────────────────────────────────────────────────────

@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display  = ['code', 'name_ar', 'account_type', 'nature', 'level', 'is_leaf', 'is_active']
    list_filter   = ['account_type', 'nature', 'is_leaf', 'is_active']
    search_fields = ['code', 'name', 'name_ar', 'softech_code']
    ordering      = ['code']
    raw_id_fields = ['parent']


# ── Periods ───────────────────────────────────────────────────────────────────

@admin.register(FinancialPeriod)
class FinancialPeriodAdmin(admin.ModelAdmin):
    list_display = ['label', 'period_type', 'period_start', 'period_end', 'is_closed']
    list_filter  = ['period_type', 'is_closed', 'year']
    ordering     = ['-year', '-month']


# ── Journal ───────────────────────────────────────────────────────────────────

class JournalLineInline(admin.TabularInline):
    model  = JournalLine
    extra  = 0
    fields = ['line_number', 'account', 'account_code', 'debit', 'credit', 'party_code', 'party_name']


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display  = ['softech_number', 'entry_date', 'entry_type', 'branch', 'total_debit', 'is_balanced']
    list_filter   = ['entry_type', 'is_balanced', 'period']
    search_fields = ['softech_number', 'description', 'reference']
    raw_id_fields = ['branch', 'period']
    inlines       = [JournalLineInline]
    ordering      = ['-entry_date']


# ── Account Balances ──────────────────────────────────────────────────────────

@admin.register(AccountBalance)
class AccountBalanceAdmin(admin.ModelAdmin):
    list_display  = ['account', 'period', 'branch', 'opening_balance', 'total_debit', 'total_credit', 'closing_balance']
    list_filter   = ['period', 'branch']
    search_fields = ['account__code', 'account__name']
    raw_id_fields = ['account', 'period', 'branch']


# ── Treasury ──────────────────────────────────────────────────────────────────

@admin.register(TreasuryMovement)
class TreasuryMovementAdmin(admin.ModelAdmin):
    list_display  = ['softech_number', 'movement_date', 'direction', 'payment_method', 'amount', 'party_name', 'branch']
    list_filter   = ['direction', 'payment_method', 'movement_type', 'period', 'branch']
    search_fields = ['softech_number', 'party_name', 'party_code', 'reference']
    ordering      = ['-movement_date']
    raw_id_fields = ['branch', 'period']


# ── Expenses ──────────────────────────────────────────────────────────────────

@admin.register(ExpenseRecord)
class ExpenseRecordAdmin(admin.ModelAdmin):
    list_display  = ['expense_date', 'category', 'amount', 'vendor', 'branch', 'is_recurring']
    list_filter   = ['category', 'is_recurring', 'period', 'branch']
    search_fields = ['softech_ref', 'description', 'vendor', 'reference']
    ordering      = ['-expense_date']
    raw_id_fields = ['branch', 'period']


# ── Snapshots ─────────────────────────────────────────────────────────────────

@admin.register(FinancialSnapshot)
class FinancialSnapshotAdmin(admin.ModelAdmin):
    list_display  = [
        'period', 'branch_label', 'net_revenue', 'gross_profit',
        'gross_margin_pct', 'net_profit', 'is_complete', 'computed_at',
    ]
    list_filter   = ['period', 'is_complete']
    ordering      = ['-period']
    raw_id_fields = ['period', 'branch']
    readonly_fields = ['computed_at']

    def branch_label(self, obj):
        return obj.branch.name if obj.branch else '— موحد —'
    branch_label.short_description = 'الفرع'


# ── Sync Runs ────────────────────────────────────────────────────────────────

@admin.register(FinanceSyncRun)
class FinanceSyncRunAdmin(admin.ModelAdmin):
    list_display  = ['sync_type', 'status', 'started_at', 'finished_at', 'duration_seconds', 'triggered_by']
    list_filter   = ['status', 'sync_type']
    ordering      = ['-started_at']
    readonly_fields = ['started_at', 'finished_at', 'duration_seconds', 'records_synced', 'errors']
