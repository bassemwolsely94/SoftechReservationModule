from rest_framework import serializers
from .models import CallLog, AddressUpdate


class AddressUpdateSerializer(serializers.ModelSerializer):
    customer_name  = serializers.CharField(source='customer.name',        read_only=True)
    applied_by_name = serializers.CharField(source='applied_by.full_name', read_only=True)
    status_label   = serializers.CharField(source='get_status_display',    read_only=True)

    class Meta:
        model  = AddressUpdate
        fields = [
            'id', 'customer', 'customer_name',
            'label', 'label_custom', 'address_text', 'area',
            'floor', 'apartment', 'landmark',
            'google_maps_link', 'delivery_phone', 'delivery_notes',
            'set_as_default', 'status', 'status_label',
            'applied_location', 'applied_by_name', 'applied_at',
            'notes', 'collected_at',
        ]
        read_only_fields = ['applied_location', 'applied_by', 'applied_at', 'collected_at']


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


class CallLogListSerializer(serializers.ModelSerializer):
    customer_name   = serializers.CharField(source='customer.name',        read_only=True)
    handled_by_name = serializers.CharField(source='handled_by.full_name', read_only=True)
    branch_name     = serializers.CharField(source='branch.name_ar',       read_only=True)
    direction_label = serializers.CharField(source='get_direction_display', read_only=True)
    status_label    = serializers.CharField(source='get_status_display',    read_only=True)
    purpose_label   = serializers.CharField(source='get_purpose_display',   read_only=True)
    duration_label  = serializers.CharField(read_only=True)
    whatsapp_url    = serializers.CharField(read_only=True)

    class Meta:
        model  = CallLog
        fields = [
            'id', 'phone_number', 'caller_name',
            'customer', 'customer_name',
            'direction', 'direction_label',
            'status', 'status_label',
            'purpose', 'purpose_label',
            'duration_seconds', 'duration_label',
            'summary', 'whatsapp_url',
            'handled_by', 'handled_by_name',
            'branch_name', 'called_at',
            'callback_due', 'needs_callback',
        ]


class CallLogDetailSerializer(serializers.ModelSerializer):
    customer_name   = serializers.CharField(source='customer.name',          read_only=True)
    customer_phone  = serializers.CharField(source='customer.phone',         read_only=True)
    handled_by_name = serializers.CharField(source='handled_by.full_name',   read_only=True)
    branch_name     = serializers.CharField(source='branch.name_ar',         read_only=True)
    direction_label = serializers.CharField(source='get_direction_display',   read_only=True)
    status_label    = serializers.CharField(source='get_status_display',      read_only=True)
    purpose_label   = serializers.CharField(source='get_purpose_display',     read_only=True)
    duration_label  = serializers.CharField(read_only=True)
    whatsapp_url    = serializers.CharField(read_only=True)
    address_updates = AddressUpdateSerializer(many=True, read_only=True)

    # Linked ERP identity
    local_customer_phcode = serializers.CharField(
        source='local_customer.phcode', read_only=True
    )

    class Meta:
        model  = CallLog
        fields = [
            'id', 'phone_number', 'caller_name',
            'customer', 'customer_name', 'customer_phone',
            'local_customer', 'local_customer_phcode',
            'direction', 'direction_label',
            'status', 'status_label',
            'purpose', 'purpose_label',
            'duration_seconds', 'duration_label',
            'notes', 'summary', 'whatsapp_url',
            'reservation', 'followup_task',
            'payment_method',
            'handled_by', 'handled_by_name',
            'branch', 'branch_name',
            'called_at', 'updated_at', 'callback_due', 'needs_callback',
            'address_updates',
        ]
        read_only_fields = ['called_at', 'updated_at']


class CallLogCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = CallLog
        fields = [
            'phone_number', 'caller_name', 'customer',
            'direction', 'status', 'purpose',
            'duration_seconds', 'notes', 'summary',
            'reservation', 'followup_task',
            'payment_method', 'branch', 'callback_due',
        ]

    def validate_phone_number(self, v):
        if not v or not v.strip():
            raise serializers.ValidationError('رقم الهاتف مطلوب')
        return v.strip()
