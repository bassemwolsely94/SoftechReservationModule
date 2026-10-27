from rest_framework import serializers
from .models import Reservation, ReservationStatusLog, ReservationActivity, ReservationDownpayment, ReservationImage, ReservationLine


# ── Reservation Images ────────────────────────────────────────────────────────

class ReservationImageSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    uploaded_by_name = serializers.CharField(source='uploaded_by.full_name', read_only=True)

    def get_image_url(self, obj):
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.image.url)
        return obj.image.url

    class Meta:
        model = ReservationImage
        fields = ['id', 'image_url', 'uploaded_by_name', 'uploaded_at']


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


# ── Reservation Lines (basket) ────────────────────────────────────────────────
# Defined here — before ReservationDetailSerializer which embeds them.

class ReservationLineSerializer(serializers.ModelSerializer):
    item_name = serializers.SerializerMethodField()
    item_softech_id = serializers.SerializerMethodField()
    item_sale_price = serializers.SerializerMethodField()

    def get_item_name(self, obj):
        return obj.item.name if obj.item_id else obj.manual_item_name or '(صنف غير مكوَّد)'

    def get_item_softech_id(self, obj):
        return obj.item.softech_id if obj.item_id else None

    def get_item_sale_price(self, obj):
        if not obj.item_id:
            return None
        price = obj.item.pack_price
        return float(price) if price is not None else None

    class Meta:
        model = ReservationLine
        fields = [
            'id', 'item', 'item_name', 'item_softech_id', 'item_sale_price',
            'manual_item_name', 'quantity_requested', 'notes', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class ReservationLineCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReservationLine
        fields = ['item', 'manual_item_name', 'quantity_requested', 'notes']

    def validate(self, data):
        has_item = bool(data.get('item'))
        has_manual = bool((data.get('manual_item_name') or '').strip())
        if not has_item and not has_manual:
            raise serializers.ValidationError(
                {'item': 'يجب تحديد صنف أو إدخال اسمه يدوياً'}
            )
        if data.get('quantity_requested', 1) <= 0:
            raise serializers.ValidationError({'quantity_requested': 'الكمية يجب أن تكون أكبر من صفر'})
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
    lines_count = serializers.SerializerMethodField()
    lines = serializers.SerializerMethodField()

    def get_lines(self, obj):
        return [
            {
                'id': line.pk,
                'item_name': line.item.name if line.item_id else (line.manual_item_name or '—'),
                'item_softech_id': line.item.softech_id if line.item_id else None,
                'quantity_requested': float(line.quantity_requested),
            }
            for line in obj.lines.select_related('item').all()
        ]

    def get_customer_name(self, obj):
        customer = getattr(obj, 'customer', None)
        return getattr(customer, 'name', None) or obj.contact_name or 'عميل'

    def get_customer_phone(self, obj):
        customer = getattr(obj, 'customer', None)
        return getattr(customer, 'phone', None) or obj.contact_phone or ''

    def get_customer_softech_pic(self, obj):
        customer = getattr(obj, 'customer', None)
        return getattr(customer, 'softech_pic', None)

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

    def get_lines_count(self, obj):
        # Populated via annotation in viewset (lines__count); fall back to queryset count
        annotated = getattr(obj, 'lines_count', None)
        if annotated is not None:
            return annotated
        return obj.lines.count()

    def get_item_sale_price(self, obj):
        if not obj.item_id:
            return None
        price = obj.item.pack_price
        return float(price) if price is not None else None

    item_sale_price         = serializers.SerializerMethodField()
    customer_softech_pic    = serializers.SerializerMethodField()
    channel_label           = serializers.SerializerMethodField()
    contract_subtype_label  = serializers.SerializerMethodField()
    channel_display         = serializers.SerializerMethodField()

    def get_channel_label(self, obj):
        return dict(Reservation.CHANNEL_CHOICES).get(obj.channel, obj.channel)

    def get_contract_subtype_label(self, obj):
        if not obj.contract_subtype:
            return ''
        return dict(Reservation.CONTRACT_SUBTYPE_CHOICES).get(obj.contract_subtype, obj.contract_subtype)

    def get_channel_display(self, obj):
        """Full display: 'بيع بالكنتراكت — تأمين صحي' or 'بيع نقدي / كاش (F2)'"""
        base = dict(Reservation.CHANNEL_CHOICES).get(obj.channel, obj.channel)
        if obj.channel == 'contract_sales' and obj.contract_subtype:
            sub = dict(Reservation.CONTRACT_SUBTYPE_CHOICES).get(obj.contract_subtype, obj.contract_subtype)
            return f'{base} — {sub}'
        return base

    class Meta:
        model = Reservation
        fields = [
            'id', 'customer_name', 'customer_phone', 'customer_softech_pic',
            'item_name', 'item_softech_id', 'manual_item_name', 'is_manual_item',
            'item_sale_price',
            'branch_name', 'branch_id',
            'quantity_requested', 'status', 'status_label', 'priority',
            'channel', 'channel_label', 'contract_subtype', 'contract_subtype_label', 'channel_display',
            'order_source', 'fulfillment_method',
            'contact_phone', 'contact_name',
            'expected_arrival_date', 'follow_up_date',
            'assigned_to_name', 'created_by_name',
            'status_color', 'priority_color',
            'image_url', 'activity_count', 'lines_count', 'lines',
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
    images = ReservationImageSerializer(many=True, read_only=True)
    image_url = serializers.SerializerMethodField()

    lines = ReservationLineSerializer(many=True, read_only=True)

    # Live stock at all branches for this item
    stock_by_branch      = serializers.SerializerMethodField()
    item_sale_price      = serializers.SerializerMethodField()
    customer_softech_pic = serializers.SerializerMethodField()
    channel_label        = serializers.SerializerMethodField()
    contract_subtype_label = serializers.SerializerMethodField()
    channel_display      = serializers.SerializerMethodField()
    can_check_erp_match  = serializers.SerializerMethodField()

    def get_can_check_erp_match(self, obj):
        """True when admin/pharmacist can trigger ERP match on a fulfilled reservation."""
        if obj.status != 'fulfilled':
            return False
        request = self.context.get('request')
        if not request:
            return False
        profile = getattr(request.user, 'staff_profile', None)
        return profile is not None and profile.role in ('admin', 'pharmacist', 'purchasing')

    def get_item_sale_price(self, obj):
        if not obj.item_id:
            return None
        price = obj.item.pack_price
        return float(price) if price is not None else None

    def get_channel_label(self, obj):
        return dict(Reservation.CHANNEL_CHOICES).get(obj.channel, obj.channel)

    def get_contract_subtype_label(self, obj):
        if not obj.contract_subtype:
            return ''
        return dict(Reservation.CONTRACT_SUBTYPE_CHOICES).get(obj.contract_subtype, obj.contract_subtype)

    def get_channel_display(self, obj):
        base = dict(Reservation.CHANNEL_CHOICES).get(obj.channel, obj.channel)
        if obj.channel == 'contract_sales' and obj.contract_subtype:
            sub = dict(Reservation.CONTRACT_SUBTYPE_CHOICES).get(obj.contract_subtype, obj.contract_subtype)
            return f'{base} — {sub}'
        return base

    def get_customer_name(self, obj):
        customer = getattr(obj, 'customer', None)
        return getattr(customer, 'name', None) or obj.contact_name or 'عميل'

    def get_customer_phone(self, obj):
        customer = getattr(obj, 'customer', None)
        return getattr(customer, 'phone', None) or obj.contact_phone or ''

    def get_customer_softech_pic(self, obj):
        customer = getattr(obj, 'customer', None)
        return getattr(customer, 'softech_pic', None)

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
            'id', 'customer', 'customer_id', 'customer_name', 'customer_phone', 'customer_softech_pic',
            'item', 'item_name', 'item_softech_id', 'item_scientific',
            'item_sale_price',
            'manual_item_name', 'is_manual_item',
            'branch', 'branch_name', 'branch_id',
            'assigned_to', 'assigned_to_name',
            'created_by_name',
            'quantity_requested', 'status', 'status_label', 'priority',
            'channel', 'channel_label', 'contract_subtype', 'contract_subtype_label', 'channel_display',
            'order_source', 'fulfillment_method',
            'contact_phone', 'contact_name', 'notes',
            'expected_arrival_date', 'follow_up_date',
            'softech_reserve_id', 'status_color', 'priority_color',
            'image_url', 'images',
            'stock_by_branch',
            'status_logs',
            'activities',
            'created_at', 'updated_at',
            # ERP match fields
            'erp_reference',
            'erp_match_status', 'erp_match_detail',
            'erp_last_checked', 'erp_check_attempts', 'erp_matched_at',
            'erp_match_doc_code', 'erp_match_doc_date', 'erp_match_doc_value',
            'erp_match_user_code', 'erp_match_user_id', 'erp_match_user_name',
            'erp_match_trans_time', 'erp_match_store_code', 'erp_matched_items',
            'erp_receipt_lines', 'erp_customer_info',
            'can_check_erp_match',
            'lines',
        ]
        read_only_fields = ['softech_reserve_id', 'created_at', 'updated_at']


# ── Create / Update ───────────────────────────────────────────────────────────

class ReservationCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reservation
        fields = [
            'id',
            'customer', 'item', 'manual_item_name', 'branch', 'assigned_to',
            'quantity_requested', 'priority', 'channel', 'contract_subtype',
            'order_source', 'fulfillment_method',
            'contact_phone', 'contact_name',
            'notes', 'expected_arrival_date', 'follow_up_date', 'image',
        ]
        read_only_fields = ['id']

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
            'assigned_to', 'quantity_requested', 'priority', 'channel', 'contract_subtype',
            'order_source', 'fulfillment_method',
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


# ── Bulk actions ───────────────────────────────────────────────────────────────

class BulkActionSerializer(serializers.Serializer):
    ACTION_CHOICES = ['assign', 'change_status', 'export']
    action = serializers.ChoiceField(choices=ACTION_CHOICES)
    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        max_length=200,
    )
    # For assign
    assigned_to = serializers.IntegerField(required=False, allow_null=True)
    # For change_status
    status = serializers.ChoiceField(
        choices=[s[0] for s in Reservation.STATUS_CHOICES],
        required=False,
    )
    note = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, data):
        if data['action'] == 'change_status' and not data.get('status'):
            raise serializers.ValidationError({'status': 'الحالة مطلوبة لهذا الإجراء'})
        return data
