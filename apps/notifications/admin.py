from django.contrib import admin
from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'recipient', 'notification_type', 'title',
        'is_read', 'created_at',
    ]
    list_filter = ['notification_type', 'is_read', 'created_at']
    search_fields = ['title', 'body', 'recipient__user__username']
    readonly_fields = ['created_at']
    ordering = ['-created_at']
    list_select_related = ['recipient__user']

    actions = ['mark_as_read', 'mark_as_unread']

    @admin.action(description='تعليم المحدد كمقروء')
    def mark_as_read(self, request, queryset):
        queryset.update(is_read=True)

    @admin.action(description='تعليم المحدد كغير مقروء')
    def mark_as_unread(self, request, queryset):
        queryset.update(is_read=False)
