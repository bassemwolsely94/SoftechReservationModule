from django.contrib import admin

from apps.omni.models import (
    AutomationRule, AutomationRun, ChannelAccount, Conversation, TimelineEvent,
)


@admin.register(ChannelAccount)
class ChannelAccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'channel', 'phone_or_handle', 'provider', 'branch', 'status', 'is_active')
    list_filter = ('channel', 'provider', 'status', 'is_active')
    search_fields = ('name', 'phone_or_handle')


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'contact_phone', 'status', 'priority',
                    'assigned_to', 'created_from_channel', 'last_activity_at')
    list_filter = ('status', 'priority', 'created_from_channel')
    search_fields = ('contact_phone', 'customer__name', 'customer__phone', 'subject')
    raw_id_fields = ('customer', 'assigned_to', 'branch')


@admin.register(TimelineEvent)
class TimelineEventAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversation', 'event_type', 'channel', 'summary', 'actor', 'occurred_at')
    list_filter = ('event_type', 'channel')
    search_fields = ('summary',)
    raw_id_fields = ('conversation', 'actor', 'account')

    def has_change_permission(self, request, obj=None):
        return False  # append-only

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AutomationRule)
class AutomationRuleAdmin(admin.ModelAdmin):
    list_display = ('name', 'trigger', 'is_active', 'order', 'run_count', 'last_run_at')
    list_filter = ('trigger', 'is_active')
    search_fields = ('name',)


@admin.register(AutomationRun)
class AutomationRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'rule', 'conversation', 'matched', 'created_at')
    list_filter = ('matched', 'rule')
    raw_id_fields = ('rule', 'event', 'conversation')

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
