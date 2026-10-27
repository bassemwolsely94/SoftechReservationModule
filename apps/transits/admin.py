from django.contrib import admin
from .models import (
    InTransitAuditEvent, InTransitNote, InTransitTransfer,
    ItemPickOverride, PickZone, PickZoneRule,
)


@admin.register(PickZone)
class PickZoneAdmin(admin.ModelAdmin):
    list_display = ['sort_key', 'name', 'location', 'is_active',
                    'is_price_zone', 'is_fridge_zone', 'is_fallback']
    list_display_links = ['name']
    list_editable = ['location', 'is_active']
    ordering = ['sort_key']


@admin.register(PickZoneRule)
class PickZoneRuleAdmin(admin.ModelAdmin):
    list_display = ['priority', 'zone', 'keywords', 'is_active', 'note']
    list_display_links = ['priority']
    list_filter  = ['zone', 'is_active']
    ordering = ['priority']


@admin.register(ItemPickOverride)
class ItemPickOverrideAdmin(admin.ModelAdmin):
    list_display = ['item', 'zone', 'tag', 'created_by', 'updated_at']
    search_fields = ['item__name', 'item__softech_id', 'tag']
    list_filter  = ['zone']
    raw_id_fields = ['item']


@admin.register(InTransitTransfer)
class InTransitTransferAdmin(admin.ModelAdmin):
    list_display = [
        'erp_doc_number', 'erp_supplying_branch_code', 'erp_receiving_branch_code',
        'issue_date', 'days_in_transit', 'transit_status', 'priority',
        'doc_value', 'item_count', 'cancellation_available', 'last_synced_at',
    ]
    list_filter  = ['transit_status', 'priority', 'cancellation_available',
                    'supplying_branch', 'receiving_branch']
    search_fields = ['erp_doc_number', 'erp_supplying_branch_code', 'erp_receiving_branch_code']
    readonly_fields = [
        'erp_doc_number', 'erp_doc_code', 'erp_supplying_branch_code',
        'erp_receiving_branch_code', 'erp_user_code', 'erp_store_code',
        'issue_date', 'erp_received_date', 'days_in_transit',
        'item_count', 'total_quantity', 'items_snapshot',
        'first_seen_at', 'last_synced_at', 'updated_at',
        'alert_notification_count', 'last_alert_sent_at', 'last_alert_level',
    ]
    date_hierarchy = 'issue_date'
    ordering = ['-issue_date']


@admin.register(InTransitNote)
class InTransitNoteAdmin(admin.ModelAdmin):
    list_display = ['transfer', 'note_type', 'body', 'created_by', 'created_at']
    list_filter  = ['note_type']
    readonly_fields = ['created_at']


@admin.register(InTransitAuditEvent)
class InTransitAuditEventAdmin(admin.ModelAdmin):
    list_display = ['transfer', 'action', 'actor', 'detail', 'created_at']
    list_filter  = ['action']
    readonly_fields = ['created_at']
