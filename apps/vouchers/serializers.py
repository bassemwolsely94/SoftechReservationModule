"""
apps/vouchers/serializers.py

Field-level security:
  - OTP plain code NEVER serialized
  - customer_phone masked for non-PII roles in document serializer
"""
from rest_framework import serializers
from .models import (
    Voucher, VoucherAssignment, VoucherOTP,
    VoucherRedemptionDocument, VoucherRedemption,
)


# ── Voucher ────────────────────────────────────────────────────────────────────

class VoucherListSerializer(serializers.ModelSerializer):
    customer_name    = serializers.CharField(source='customer.name',      read_only=True, default=None)
    branch_name      = serializers.CharField(source='branch.name_ar',     read_only=True, default=None)
    created_by_name  = serializers.CharField(source='created_by.full_name', read_only=True, default=None)
    free_item_name   = serializers.CharField(source='free_item.name',     read_only=True, default=None)
    type_label       = serializers.SerializerMethodField()
    category_label   = serializers.SerializerMethodField()
    status_label     = serializers.SerializerMethodField()
    is_expired       = serializers.BooleanField(read_only=True)
    is_exhausted     = serializers.BooleanField(read_only=True)
    value_display    = serializers.SerializerMethodField()
    # Targeting restrictions — needed by the redeem UI to gate item/branch (TD-M006)
    applicable_items_detail = serializers.SerializerMethodField()

    TYPE_LABELS     = dict(Voucher.TYPE_CHOICES)
    CATEGORY_LABELS = dict(Voucher.CATEGORY_CHOICES)
    STATUS_LABELS   = dict(Voucher.STATUS_CHOICES)

    def get_type_label(self, obj):
        return self.TYPE_LABELS.get(obj.voucher_type, obj.voucher_type)

    def get_category_label(self, obj):
        return self.CATEGORY_LABELS.get(obj.voucher_category, obj.voucher_category)

    def get_status_label(self, obj):
        return self.STATUS_LABELS.get(obj.status, obj.status)

    def get_value_display(self, obj):
        """Human-readable discount value."""
        if obj.voucher_type == 'discount_pct':
            return f'{obj.discount_pct}%'
        if obj.voucher_type == 'discount_fixed':
            return f'{float(obj.discount_amount):.2f} ج.م'
        if obj.voucher_type == 'credit':
            return f'{float(obj.credit_amount):.2f} ج.م'
        if obj.voucher_type == 'free_item':
            return obj.free_item.name if obj.free_item_id else '—'
        return '—'

    def get_applicable_items_detail(self, obj):
        """[{id, name}] for the voucher's eligible items (empty ⇒ unrestricted)."""
        return [{'id': i.id, 'name': i.name} for i in obj.applicable_items.all()]

    class Meta:
        model  = Voucher
        fields = [
            'id', 'code', 'title', 'description',
            'voucher_category', 'category_label',
            'voucher_type', 'type_label', 'value_display',
            'discount_pct', 'discount_amount', 'credit_amount',
            'free_item', 'free_item_name',
            'max_discount_cap', 'min_order_value',
            'customer', 'customer_name',
            'branch', 'branch_name',
            'applicable_items', 'applicable_items_detail', 'applicable_branches',
            'valid_from', 'valid_until',
            'max_uses', 'times_used',
            'usage_limit_per_customer', 'usage_limit_per_day',
            'validity_days_after_assignment',
            'status', 'status_label',
            'is_expired', 'is_exhausted',
            'created_by_name', 'notes',
            'created_at', 'updated_at',
        ]


