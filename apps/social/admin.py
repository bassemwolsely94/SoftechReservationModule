from django.contrib import admin

from apps.social.models import SocialMessage, SocialThread, SocialWebhookLog


@admin.register(SocialThread)
class SocialThreadAdmin(admin.ModelAdmin):
    list_display = ('id', 'account', 'display_name', 'external_user_id',
                    'last_message_at', 'unread_count')
    list_filter = ('account__channel',)
    search_fields = ('display_name', 'external_user_id')
    raw_id_fields = ('account', 'omni_conversation')


@admin.register(SocialMessage)
class SocialMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'thread', 'direction', 'message_type', 'body', 'status', 'created_at')
    list_filter = ('direction', 'message_type', 'status')
    search_fields = ('body', 'external_id')
    raw_id_fields = ('thread', 'sent_by')


@admin.register(SocialWebhookLog)
class SocialWebhookLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'source', 'processed', 'received_at')
    list_filter = ('source', 'processed')

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
