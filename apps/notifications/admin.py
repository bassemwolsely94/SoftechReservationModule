from django.contrib import admin
from .models import Notification, NotificationLog, ChatterMessage, PushSubscription


# ── Notification ──────────────────────────────────────────────────────────────

class NotificationLogInline(admin.TabularInline):
    model           = NotificationLog
    extra           = 0
    readonly_fields = ('delivered_at', 'read_at', 'recipient')
    can_delete      = False
    verbose_name    = 'سجل تسليم'


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display        = ['id', 'recipient', 'notification_type', 'title', 'priority', 'is_read', 'created_at']
    list_filter         = ['notification_type', 'is_read', 'priority', 'created_at']
    search_fields       = ['title', 'body', 'recipient__user__username']
    readonly_fields     = ['created_at']
    ordering            = ['-created_at']
    list_select_related = ['recipient__user']
    inlines             = [NotificationLogInline]

    actions = ['mark_as_read', 'mark_as_unread']

    @admin.action(description='تعليم المحدد كمقروء')
    def mark_as_read(self, request, queryset):
        queryset.update(is_read=True)

    @admin.action(description='تعليم المحدد كغير مقروء')
    def mark_as_unread(self, request, queryset):
        queryset.update(is_read=False)


# ── Notification Log ──────────────────────────────────────────────────────────

@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display        = ['id', 'recipient', 'notification', 'delivered_at', 'read_at']
    list_filter         = ['delivered_at']
    search_fields       = ['recipient__user__username', 'notification__title']
    readonly_fields     = ['delivered_at']
    ordering            = ['-delivered_at']
    list_select_related = ['recipient__user', 'notification']


# ── Chatter ───────────────────────────────────────────────────────────────────

@admin.register(ChatterMessage)
class ChatterMessageAdmin(admin.ModelAdmin):
    list_display        = ['id', 'author', 'model_name', 'record_id', 'created_at',
                           'message_preview']
    list_filter         = ['model_name', 'created_at']
    search_fields       = ['message', 'author__user__username']
    readonly_fields     = ['created_at']
    ordering            = ['-created_at']
    list_select_related = ['author__user']

    @admin.display(description='الرسالة')
    def message_preview(self, obj):
        return obj.message[:80] + ('…' if len(obj.message) > 80 else '')


# ── Web Push subscriptions ──────────────────────────────────────────────────────

@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display        = ['id', 'recipient', 'user_agent', 'created_at']
    search_fields       = ['recipient__user__username', 'endpoint', 'user_agent']
    readonly_fields     = ['created_at', 'endpoint', 'p256dh', 'auth']
    ordering            = ['-created_at']
    list_select_related = ['recipient__user']
