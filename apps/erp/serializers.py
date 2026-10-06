from rest_framework import serializers
from .models import ERPTransaction, ERPTransactionLine, LocalCustomer


class ERPTransactionLineSerializer(serializers.ModelSerializer):
    item_name_resolved = serializers.CharField(source='item.name', read_only=True)

    class Meta:
        model  = ERPTransactionLine
        fields = [
            'id', 'item_code', 'item_name', 'item_name_resolved',
            'quantity', 'unit_price', 'line_total', 'store_code',
        ]


class ERPTransactionSerializer(serializers.ModelSerializer):
    branch_name   = serializers.CharField(source='branch.name_ar',              read_only=True)
    doccode_label = serializers.CharField(source='get_doccode_display',          read_only=True)
    lines         = ERPTransactionLineSerializer(many=True, read_only=True)

    class Meta:
        model  = ERPTransaction
        fields = [
            'id', 'transaction_id', 'doccode', 'doccode_label',
            'reference_number', 'branch', 'branch_name',
            'softech_branch_code', 'phcode',
            'transaction_date', 'total_amount',
            'lines', 'synced_at',
        ]


class LocalCustomerSerializer(serializers.ModelSerializer):
    branch_name     = serializers.CharField(source='branch.name_ar', read_only=True)
    whatsapp_url    = serializers.CharField(read_only=True)
    linked_customer_name = serializers.CharField(source='linked_customer.name', read_only=True)

    class Meta:
        model  = LocalCustomer
        fields = [
            'id', 'phcode', 'name', 'phone', 'phone_alt',
            'erp_branch_code', 'branch', 'branch_name',
            'address', 'area', 'customer_type', 'is_active',
            'linked_customer', 'linked_customer_name',
            'whatsapp_url', 'synced_at',
        ]


class LocalCustomerListSerializer(serializers.ModelSerializer):
    branch_name  = serializers.CharField(source='branch.name_ar', read_only=True)
    whatsapp_url = serializers.CharField(read_only=True)

    class Meta:
        model  = LocalCustomer
        fields = [
            'id', 'phcode', 'name', 'phone',
            'branch_name', 'customer_type', 'is_active',
            'whatsapp_url',
        ]
