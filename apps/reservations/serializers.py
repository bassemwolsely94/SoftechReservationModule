from rest_framework import serializers
from .models import Reservation, ReservationStatusLog, ReservationActivity, ReservationDownpayment


# ── Status Log ────────────────────────────────────────────────────────────────

class ReservationStatusLogSerializer(serializers.ModelSerializer):
    changed_by_name = serializers.CharField(source='changed_by.full_name', read_only=True)
    changed_by_username = serializers.CharField(source='changed_by.user.username', read_only=True)
    old_status_label = serializers.SerializerMethodField()
    new_status_label = serializers.SerializerMethodField()

    STATUS_LABELS = dict(Reservation.STATUS_CHOICES)

    def get_old_status_label(self, obj):
        return self.STATUS_LABELS.get(obj.old_status, obj.old_status)

    def get_new_status_label(self, obj):
        return self.STATUS_LABELS.get(obj.new_status, obj.new_status)

    class Meta:
        model = ReservationStatusLog
        fields = [
            'id', 'old_status', 'old_status_label',
            'new_status', 'new_status_label',
            'changed_by_name', 'changed_by_username',
            'note', 'changed_at',
        ]


# ── Activity / Chatter ────────────────────────────────────────────────────────

class ReservationActivitySerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True)
    created_by_id   = serializers.IntegerField(source='created_by.id',     read_only=True)
    created_by_username = serializers.CharField(
        source='created_by.user.username', read_only=True
    )
    created_by_role   = serializers.CharField(source='created_by.role',        read_only=True)
    created_by_branch = serializers.CharField(source='created_by.branch_name', read_only=True)
    activity_icon     = serializers.CharField(read_only=True)
    activity_label    = serializers.CharField(read_only=True)
    mentioned_users_names = serializers.SerializerMethodField()
    attachment_url    = serializers.SerializerMethodField()
    voice_note_url    = serializers.SerializerMethodField()
    deleted_by_name   = serializers.SerializerMethodField()
    can_delete        = serializers.SerializerMethodField()

    def get_mentioned_users_names(self, obj):
        return [
            {'id': u.id, 'name': u.full_name}
            for u in obj.mentioned_users.all()
        ]

    def get_attachment_url(self, obj):
        if obj.is_deleted or not obj.attachment:
            return None
        request = self.context.get('request')
        return request.build_absolute_uri(obj.attachment.url) if request else None

    def get_voice_note_url(self, obj):
        if obj.is_deleted or not obj.voice_note:
            return None
        request = self.context.get('request')
        return request.build_absolute_uri(obj.voice_note.url) if request else None

    def get_deleted_by_name(self, obj):
        return obj.deleted_by.full_name if obj.deleted_by_id else None

    def get_can_delete(self, obj):
        """True if the requesting user owns this activity or is an admin."""
        if obj.is_deleted:
            return False
        request = self.context.get('request')
        if not request:
            return False
        profile = getattr(request.user, 'staff_profile', None)
        if not profile:
            return False
        if profile.role == 'admin':
            return True
        return obj.created_by_id == profile.id

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.is_deleted:
            # Redact content, keep tombstone metadata
            data['message']       = None
            data['attachment_url'] = None
            data['voice_note_url'] = None
            data['mentioned_users_names'] = []
        return data

    class Meta:
        model = ReservationActivity
        fields = [
            'id',
            'activity_type', 'activity_icon', 'activity_label',
            'message',
            'created_by', 'created_by_id', 'created_by_name', 'created_by_username',
            'created_by_role', 'created_by_branch',
            'created_at',
            'attachment_url',
            'voice_note_url',
            'mentioned_users_names',
            'transfer_request_id_ref',
            'is_deleted', 'deleted_at', 'deleted_by_name',
            'can_delete',
        ]


class ReservationActivityCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReservationActivity
        fields = [
            'activity_type', 'message', 'attachment', 'voice_note',
            'mentioned_users', 'transfer_request_id_ref',
        ]

    def validate(self, data):
        has_message    = bool((data.get('message') or '').strip())
        has_attachment = bool(data.get('attachment'))
        has_voice      = bool(data.get('voice_note'))
        if not has_message and not has_attachment and not has_voice:
            raise serializers.ValidationError(
                'يجب كتابة رسالة أو إرفاق صورة أو تسجيل ملاحظة صوتية'
            )
        return data


