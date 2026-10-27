from django.contrib import admin
from .models import StockCountSession, StockCountSnapshot


class StockCountSnapshotInline(admin.TabularInline):
    model         = StockCountSnapshot
    extra         = 0
    fields        = ('item_code', 'item_name', 'expected_qty', 'counted_qty', 'difference', 'variance_type')
    readonly_fields = ('item_code', 'item_name', 'expected_qty', 'snapshot_time', 'difference', 'variance_type')
    can_delete    = False
    max_num       = 0  # read-only inline — no adding rows


@admin.register(StockCountSession)
class StockCountSessionAdmin(admin.ModelAdmin):
    list_display   = ('name', 'branch_code', 'mode', 'status', 'item_count',
                      'surplus_count', 'deficit_count', 'ok_count', 'created_by', 'created_at')
    list_filter    = ('status', 'mode', 'branch_code')
    search_fields  = ('name', 'branch_code', 'notes')
    readonly_fields = ('created_at', 'updated_at', 'snapshot_at', 'exported_at', 'uploaded_at', 'variance_at',
                       'item_count', 'surplus_count', 'deficit_count', 'ok_count')
    inlines        = [StockCountSnapshotInline]


@admin.register(StockCountSnapshot)
class StockCountSnapshotAdmin(admin.ModelAdmin):
    list_display   = ('session', 'item_code', 'item_name', 'branch_code',
                      'expected_qty', 'counted_qty', 'difference', 'variance_type')
    list_filter    = ('variance_type', 'branch_code')
    search_fields  = ('item_code', 'item_name')
    readonly_fields = ('expected_qty', 'snapshot_time')
