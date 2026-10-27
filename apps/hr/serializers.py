from decimal import Decimal
from rest_framework import serializers

from .models import (
    LeaveType, LeaveBalance, LeaveRequest,
    ShiftTemplate, ShiftAssignment,
    OvertimeRequest, SalaryAdvance, ExpenseClaim,
    Permit,
)


def _staff_code(staff):
    """Employee code (كود رقم) — the SOFTECH user id, falling back to username."""
    if not staff:
        return ''
    return (getattr(staff, 'softech_user_id', '') or getattr(staff, 'softech_username', '') or '').strip()


class StaffCodeMixin(serializers.Serializer):
    """Read-only identity fields shared by every HR request output serializer:
    the SOFTECH staff_code, the submitter, and the requester-nominated approvers."""
    staff_code        = serializers.SerializerMethodField()
    submitted_by_name = serializers.CharField(source='submitted_by.full_name', read_only=True, default=None)
    approver_names    = serializers.SerializerMethodField()

    def get_staff_code(self, obj):
        return _staff_code(getattr(obj, 'staff', None))

    def get_approver_names(self, obj):
        ar = getattr(obj, 'approval_request', None)
        if not ar:
            return []
        return [a.full_name for a in ar.nominated_approvers.all()]


class SubjectFieldsMixin(serializers.Serializer):
    """Write-side subject + approver inputs shared by every HR submit serializer.

    - subject_staff: optional StaffProfile pk the request is *about* (defaults to
      the caller for self-service; omit + fill employee_* for non-login staff).
    - employee_hr_code: HR code (mandatory at the service layer; may be prefilled
      from a linked profile).
    - approver_ids: StaffProfile pks the requester nominates as approvers.
    """
    subject_staff    = serializers.IntegerField(required=False, allow_null=True)
    employee_hr_code = serializers.CharField(required=False, allow_blank=True, default='')
    employee_name    = serializers.CharField(required=False, allow_blank=True, default='')
    softech_code     = serializers.CharField(required=False, allow_blank=True, default='')
    approver_ids     = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list,
    )


# ── Leave ──────────────────────────────────────────────────────────────────────

class LeaveTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model  = LeaveType
        fields = [
            'id', 'code', 'name', 'name_ar', 'is_paid',
            'accrues_balance', 'max_days_per_year', 'max_days_per_request',
            'approval_workflow_code', 'is_active',
        ]


class LeaveBalanceSerializer(serializers.ModelSerializer):
    leave_type_name = serializers.CharField(source='leave_type.name_ar', read_only=True)
    remaining_days  = serializers.DecimalField(max_digits=6, decimal_places=2, read_only=True)

    class Meta:
        model  = LeaveBalance
        fields = [
            'id', 'leave_type', 'leave_type_name', 'year',
            'entitled_days', 'consumed_days', 'carried_forward', 'remaining_days',
        ]


class LeaveRequestSerializer(StaffCodeMixin, serializers.ModelSerializer):
    staff_name      = serializers.CharField(source='staff.full_name', read_only=True)
    leave_type_name = serializers.CharField(source='leave_type.name_ar', read_only=True)
    status_display  = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model  = LeaveRequest
        fields = [
            'id', 'staff', 'staff_name', 'staff_code', 'leave_type', 'leave_type_name',
            'employee_hr_code', 'employee_name', 'submitted_by_name', 'approver_names',
            'start_date', 'end_date', 'return_to_work_date', 'days_requested', 'reason',
            'status', 'status_display', 'approval_request',
            'rejection_reason', 'created_at',
        ]
        read_only_fields = ['status', 'approval_request', 'rejection_reason', 'created_at']


class SubmitLeaveSerializer(SubjectFieldsMixin, serializers.Serializer):
    leave_type_code = serializers.CharField()
    start_date      = serializers.DateField()
    end_date        = serializers.DateField()
    return_to_work_date = serializers.DateField(required=False, allow_null=True)
    days_requested  = serializers.DecimalField(max_digits=5, decimal_places=2)
    reason          = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, data):
        if data['end_date'] < data['start_date']:
            raise serializers.ValidationError({'end_date': 'تاريخ الانتهاء يجب أن يكون بعد تاريخ البدء.'})
        rtw = data.get('return_to_work_date')
        if rtw and rtw <= data['end_date']:
            raise serializers.ValidationError({'return_to_work_date': 'تاريخ العودة يجب أن يكون بعد نهاية الإجازة.'})
        return data


# ── Shift ──────────────────────────────────────────────────────────────────────

class ShiftTemplateSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name_ar', read_only=True)

    class Meta:
        model  = ShiftTemplate
        fields = ['id', 'name', 'name_ar', 'branch', 'branch_name',
                  'start_time', 'end_time', 'days_of_week', 'is_active']


class ShiftAssignmentSerializer(serializers.ModelSerializer):
    staff_name  = serializers.CharField(source='staff.full_name', read_only=True)
    shift_name  = serializers.CharField(source='shift.name_ar', read_only=True)

    class Meta:
        model  = ShiftAssignment
        fields = ['id', 'staff', 'staff_name', 'shift', 'shift_name',
                  'valid_from', 'valid_until', 'assigned_at']
        read_only_fields = ['assigned_at']


# ── Overtime ───────────────────────────────────────────────────────────────────

