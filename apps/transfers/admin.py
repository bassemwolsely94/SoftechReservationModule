from django.contrib import admin
from .models import TransferRequest, TransferRequestItem, TransferRequestMessage


class TransferRequestItemInline(admin.TabularInline):
    model = TransferRequestItem
    extra = 0
    raw_id_fields = ['item']
    fields = ['item', 'quantity', 'notes']


class TransferRequestMessageInline(admin.TabularInline):
    model = TransferRequestMessage
    extra = 0
    readonly_fields = ['created_at', 'created_by', 'message_type']
    fields = ['message_type', 'message', 'created_by', 'created_at']


@admin.register(TransferRequest)
class TransferRequestAdmin(admin.ModelAdmin):
    list_display = [
        'request_number', 'source_branch', 'destination_branch',
        'status', 'created_by', 'total_items', 'created_at',
    ]
    list_filter  = ['status', 'source_branch', 'destination_branch']
    search_fields = ['request_number', 'notes', 'items__item__name']
    readonly_fields = [
        'request_number', 'created_at', 'updated_at',
        'submitted_at', 'reviewed_at', 'sent_to_erp_at', 'completed_at',
    ]
    inlines = [TransferRequestItemInline, TransferRequestMessageInline]
    ordering = ['-created_at']
