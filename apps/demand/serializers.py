from rest_framework import serializers
from .models import DemandRecord, DemandItem, FollowUpTask, DemandLog, ItemDemandStat


# ── Item serializers ──────────────────────────────────────────────────────────

class DemandItemSerializer(serializers.ModelSerializer):
    item_name        = serializers.CharField(source='item.name',            read_only=True)
    item_softech_id  = serializers.CharField(source='item.softech_id',       read_only=True)
    item_scientific  = serializers.CharField(source='item.name_scientific',  read_only=True)
    display_name     = serializers.CharField(read_only=True)
    stock_at_branch  = serializers.FloatField(read_only=True)
    stock_network    = serializers.FloatField(source='stock_network_total',  read_only=True)
    demand_type_label = serializers.CharField(source='get_demand_type_display', read_only=True)
    item_status_label = serializers.CharField(source='get_item_status_display', read_only=True)

    class Meta:
        model  = DemandItem
        fields = [
            'id', 'item', 'item_name', 'item_softech_id', 'item_scientific',
            'item_name_free', 'display_name',
            'quantity', 'demand_type', 'demand_type_label',
            'item_status', 'item_status_label',
            'is_long_shortage', 'is_discontinued', 'shortage_note',
            'stock_at_branch', 'stock_network',
            'notes',
        ]


class DemandItemWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model  = DemandItem
        fields = ['item', 'item_name_free', 'quantity', 'demand_type',
                  'is_long_shortage', 'is_discontinued', 'shortage_note', 'notes']

    def validate(self, data):
        if not data.get('item') and not data.get('item_name_free'):
            raise serializers.ValidationError('يجب تحديد الصنف أو كتابة اسمه')
        return data


# ── Follow-up serializers ─────────────────────────────────────────────────────

class FollowUpTaskSerializer(serializers.ModelSerializer):
    assigned_to_name  = serializers.CharField(source='assigned_to.full_name',  read_only=True)
    completed_by_name = serializers.CharField(source='completed_by.full_name', read_only=True)
    is_overdue        = serializers.BooleanField(read_only=True)
    overdue_hours     = serializers.FloatField(read_only=True)
    task_type_label   = serializers.CharField(source='get_task_type_display',  read_only=True)
    status_label      = serializers.CharField(source='get_status_display',      read_only=True)

    class Meta:
        model  = FollowUpTask
        fields = [
            'id', 'task_type', 'task_type_label',
            'due_date', 'status', 'status_label',
            'assigned_to', 'assigned_to_name',
            'note', 'is_overdue', 'overdue_hours',
            'completed_at', 'completed_by_name',
            'created_at',
        ]
        read_only_fields = ['created_at', 'completed_at']


# ── Log serializers ───────────────────────────────────────────────────────────

class DemandLogSerializer(serializers.ModelSerializer):
    created_by_name   = serializers.CharField(source='created_by.full_name',   read_only=True)
    created_by_branch = serializers.CharField(source='created_by.branch_name', read_only=True)
    log_type_label    = serializers.CharField(source='get_log_type_display',   read_only=True)
    call_outcome_label = serializers.CharField(source='get_call_outcome_display', read_only=True)
    type_icon = serializers.SerializerMethodField()

    def get_type_icon(self, obj):
        return {
            'note': '📝', 'call': '📞', 'whatsapp': '💬',
            'sms': '📱', 'system': '⚙️', 'status': '🔄',
        }.get(obj.log_type, '💬')

    class Meta:
        model  = DemandLog
        fields = [
            'id', 'log_type', 'log_type_label', 'type_icon', 'message',
            'call_outcome', 'call_outcome_label', 'call_duration_seconds',
            'created_by', 'created_by_name', 'created_by_branch',
            'created_at',
        ]
        read_only_fields = ['created_at', 'created_by']


class DemandLogCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = DemandLog
        fields = ['log_type', 'message', 'call_outcome', 'call_duration_seconds']


# ── Demand list serializer ────────────────────────────────────────────────────

class DemandListSerializer(serializers.ModelSerializer):
    branch_name    = serializers.CharField(source='branch.name_ar',           read_only=True)
    assigned_name  = serializers.CharField(source='assigned_to.full_name',    read_only=True)
    created_by_name = serializers.CharField(source='created_by.full_name',   read_only=True)
    status_label   = serializers.CharField(source='get_status_display',       read_only=True)
    priority_label = serializers.CharField(source='get_priority_display',     read_only=True)
    source_label   = serializers.CharField(source='get_source_display',       read_only=True)
    status_color   = serializers.CharField(read_only=True)
    total_items    = serializers.IntegerField(read_only=True)
    sla_breached   = serializers.BooleanField(read_only=True)
    sla_minutes_remaining = serializers.FloatField(read_only=True)
    item_names     = serializers.SerializerMethodField()

    def get_item_names(self, obj):
        return [i.item_display_name for i in obj.items.all()[:3]]

    class Meta:
        model  = DemandRecord
        fields = [
            'id', 'demand_number',
            'phone', 'customer_name', 'phcode',
            'branch_name', 'assigned_name', 'created_by_name',
            'status', 'status_label', 'status_color',
            'priority', 'priority_label',
            'source', 'source_label',
            'total_items', 'item_names',
            'follow_up_date', 'sla_breached', 'sla_minutes_remaining',
            'created_at', 'updated_at',
        ]