class OvertimeRequestSerializer(StaffCodeMixin, serializers.ModelSerializer):
    staff_name     = serializers.CharField(source='staff.full_name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model  = OvertimeRequest
        fields = [
            'id', 'staff', 'staff_name', 'staff_code', 'branch', 'date', 'hours',
            'employee_hr_code', 'employee_name', 'submitted_by_name', 'approver_names',
            'reason', 'status', 'status_display', 'approval_request', 'created_at',
        ]
        read_only_fields = ['status', 'approval_request', 'created_at']


class SubmitOvertimeSerializer(SubjectFieldsMixin, serializers.Serializer):
    date   = serializers.DateField()
    hours  = serializers.DecimalField(max_digits=4, decimal_places=2)
    reason = serializers.CharField()

    def validate_hours(self, v):
        if v <= 0 or v > 12:
            raise serializers.ValidationError('الساعات يجب أن تكون بين 0.5 و12.')
        return v


# ── Salary advance ─────────────────────────────────────────────────────────────

class SalaryAdvanceSerializer(StaffCodeMixin, serializers.ModelSerializer):
    staff_name     = serializers.CharField(source='staff.full_name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model  = SalaryAdvance
        fields = [
            'id', 'staff', 'staff_name', 'staff_code', 'amount', 'repayment_date',
            'employee_hr_code', 'employee_name', 'submitted_by_name', 'approver_names',
            'reason', 'status', 'status_display',
            'approval_request', 'finance_record_id', 'settled_at', 'created_at',
        ]
        read_only_fields = ['status', 'approval_request', 'finance_record_id', 'settled_at', 'created_at']


class SubmitAdvanceSerializer(SubjectFieldsMixin, serializers.Serializer):
    amount         = serializers.DecimalField(max_digits=10, decimal_places=2)
    repayment_date = serializers.DateField()
    reason         = serializers.CharField()

    def validate_amount(self, v):
        if v <= 0:
            raise serializers.ValidationError('المبلغ يجب أن يكون أكبر من صفر.')
        return v


# ── Expense claim ──────────────────────────────────────────────────────────────

class ExpenseClaimSerializer(StaffCodeMixin, serializers.ModelSerializer):
    staff_name       = serializers.CharField(source='staff.full_name', read_only=True)
    branch_name      = serializers.CharField(source='branch.name_ar', read_only=True)
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    status_display   = serializers.CharField(source='get_status_display', read_only=True)
    total_amount     = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model  = ExpenseClaim
        fields = [
            'id', 'staff', 'staff_name', 'staff_code',
            'employee_hr_code', 'employee_name', 'submitted_by_name', 'approver_names',
            'branch', 'branch_name',
            'category', 'category_display', 'expense_date', 'amount', 'description',
            'receipt', 'total_amount',
            'trip_destination', 'trip_purpose', 'trip_start', 'trip_end',
            'distance_km', 'transport_type', 'allowance_amount',
            'status', 'status_display', 'approval_request',
            'finance_record_id', 'paid_at', 'rejection_reason', 'created_at',
        ]
        read_only_fields = [
            'status', 'approval_request', 'finance_record_id', 'paid_at', 'created_at',
        ]


class SubmitExpenseClaimSerializer(SubjectFieldsMixin, serializers.Serializer):
    category       = serializers.ChoiceField(choices=ExpenseClaim.CATEGORY_CHOICES)
    expense_date   = serializers.DateField()
    amount         = serializers.DecimalField(max_digits=10, decimal_places=2)
    description    = serializers.CharField()
    # Trip fields (only required for mamoriya)
    trip_destination = serializers.CharField(required=False, allow_blank=True, default='')
    trip_purpose     = serializers.CharField(required=False, allow_blank=True, default='')
    trip_start       = serializers.DateField(required=False, allow_null=True)
    trip_end         = serializers.DateField(required=False, allow_null=True)
    distance_km      = serializers.DecimalField(max_digits=8, decimal_places=2, required=False, allow_null=True)
    transport_type   = serializers.CharField(required=False, allow_blank=True, default='')
    allowance_amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, default=Decimal('0'))

    def validate(self, data):
        if data['category'] == 'mamoriya' and not data.get('trip_destination'):
            raise serializers.ValidationError({'trip_destination': 'وجهة المأمورية مطلوبة.'})
        return data


# ── Permits (أذونات: مأمورية / تعديل شيفت) ───────────────────────────────────────

class PermitSerializer(StaffCodeMixin, serializers.ModelSerializer):
    staff_name          = serializers.CharField(source='staff.full_name', read_only=True)
    branch_name         = serializers.CharField(source='branch.name_ar', read_only=True)
    permit_type_display = serializers.CharField(source='get_permit_type_display', read_only=True)
    status_display      = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model  = Permit
        fields = [
            'id', 'staff', 'staff_name', 'staff_code',
            'employee_hr_code', 'employee_name', 'submitted_by_name', 'approver_names',
            'branch', 'branch_name',
            'permit_type', 'permit_type_display', 'date', 'time_from', 'time_to',
            'destination', 'reason', 'status', 'status_display',
            'approval_request', 'rejection_reason', 'created_at',
        ]
        read_only_fields = ['status', 'approval_request', 'rejection_reason', 'created_at']


class SubmitPermitSerializer(SubjectFieldsMixin, serializers.Serializer):
    permit_type = serializers.ChoiceField(choices=Permit.TYPE_CHOICES)
    date        = serializers.DateField()
    time_from   = serializers.TimeField()
    time_to     = serializers.TimeField(required=False, allow_null=True)
    destination = serializers.CharField(required=False, allow_blank=True, default='')
    reason      = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, data):
        if data['permit_type'] == Permit.TYPE_MAMORIYA and not data.get('destination'):
            raise serializers.ValidationError({'destination': 'جهة المأمورية مطلوبة.'})
        if data.get('time_to') and data['time_to'] <= data['time_from']:
            raise serializers.ValidationError({'time_to': 'وقت النهاية يجب أن يكون بعد وقت البداية.'})
        return data
