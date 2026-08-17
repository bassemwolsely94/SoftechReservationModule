from django.contrib import admin
from .models import StockBatch, BatchMovement, NearExpiryAlert


class BatchMovementInline(admin.TabularInline):
    model       = BatchMovement
    extra       = 0
    readonly_fields = [
        'movement_type', 'qty_change', 'qty_after',
        'branch', 'performed_by', 'reference_type', 'reference_id',
        'notes', 'created_at',
    ]
    can_delete  = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(StockBatch)
class StockBatchAdmin(admin.ModelAdmin):
    list_display   = [
        'batch_number', 'item', 'branch', 'expiry_date', 'current_qty',
        'is_quarantined', 'is_expired', 'vendor',
    ]
    list_filter    = ['is_quarantined', 'is_expired', 'storage_condition', 'branch']
    search_fields  = ['batch_number', 'item__name', 'vendor__name']
    readonly_fields = ['original_qty', 'created_at', 'updated_at']
    inlines        = [BatchMovementInline]

    def has_add_permission(self, request):
        return False  # batches are created via service.receive_from_invoice()


@admin.register(BatchMovement)
class BatchMovementAdmin(admin.ModelAdmin):
    list_display  = ['batch', 'movement_type', 'qty_change', 'qty_after', 'branch', 'performed_by', 'created_at']
    list_filter   = ['movement_type']
    readonly_fields = [f.name for f in BatchMovement._meta.get_fields() if hasattr(f, 'name')]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(NearExpiryAlert)
class NearExpiryAlertAdmin(admin.ModelAdmin):
    list_display  = ['batch', 'threshold_days', 'alerted_at', 'resolved_at', 'resolution']
    list_filter   = ['threshold_days']
    readonly_fields = ['batch', 'threshold_days', 'alerted_at']
