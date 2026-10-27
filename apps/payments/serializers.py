"""
apps/payments/serializers.py
"""
from rest_framework import serializers

from .models import ExternalPayment, PaymentReconciliationLog


class PaymentReconciliationLogSerializer(serializers.ModelSerializer):
    performed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = PaymentReconciliationLog
        fields = '__all__'
        read_only_fields = ('payment', 'performed_by', 'performed_at')

    def get_performed_by_name(self, obj):
        if obj.performed_by:
            return obj.performed_by.get_full_name() or obj.performed_by.username
        return ''


class ExternalPaymentSerializer(serializers.ModelSerializer):
    reconciliation_logs = PaymentReconciliationLogSerializer(many=True, read_only=True)
    method_display      = serializers.CharField(source='get_method_display', read_only=True)
    status_display      = serializers.CharField(source='get_status_display', read_only=True)
    branch_name         = serializers.SerializerMethodField()
    created_by_name     = serializers.SerializerMethodField()
    confirmed_by_name   = serializers.SerializerMethodField()

    class Meta:
        model = ExternalPayment
        fields = '__all__'
        read_only_fields = ('created_by', 'confirmed_by', 'confirmed_at', 'created_at', 'updated_at')

    def get_branch_name(self, obj):
        return obj.branch.name_ar or obj.branch.name if obj.branch else ''

    def get_created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.get_full_name() or obj.created_by.username
        return ''

    def get_confirmed_by_name(self, obj):
        if obj.confirmed_by:
            return obj.confirmed_by.get_full_name() or obj.confirmed_by.username
        return ''


class ExternalPaymentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExternalPayment
        fields = (
            'branch', 'customer', 'customer_name', 'customer_phone',
            'method', 'amount', 'invoice_total', 'is_partial', 'remaining_amount',
            'reference_number', 'payment_date', 'notes',
            'softech_invoice_code', 'softech_doc_number',
        )

    def create(self, validated_data):
        validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)
