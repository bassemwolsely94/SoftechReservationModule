from django.contrib import admin

from .models import RefillReminder, RefillReminderOptOut


@admin.register(RefillReminder)
class RefillReminderAdmin(admin.ModelAdmin):
    list_display = ['id', 'task', 'customer', 'branch', 'due_date', 'status', 'reply_choice', 'sent_at']
    list_filter = ['status', 'reply_choice', 'branch']
    search_fields = ['customer__name', 'customer__softech_pic', 'phone']
    raw_id_fields = ['task', 'customer', 'reservation']
    readonly_fields = ['wamid', 'sent_at', 'replied_at', 'created_at']


@admin.register(RefillReminderOptOut)
class RefillReminderOptOutAdmin(admin.ModelAdmin):
    """Delete a row to resume reminders — only when the customer asks for it."""
    list_display = ['customer', 'source', 'created_at']
    search_fields = ['customer__name', 'customer__softech_pic']
    raw_id_fields = ['customer']
