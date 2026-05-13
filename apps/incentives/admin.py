from django.contrib import admin
from .models import IncentiveProgram, IncentiveRule, IncentiveTransaction, IncentiveSettlement


class IncentiveRuleInline(admin.TabularInline):
    model  = IncentiveRule
    extra  = 0
    fields = [
        'rule_name', 'item_code', 'item_name', 'category_code',
        'incentive_type', 'incentive_value', 'min_qty',
        'person_code_filter', 'priority', 'is_active',
    ]


@admin.register(IncentiveProgram)
class IncentiveProgramAdmin(admin.ModelAdmin):
    list_display   = ['name', 'start_date', 'end_date', 'calculation_period', 'is_active', 'created_at']
    list_filter    = ['is_active', 'calculation_period']
    search_fields  = ['name']
    inlines        = [IncentiveRuleInline]


@admin.register(IncentiveRule)
class IncentiveRuleAdmin(admin.ModelAdmin):
    list_display  = ['program', 'rule_name', 'item_code', 'category_code',
                     'incentive_type', 'incentive_value', 'priority', 'is_active']
    list_filter   = ['program', 'incentive_type', 'is_active']
    search_fields = ['item_code', 'item_name', 'category_code', 'rule_name']


@admin.register(IncentiveTransaction)
class IncentiveTransactionAdmin(admin.ModelAdmin):
    list_display  = ['program', 'user', 'item_code', 'doc_no', 'doc_type',
                     'quantity', 'incentive_amount', 'is_reversed', 'erp_date']
    list_filter   = ['program', 'doc_type', 'is_reversed']
    search_fields = ['doc_no', 'item_code', 'ref_doc_no']
    readonly_fields = [f.name for f in IncentiveTransaction._meta.fields]

    def has_add_permission(self, request):
        return False  # Only engine writes transactions

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(IncentiveSettlement)
class IncentiveSettlementAdmin(admin.ModelAdmin):
    list_display  = ['program', 'user', 'period_start', 'period_end',
                     'total_incentive', 'transaction_count', 'is_finalized']
    list_filter   = ['program', 'is_finalized']
    search_fields = ['user__user__first_name', 'user__user__last_name']
    readonly_fields = ['total_incentive', 'transaction_count', 'is_finalized',
                       'finalized_at', 'finalized_by', 'created_at', 'updated_at']
