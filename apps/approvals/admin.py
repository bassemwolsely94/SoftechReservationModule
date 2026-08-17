from django.contrib import admin
from .models import (
    ApprovalWorkflowDefinition, ApprovalStepDefinition,
    ApprovalRequest, ApprovalDecision, ApprovalEscalationLog,
)


class ApprovalStepInline(admin.TabularInline):
    model  = ApprovalStepDefinition
    extra  = 1
    fields = [
        'order', 'name_ar', 'approver_role', 'approver_user',
        'restrict_to_branch', 'is_optional', 'escalation_hours', 'on_reject',
    ]
    ordering = ['order']


@admin.register(ApprovalWorkflowDefinition)
class ApprovalWorkflowDefinitionAdmin(admin.ModelAdmin):
    list_display  = ['code', 'name_ar', 'is_active', 'reject_terminates', 'sla_hours']
    list_filter   = ['is_active']
    search_fields = ['code', 'name', 'name_ar']
    inlines       = [ApprovalStepInline]


class ApprovalDecisionInline(admin.TabularInline):
    model          = ApprovalDecision
    extra          = 0
    readonly_fields = ['step_order', 'step_name', 'decision', 'decided_by', 'decided_at', 'notes']
    can_delete     = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    list_display   = ['title', 'workflow', 'status', 'requested_by', 'requested_at', 'is_overdue']
    list_filter    = ['status', 'workflow', 'is_overdue']
    search_fields  = ['title', 'requested_by__user__first_name', 'requested_by__user__last_name']
    readonly_fields = ['content_type', 'object_id', 'context_data', 'requested_at', 'completed_at']
    inlines        = [ApprovalDecisionInline]

    def has_add_permission(self, request):
        return False  # requests are created programmatically via ApprovalService.submit()


@admin.register(ApprovalDecision)
class ApprovalDecisionAdmin(admin.ModelAdmin):
    list_display  = ['request', 'step_order', 'step_name', 'decision', 'decided_by', 'decided_at']
    list_filter   = ['decision']
    readonly_fields = list_display

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ApprovalEscalationLog)
class ApprovalEscalationLogAdmin(admin.ModelAdmin):
    list_display  = ['request', 'step_order', 'escalated_at', 'note']
    readonly_fields = list_display

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
