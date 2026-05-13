from django.contrib import admin
from .models import StockCountSession, StockCountLine


class StockCountLineInline(admin.TabularInline):
    model  = StockCountLine
    extra  = 0
    fields = ('item', 'manual_item_name', 'system_qty', 'erp_transqty', 'counted_qty', 'difference', 'has_discrepancy')
    readonly_fields = ('difference', 'has_discrepancy')


@admin.register(StockCountSession)
class StockCountSessionAdmin(admin.ModelAdmin):
    list_display   = ('branch', 'count_date', 'status', 'erp_doc_number', 'created_by', 'created_at')
    list_filter    = ('status', 'branch', 'count_date')
    search_fields  = ('erp_doc_number', 'notes')
    readonly_fields = ('created_at', 'completed_at')
    inlines        = [StockCountLineInline]