class VoucherCreateSerializer(serializers.ModelSerializer):
    # Gap-7: id and code are server-generated and read-only.
    # They are included here so the 201 response gives the client everything
    # it needs to display/navigate to the newly created voucher immediately,
    # without a follow-up GET request.
    id   = serializers.IntegerField(read_only=True)
    code = serializers.CharField(read_only=True)

    class Meta:
        model  = Voucher
        fields = [
            'id', 'code',   # read-only — returned in 201 response
            'title', 'description',
            'voucher_category', 'voucher_type',
            'discount_pct', 'discount_amount', 'credit_amount',
            'free_item', 'max_discount_cap', 'min_order_value',
            'customer', 'branch',
            'applicable_items', 'applicable_branches',
            'valid_from', 'valid_until',
            'max_uses', 'usage_limit_per_customer', 'usage_limit_per_day',
            'validity_days_after_assignment', 'notes',
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

        # Date validation
        vf = data.get('valid_from')
        vu = data.get('valid_until')
        if vf and vu and vu < vf:
            raise serializers.ValidationError({'valid_until': 'تاريخ الانتهاء يجب أن يكون بعد تاريخ البدء'})
        return data


# ── VoucherAssignment ─────────────────────────────────────────────────────────

class VoucherAssignmentSerializer(serializers.ModelSerializer):
    assigned_by_name = serializers.CharField(source='assigned_by.full_name',
                                              read_only=True, default=None)
    customer_name    = serializers.CharField(source='customer.name',
                                              read_only=True, default=None)

    class Meta:
        model  = VoucherAssignment
        fields = [
            'id', 'voucher', 'customer_phone', 'customer', 'customer_name',
            'assigned_by_name', 'assigned_at', 'expires_at',
            'usage_count', 'is_active',
        ]
        read_only_fields = ['assigned_at', 'usage_count']


class VoucherAssignmentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = VoucherAssignment
        fields = ['customer_phone', 'customer', 'expires_at']

    def validate_customer_phone(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError('رقم الهاتف مطلوب')
        return value.strip()


# ── VoucherOTP (read-only — never expose code_hash or otp_salt) ───────────────

class VoucherOTPSerializer(serializers.ModelSerializer):
    """Safe read-only serializer — code_hash and otp_salt are EXCLUDED."""
    class Meta:
        model  = VoucherOTP
        fields = [
            'id', 'phone', 'is_used', 'is_expired', 'is_valid',
            'expires_at', 'created_at', 'sent_via',
            'retry_count', 'resend_count',
        ]
        read_only_fields = fields


# ── VoucherRedemptionDocument ─────────────────────────────────────────────────

class VoucherRedemptionDocumentSerializer(serializers.ModelSerializer):
    voucher_code     = serializers.CharField(source='voucher.code',       read_only=True)
    voucher_title    = serializers.CharField(source='voucher.title',      read_only=True)
    voucher_type     = serializers.CharField(source='voucher.voucher_type', read_only=True)
    value_display    = serializers.SerializerMethodField()
    employee_name    = serializers.CharField(source='employee.full_name', read_only=True, default=None)
    branch_name      = serializers.CharField(source='branch.name_ar',     read_only=True, default=None)
    status_label     = serializers.SerializerMethodField()
    minutes_left     = serializers.SerializerMethodField()
    is_document_expired = serializers.BooleanField(read_only=True)
    customer_phone_masked = serializers.SerializerMethodField()

    STATUS_LABELS = {'active': 'نشط', 'used': 'مُستخدَم', 'expired': 'منتهي', 'cancelled': 'ملغى'}

    def get_status_label(self, obj):
        return self.STATUS_LABELS.get(obj.status, obj.status)

    def get_minutes_left(self, obj):
        from django.utils import timezone
        if obj.status != 'active':
            return 0
        remaining = (obj.expires_at - timezone.now()).total_seconds()
        return max(0, int(remaining / 60))

    def get_value_display(self, obj):
        v = obj.voucher
        if v.voucher_type == 'discount_pct':
            return f'{v.discount_pct}%'
        if v.voucher_type == 'discount_fixed':
            return f'{float(v.discount_amount):.2f} ج.م'
        if v.voucher_type == 'credit':
            return f'{float(v.credit_amount):.2f} ج.م'
        return '—'

    def get_customer_phone_masked(self, obj):
        """Mask middle digits: 010XXXXX789 → 010****789"""
        p = obj.customer_phone or ''
        if len(p) >= 7:
            return p[:3] + '*' * (len(p) - 6) + p[-3:]
        return p

    class Meta:
        model  = VoucherRedemptionDocument
        fields = [
            'id', 'reference_code',
            'voucher', 'voucher_code', 'voucher_title', 'voucher_type', 'value_display',
            'customer_phone', 'customer_phone_masked',
            'employee_name', 'branch_name',
            'generated_at', 'expires_at', 'used_at',
            'status', 'status_label', 'minutes_left', 'is_document_expired',
            'discount_applied', 'order_amount',
            'notes',
        ]


# ── VoucherRedemption (audit) ─────────────────────────────────────────────────

class VoucherRedemptionSerializer(serializers.ModelSerializer):
    redeemed_by_name  = serializers.CharField(source='redeemed_by.full_name',
                                               read_only=True, default=None)
    branch_name       = serializers.CharField(source='branch.name_ar',
                                               read_only=True, default=None)
    voucher_code      = serializers.CharField(source='voucher.code', read_only=True)
    reference_code    = serializers.CharField(source='document.reference_code',
                                               read_only=True, default=None)

    class Meta:
        model  = VoucherRedemption
        fields = [
            'id', 'voucher', 'voucher_code', 'reference_code',
            'customer_phone', 'redeemed_by_name', 'branch_name',
            'redeemed_at', 'discount_applied', 'order_amount', 'notes',
        ]


# ── Action serializers ────────────────────────────────────────────────────────

# item_ids — the order's catalog item ids; required to redeem an item-restricted
# voucher (TD-M006). Optional for unrestricted vouchers.
def _item_ids_field():
    return serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list,
    )


class GenerateOTPSerializer(serializers.Serializer):
    phone        = serializers.CharField(max_length=20)
    order_amount = serializers.DecimalField(max_digits=10, decimal_places=3,
                                             required=False, allow_null=True)
    item_ids     = _item_ids_field()

    def validate_phone(self, value):
        v = value.strip()
        if not v:
            raise serializers.ValidationError('رقم الهاتف مطلوب')
        return v


class VerifyOTPSerializer(serializers.Serializer):
    code         = serializers.CharField(max_length=10)
    phone        = serializers.CharField(max_length=20)
    order_amount = serializers.DecimalField(max_digits=10, decimal_places=3,
                                             required=False, allow_null=True)
    item_ids     = _item_ids_field()

    def validate_code(self, value):
        v = value.strip()
        if not v.isdigit() or len(v) != 6:
            raise serializers.ValidationError('الرمز يجب أن يكون 6 أرقام')
        return v


class ValidateVoucherSerializer(serializers.Serializer):
    phone        = serializers.CharField(max_length=20)
    order_amount = serializers.DecimalField(max_digits=10, decimal_places=3,
                                             required=False, allow_null=True)
    item_ids     = _item_ids_field()


class MarkUsedSerializer(serializers.Serializer):
    reference_code = serializers.CharField(max_length=20)
    order_amount   = serializers.DecimalField(max_digits=10, decimal_places=3,
                                               required=False, allow_null=True)
    notes          = serializers.CharField(max_length=300, required=False, allow_blank=True)
