from rest_framework import serializers
from .models import TransferRequest, TransferRequestItem, TransferRequestMessage
from apps.catalog.models import ItemStock


# ── Item line serializers ─────────────────────────────────────────────────────

class TransferRequestItemSerializer(serializers.ModelSerializer):
    item_name       = serializers.CharField(source='item.name',             read_only=True)
    item_softech_id = serializers.CharField(source='item.softech_id',       read_only=True)
    item_scientific = serializers.CharField(source='item.name_scientific',  read_only=True)
    item_sale_price = serializers.DecimalField(
        source='item.unit_price', max_digits=10, decimal_places=3, read_only=True
    )
    available_stock = serializers.FloatField(
        source='available_stock_at_destination', read_only=True
    )

    class Meta:
        model  = TransferRequestItem
        fields = [
            'id', 'item', 'item_name', 'item_softech_id', 'item_scientific',
            'item_sale_price', 'quantity', 'notes', 'available_stock',
        ]


class TransferRequestItemWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model  = TransferRequestItem
        fields = ['item', 'quantity', 'notes']

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError('الكمية يجب أن تكون أكبر من صفر')
        return value


# ── Message serializers ───────────────────────────────────────────────────────

class TransferRequestMessageSerializer(serializers.ModelSerializer):
    created_by_name   = serializers.CharField(source='created_by.full_name', read_only=True)
    created_by_id     = serializers.IntegerField(source='created_by.id',     read_only=True)
    created_by_role   = serializers.CharField(source='created_by.role',      read_only=True)
    created_by_branch = serializers.CharField(source='created_by.branch_name', read_only=True)
    type_icon         = serializers.SerializerMethodField()
    attachment_url    = serializers.SerializerMethodField()
    voice_note_url    = serializers.SerializerMethodField()
    deleted_by_name   = serializers.SerializerMethodField()
    can_delete        = serializers.SerializerMethodField()

    def get_type_icon(self, obj):
        return {'message': '💬', 'system': '⚙️', 'note': '📝'}.get(obj.message_type, '💬')

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
        if obj.is_deleted or obj.message_type == 'system':
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
            data['message']        = None
            data['attachment_url'] = None
            data['voice_note_url'] = None
        return data

    class Meta:
        model  = TransferRequestMessage
        fields = [
            'id', 'message_type', 'type_icon', 'message',
            'created_by', 'created_by_id', 'created_by_name',
            'created_by_role', 'created_by_branch',
            'created_at',
            'attachment_url', 'voice_note_url',
            'is_deleted', 'deleted_at', 'deleted_by_name',
            'can_delete',
        ]
        read_only_fields = ['created_at', 'created_by']


class TransferRequestMessageCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = TransferRequestMessage
        fields = ['message_type', 'message', 'attachment', 'voice_note']

    def validate(self, data):
        has_message    = bool((data.get('message') or '').strip())
        has_attachment = bool(data.get('attachment'))
        has_voice      = bool(data.get('voice_note'))
        if not has_message and not has_attachment and not has_voice:
            raise serializers.ValidationError(
                'يجب كتابة رسالة أو إرفاق صورة أو تسجيل ملاحظة صوتية'
            )
        return data


# ── Request list serializer ───────────────────────────────────────────────────

class TransferRequestListSerializer(serializers.ModelSerializer):
    requesting_branch_name = serializers.SerializerMethodField()
    supplying_branch_name  = serializers.SerializerMethodField()
    created_by_name        = serializers.SerializerMethodField()
    reviewed_by_name       = serializers.SerializerMethodField()
    status_label           = serializers.CharField(source='status_label_ar', read_only=True)
    status_color           = serializers.CharField(read_only=True)
    total_items            = serializers.SerializerMethodField()

    def get_requesting_branch_name(self, obj):
        b = obj.requesting_branch
        return (b.name_ar or b.name) if b else '—'

    def get_supplying_branch_name(self, obj):
        b = obj.supplying_branch
        return (b.name_ar or b.name) if b else '—'

    def get_created_by_name(self, obj):
        return obj.created_by.full_name if obj.created_by_id else '—'

    def get_reviewed_by_name(self, obj):
        return obj.reviewed_by.full_name if obj.reviewed_by_id else None

    def get_total_items(self, obj):
        return obj.items.count()

    class Meta:
        model  = TransferRequest
        fields = [
            'id', 'request_number',
            'requesting_branch', 'requesting_branch_name',
            'supplying_branch', 'supplying_branch_name',
            'status', 'status_label', 'status_color',
            'created_by_name', 'reviewed_by_name',
            'total_items',
            'notes',
            'created_at', 'updated_at', 'submitted_at',
        ]


