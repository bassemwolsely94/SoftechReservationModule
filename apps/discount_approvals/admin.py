from django.contrib import admin
from .models import ItemPriceChangeRequest


@admin.register(ItemPriceChangeRequest)
class ItemPriceChangeRequestAdmin(admin.ModelAdmin):
    list_display  = ['id', 'item', 'requested_by', 'status', 'requested_at', 'reviewed_by']
    list_filter   = ['status', 'requested_at']
    search_fields = ['item__name', 'item__softech_id', 'requested_by__username']
    readonly_fields = [
        'requested_by', 'requested_at', 'old_values',
        'reviewed_by', 'reviewed_at',
        'erp_executed_at', 'erp_usercode', 'erp_error',
    ]

from .models import ReplicationScan, ReplicationGap, ReplicationPolicy


@admin.register(ReplicationScan)
class ReplicationScanAdmin(admin.ModelAdmin):
    list_display = ['id', 'started_at', 'days_window', 'status', 'items_checked', 'items_with_gaps', 'is_scheduled']
    list_filter = ['status', 'is_scheduled']


@admin.register(ReplicationGap)
class ReplicationGapAdmin(admin.ModelAdmin):
    list_display = ['item_softech_id', 'branch_code', 'status', 'source_channel', 'source_user']
    list_filter = ['status', 'source_channel', 'branch_code']
    search_fields = ['item_softech_id', 'item_name']


@admin.register(ReplicationPolicy)
class ReplicationPolicyAdmin(admin.ModelAdmin):
    list_display = ['id', 'auto_repair_enabled', 'max_items_per_run', 'weekly_full_audit', 'updated_at']
