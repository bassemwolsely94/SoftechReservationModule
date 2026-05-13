from rest_framework import serializers
from .models import ChronicMedicationProfile, FollowUpTask


class ChronicMedicationProfileSerializer(serializers.ModelSerializer):
    item_name       = serializers.CharField(source='item.name',       read_only=True)
    item_softech_id = serializers.CharField(source='item.softech_id', read_only=True)
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True)
    source_label    = serializers.CharField(source='get_source_display', read_only=True)

    class Meta:
        model  = ChronicMedicationProfile
        fields = [
            'id', 'item', 'item_name', 'item_softech_id',
            'is_chronic', 'avg_daily_usage', 'pack_size',
            'expected_duration_days', 'followup_before_days', 'followup_trigger_day',
            'notes', 'source', 'source_label',
            'created_by_name', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at', 'created_by', 'followup_trigger_day']


class ChronicMedicationProfileWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ChronicMedicationProfile
        fields = [
            'item', 'is_chronic', 'avg_daily_usage',
            'pack_size', 'followup_before_days', 'notes',
        ]

    def validate_avg_daily_usage(self, v):
        if v <= 0:
            raise serializers.ValidationError('الاستخدام اليومي يجب أن يكون أكبر من صفر')
        return v


class FollowUpTaskListSerializer(serializers.ModelSerializer):
    customer_name    = serializers.CharField(source='customer.name',      read_only=True)
    customer_phone   = serializers.CharField(source='customer.phone',     read_only=True)
    item_name        = serializers.CharField(source='item.name',          read_only=True)
    item_softech_id  = serializers.CharField(source='item.softech_id',   read_only=True)
    branch_name      = serializers.CharField(source='branch.name_ar',    read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.full_name', read_only=True)
    status_label     = serializers.CharField(source='get_status_display',    read_only=True)
    task_type_label  = serializers.CharField(source='get_task_type_display', read_only=True)
    is_overdue       = serializers.BooleanField(read_only=True)
    whatsapp_url     = serializers.CharField(read_only=True)

    class Meta:
        model  = FollowUpTask
        fields = [
            'id', 'customer', 'customer_name', 'customer_phone',
            'item', 'item_name', 'item_softech_id',
            'branch', 'branch_name',
            'assigned_to', 'assigned_to_name',
            'task_type', 'task_type_label',
            'due_date', 'status', 'status_label',
            'attempts', 'is_overdue', 'whatsapp_url',
            'source_sale_date', 'created_at',
        ]


class FollowUpTaskDetailSerializer(serializers.ModelSerializer):
    customer_name    = serializers.CharField(source='customer.name',      read_only=True)
    customer_phone   = serializers.CharField(source='customer.phone',     read_only=True)
    item_name        = serializers.CharField(source='item.name',          read_only=True)
    branch_name      = serializers.CharField(source='branch.name_ar',    read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.full_name',   read_only=True)
    completed_by_name = serializers.CharField(source='completed_by.full_name', read_only=True)
    status_label     = serializers.CharField(source='get_status_display',      read_only=True)
    task_type_label  = serializers.CharField(source='get_task_type_display',   read_only=True)
    is_overdue       = serializers.BooleanField(read_only=True)
    whatsapp_url     = serializers.CharField(read_only=True)
    profile          = ChronicMedicationProfileSerializer(source='chronic_profile', read_only=True)

    class Meta:
        model  = FollowUpTask
        fields = [
            'id', 'customer', 'customer_name', 'customer_phone',
            'item', 'item_name', 'branch', 'branch_name',
            'assigned_to', 'assigned_to_name',
            'task_type', 'task_type_label',
            'due_date', 'status', 'status_label', 'is_overdue',
            'attempts', 'notes', 'result_note',
            'whatsapp_url',
            'profile',
            'source_sale_date',
            'source_erp_transaction', 'closing_erp_transaction',
            'created_at', 'updated_at', 'completed_at',
            'completed_by_name',
        ]


class FollowUpTaskCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = FollowUpTask
        fields = [
            'customer', 'item', 'branch', 'assigned_to',
            'task_type', 'due_date', 'notes',
        ]


class FollowUpActionSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True)
