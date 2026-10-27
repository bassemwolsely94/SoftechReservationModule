from django.contrib import admin

from .models import (StockAuditFinding, StockAuditRule, StockAuditRuleOverride, StockAuditRun,
                     StockLedgerLine, StockLedgerSyncRun)


@admin.register(StockLedgerSyncRun)
class StockLedgerSyncRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'started_at', 'status', 'date_from', 'date_to', 'rows_synced',
                    'chunks_ok', 'chunks_failed', 'rows_pruned', 'triggered_by')
    list_filter = ('status',)
    readonly_fields = [f.name for f in StockLedgerSyncRun._meta.fields]


@admin.register(StockLedgerLine)
class StockLedgerLineAdmin(admin.ModelAdmin):
    """Read-only: the mirror is owned by sync_stock_ledger."""
    list_display = ('branchcode', 'doccode', 'docnumber', 'docdate', 'trans_time', 'itemcode',
                    'transqty', 'transprice', 'newcostprice', 'newqty', 'usercode')
    list_filter = ('doccode', 'branchcode')
    search_fields = ('itemcode', '=docnumber', 'usercode', 'personcode')
    date_hierarchy = 'docdate'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StockAuditRule)
class StockAuditRuleAdmin(admin.ModelAdmin):
    list_display = ('code', 'enabled', 'params', 'updated_at')
    readonly_fields = ('code', 'params', 'updated_at', 'updated_by')   # edited via the API (validated + audited)


@admin.register(StockAuditRuleOverride)
class StockAuditRuleOverrideAdmin(admin.ModelAdmin):
    list_display = ('rule', 'branch', 'enabled', 'params', 'updated_at')
    readonly_fields = ('rule', 'branch', 'enabled', 'params', 'updated_at', 'updated_by')


@admin.register(StockAuditRun)
class StockAuditRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'started_at', 'status', 'date_from', 'date_to', 'triggered_by')
    readonly_fields = [f.name for f in StockAuditRun._meta.fields]


@admin.register(StockAuditFinding)
class StockAuditFindingAdmin(admin.ModelAdmin):
    list_display = ('rule_code', 'severity', 'status', 'branchcode', 'itemcode', 'docnumber',
                    'value_egp', 'softech_user', 'occurred_at')
    list_filter = ('rule_code', 'severity', 'status', 'branchcode')
    search_fields = ('itemcode', '=docnumber', 'softech_user', 'message_ar')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
