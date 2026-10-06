"""
apps/tasks/serializers.py
"""
from rest_framework import serializers
from django.utils import timezone
from .models import (
    OperationalTask, TaskAssignment, TaskItem,
    TaskMessage, TaskAttachment, TaskSchedule, TaskAuditLog,
)


# ── Nested light serializers ───────────────────────────────────────────────────

class StaffMiniSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    display_name = serializers.CharField(source='full_name')
    role = serializers.CharField()
    branch_name = serializers.SerializerMethodField()

    def get_branch_name(self, obj):
        return getattr(obj.branch, 'name', None)


class BranchMiniSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    name_ar = serializers.CharField()


# ── TaskAttachment ─────────────────────────────────────────────────────────────

class TaskAttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    uploaded_by_name = serializers.SerializerMethodField()

    class Meta:
        model = TaskAttachment
        fields = [
            'id', 'file_url', 'file_name', 'file_type', 'file_size',
            'uploaded_by_name', 'uploaded_at',
        ]

    def get_file_url(self, obj):
        req = self.context.get('request')
        if req and obj.file:
            return req.build_absolute_uri(obj.file.url)
        return obj.file.url if obj.file else None

    def get_uploaded_by_name(self, obj):
        return obj.uploaded_by.full_name if obj.uploaded_by else None


# ── TaskMessage ────────────────────────────────────────────────────────────────

class TaskMessageSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    author_role = serializers.SerializerMethodField()

    class Meta:
        model = TaskMessage
        fields = [
            'id', 'message_type', 'body',
            'author_name', 'author_role', 'created_at', 'is_deleted',
        ]

    def get_author_name(self, obj):
        return obj.author.full_name if obj.author else 'النظام'

    def get_author_role(self, obj):
        return obj.author.get_role_display() if obj.author else None


# ── TaskItem ───────────────────────────────────────────────────────────────────

class TaskItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskItem
        fields = [
            'id', 'item', 'item_name', 'item_code',
            'quantity_expected', 'quantity_actual', 'unit',
            'notes', 'is_checked', 'checked_at', 'sort_order',
        ]
        read_only_fields = ['checked_at']


# ── TaskAssignment ─────────────────────────────────────────────────────────────

class TaskAssignmentSerializer(serializers.ModelSerializer):
    staff_name = serializers.SerializerMethodField()
    staff_role = serializers.SerializerMethodField()

    class Meta:
        model = TaskAssignment
        fields = [
            'id', 'staff', 'staff_name', 'staff_role',
            'role', 'assigned_at', 'is_completed', 'completed_at',
        ]
        read_only_fields = ['assigned_at', 'completed_at']

    def get_staff_name(self, obj):
        return obj.staff.full_name if obj.staff else None

    def get_staff_role(self, obj):
        return obj.staff.get_role_display() if obj.staff else None


# ── TaskAuditLog ───────────────────────────────────────────────────────────────

class TaskAuditLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = TaskAuditLog
        fields = ['id', 'action', 'actor_name', 'field_name', 'old_value', 'new_value', 'created_at']

    def get_actor_name(self, obj):
        return obj.actor.full_name if obj.actor else 'النظام'


# ── OperationalTask (list) ─────────────────────────────────────────────────────

class TaskListSerializer(serializers.ModelSerializer):
    assigned_to_name = serializers.SerializerMethodField()
    branch_name = serializers.SerializerMethodField()
    is_overdue = serializers.BooleanField(read_only=True)
    subtask_count = serializers.IntegerField(read_only=True, default=0)
    item_count = serializers.IntegerField(read_only=True, default=0)
    unread_messages = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = OperationalTask
        fields = [
            'id', 'task_number', 'title', 'task_type', 'category',
            'priority', 'status',
            'assigned_to', 'assigned_to_name',
            'branch', 'branch_name',
            'due_date', 'created_at', 'updated_at',
            'is_overdue', 'subtask_count', 'item_count', 'unread_messages',
            'tags',
        ]

    def get_assigned_to_name(self, obj):
        return obj.assigned_to.full_name if obj.assigned_to else None

    def get_branch_name(self, obj):
        return obj.branch.name if obj.branch else None


