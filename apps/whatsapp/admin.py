from django.contrib import admin
from apps.whatsapp.models import (
    WATemplate, WAConversation, WAMessage,
    WAMediaFile, WAWebhookLog, WAMessageQueue,
)


@admin.register(WATemplate)
class WATemplateAdmin(admin.ModelAdmin):
    list_display  = ['name', 'language', 'category', 'status', 'created_at']
    list_filter   = ['status', 'category', 'language']
    search_fields = ['name', 'body_text']


class WAMessageInline(admin.TabularInline):
    model         = WAMessage
    extra         = 0
    readonly_fields = ['direction', 'message_type', 'status', 'wamid', 'body', 'created_at']
    can_delete    = False


@admin.register(WAConversation)
class WAConversationAdmin(admin.ModelAdmin):
    list_display   = ['wa_id', 'customer', 'status', 'assigned_to',
                      'last_message_at', 'unread_count', 'window_open']
    list_filter    = ['status']
    search_fields  = ['wa_id', 'customer__name', 'customer__phone']
    raw_id_fields  = ['customer', 'assigned_to']
    inlines        = [WAMessageInline]
    readonly_fields = ['window_open', 'window_expires_at']


@admin.register(WAWebhookLog)
class WAWebhookLogAdmin(admin.ModelAdmin):
    list_display  = ['received_at', 'object_type', 'entry_id', 'processed', 'processing_error']
    list_filter   = ['processed', 'object_type']
    readonly_fields = ['received_at', 'payload', 'object_type', 'entry_id',
                       'phone_number_id', 'processed', 'processing_error', 'wa_message']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(WAMessageQueue)
class WAMessageQueueAdmin(admin.ModelAdmin):
    list_display = ['conversation', 'priority', 'status', 'attempts', 'next_attempt_at']
    list_filter  = ['status', 'priority']
