"""
apps/callcenter/serializers.py — v2

Serializers for Call Center module:
  CallLog (list / detail / create)
  AddressUpdate (read / write)
  CallLogAttachment
  CustomerCase (list / detail / create)
  CaseEvent
  CallQualityScore
"""
from rest_framework import serializers
from .models import (
    CallLog, AddressUpdate,
    CallLogAttachment, CustomerCase, CaseEvent, CallQualityScore,
    CallItem,
)


# ─────────────────────────────────────────────────────────────────────────────
# AddressUpdate
# ─────────────────────────────────────────────────────────────────────────────

class AddressUpdateSerializer(serializers.ModelSerializer):
    customer_name   = serializers.CharField(source='customer.name',        read_only=True)
    applied_by_name = serializers.CharField(source='applied_by.full_name', read_only=True, default=None)
    status_label    = serializers.CharField(source='get_status_display',   read_only=True)

    class Meta:
        model  = AddressUpdate
        fields = [
            'id', 'customer', 'customer_name',
            'label', 'label_custom', 'address_text', 'area',
            'floor', 'apartment', 'landmark',
            'google_maps_link', 'delivery_phone', 'delivery_notes',
            'set_as_default', 'status', 'status_label',
            'applied_location_ref', 'applied_by_name', 'applied_at',
            'notes', 'collected_at',
        ]
        read_only_fields = ['applied_location_ref', 'applied_by', 'applied_at', 'collected_at']


class AddressUpdateWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model  = AddressUpdate
        fields = [
            'customer', 'label', 'label_custom', 'address_text', 'area',
            'floor', 'apartment', 'landmark',
            'google_maps_link', 'delivery_phone', 'delivery_notes',
            'set_as_default', 'notes',
        ]

    def validate_address_text(self, v):
        if not v.strip():
            raise serializers.ValidationError('العنوان لا يمكن أن يكون فارغاً')
        return v


# ─────────────────────────────────────────────────────────────────────────────
# CallLogAttachment
# ─────────────────────────────────────────────────────────────────────────────

class CallLogAttachmentSerializer(serializers.ModelSerializer):
    file_type_label  = serializers.CharField(source='get_file_type_display', read_only=True)
    uploaded_by_name = serializers.CharField(source='uploaded_by.full_name', read_only=True, default=None)
    file_url         = serializers.SerializerMethodField()

    class Meta:
        model  = CallLogAttachment
        fields = [
            'id', 'call_log', 'file', 'file_url',
            'file_type', 'file_type_label',
            'description', 'file_size',
            'uploaded_by', 'uploaded_by_name', 'uploaded_at',
        ]
        read_only_fields = ['uploaded_by', 'uploaded_at', 'file_size']

    def get_file_url(self, obj):
        request = self.context.get('request')
        if request and obj.file:
            return request.build_absolute_uri(obj.file.url)
        return obj.file.url if obj.file else None

    def create(self, validated_data):
        f = validated_data.get('file')
        if f:
            validated_data['file_size'] = f.size
        return super().create(validated_data)


# ─────────────────────────────────────────────────────────────────────────────
# CaseEvent
# ─────────────────────────────────────────────────────────────────────────────

class CaseEventSerializer(serializers.ModelSerializer):
    event_type_label  = serializers.CharField(source='get_event_type_display', read_only=True)
    created_by_name   = serializers.CharField(source='created_by.full_name',   read_only=True, default=None)
    attachment_url    = serializers.SerializerMethodField()

    class Meta:
        model  = CaseEvent
        fields = [
            'id', 'case', 'event_type', 'event_type_label',
            'message', 'attachment', 'attachment_type', 'attachment_url',
            'created_by', 'created_by_name', 'created_at',
        ]
        read_only_fields = ['created_by', 'created_at']

    def get_attachment_url(self, obj):
        if not obj.attachment:
            return None
        request = self.context.get('request')
        return request.build_absolute_uri(obj.attachment.url) if request else obj.attachment.url


# ─────────────────────────────────────────────────────────────────────────────
# CustomerCase
# ─────────────────────────────────────────────────────────────────────────────