# ── OperationalTask (detail) ───────────────────────────────────────────────────

class TaskDetailSerializer(serializers.ModelSerializer):
    assigned_to_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    completed_by_name = serializers.SerializerMethodField()
    branch_name = serializers.SerializerMethodField()
    is_overdue = serializers.BooleanField(read_only=True)
    tags_list = serializers.ListField(read_only=True)

    messages = serializers.SerializerMethodField()
    assignments = TaskAssignmentSerializer(many=True, read_only=True)
    items = TaskItemSerializer(many=True, read_only=True)
    attachments = TaskAttachmentSerializer(many=True, read_only=True)
    audit_logs = TaskAuditLogSerializer(many=True, read_only=True)
    subtask_count = serializers.SerializerMethodField()

    class Meta:
        model = OperationalTask
        fields = [
            'id', 'task_number', 'title', 'description',
            'task_type', 'category', 'priority', 'status',
            'branch', 'branch_name',
            'assigned_to', 'assigned_to_name',
            'created_by', 'created_by_name',
            'completed_by', 'completed_by_name',
            'parent_task',
            'related_model', 'related_id',
            'due_date', 'start_date', 'estimated_hours', 'actual_hours',
            'completed_at', 'completion_notes',
            'recurrence', 'tags', 'tags_list',
            'created_at', 'updated_at', 'is_overdue',
            'messages', 'assignments', 'items', 'attachments',
            'audit_logs', 'subtask_count',
        ]

    def get_assigned_to_name(self, obj):
        return obj.assigned_to.full_name if obj.assigned_to else None

    def get_created_by_name(self, obj):
        return obj.created_by.full_name if obj.created_by else None

    def get_completed_by_name(self, obj):
        return obj.completed_by.full_name if obj.completed_by else None

    def get_branch_name(self, obj):
        return obj.branch.name if obj.branch else None

    def get_messages(self, obj):
        msgs = obj.messages.filter(is_deleted=False).order_by('created_at')
        return TaskMessageSerializer(msgs, many=True, context=self.context).data

    def get_subtask_count(self, obj):
        return obj.subtasks.count()


# ── Write serializer ───────────────────────────────────────────────────────────

class TaskWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = OperationalTask
        fields = [
            'title', 'description', 'task_type', 'category', 'priority', 'status',
            'branch', 'assigned_to', 'parent_task',
            'related_model', 'related_id',
            'due_date', 'start_date', 'estimated_hours', 'actual_hours',
            'completion_notes', 'recurrence', 'tags',
        ]

    def validate_status(self, value):
        if value == 'completed':
            raise serializers.ValidationError(
                'استخدم endpoint الإكمال لإغلاق المهمة'
            )
        return value


# ── TaskSchedule ───────────────────────────────────────────────────────────────

class TaskScheduleSerializer(serializers.ModelSerializer):
    branch_name = serializers.SerializerMethodField()
    assign_to_name = serializers.SerializerMethodField()
    generated_count = serializers.SerializerMethodField()

    class Meta:
        model = TaskSchedule
        fields = [
            'id', 'name', 'task_type', 'category', 'priority',
            'title_template', 'description_template',
            'branch', 'branch_name',
            'assign_to', 'assign_to_name', 'assign_to_role',
            'frequency', 'day_of_week', 'day_of_month', 'time_of_day',
            'advance_days', 'estimated_hours',
            'is_active', 'last_run_at', 'next_run_at',
            'created_at', 'updated_at', 'generated_count',
        ]
        read_only_fields = ['last_run_at', 'next_run_at', 'created_at', 'updated_at']

    def get_branch_name(self, obj):
        return obj.branch.name if obj.branch else 'جميع الفروع'

    def get_assign_to_name(self, obj):
        return obj.assign_to.full_name if obj.assign_to else None

    def get_generated_count(self, obj):
        return obj.generated_tasks.count()