# ── Reservation List ──────────────────────────────────────────────────────────

class ReservationListSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()
    customer_phone = serializers.SerializerMethodField()
    item_name = serializers.SerializerMethodField()
    item_softech_id = serializers.SerializerMethodField()
    branch_name = serializers.CharField(source='branch.name_ar', read_only=True)
    branch_id = serializers.IntegerField(source='branch.id', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.full_name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True)
    status_color = serializers.CharField(read_only=True)
    priority_color = serializers.CharField(read_only=True)
    status_label = serializers.CharField(source='status_label_ar', read_only=True)
    image_url = serializers.SerializerMethodField()
    activity_count = serializers.SerializerMethodField()
    is_manual_item = serializers.SerializerMethodField()

    def get_customer_name(self, obj):
        customer = getattr(obj, 'customer', None)
        return getattr(customer, 'name', None) or obj.contact_name or 'عميل'

    def get_customer_phone(self, obj):
        customer = getattr(obj, 'customer', None)
        return getattr(customer, 'phone', None) or obj.contact_phone or ''

    def get_item_name(self, obj):
        if obj.item_id:
            return obj.item.name
        return obj.manual_item_name or '(صنف غير مكوَّد)'

    def get_item_softech_id(self, obj):
        if obj.item_id:
            return obj.item.softech_id
        return None

    def get_is_manual_item(self, obj):
        return not bool(obj.item_id)

    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
        return None

    def get_activity_count(self, obj):
        # Populated via annotation in viewset
        return getattr(obj, 'activity_count', 0)

    def get_item_sale_price(self, obj):
        return float(obj.item.unit_price) if obj.item_id else None

    item_sale_price = serializers.SerializerMethodField()
    channel_label   = serializers.SerializerMethodField()

    def get_channel_label(self, obj):
        return dict(Reservation.CHANNEL_CHOICES).get(obj.channel, obj.channel)

    class Meta:
        model = Reservation
        fields = [
            'id', 'customer_name', 'customer_phone',
            'item_name', 'item_softech_id', 'manual_item_name', 'is_manual_item',
            'item_sale_price',
            'branch_name', 'branch_id',
            'quantity_requested', 'status', 'status_label', 'priority',
            'channel', 'channel_label',
            'contact_phone', 'contact_name',
            'expected_arrival_date', 'follow_up_date',
            'assigned_to_name', 'created_by_name',
            'status_color', 'priority_color',
            'image_url', 'activity_count',
            'created_at', 'updated_at',
        ]


# ── Reservation Detail ────────────────────────────────────────────────────────

class ReservationDetailSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()
    customer_phone = serializers.SerializerMethodField()
    customer_id = serializers.SerializerMethodField()
    item_name = serializers.SerializerMethodField()
    item_softech_id = serializers.SerializerMethodField()
    item_scientific = serializers.SerializerMethodField()
    is_manual_item = serializers.SerializerMethodField()
    branch_name = serializers.CharField(source='branch.name_ar', read_only=True)
    branch_id = serializers.IntegerField(source='branch.id', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.full_name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True)
    status_color = serializers.CharField(read_only=True)
    priority_color = serializers.CharField(read_only=True)
    status_label = serializers.CharField(source='status_label_ar', read_only=True)
    status_logs = ReservationStatusLogSerializer(many=True, read_only=True)
    activities = ReservationActivitySerializer(many=True, read_only=True)
    image_url = serializers.SerializerMethodField()

    # Live stock at all branches for this item
    stock_by_branch = serializers.SerializerMethodField()
    item_sale_price = serializers.SerializerMethodField()
    channel_label   = serializers.SerializerMethodField()

    def get_item_sale_price(self, obj):
        return float(obj.item.unit_price) if obj.item_id else None

    def get_channel_label(self, obj):
        return dict(Reservation.CHANNEL_CHOICES).get(obj.channel, obj.channel)

    def get_customer_name(self, obj):
        customer = getattr(obj, 'customer', None)
        return getattr(customer, 'name', None) or obj.contact_name or 'عميل'

    def get_customer_phone(self, obj):
        customer = getattr(obj, 'customer', None)
        return getattr(customer, 'phone', None) or obj.contact_phone or ''

    def get_customer_id(self, obj):
        customer = getattr(obj, 'customer', None)
        return getattr(customer, 'id', None)

    def get_item_name(self, obj):
        if obj.item_id:
            return obj.item.name
        return obj.manual_item_name or '(صنف غير مكوَّد)'

    def get_item_softech_id(self, obj):
        return obj.item.softech_id if obj.item_id else None

    def get_item_scientific(self, obj):
        return obj.item.name_scientific if obj.item_id else None

    def get_is_manual_item(self, obj):
        return not bool(obj.item_id)

    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
        return None

    def get_stock_by_branch(self, obj):
        if not obj.item_id:
            return []
        from apps.catalog.models import ItemStock, EXCLUDED_STORE_CODES
        from django.db.models import Sum
        # Aggregate quantities per branch, excluding expired-stock stores
        rows = (
            ItemStock.objects
            .filter(item=obj.item)
            .exclude(softech_store_code__in=EXCLUDED_STORE_CODES)
            .select_related('branch')
            .values('branch__id', 'branch__name', 'branch__name_ar')
            .annotate(qty=Sum('quantity_on_hand'))
            .order_by('-qty')
        )
        result = []
        for r in rows:
            qty = float(r['qty'] or 0)
            if qty >= 5:
                stock_status, label = 'in_stock', 'متوفر'
            elif qty > 0:
                stock_status, label = 'low_stock', 'كمية محدودة'
            else:
                stock_status, label = 'out_of_stock', 'غير متوفر'
            result.append({
                'branch_id':   r['branch__id'],
                'branch_name': r['branch__name_ar'] or r['branch__name'],
                'quantity':    qty,
                'status':      stock_status,
                'status_label': label,
            })
        return result

    class Meta:
        model = Reservation
        fields = [
            'id', 'customer', 'customer_id', 'customer_name', 'customer_phone',
            'item', 'item_name', 'item_softech_id', 'item_scientific',
            'item_sale_price',
            'manual_item_name', 'is_manual_item',
            'branch', 'branch_name', 'branch_id',
            'assigned_to', 'assigned_to_name',
            'created_by_name',
            'quantity_requested', 'status', 'status_label', 'priority',
            'channel', 'channel_label',
            'contact_phone', 'contact_name', 'notes',
            'expected_arrival_date', 'follow_up_date',
            'softech_reserve_id', 'status_color', 'priority_color',
            'image_url',
            'stock_by_branch',
            'status_logs',
            'activities',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['softech_reserve_id', 'created_at', 'updated_at']


# ── Create / Update ───────────────────────────────────────────────────────────

class ReservationCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reservation
        fields = [
            'customer', 'item', 'manual_item_name', 'branch', 'assigned_to',
            'quantity_requested', 'priority', 'channel',
            'contact_phone', 'contact_name',
            'notes', 'expected_arrival_date', 'follow_up_date', 'image',
        ]

    def validate_quantity_requested(self, value):
        if value <= 0:
            raise serializers.ValidationError('الكمية يجب أن تكون أكبر من صفر')
        return value

    def validate(self, data):
        has_item        = bool(data.get('item'))
        has_manual_name = bool((data.get('manual_item_name') or '').strip())
        if not has_item and not has_manual_name:
            raise serializers.ValidationError(
                {'item': 'يجب تحديد صنف من القائمة أو إدخال اسم الصنف يدوياً'}
            )
        return data


class ReservationUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reservation
        fields = [
            'branch', 'item', 'manual_item_name',
            'assigned_to', 'quantity_requested', 'priority', 'channel',
            'contact_phone', 'contact_name', 'notes',
            'expected_arrival_date', 'follow_up_date', 'image',
        ]


class ChangeStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[s[0] for s in Reservation.STATUS_CHOICES])
    note = serializers.CharField(required=False, allow_blank=True)


class ReservationDownpaymentSerializer(serializers.ModelSerializer):
    received_by_name = serializers.CharField(source='received_by.full_name', read_only=True)
    payment_method_label = serializers.CharField(
        source='get_payment_method_display', read_only=True
    )

    class Meta:
        model = ReservationDownpayment
        fields = [
            'id', 'amount', 'payment_method', 'payment_method_label',
            'reference_number', 'notes',
            'received_by_name', 'received_at',
        ]
        read_only_fields = ['received_at']


class ReservationDownpaymentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReservationDownpayment
        fields = ['amount', 'payment_method', 'reference_number', 'notes']

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError('المبلغ يجب أن يكون أكبر من صفر')
        return value