# ── Request detail serializer ─────────────────────────────────────────────────

class TransferRequestDetailSerializer(serializers.ModelSerializer):
    requesting_branch_name = serializers.SerializerMethodField()
    supplying_branch_name  = serializers.SerializerMethodField()
    requesting_branch_id   = serializers.SerializerMethodField()
    supplying_branch_id    = serializers.SerializerMethodField()
    created_by_name        = serializers.SerializerMethodField()
    created_by_branch      = serializers.SerializerMethodField()
    reviewed_by_name       = serializers.SerializerMethodField()
    sent_to_erp_by_name    = serializers.SerializerMethodField()
    dispatched_by_name     = serializers.SerializerMethodField()

    def get_requesting_branch_name(self, obj):
        b = obj.requesting_branch
        return (b.name_ar or b.name) if b else '—'

    def get_supplying_branch_name(self, obj):
        b = obj.supplying_branch
        return (b.name_ar or b.name) if b else '—'

    def get_requesting_branch_id(self, obj):
        return obj.requesting_branch_id

    def get_supplying_branch_id(self, obj):
        return obj.supplying_branch_id

    def get_created_by_name(self, obj):
        return obj.created_by.full_name if obj.created_by_id else '—'

    def get_created_by_branch(self, obj):
        return obj.created_by.branch_name if obj.created_by_id else None

    def get_reviewed_by_name(self, obj):
        return obj.reviewed_by.full_name if obj.reviewed_by_id else None

    def get_sent_to_erp_by_name(self, obj):
        return obj.sent_to_erp_by.full_name if obj.sent_to_erp_by_id else None

    def get_dispatched_by_name(self, obj):
        return obj.dispatched_by.full_name if obj.dispatched_by_id else None
    status_label            = serializers.CharField(source='status_label_ar', read_only=True)
    status_color            = serializers.CharField(read_only=True)
    items                   = TransferRequestItemSerializer(many=True, read_only=True)
    messages                = serializers.SerializerMethodField()

    # ── RBAC-aware action flags ───────────────────────────────────────────────
    # Rules:
    #   is_editable / can_submit / can_cancel : requesting branch + HQ
    #   can_approve / can_reject / can_request_revision / can_send_to_erp / can_dispatch :
    #       supplying branch + HQ
    #   can_complete : requesting branch + HQ (they receive the goods)

    is_editable          = serializers.SerializerMethodField()
    can_submit           = serializers.SerializerMethodField()
    can_approve          = serializers.SerializerMethodField()
    can_reject           = serializers.SerializerMethodField()
    can_request_revision = serializers.SerializerMethodField()
    can_send_to_erp      = serializers.SerializerMethodField()
    can_dispatch         = serializers.SerializerMethodField()
    can_cancel           = serializers.SerializerMethodField()
    can_complete         = serializers.SerializerMethodField()

    def _profile(self):
        request = self.context.get('request')
        return getattr(request.user, 'staff_profile', None) if request else None

    def _is_hq(self, profile):
        return profile and profile.role in ('admin', 'purchasing', 'call_center')

    def _is_requesting_side(self, profile, obj):
        """Requesting branch staff OR HQ."""
        if not profile:
            return False
        if self._is_hq(profile):
            return True
        return bool(profile.branch_id and profile.branch_id == obj.requesting_branch_id)

    def _is_supplying_side(self, profile, obj):
        """Supplying branch staff OR HQ (admin/purchasing only, not call_center)."""
        if not profile:
            return False
        if profile.role in ('admin', 'purchasing'):
            return True
        return bool(profile.branch_id and profile.branch_id == obj.supplying_branch_id)

    def get_messages(self, obj):
        msgs = obj.messages.select_related('created_by__user').order_by('created_at')
        return TransferRequestMessageSerializer(
            msgs, many=True, context=self.context
        ).data

    def get_is_editable(self, obj):
        return obj.is_editable and self._is_requesting_side(self._profile(), obj)

    def get_can_submit(self, obj):
        return obj.can_submit and self._is_requesting_side(self._profile(), obj)

    def get_can_approve(self, obj):
        return obj.can_approve and self._is_supplying_side(self._profile(), obj)

    def get_can_reject(self, obj):
        return obj.can_reject and self._is_supplying_side(self._profile(), obj)

    def get_can_request_revision(self, obj):
        return obj.can_request_revision and self._is_supplying_side(self._profile(), obj)

    def get_can_send_to_erp(self, obj):
        return obj.can_send_to_erp and self._is_supplying_side(self._profile(), obj)

    def get_can_dispatch(self, obj):
        return obj.can_dispatch and self._is_supplying_side(self._profile(), obj)

    def get_can_cancel(self, obj):
        return obj.can_cancel and self._is_requesting_side(self._profile(), obj)

    def get_can_complete(self, obj):
        return (obj.status == 'sent_to_erp') and self._is_requesting_side(self._profile(), obj)

    # Live stock at destination for all items
    destination_stock = serializers.SerializerMethodField()

    def get_destination_stock(self, obj):
        if not obj.supplying_branch_id:
            return {}
        from apps.catalog.models import EXCLUDED_STORE_CODES
        from django.db.models import Sum
        item_ids = set(obj.items.values_list('item_id', flat=True))
        if not item_ids:
            return {}
        rows = (
            ItemStock.objects
            .filter(item_id__in=item_ids, branch=obj.supplying_branch)
            .exclude(softech_store_code__in=EXCLUDED_STORE_CODES)
            .values('item_id')
            .annotate(qty=Sum('quantity_on_hand'))
        )
        return {str(r['item_id']): float(r['qty'] or 0) for r in rows}

    class Meta:
        model  = TransferRequest
        fields = [
            'id', 'request_number',
            'requesting_branch', 'requesting_branch_name', 'requesting_branch_id',
            'supplying_branch', 'supplying_branch_name', 'supplying_branch_id',
            'status', 'status_label', 'status_color',
            'created_by', 'created_by_name', 'created_by_branch',
            'reviewed_by', 'reviewed_by_name',
            'sent_to_erp_by_name',
            'notes', 'rejection_reason', 'revision_notes',
            'erp_reference',
            'is_editable', 'can_submit', 'can_approve', 'can_reject',
            'can_request_revision', 'can_send_to_erp', 'can_cancel', 'can_complete',
            'items', 'messages', 'destination_stock',
            'created_at', 'updated_at', 'submitted_at',
            'reviewed_at', 'sent_to_erp_at', 'completed_at',
            # Delivery tracking
            'delivery_person_name', 'dispatched_at', 'dispatched_by',
            'dispatched_by_name', 'can_dispatch',
        ]
        read_only_fields = [
            'request_number', 'created_by', 'reviewed_by',
            'submitted_at', 'reviewed_at', 'sent_to_erp_at', 'completed_at',
            'dispatched_at', 'dispatched_by',
        ]


