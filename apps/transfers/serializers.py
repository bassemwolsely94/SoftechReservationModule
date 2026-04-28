from rest_framework import serializers
from .models import TransferRequest, TransferRequestItem, TransferRequestMessage
from apps.catalog.models import ItemStock


# ── Item line serializers ─────────────────────────────────────────────────────

class TransferRequestItemSerializer(serializers.ModelSerializer):
    item_name       = serializers.CharField(source='item.name',       read_only=True)
    item_softech_id = serializers.CharField(source='item.softech_id', read_only=True)
    item_scientific = serializers.CharField(source='item.name_scientific', read_only=True)
    available_stock = serializers.FloatField(
        source='available_stock_at_destination', read_only=True
    )

    class Meta:
        model  = TransferRequestItem
        fields = [
            'id', 'item', 'item_name', 'item_softech_id', 'item_scientific',
            'quantity', 'notes', 'available_stock',
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
    created_by_role   = serializers.CharField(source='created_by.role',      read_only=True)
    created_by_branch = serializers.CharField(source='created_by.branch_name', read_only=True)
    type_icon         = serializers.SerializerMethodField()

    def get_type_icon(self, obj):
        return {'message': '💬', 'system': '⚙️', 'note': '📝'}.get(obj.message_type, '💬')

    class Meta:
        model  = TransferRequestMessage
        fields = [
            'id', 'message_type', 'type_icon', 'message',
            'created_by', 'created_by_name', 'created_by_role', 'created_by_branch',
            'created_at',
        ]
        read_only_fields = ['created_at', 'created_by']


class TransferRequestMessageCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = TransferRequestMessage
        fields = ['message_type', 'message']

    def validate_message(self, value):
        if not value.strip():
            raise serializers.ValidationError('الرسالة لا يمكن أن تكون فارغة')
        return value


# ── Request list serializer ───────────────────────────────────────────────────

class TransferRequestListSerializer(serializers.ModelSerializer):
    source_branch_name      = serializers.CharField(source='source_branch.name_ar',      read_only=True)
    destination_branch_name = serializers.CharField(source='destination_branch.name_ar', read_only=True)
    created_by_name         = serializers.CharField(source='created_by.full_name',        read_only=True)
    reviewed_by_name        = serializers.CharField(source='reviewed_by.full_name',       read_only=True)
    status_label            = serializers.CharField(source='status_label_ar',              read_only=True)
    status_color            = serializers.CharField(read_only=True)
    total_items             = serializers.SerializerMethodField()

    def get_total_items(self, obj):
        return obj.items.count()

    class Meta:
        model  = TransferRequest
        fields = [
            'id', 'request_number',
            'source_branch', 'source_branch_name',
            'destination_branch', 'destination_branch_name',
            'status', 'status_label', 'status_color',
            'created_by_name', 'reviewed_by_name',
            'total_items',
            'notes',
            'created_at', 'updated_at', 'submitted_at',
        ]


# ── Request detail serializer ─────────────────────────────────────────────────

class TransferRequestDetailSerializer(serializers.ModelSerializer):
    source_branch_name      = serializers.CharField(source='source_branch.name_ar',      read_only=True)
    destination_branch_name = serializers.CharField(source='destination_branch.name_ar', read_only=True)
    source_branch_id        = serializers.IntegerField(source='source_branch.id',        read_only=True)
    destination_branch_id   = serializers.IntegerField(source='destination_branch.id',   read_only=True)
    created_by_name         = serializers.CharField(source='created_by.full_name',       read_only=True)
    created_by_branch       = serializers.CharField(source='created_by.branch_name',     read_only=True)
    reviewed_by_name        = serializers.CharField(source='reviewed_by.full_name',      read_only=True)
    sent_to_erp_by_name     = serializers.CharField(source='sent_to_erp_by.full_name',   read_only=True)
    status_label            = serializers.CharField(source='status_label_ar',             read_only=True)
    status_color            = serializers.CharField(read_only=True)
    is_editable             = serializers.BooleanField(read_only=True)
    can_submit              = serializers.BooleanField(read_only=True)
    can_approve             = serializers.BooleanField(read_only=True)
    can_reject              = serializers.BooleanField(read_only=True)
    can_request_revision    = serializers.BooleanField(read_only=True)
    can_send_to_erp         = serializers.BooleanField(read_only=True)
    can_cancel              = serializers.BooleanField(read_only=True)
    items                   = TransferRequestItemSerializer(many=True, read_only=True)
    messages                = TransferRequestMessageSerializer(many=True, read_only=True)

    # Live stock at destination for all items
    destination_stock = serializers.SerializerMethodField()

    def get_destination_stock(self, obj):
        stocks = ItemStock.objects.filter(
            branch=obj.destination_branch
        ).select_related('item')
        item_ids = set(obj.items.values_list('item_id', flat=True))
        return {
            str(s.item_id): float(s.quantity_on_hand)
            for s in stocks
            if s.item_id in item_ids
        }

    class Meta:
        model  = TransferRequest
        fields = [
            'id', 'request_number',
            'source_branch', 'source_branch_name', 'source_branch_id',
            'destination_branch', 'destination_branch_name', 'destination_branch_id',
            'status', 'status_label', 'status_color',
            'created_by', 'created_by_name', 'created_by_branch',
            'reviewed_by', 'reviewed_by_name',
            'sent_to_erp_by_name',
            'notes', 'rejection_reason', 'revision_notes',
            'erp_reference',
            'is_editable', 'can_submit', 'can_approve', 'can_reject',
            'can_request_revision', 'can_send_to_erp', 'can_cancel',
            'items', 'messages', 'destination_stock',
            'created_at', 'updated_at', 'submitted_at',
            'reviewed_at', 'sent_to_erp_at', 'completed_at',
        ]
        read_only_fields = [
            'request_number', 'created_by', 'reviewed_by',
            'submitted_at', 'reviewed_at', 'sent_to_erp_at', 'completed_at',
        ]


# ── Create / update serializers ───────────────────────────────────────────────

class TransferRequestCreateSerializer(serializers.ModelSerializer):
    items = TransferRequestItemWriteSerializer(many=True, required=False)

    class Meta:
        model  = TransferRequest
        fields = [
            'source_branch', 'destination_branch', 'notes', 'items',
        ]

    def validate(self, data):
        if data.get('source_branch') == data.get('destination_branch'):
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
        fields = ['notes', 'source_branch', 'destination_branch']

    def validate(self, data):
        instance = self.instance
        if instance and not instance.is_editable:
            raise serializers.ValidationError(
                'لا يمكن تعديل هذا الطلب في حالته الحالية'
            )
        src = data.get('source_branch', instance.source_branch if instance else None)
        dst = data.get('destination_branch', instance.destination_branch if instance else None)
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
