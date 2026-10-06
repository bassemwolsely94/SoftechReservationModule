from django.contrib import admin
from .models import (
    LeaveType, LeaveBalance, LeaveRequest,
    ShiftTemplate, ShiftAssignment,
    OvertimeRequest, SalaryAdvance, ExpenseClaim,
    Permit,
)


@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display  = ['code', 'name_ar', 'is_paid', 'accrues_balance',
                     'max_days_per_year', 'max_days_per_request', 'is_active']
    list_filter   = ['is_paid', 'accrues_balance', 'is_active']
    search_fields = ['code', 'name', 'name_ar']


@admin.register(LeaveBalance)
class LeaveBalanceAdmin(admin.ModelAdmin):
    list_display  = ['staff', 'leave_type', 'year', 'entitled_days',
                     'consumed_days', 'carried_forward', 'remaining_days']
    list_filter   = ['year', 'leave_type']
    search_fields = ['staff__user__first_name', 'staff__user__last_name']
    readonly_fields = ['remaining_days']

    def remaining_days(self, obj):
        return obj.remaining_days
    remaining_days.short_description = 'متبقي'


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display  = ['staff', 'leave_type', 'start_date', 'end_date',
                     'days_requested', 'status', 'created_at']
    list_filter   = ['status', 'leave_type']
    search_fields = ['staff__user__first_name', 'staff__user__last_name']
    readonly_fields = ['approval_request', 'created_at', 'updated_at']


@admin.register(ShiftTemplate)
class ShiftTemplateAdmin(admin.ModelAdmin):
    list_display  = ['name_ar', 'branch', 'start_time', 'end_time', 'days_of_week', 'is_active']
    list_filter   = ['is_active', 'branch']


@admin.register(ShiftAssignment)
class ShiftAssignmentAdmin(admin.ModelAdmin):
    list_display  = ['staff', 'shift', 'valid_from', 'valid_until', 'assigned_by']
    list_filter   = ['shift']
    search_fields = ['staff__user__first_name', 'staff__user__last_name']


@admin.register(OvertimeRequest)
class OvertimeRequestAdmin(admin.ModelAdmin):
    list_display  = ['staff', 'branch', 'date', 'hours', 'status', 'created_at']
    list_filter   = ['status', 'branch']
    readonly_fields = ['approval_request', 'created_at']


@admin.register(SalaryAdvance)
class SalaryAdvanceAdmin(admin.ModelAdmin):
    list_display  = ['staff', 'amount', 'repayment_date', 'status', 'finance_record_id', 'created_at']
    list_filter   = ['status']
    readonly_fields = ['approval_request', 'finance_record_id', 'settled_at', 'created_at']


@admin.register(ExpenseClaim)
class ExpenseClaimAdmin(admin.ModelAdmin):
    list_display  = ['staff', 'branch', 'category', 'expense_date', 'amount',
                     'allowance_amount', 'status', 'created_at']
    list_filter   = ['status', 'category', 'branch']
    search_fields = ['staff__user__first_name', 'staff__user__last_name']
    readonly_fields = ['approval_request', 'finance_record_id', 'paid_at', 'created_at']


@admin.register(Permit)
class PermitAdmin(admin.ModelAdmin):
    list_display  = ['staff', 'permit_type', 'branch', 'date', 'time_from', 'time_to', 'status', 'created_at']
    list_filter   = ['permit_type', 'status', 'branch']
    search_fields = ['staff__user__first_name', 'staff__user__last_name', 'destination']
    readonly_fields = ['approval_request', 'created_at', 'updated_at']
