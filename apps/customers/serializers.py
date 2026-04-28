from rest_framework import serializers
from .models import Customer, CustomerNote, PurchaseHistory, PurchaseHistoryLine


class CustomerNoteSerializer(serializers.ModelSerializer):
    created_by_name   = serializers.SerializerMethodField()
    created_by_role   = serializers.CharField(source='created_by.role', read_only=True)
    created_by_branch = serializers.CharField(source='created_by.branch_name', read_only=True)

    def get_created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.full_name
        return None

    class Meta:
        model  = CustomerNote
        fields = [
            'id', 'note',
            'created_by', 'created_by_name', 'created_by_role', 'created_by_branch',
            'created_at',
        ]
        read_only_fields = ['created_at', 'created_by']


class PurchaseHistoryLineSerializer(serializers.ModelSerializer):
    item_name      = serializers.CharField(source='item.name',       read_only=True)
    item_softech_id = serializers.CharField(source='item.softech_id', read_only=True)

    class Meta:
        model  = PurchaseHistoryLine
        fields = ['id', 'item', 'item_name', 'item_softech_id',
                  'quantity', 'unit_price', 'line_total']


class PurchaseHistorySerializer(serializers.ModelSerializer):
    branch_name = serializers.SerializerMethodField()
    lines       = PurchaseHistoryLineSerializer(many=True, read_only=True)
    is_return   = serializers.BooleanField(read_only=True)

    def get_branch_name(self, obj):
        return obj.branch.name_ar or obj.branch.name

    class Meta:
        model  = PurchaseHistory
        fields = [
            'id', 'softech_invoice_id', 'branch_name',
            'doc_code', 'is_return',
            'total_amount', 'invoice_date',
            'lines',
        ]


class CustomerSerializer(serializers.ModelSerializer):
    customer_type_label  = serializers.CharField(read_only=True)
    customer_type_color  = serializers.CharField(read_only=True)
    preferred_branch_name = serializers.SerializerMethodField()
    total_purchases      = serializers.IntegerField(read_only=True)
    lifetime_value       = serializers.FloatField(read_only=True)
    notes                = CustomerNoteSerializer(many=True, read_only=True)

    def get_preferred_branch_name(self, obj):
        if obj.preferred_branch:
            return obj.preferred_branch.name_ar or obj.preferred_branch.name
        return None

    class Meta:
        model  = Customer
        fields = [
            'id', 'softech_id',
            'name', 'phone', 'phone_alt', 'email',
            'address', 'date_of_birth',
            'chronic_conditions', 'notes_softech',
            'discount_percent',
            'preferred_branch', 'preferred_branch_name',
            'softech_ptcode', 'softech_ptclassifcode',
            'customer_type_label', 'customer_type_color',
            'total_purchases', 'lifetime_value',
            'notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'softech_id', 'softech_ptcode', 'softech_ptclassifcode',
            'notes_softech', 'created_at', 'updated_at',
        ]


class CustomerUpdateSerializer(serializers.ModelSerializer):
    """Only fields staff are allowed to edit on the platform."""
    class Meta:
        model  = Customer
        fields = [
            'phone', 'phone_alt', 'email', 'address',
            'date_of_birth', 'chronic_conditions', 'preferred_branch',
        ]


class CustomerListSerializer(serializers.ModelSerializer):
    customer_type_label   = serializers.CharField(read_only=True)
    customer_type_color   = serializers.CharField(read_only=True)
    preferred_branch_name = serializers.SerializerMethodField()

    def get_preferred_branch_name(self, obj):
        if obj.preferred_branch:
            return obj.preferred_branch.name_ar or obj.preferred_branch.name
        return None

    class Meta:
        model  = Customer
        fields = [
            'id', 'softech_id',
            'name', 'phone', 'phone_alt',
            'customer_type_label', 'customer_type_color',
            'preferred_branch_name',
            'discount_percent', 'address',
        ]


class CustomerCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Customer
        fields = [
            'name', 'phone', 'phone_alt', 'email', 'address',
            'date_of_birth', 'chronic_conditions', 'preferred_branch',
        ]
