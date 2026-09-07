from rest_framework import serializers
from .models import (
    ApprovalWorkflowDefinition, ApprovalStepDefinition,
    ApprovalRequest, ApprovalDecision, ApprovalEscalationLog,
)


class ApprovalStepDefinitionSerializer(serializers.ModelSerializer):
    approver_role_display = serializers.CharField(source='get_approver_role_display', read_only=True)
    approver_user_name    = serializers.CharField(source='approver_user.full_name', read_only=True)
    on_reject_display     = serializers.CharField(source='get_on_reject_display', read_only=True)

    class Meta:
        model  = ApprovalStepDefinition
        fields = [
            'id', 'order', 'name', 'name_ar',
            'approver_role', 'approver_role_display',
            'approver_user', 'approver_user_name',
            'restrict_to_branch', 'is_optional',
            'escalation_hours', 'on_reject', 'on_reject_display',
        ]


class ApprovalWorkflowDefinitionSerializer(serializers.ModelSerializer):
    steps = ApprovalStepDefinitionSerializer(many=True, read_only=True)

    class Meta:
        model  = ApprovalWorkflowDefinition
        fields = [
            'id', 'code', 'name', 'name_ar', 'description',
            'is_active', 'reject_terminates', 'sla_hours', 'steps',
        ]


class ApprovalDecisionSerializer(serializers.ModelSerializer):
    decided_by_name  = serializers.CharField(source='decided_by.full_name', read_only=True)
    delegated_to_name = serializers.CharField(source='delegated_to.full_name', read_only=True)
    decision_display  = serializers.CharField(source='get_decision_display', read_only=True)

    class Meta:
        model  = ApprovalDecision
        fields = [
            'id', 'step_order', 'step_name',
            'decision', 'decision_display',
            'decided_by', 'decided_by_name',
            'decided_at', 'notes',
            'delegated_to', 'delegated_to_name',
        ]


class ApprovalEscalationLogSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ApprovalEscalationLog
        fields = ['id', 'step_order', 'escalated_at', 'notified_users', 'note']


class ApprovalRequestSerializer(serializers.ModelSerializer):
    status_display          = serializers.CharField(source='get_status_display', read_only=True)
    workflow_name           = serializers.CharField(source='workflow.name_ar', read_only=True)
    requested_by_name       = serializers.CharField(source='requested_by.full_name', read_only=True)
    requested_by_branch     = serializers.CharField(source='requested_by.branch_name', read_only=True)
    current_step_name       = serializers.SerializerMethodField()
    decisions               = ApprovalDecisionSerializer(many=True, read_only=True)
    escalations             = ApprovalEscalationLogSerializer(many=True, read_only=True)
    subject_type            = serializers.SerializerMethodField()

    class Meta:
        model  = ApprovalRequest
        fields = [
            'id', 'workflow', 'workflow_name',
            'title', 'body', 'context_data',
            'status', 'status_display',
            'current_step_order', 'current_step_name',
            'requested_by', 'requested_by_name', 'requested_by_branch',
            'requested_at', 'due_at', 'is_overdue',
            'completed_at', 'completion_note',
            'subject_type', 'object_id',
            'decisions', 'escalations',
        ]
        read_only_fields = fields

    def get_current_step_name(self, obj):
        step = obj.current_step
        return step.name_ar if step else None

    def get_subject_type(self, obj):
        if obj.content_type:
            return obj.content_type.model
        return None


class ApprovalRequestListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""
    status_display      = serializers.CharField(source='get_status_display', read_only=True)
    workflow_name       = serializers.CharField(source='workflow.name_ar', read_only=True)
    workflow_category   = serializers.CharField(source='workflow.category', read_only=True)
    requested_by_name   = serializers.CharField(source='requested_by.full_name', read_only=True)
    requested_by_branch = serializers.CharField(source='requested_by.branch_name', read_only=True)
    current_step_name   = serializers.SerializerMethodField()

    class Meta:
        model  = ApprovalRequest
        fields = [
            'id', 'workflow', 'workflow_name', 'workflow_category',
            'title', 'body', 'context_data',
            'status', 'status_display',
            'current_step_order', 'current_step_name',
            'requested_by_name', 'requested_by_branch',
            'requested_at', 'due_at', 'is_overdue',
        ]

    def get_current_step_name(self, obj):
        step = obj.current_step
        return step.name_ar if step else None


class DecideSerializer(serializers.Serializer):
    decision     = serializers.ChoiceField(choices=ApprovalDecision.DECISION_CHOICES)
    notes        = serializers.CharField(required=False, allow_blank=True, default='')
    delegated_to = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, data):
        if data.get('decision') == ApprovalDecision.DECISION_DELEGATED and not data.get('delegated_to'):
            raise serializers.ValidationError({'delegated_to': 'مطلوب عند التفويض.'})
        return data


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default='')