class CustomerCaseListSerializer(serializers.ModelSerializer):
    customer_name    = serializers.CharField(source='customer.name',           read_only=True)
    customer_phone   = serializers.CharField(source='customer.phone',          read_only=True)
    branch_name      = serializers.CharField(source='branch.name_ar',          read_only=True, default=None)
    status_label     = serializers.CharField(source='get_status_display',      read_only=True)
    category_label   = serializers.CharField(source='get_category_display',    read_only=True)
    priority_label   = serializers.CharField(source='get_priority_display',    read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.full_name',   read_only=True, default=None)
    opened_by_name   = serializers.CharField(source='opened_by.full_name',     read_only=True, default=None)
    is_sla_breached  = serializers.BooleanField(read_only=True)
    age_hours        = serializers.FloatField(read_only=True)

    class Meta:
        model  = CustomerCase
        fields = [
            'id', 'case_number',
            'customer', 'customer_name', 'customer_phone',
            'branch', 'branch_name',
            'category', 'category_label',
            'priority', 'priority_label',
            'status', 'status_label',
            'title',
            'assigned_to', 'assigned_to_name',
            'opened_by', 'opened_by_name',
            'sla_due', 'is_sla_breached', 'age_hours',
            'csat_score',
            'created_at', 'updated_at',
        ]


class CustomerCaseDetailSerializer(serializers.ModelSerializer):
    customer_name      = serializers.CharField(source='customer.name',         read_only=True)
    customer_phone     = serializers.CharField(source='customer.phone',        read_only=True)
    customer_segment   = serializers.CharField(source='customer.segment',      read_only=True, default=None)
    branch_name        = serializers.CharField(source='branch.name_ar',        read_only=True, default=None)
    status_label       = serializers.CharField(source='get_status_display',    read_only=True)
    category_label     = serializers.CharField(source='get_category_display',  read_only=True)
    priority_label     = serializers.CharField(source='get_priority_display',  read_only=True)
    assigned_to_name   = serializers.CharField(source='assigned_to.full_name', read_only=True, default=None)
    opened_by_name     = serializers.CharField(source='opened_by.full_name',   read_only=True, default=None)
    escalated_to_name  = serializers.CharField(source='escalated_to.full_name', read_only=True, default=None)
    is_sla_breached    = serializers.BooleanField(read_only=True)
    age_hours          = serializers.FloatField(read_only=True)
    resolution_time_hours = serializers.FloatField(read_only=True)
    events             = CaseEventSerializer(many=True, read_only=True)

    class Meta:
        model  = CustomerCase
        fields = [
            'id', 'case_number',
            'customer', 'customer_name', 'customer_phone', 'customer_segment',
            'branch', 'branch_name',
            'category', 'category_label',
            'priority', 'priority_label',
            'status', 'status_label',
            'title', 'description', 'root_cause', 'resolution',
            'demand', 'reservation', 'delivery',
            'opened_by', 'opened_by_name',
            'assigned_to', 'assigned_to_name',
            'sla_due', 'resolved_at', 'closed_at',
            'csat_score', 'csat_note',
            'escalated_to', 'escalated_to_name',
            'escalated_at', 'escalation_reason',
            'is_sla_breached', 'age_hours', 'resolution_time_hours',
            'events',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['case_number', 'created_at', 'updated_at', 'opened_by']


class CustomerCaseCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = CustomerCase
        fields = [
            'customer', 'branch', 'category', 'priority',
            'title', 'description',
            'demand', 'reservation', 'delivery',
            'sla_due',
        ]

    def validate_title(self, v):
        if not v.strip():
            raise serializers.ValidationError('عنوان الحالة مطلوب')
        return v.strip()


class CustomerCaseUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = CustomerCase
        fields = [
            'category', 'priority', 'status',
            'title', 'description', 'root_cause', 'resolution',
            'assigned_to', 'sla_due',
            'csat_score', 'csat_note',
        ]


# ─────────────────────────────────────────────────────────────────────────────
# CallQualityScore
# ─────────────────────────────────────────────────────────────────────────────

class CallQualityScoreSerializer(serializers.ModelSerializer):
    scored_by_name = serializers.CharField(source='scored_by.full_name', read_only=True, default=None)
    source_label   = serializers.CharField(source='get_source_display',  read_only=True)

    class Meta:
        model  = CallQualityScore
        fields = [
            'id', 'call_log',
            'scored_by', 'scored_by_name',
            'source', 'source_label',
            'greeting', 'resolution', 'communication', 'accuracy',
            'total_score', 'notes', 'scored_at',
        ]
        read_only_fields = ['scored_by', 'total_score', 'scored_at']

    def validate(self, data):
        errors = {}
        if data.get('greeting', 0) > 20:
            errors['greeting'] = 'الحد الأقصى 20'
        if data.get('resolution', 0) > 30:
            errors['resolution'] = 'الحد الأقصى 30'
        if data.get('communication', 0) > 25:
            errors['communication'] = 'الحد الأقصى 25'
        if data.get('accuracy', 0) > 25:
            errors['accuracy'] = 'الحد الأقصى 25'
        if errors:
            raise serializers.ValidationError(errors)
        return data


# ─────────────────────────────────────────────────────────────────────────────
# CallLog — extended
# ─────────────────────────────────────────────────────────────────────────────

class CallLogListSerializer(serializers.ModelSerializer):
    customer_name   = serializers.CharField(source='customer.name',        read_only=True)
    customer_segment = serializers.CharField(source='customer.segment',    read_only=True, default=None)
    handled_by_name = serializers.CharField(source='handled_by.full_name', read_only=True)
    branch_name     = serializers.CharField(source='branch.name_ar',       read_only=True)
    direction_label = serializers.CharField(source='get_direction_display', read_only=True)
    status_label    = serializers.CharField(source='get_status_display',    read_only=True)
    purpose_label   = serializers.CharField(source='get_purpose_display',   read_only=True)
    duration_label  = serializers.CharField(read_only=True)
    whatsapp_url    = serializers.CharField(read_only=True)
    has_case        = serializers.SerializerMethodField()

    class Meta:
        model  = CallLog
        fields = [
            'id', 'phone_number', 'caller_name',
            'customer', 'customer_name', 'customer_segment',
            'direction', 'direction_label',
            'status', 'status_label',
            'purpose', 'purpose_label',
            'duration_seconds', 'duration_label',
            'summary', 'whatsapp_url',
            'handled_by', 'handled_by_name',
            'branch_name', 'called_at',
            'callback_due', 'needs_callback',
            'case', 'has_case',
            'quality_score',
            'ai_sentiment', 'ai_urgency',
        ]

    def get_has_case(self, obj):
        return obj.case_id is not None


class CallLogDetailSerializer(serializers.ModelSerializer):
    customer_name    = serializers.CharField(source='customer.name',          read_only=True)
    customer_phone   = serializers.CharField(source='customer.phone',         read_only=True)
    customer_segment = serializers.CharField(source='customer.segment',       read_only=True, default=None)
    customer_ltv     = serializers.DecimalField(source='customer.ltv',        read_only=True,
                                                max_digits=12, decimal_places=2, default=None)
    handled_by_name  = serializers.CharField(source='handled_by.full_name',   read_only=True)
    branch_name      = serializers.CharField(source='branch.name_ar',         read_only=True)
    direction_label  = serializers.CharField(source='get_direction_display',   read_only=True)
    status_label     = serializers.CharField(source='get_status_display',      read_only=True)
    purpose_label    = serializers.CharField(source='get_purpose_display',     read_only=True)
    duration_label   = serializers.CharField(read_only=True)
    whatsapp_url     = serializers.CharField(read_only=True)
    address_updates  = AddressUpdateSerializer(many=True, read_only=True)
    attachments      = CallLogAttachmentSerializer(many=True, read_only=True)
    quality          = CallQualityScoreSerializer(read_only=True)
    case_number      = serializers.CharField(source='case.case_number', read_only=True, default=None)
    ai_sentiment_label = serializers.SerializerMethodField()

    class Meta:
        model  = CallLog
        fields = [
            'id', 'phone_number', 'caller_name',
            'customer', 'customer_name', 'customer_phone',
            'customer_segment', 'customer_ltv',
            'direction', 'direction_label',
            'status', 'status_label',
            'purpose', 'purpose_label',
            'duration_seconds', 'duration_label',
            'notes', 'summary', 'whatsapp_url',
            'case', 'case_number',
            'reservation', 'followup_task',
            'payment_method',
            'recording_url', 'voice_transcript',
            'prescription_image',
            'ai_summary', 'ai_intent',
            'ai_sentiment', 'ai_sentiment_label',
            'ai_urgency', 'ai_next_action', 'ai_processed_at',
            'quality_score', 'quality',
            'handled_by', 'handled_by_name',
            'branch', 'branch_name',
            'called_at', 'updated_at', 'callback_due', 'needs_callback',
            'address_updates', 'attachments',
        ]
        read_only_fields = ['called_at', 'updated_at']

    def get_ai_sentiment_label(self, obj):
        labels = {'positive': 'إيجابي 😊', 'neutral': 'محايد 😐', 'negative': 'سلبي 😟'}
        return labels.get(obj.ai_sentiment, '')


class CallLogCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = CallLog
        fields = [
            'phone_number', 'caller_name', 'customer',
            'direction', 'status', 'purpose',
            'duration_seconds', 'notes', 'summary',
            'case', 'reservation', 'followup_task',
            'payment_method', 'branch', 'callback_due',
            'recording_url', 'voice_transcript',
        ]

    def validate_phone_number(self, v):
        if not v or not v.strip():
            raise serializers.ValidationError('رقم الهاتف مطلوب')
        return v.strip()


# ─────────────────────────────────────────────────────────────────────────────
# CallItem
# ─────────────────────────────────────────────────────────────────────────────

class CallItemSerializer(serializers.ModelSerializer):
    item_name        = serializers.CharField(source='item.name',        read_only=True, default=None)
    item_code        = serializers.CharField(source='item.softech_id',  read_only=True, default=None)
    converted_to_label = serializers.CharField(source='get_converted_to_display', read_only=True)
    display_name     = serializers.CharField(read_only=True)
    display_code     = serializers.CharField(read_only=True)

    class Meta:
        model  = CallItem
        fields = [
            'id', 'call_log',
            'item', 'item_name', 'item_code',
            'manual_item_name', 'manual_item_code',
            'quantity', 'notes',
            'converted_to', 'converted_to_label',
            'converted_reservation', 'converted_transfer',
            'display_name', 'display_code',
            'created_at',
        ]
        read_only_fields = ['call_log', 'converted_to', 'converted_reservation', 'converted_transfer', 'created_at']

    def validate(self, data):
        if not data.get('item') and not (data.get('manual_item_name') or '').strip():
            raise serializers.ValidationError(
                'يجب تحديد الصنف من الكتالوج أو كتابة الاسم يدوياً'
            )
        return data
