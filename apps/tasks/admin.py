from django.contrib import admin
from .models import (
    OperationalTask, TaskAssignment, TaskItem,
    TaskMessage, TaskAttachment, TaskSchedule, TaskAuditLog,
)


class TaskAssignmentInline(admin.TabularInline):
    model = TaskAssignment
    extra = 0
    fields = ('staff', 'role', 'is_completed', 'assigned_at')
    readonly_fields = ('assigned_at',)


class TaskItemInline(admin.TabularInline):
    model = TaskItem
    extra = 0
    fields = ('item_name', 'item_code', 'quantity_expected', 'quantity_actual', 'is_checked')


class TaskMessageInline(admin.TabularInline):
    model = TaskMessage
    extra = 0
    fields = ('author', 'message_type', 'body', 'created_at', 'is_deleted')
    readonly_fields = ('created_at',)


@admin.register(OperationalTask)
class OperationalTaskAdmin(admin.ModelAdmin):
    list_display = (
        'task_number', 'title', 'task_type', 'priority', 'status',
        'branch', 'assigned_to', 'due_date', 'created_at',
    )
    list_filter = ('status', 'priority', 'task_type', 'category', 'branch')
    search_fields = ('task_number', 'title', 'tags')
    ordering = ('-created_at',)
    readonly_fields = ('task_number', 'created_at', 'updated_at')
    inlines = [TaskAssignmentInline, TaskItemInline, TaskMessageInline]
    date_hierarchy = 'created_at'

    fieldsets = (
        ('المهمة', {
            'fields': ('task_number', 'title', 'description', 'task_type', 'category', 'priority', 'status'),
        }),
        ('الفرع والتعيين', {
            'fields': ('branch', 'assigned_to', 'created_by', 'completed_by'),
        }),
        ('الجدول الزمني', {
            'fields': ('start_date', 'due_date', 'estimated_hours', 'actual_hours',
                       'completed_at', 'completion_notes'),
        }),
        ('التكرار والروابط', {
            'fields': ('recurrence', 'schedule', 'parent_task', 'related_model', 'related_id', 'tags'),
            'classes': ('collapse',),
        }),
        ('الطوابع الزمنية', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )


@admin.register(TaskSchedule)
class TaskScheduleAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'task_type', 'frequency', 'branch',
        'assign_to', 'is_active', 'last_run_at', 'next_run_at',
    )
    list_filter = ('frequency', 'task_type', 'is_active', 'branch')
    search_fields = ('name', 'title_template')
    readonly_fields = ('last_run_at', 'next_run_at', 'created_at', 'updated_at')


@admin.register(TaskAuditLog)
class TaskAuditLogAdmin(admin.ModelAdmin):
    list_display = ('task', 'action', 'actor', 'field_name', 'created_at')
    list_filter = ('action',)
    readonly_fields = ('task', 'action', 'actor', 'field_name', 'old_value', 'new_value', 'created_at')
    ordering = ('-created_at',)
