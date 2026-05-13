from rest_framework import serializers
from .models import Voucher, VoucherOTP, VoucherRedemption


class VoucherListSerializer(serializers.ModelSerializer):
    customer_name   = serializers.CharField(source='customer.name', read_only=True, default=None)
    branch_name     = serializers.CharField(source='branch.name_ar', read_only=True, default=None)
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True, default=None)
    free_item_name  = serializers.CharField(source='free_item.name', read_only=True, default=None)
    type_label      = serializers.SerializerMethodField()
    status_label    = serializers.SerializerMethodField()
    is_expired      = serializers.BooleanField(read_only=True)
    is_exhausted    = serializers.BooleanField(read_only=True)

    TYPE_LABELS   = dict(Voucher.TYPE_CHOICES)
    STATUS_LABELS = dict(Voucher.STATUS_CHOICES)

    def get_type_label(self, obj):
        return self.TYPE_LABELS.get(obj.voucher_type, obj.voucher_type)

    def get_status_label(self, obj):
        return self.STATUS_LABELS.get(obj.status, obj.status)

    class Meta:
        model  = Voucher
        fields = [
            'id', 'code', 'title', 'description',
            'voucher_type', 'type_label',
            'discount_pct', 'discount_amount', 'credit_amount',
            'free_item', 'free_item_name',
            'customer', 'customer_name',
            'branch', 'branch_name',
            'valid_from', 'valid_until',
            'max_uses', 'times_used',
            'status', 'status_label',
            'is_expired', 'is_exhausted',
            'created_by_name', 'notes',
            'created_at', 'updated_at',
        ]


class VoucherCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Voucher
        fields = [
            'title', 'description', 'voucher_type',
            'discount_pct', 'discount_amount', 'credit_amount',
            'free_item', 'customer', 'branch',
            'valid_from', 'valid_until',
            'max_uses', 'notes',
        ]

    def validate(self, data):
        vtype = data.get('voucher_type')
        if vtype == 'discount_pct' and not data.get('discount_pct'):
            raise serializers.ValidationError({'discount_pct': 'نسبة الخصم مطلوبة'})
        if vtype == 'discount_fixed' and not data.get('discount_amount'):
            raise serializers.ValidationError({'discount_amount': 'مبلغ الخصم مطلوب'})
        if vtype == 'credit' and not data.get('credit_amount'):
            raise serializers.ValidationError({'credit_amount': 'قيمة الرصيد مطلوبة'})
        if vtype == 'free_item' and not data.get('free_item'):
            raise serializers.ValidationError({'free_item': 'حدد الصنف المجاني'})
        return data


class VoucherOTPSerializer(serializers.ModelSerializer):
    class Meta:
        model  = VoucherOTP
        fields = ['id', 'phone', 'is_used', 'is_expired', 'expires_at', 'created_at', 'sent_via']
        read_only_fields = ['is_used', 'expires_at', 'created_at']


class VoucherRedemptionSerializer(serializers.ModelSerializer):
    redeemed_by_name = serializers.CharField(source='redeemed_by.full_name', read_only=True, default=None)
    branch_name      = serializers.CharField(source='branch.name_ar', read_only=True, default=None)

    class Meta:
        model  = VoucherRedemption
        fields = ['id', 'voucher', 'redeemed_by_name', 'branch_name', 'redeemed_at', 'notes']


class GenerateOTPSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)


class VerifyOTPSerializer(serializers.Serializer):
    code  = serializers.CharField(max_length=10)
    phone = serializers.CharField(max_length=20)
