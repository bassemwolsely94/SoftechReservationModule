from django.contrib import admin

from .models import (
    CashCollection,
    CustomerLocation,
    DeliveryAssignment,
    DeliveryDriver,
    DeliveryOrder,
    DeliveryOrderItem,
    DeliveryStatusLog,
)


@admin.register(DeliveryDriver)
class DeliveryDriverAdmin(admin.ModelAdmin):
    list_display  = ['full_name', 'mobile', 'branch', 'vehicle_type', 'status', 'max_daily_orders']
    list_filter   = ['status', 'vehicle_type', 'branch']
    search_fields = ['full_name', 'mobile', 'national_id']
    raw_id_fields = ['branch', 'staff_profile']


class CustomerLocationInline(admin.TabularInline):
    model  = CustomerLocation
    extra  = 0
    fields = ['label', 'is_default', 'address_line', 'area', 'governorate', 'latitude', 'longitude']


@admin.register(CustomerLocation)
class CustomerLocationAdmin(admin.ModelAdmin):
    list_display  = ['customer', 'label', 'is_default', 'area', 'governorate', 'location_accuracy']
    list_filter   = ['label', 'is_default', 'location_accuracy', 'governorate']
    search_fields = ['customer__name', 'address_line', 'area']
    raw_id_fields = ['customer']


class DeliveryOrderItemInline(admin.TabularInline):
    model  = DeliveryOrderItem
    extra  = 0
    fields = ['item_name', 'item_code', 'quantity', 'unit_price', 'line_total', 'delivered_quantity']


class DeliveryStatusLogInline(admin.TabularInline):
    model          = DeliveryStatusLog
    extra          = 0
    readonly_fields = ['from_status', 'to_status', 'source', 'notes', 'recorded_by', 'recorded_at']
    can_delete     = False

    def has_add_permission(self, request, obj=None):
        return False


class DeliveryAssignmentInline(admin.TabularInline):
    model          = DeliveryAssignment
    extra          = 0
    readonly_fields = ['assigned_at', 'assigned_by']
    fields         = ['driver', 'driver_name', 'vehicle', 'is_current', 'assigned_by', 'assigned_at', 'notes']


@admin.register(DeliveryOrder)
class DeliveryOrderAdmin(admin.ModelAdmin):
    list_display  = [
        'order_number', 'source_type', 'branch', 'customer_name',
        'customer_phone', 'status', 'assigned_driver', 'ordered_at', 'is_late',
    ]
    list_filter   = ['status', 'source_type', 'branch', 'payment_method']
    search_fields = ['order_number', 'customer_name', 'customer_phone', 'softech_doc_ref']
    raw_id_fields = ['branch', 'customer', 'assigned_driver', 'location', 'created_by']
    readonly_fields = ['order_number', 'created_at', 'updated_at']
    inlines       = [DeliveryOrderItemInline, DeliveryAssignmentInline, DeliveryStatusLogInline]

    def is_late(self, obj):
        return obj.is_late
    is_late.boolean = True
    is_late.short_description = 'متأخر'


@admin.register(CashCollection)
class CashCollectionAdmin(admin.ModelAdmin):
    list_display  = ['order', 'expected_amount', 'collected_amount', 'shortage_amount', 'overage_amount', 'status']
    list_filter   = ['status']
    raw_id_fields = ['order', 'collected_by']
    readonly_fields = ['shortage_amount', 'overage_amount', 'created_at', 'updated_at']
