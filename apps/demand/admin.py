from django.contrib import admin
from .models import DemandRecord, DemandItem, DemandFollowUp, DemandLog, ItemDemandStat


class DemandItemInline(admin.TabularInline):
    model = DemandItem
    extra = 0
    raw_id_fields = ['item']
    fields = ['item', 'item_name_free', 'quantity', 'demand_type', 'item_status',
              'is_long_shortage', 'is_discontinued',
              'unit_price_snapshot', 'back_in_stock_at', 'recovered_revenue',
              'disqualified', 'contact_opt_out']
    readonly_fields = ['unit_price_snapshot', 'back_in_stock_at', 'recovered_revenue']


class FollowUpInline(admin.TabularInline):
    model = DemandFollowUp
    extra = 0
    readonly_fields = ['created_at', 'completed_at']
    fields = ['task_type', 'due_date', 'status', 'assigned_to', 'note',
              'completed_at', 'completed_by']


class DemandLogInline(admin.TabularInline):
    model = DemandLog
    extra = 0
    readonly_fields = ['created_at', 'log_type', 'created_by']
    fields = ['log_type', 'message', 'call_outcome', 'created_by', 'created_at']
    can_delete = False


@admin.register(DemandRecord)
class DemandRecordAdmin(admin.ModelAdmin):
    list_display = [
        'demand_number', 'customer_name', 'phone', 'phcode',
        'branch', 'status', 'priority', 'source', 'created_at',
    ]
    list_filter  = ['status', 'priority', 'source', 'branch']
    search_fields = ['demand_number', 'phone', 'customer_name', 'phcode']
    readonly_fields = ['demand_number', 'created_at', 'updated_at', 'fulfilled_at', 'assigned_at']
    inlines = [DemandItemInline, FollowUpInline, DemandLogInline]
    ordering = ['-created_at']
    raw_id_fields = ['customer', 'assigned_to', 'created_by']


@admin.register(DemandItem)
class DemandItemAdmin(admin.ModelAdmin):
    """Recovery-queue audit surface (Phase 1)."""
    list_display = [
        'id', 'demand', 'item', 'item_name_free', 'quantity', 'item_status',
        'back_in_stock_at', 'notified_customer_at', 'recovered_revenue',
        'disqualified', 'contact_opt_out',
    ]
    list_filter  = ['item_status', 'disqualified', 'contact_opt_out',
                    'disqualified_reason', 'contact_opt_out_reason']
    search_fields = ['demand__demand_number', 'demand__phone', 'item__name', 'item__softech_id']
    raw_id_fields = ['demand', 'item', 'disqualified_by', 'reservation']
    readonly_fields = ['unit_price_snapshot', 'cost_price_snapshot', 'price_snapshot_at',
                       'back_in_stock_at', 'recovered_at']
    ordering = ['-back_in_stock_at']


@admin.register(ItemDemandStat)
class ItemDemandStatAdmin(admin.ModelAdmin):
    list_display = [
        'item', 'branch', 'demand_count_30d', 'lost_count_30d',
        'is_long_shortage', 'suggest_order', 'last_updated',
    ]
    list_filter = ['is_long_shortage', 'is_discontinued', 'suggest_order']
    search_fields = ['item__name', 'item__softech_id']