# ── Create / update serializers ───────────────────────────────────────────────

class TransferRequestCreateSerializer(serializers.ModelSerializer):
    items = TransferRequestItemWriteSerializer(many=True, required=False)

    class Meta:
        model  = TransferRequest
        fields = [
            'id', 'requesting_branch', 'supplying_branch', 'notes', 'items',
        ]
        read_only_fields = ['id']

    def validate(self, data):
        if data.get('requesting_branch') == data.get('supplying_branch'):
            raise serializers.ValidationError(
                'الفرع الطالب والفرع المصدر لا يمكن أن يكونا نفس الفرع'
            )
        return data

    def create(self, validated_data):
        items_data = validated_data.pop('items', [])
        request = TransferRequest.objects.create(**validated_data)
        for item_data in items_data:
            TransferRequestItem.objects.create(request=request, **item_data)
        return request


class TransferRequestUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = TransferRequest
        fields = ['notes', 'requesting_branch', 'supplying_branch']

    def validate(self, data):
        instance = self.instance
        if instance and not instance.is_editable:
            raise serializers.ValidationError(
                'لا يمكن تعديل هذا الطلب في حالته الحالية'
            )
        src = data.get('requesting_branch', instance.requesting_branch if instance else None)
        dst = data.get('supplying_branch', instance.supplying_branch if instance else None)
        if src and dst and src == dst:
            raise serializers.ValidationError('الفرع الطالب والفرع المصدر لا يمكن أن يكونا نفس الفرع')
        return data


# ── Action serializers ────────────────────────────────────────────────────────

class RejectSerializer(serializers.Serializer):
    rejection_reason = serializers.CharField(min_length=5)


class RevisionSerializer(serializers.Serializer):
    revision_notes = serializers.CharField(min_length=5)


class SendToERPSerializer(serializers.Serializer):
    erp_reference = serializers.CharField(required=False, allow_blank=True)