# ── Demand detail serializer ──────────────────────────────────────────────────

class DemandDetailSerializer(serializers.ModelSerializer):
    branch_name         = serializers.CharField(source='branch.name_ar',         read_only=True)
    assigned_name       = serializers.CharField(source='assigned_to.full_name',  read_only=True)
    created_by_name     = serializers.CharField(source='created_by.full_name',   read_only=True)
    customer_softech_id = serializers.CharField(source='customer.softech_id',    read_only=True)
    status_label        = serializers.CharField(source='get_status_display',      read_only=True)
    priority_label      = serializers.CharField(source='get_priority_display',    read_only=True)
    source_label        = serializers.CharField(source='get_source_display',      read_only=True)
    lost_reason_label   = serializers.CharField(source='get_lost_reason_display', read_only=True)
    status_color        = serializers.CharField(read_only=True)
    sla_breached        = serializers.BooleanField(read_only=True)
    sla_deadline        = serializers.DateTimeField(read_only=True)
    sla_minutes_remaining = serializers.FloatField(read_only=True)
    is_active           = serializers.BooleanField(read_only=True)

    items    = DemandItemSerializer(many=True, read_only=True)
    followups = FollowUpTaskSerializer(many=True, read_only=True)
    logs     = DemandLogSerializer(many=True, read_only=True)

    class Meta:
        model  = DemandRecord
        fields = [
            'id', 'demand_number',
            'phone', 'customer_name', 'phcode', 'erp_branch_code',
            'customer', 'customer_softech_id',
            'branch', 'branch_name',
            'assigned_to', 'assigned_name',
            'created_by', 'created_by_name',
            'status', 'status_label', 'status_color',
            'priority', 'priority_label',
            'source', 'source_label',
            'is_active',
            'notes', 'lost_reason', 'lost_reason_label',
            'erp_invoice_ref', 'fulfilled_at',
            'follow_up_date', 'expected_stock_date',
            'sla_breached', 'sla_deadline', 'sla_minutes_remaining',
            'assigned_at', 'contacted_at',
            'items', 'followups', 'logs',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'demand_number', 'created_by', 'created_at', 'updated_at',
            'assigned_at', 'contacted_at', 'fulfilled_at',
        ]


# ── Create serializer ─────────────────────────────────────────────────────────

class DemandCreateSerializer(serializers.ModelSerializer):
    items = DemandItemWriteSerializer(many=True, required=False)

    class Meta:
        model  = DemandRecord
        fields = [
            'phone', 'customer_name', 'phcode',
            'branch', 'assigned_to', 'priority', 'source',
            'notes', 'follow_up_date', 'items',
        ]

    def validate_phone(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError('رقم الهاتف مطلوب')
        return value.strip()


# ── Update serializer ─────────────────────────────────────────────────────────

class DemandUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = DemandRecord
        fields = [
            'customer_name', 'phcode', 'priority', 'source',
            'assigned_to', 'follow_up_date', 'expected_stock_date', 'notes',
        ]


# ── Action serializers ────────────────────────────────────────────────────────

class TransitionSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default='')


class AssignSerializer(serializers.Serializer):
    assigned_to = serializers.IntegerField()
    note        = serializers.CharField(required=False, allow_blank=True, default='')


class FulfillSerializer(serializers.Serializer):
    erp_invoice_ref = serializers.CharField(required=False, allow_blank=True, default='')
    note            = serializers.CharField(required=False, allow_blank=True, default='')


class LostSerializer(serializers.Serializer):
    lost_reason = serializers.ChoiceField(choices=[
        'no_stock', 'delayed', 'discontinued',
        'no_response', 'price', 'competitor', 'other',
    ])
    note = serializers.CharField(required=False, allow_blank=True, default='')


class ScheduleFollowupSerializer(serializers.Serializer):
    hours_from_now = serializers.FloatField(default=24, min_value=0.25)
    task_type      = serializers.ChoiceField(
        choices=['call', 'whatsapp', 'sms', 'visit', 'stock_check', 'other'],
        default='call',
    )
    note = serializers.CharField(required=False, allow_blank=True, default='')


# ── Dashboard serializer ──────────────────────────────────────────────────────

class ItemDemandStatSerializer(serializers.ModelSerializer):
    item_name      = serializers.CharField(source='item.name',       read_only=True)
    item_softech   = serializers.CharField(source='item.softech_id', read_only=True)
    branch_name    = serializers.CharField(source='branch.name_ar',  read_only=True)
    fulfillment_rate = serializers.FloatField(read_only=True)
    lost_rate        = serializers.FloatField(read_only=True)

    class Meta:
        model  = ItemDemandStat
        fields = [
            'id', 'item', 'item_name', 'item_softech',
            'branch', 'branch_name',
            'demand_count_30d', 'lost_count_30d', 'fulfilled_count_30d',
            'lost_qty_30d', 'fulfillment_rate', 'lost_rate',
            'is_long_shortage', 'is_discontinued',
            'suggest_order', 'suggest_transfer',
            'last_updated',
        ]
