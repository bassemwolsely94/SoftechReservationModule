"""
apps/cheques/serializers.py
"""
from decimal import Decimal
from datetime import date
from rest_framework import serializers
from .models import EgyptianHoliday, ChequePlan, ChequeInstalment


# ── Holiday ───────────────────────────────────────────────────────────────────

class HolidaySerializer(serializers.ModelSerializer):
    holiday_type_label = serializers.CharField(source='get_holiday_type_display', read_only=True)

    class Meta:
        model  = EgyptianHoliday
        fields = ['id', 'date', 'name_ar', 'name_en', 'holiday_type',
                  'holiday_type_label', 'is_annual']


# ── Instalment ────────────────────────────────────────────────────────────────

class ChequeInstalmentSerializer(serializers.ModelSerializer):
    status_label   = serializers.CharField(source='get_status_display', read_only=True)
    adjusted       = serializers.SerializerMethodField()
    days_until_due = serializers.SerializerMethodField()

    class Meta:
        model  = ChequeInstalment
        fields = [
            'id', 'instalment_no', 'amount',
            'nominal_date', 'due_date', 'adjusted',
            'cheque_number', 'status', 'status_label',
            'issued_at', 'cleared_at',
            'days_until_due', 'notes',
        ]
        read_only_fields = ['id', 'instalment_no', 'nominal_date', 'due_date', 'adjusted']

    def get_adjusted(self, obj):
        return obj.due_date != obj.nominal_date

    def get_days_until_due(self, obj):
        delta = obj.due_date - date.today()
        return delta.days


class ChequeInstalmentUpdateSerializer(serializers.ModelSerializer):
    """Used for PATCH — only mutable fields."""
    class Meta:
        model  = ChequeInstalment
        fields = ['cheque_number', 'status', 'issued_at', 'cleared_at', 'notes']


# ── Plan ──────────────────────────────────────────────────────────────────────

class ChequePlanListSerializer(serializers.ModelSerializer):
    status_label   = serializers.CharField(source='get_status_display', read_only=True)
    interval_label = serializers.CharField(source='get_interval_unit_display', read_only=True)
    created_by_name = serializers.SerializerMethodField()
    branch_name    = serializers.SerializerMethodField()
    cleared_count  = serializers.IntegerField(read_only=True)
    pending_count  = serializers.IntegerField(read_only=True)
    total_cleared  = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True,
    )
    next_due_date  = serializers.SerializerMethodField()

    class Meta:
        model  = ChequePlan
        fields = [
            'id', 'title', 'payee_name', 'bank_name', 'total_amount',
            'cheque_count', 'first_due_date', 'interval_value', 'interval_unit',
            'interval_label', 'status', 'status_label',
            'reference_doc', 'branch', 'branch_name',
            'created_by_name', 'cleared_count', 'pending_count', 'total_cleared',
            'next_due_date', 'created_at',
        ]

    def get_created_by_name(self, obj):
        return obj.created_by.user.get_full_name() if obj.created_by_id else ''

    def get_branch_name(self, obj):
        return obj.branch.name_ar if obj.branch_id else ''

    def get_next_due_date(self, obj):
        nxt = obj.instalments.filter(
            status__in=['pending', 'issued']
        ).order_by('due_date').first()
        return nxt.due_date if nxt else None


class ChequePlanDetailSerializer(serializers.ModelSerializer):
    status_label   = serializers.CharField(source='get_status_display', read_only=True)
    interval_label = serializers.CharField(source='get_interval_unit_display', read_only=True)
    created_by_name = serializers.SerializerMethodField()
    branch_name    = serializers.SerializerMethodField()
    cleared_count  = serializers.SerializerMethodField()
    pending_count  = serializers.SerializerMethodField()
    total_cleared  = serializers.SerializerMethodField()
    instalments    = ChequeInstalmentSerializer(many=True, read_only=True)

    class Meta:
        model  = ChequePlan
        fields = [
            'id', 'title', 'notes', 'payee_name', 'bank_name', 'account_number',
            'total_amount', 'reference_doc',
            'cheque_count', 'first_due_date', 'interval_value', 'interval_unit',
            'interval_label', 'status', 'status_label',
            'branch', 'branch_name', 'created_by', 'created_by_name',
            'cleared_count', 'pending_count', 'total_cleared',
            'created_at', 'updated_at',
            'instalments',
        ]
        read_only_fields = [
            'id', 'status', 'status_label', 'interval_label',
            'created_by', 'created_by_name', 'branch_name',
            'cleared_count', 'pending_count', 'total_cleared',
            'created_at', 'updated_at', 'instalments',
        ]

    def get_created_by_name(self, obj):
        return obj.created_by.user.get_full_name() if obj.created_by_id else ''

    def get_branch_name(self, obj):
        return obj.branch.name_ar if obj.branch_id else ''

    def get_cleared_count(self, obj):
        return obj.cleared_count

    def get_pending_count(self, obj):
        return obj.pending_count

    def get_total_cleared(self, obj):
        return obj.total_cleared


class ChequePlanCreateSerializer(serializers.ModelSerializer):
    """Write serializer — triggers instalment generation on create."""

    class Meta:
        model  = ChequePlan
        fields = [
            'title', 'notes', 'payee_name', 'bank_name', 'account_number',
            'total_amount', 'reference_doc',
            'cheque_count', 'first_due_date', 'interval_value', 'interval_unit',
            'branch',
        ]

    def validate_cheque_count(self, value):
        if value < 1 or value > 120:
            raise serializers.ValidationError('عدد الشيكات يجب أن يكون بين 1 و 120.')
        return value

    def validate_total_amount(self, value):
        if value <= Decimal('0'):
            raise serializers.ValidationError('المبلغ الإجمالي يجب أن يكون أكبر من صفر.')
        return value

    def validate_first_due_date(self, value):
        if value < date.today():
            raise serializers.ValidationError('تاريخ الشيك الأول يجب أن يكون في المستقبل.')
        return value


# ── Preview ───────────────────────────────────────────────────────────────────

class PlanPreviewRequestSerializer(serializers.Serializer):
    first_due_date = serializers.DateField()
    count          = serializers.IntegerField(min_value=1, max_value=120)
    total_amount   = serializers.DecimalField(max_digits=14, decimal_places=2)
    interval_value = serializers.IntegerField(min_value=1, default=1)
    interval_unit  = serializers.ChoiceField(
        choices=['days', 'weeks', 'months'], default='months'
    )

    def validate_first_due_date(self, value):
        if value < date.today():
            raise serializers.ValidationError('التاريخ يجب أن يكون اليوم أو في المستقبل.')
        return value


class PlanPreviewItemSerializer(serializers.Serializer):
    instalment_no = serializers.IntegerField()
    nominal_date  = serializers.DateField()
    due_date      = serializers.DateField()
    amount        = serializers.DecimalField(max_digits=14, decimal_places=2)
    adjusted      = serializers.BooleanField()
