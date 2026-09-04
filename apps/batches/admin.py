from django.contrib import admin
from .models import (
    StockBatch, BatchMovement, NearExpiryAlert,
    PurchaseExpiryEntry, PurchaseExpiryAuditRun,
)


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


@admin.register(PurchaseExpiryEntry)
class PurchaseExpiryEntryAdmin(admin.ModelAdmin):
    list_display  = [
        'item_code', 'item_name', 'entered_expiry', 'qty',
        'supplier_code', 'supplier_category', 'doc_number', 'doc_date', 'branch_code',
    ]
    list_filter   = ['supplier_category', 'branch_code']
    search_fields = ['item_code', 'item_name', 'supplier_code', 'supplier_name', 'doc_number']
    date_hierarchy = 'doc_date'

    def has_add_permission(self, request):
        return False  # mirror rows come only from sync_purchase_expiry

    def has_change_permission(self, request, obj=None):
        return False  # immutable historical facts


@admin.register(PurchaseExpiryAuditRun)
class PurchaseExpiryAuditRunAdmin(admin.ModelAdmin):
    list_display  = [
        'id', 'status', 'window_from', 'window_to', 'branch_scope',
        'suppliers_count', 'lines_fetched', 'lines_upserted', 'started_at', 'finished_at',
    ]
    list_filter   = ['status']
    readonly_fields = [f.name for f in PurchaseExpiryAuditRun._meta.get_fields() if hasattr(f, 'name')]
