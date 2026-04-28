from rest_framework import serializers
from .models import Reservation, ReservationStatusLog, ReservationActivity


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
    created_by_username = serializers.CharField(
        source='created_by.user.username', read_only=True
    )
    created_by_role = serializers.CharField(source='created_by.role', read_only=True)
    created_by_branch = serializers.CharField(source='created_by.branch_name', read_only=True)
    activity_icon = serializers.CharField(read_only=True)
    activity_label = serializers.CharField(read_only=True)
    mentioned_users_names = serializers.SerializerMethodField()
    attachment_url = serializers.SerializerMethodField()

    def get_mentioned_users_names(self, obj):
        return [
            {'id': u.id, 'name': u.full_name}
            for u in obj.mentioned_users.all()
        ]

    def get_attachment_url(self, obj):
        if obj.attachment:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.attachment.url)
        return None

    class Meta:
        model = ReservationActivity
        fields = [
            'id',
            'activity_type', 'activity_icon', 'activity_label',
            'message',
            'created_by_name', 'created_by_username',
            'created_by_role', 'created_by_branch',
            'created_at',
            'attachment_url',
            'mentioned_users_names',
            'transfer_request_id_ref',
        ]


class ReservationActivityCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReservationActivity
        fields = [
            'activity_type', 'message', 'attachment', 'mentioned_users',
            'transfer_request_id_ref',
        ]

    def validate_message(self, value):
        # Message is required unless attachment is provided
        return value

    def validate(self, data):
        if not data.get('message') and not data.get('attachment'):
            raise serializers.ValidationError('يجب كتابة رسالة أو إرفاق صورة')
        return data


# ── Reservation List ──────────────────────────────────────────────────────────

class ReservationListSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    customer_phone = serializers.CharField(source='customer.phone', read_only=True)
    item_name = serializers.CharField(source='item.name', read_only=True)
    item_softech_id = serializers.CharField(source='item.softech_id', read_only=True)
    branch_name = serializers.CharField(source='branch.name_ar', read_only=True)
    branch_id = serializers.IntegerField(source='branch.id', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.full_name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True)
    status_color = serializers.CharField(read_only=True)
    priority_color = serializers.CharField(read_only=True)
    status_label = serializers.CharField(source='status_label_ar', read_only=True)
    image_url = serializers.SerializerMethodField()
    activity_count = serializers.SerializerMethodField()

    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
        return None

    def get_activity_count(self, obj):
        # Populated via annotation in viewset
        return getattr(obj, 'activity_count', 0)

    class Meta:
        model = Reservation
        fields = [
            'id', 'customer_name', 'customer_phone',
            'item_name', 'item_softech_id',
            'branch_name', 'branch_id',
            'quantity_requested', 'status', 'status_label', 'priority',
            'contact_phone', 'contact_name',
            'expected_arrival_date', 'follow_up_date',
            'assigned_to_name', 'created_by_name',
            'status_color', 'priority_color',
            'image_url', 'activity_count',
            'created_at', 'updated_at',
        ]


# ── Reservation Detail ────────────────────────────────────────────────────────

class ReservationDetailSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    customer_phone = serializers.CharField(source='customer.phone', read_only=True)
    customer_id = serializers.IntegerField(source='customer.id', read_only=True)
    item_name = serializers.CharField(source='item.name', read_only=True)
    item_softech_id = serializers.CharField(source='item.softech_id', read_only=True)
    item_scientific = serializers.CharField(source='item.name_scientific', read_only=True)
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

    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
        return None

    def get_stock_by_branch(self, obj):
        from apps.catalog.models import ItemStock
        stocks = ItemStock.objects.filter(item=obj.item).select_related('branch')
        return [
            {
                'branch_id': s.branch.id,
                'branch_name': s.branch.name_ar or s.branch.name,
                'quantity': float(s.quantity_on_hand),
                'status': s.stock_status,
                'status_label': s.stock_status_label,
            }
            for s in stocks
        ]

    class Meta:
        model = Reservation
        fields = [
            'id', 'customer', 'customer_id', 'customer_name', 'customer_phone',
            'item', 'item_name', 'item_softech_id', 'item_scientific',
            'branch', 'branch_name', 'branch_id',
            'assigned_to', 'assigned_to_name',
            'created_by_name',
            'quantity_requested', 'status', 'status_label', 'priority',
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
            'customer', 'item', 'branch', 'assigned_to',
            'quantity_requested', 'priority', 'contact_phone', 'contact_name',
            'notes', 'expected_arrival_date', 'follow_up_date', 'image',
        ]

    def validate_quantity_requested(self, value):
        if value <= 0:
            raise serializers.ValidationError('الكمية يجب أن تكون أكبر من صفر')
        return value


class ReservationUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reservation
        fields = [
            'assigned_to', 'quantity_requested', 'priority',
            'contact_phone', 'contact_name', 'notes',
            'expected_arrival_date', 'follow_up_date', 'image',
        ]


class ChangeStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[s[0] for s in Reservation.STATUS_CHOICES])
    note = serializers.CharField(required=False, allow_blank=True)
