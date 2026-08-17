"""
apps/delivery/serializers.py
"""
from rest_framework import serializers

from .models import (
    CashCollection,
    CustomerLocation,
    DeliveryAssignment,
    DeliveryDriver,
    DeliveryOrder,
    DeliveryOrderItem,
    DeliveryStatusLog,
)


class DeliveryDriverSerializer(serializers.ModelSerializer):
    branch_name       = serializers.CharField(source='branch.name', read_only=True)
    vehicle_label     = serializers.CharField(source='get_vehicle_type_display', read_only=True)
    status_label      = serializers.CharField(source='get_status_display', read_only=True)
    today_order_count = serializers.SerializerMethodField()

    class Meta:
        model = DeliveryDriver
        fields = [
            'id', 'full_name', 'mobile', 'national_id',
            'staff_profile', 'branch', 'branch_name',
            'vehicle_type', 'vehicle_label', 'vehicle_plate',
            'status', 'status_label', 'max_daily_orders',
            'notes', 'today_order_count',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_today_order_count(self, obj):
        from django.utils import timezone
        return obj.assignments.filter(
            assigned_at__date=timezone.localdate(),
            is_current=True,
        ).count()


class CustomerLocationSerializer(serializers.ModelSerializer):
    label_display    = serializers.CharField(source='get_label_display', read_only=True)
    accuracy_display = serializers.CharField(source='get_location_accuracy_display', read_only=True)
    full_address     = serializers.CharField(read_only=True)

    class Meta:
        model = CustomerLocation
        fields = [
            'id', 'customer', 'label', 'label_display', 'label_custom', 'is_default',
            'address_line', 'building', 'floor', 'apartment', 'landmark',
            'area', 'district', 'governorate',
            'latitude', 'longitude', 'google_maps_url',
            'location_accuracy', 'accuracy_display',
            'delivery_phone', 'notes',
            'full_address',
            'updated_by', 'updated_at', 'created_at',
        ]
        read_only_fields = ['updated_at', 'created_at', 'updated_by']


class DeliveryOrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryOrderItem
        fields = [
            'id', 'item', 'item_name', 'item_code',
            'quantity', 'unit_price', 'line_total',
            'delivered_quantity', 'notes',
        ]


class DeliveryAssignmentSerializer(serializers.ModelSerializer):
    driver_display   = serializers.SerializerMethodField()
    assigned_by_name = serializers.CharField(source='assigned_by.get_full_name', read_only=True)

    class Meta:
        model = DeliveryAssignment
        fields = [
            'id', 'order', 'driver', 'driver_name', 'driver_display',
            'vehicle', 'is_current',
            'assigned_by', 'assigned_by_name',
            'assigned_at', 'notes',
        ]
        read_only_fields = ['assigned_at']

    def get_driver_display(self, obj):
        if obj.driver:
            return obj.driver.full_name
        return obj.driver_name or '—'


class DeliveryStatusLogSerializer(serializers.ModelSerializer):
    recorded_by_name = serializers.CharField(source='recorded_by.get_full_name', read_only=True)
    source_label     = serializers.CharField(source='get_source_display', read_only=True)

    class Meta:
        model = DeliveryStatusLog
        fields = [
            'id', 'from_status', 'to_status',
            'source', 'source_label',
            'notes', 'recorded_by', 'recorded_by_name', 'recorded_at',
        ]
        read_only_fields = ['recorded_at']


class CashCollectionSerializer(serializers.ModelSerializer):
    status_label      = serializers.CharField(source='get_status_display', read_only=True)
    collected_by_name = serializers.CharField(source='collected_by.get_full_name', read_only=True)

    class Meta:
        model = CashCollection
        fields = [
            'id', 'order',
            'expected_amount', 'collected_amount',
            'shortage_amount', 'overage_amount',
            'status', 'status_label',
            'collection_time', 'collected_by', 'collected_by_name',
            'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = ['shortage_amount', 'overage_amount', 'created_at', 'updated_at']


class DeliveryOrderItemWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryOrderItem
        fields = ['item', 'item_name', 'item_code', 'quantity', 'unit_price', 'line_total', 'notes']


class DeliveryOrderCreateSerializer(serializers.ModelSerializer):
    items = DeliveryOrderItemWriteSerializer(many=True, required=False)

    class Meta:
        model = DeliveryOrder
        fields = [
            'source_type', 'branch', 'softech_doc_ref', 'softech_branch_code',
            'customer', 'customer_name', 'customer_phone', 'customer_phone_alt',
            'location',
            'delivery_address', 'delivery_area', 'delivery_district',
            'delivery_governorate', 'delivery_landmark',
            'delivery_lat', 'delivery_lng', 'google_maps_url',
            'items_count', 'total_value', 'delivery_fees',
            'payment_method',
            'sla_due_at', 'ordered_at',
            'notes',
            'items',
        ]

    def create(self, validated_data):
        items_data = validated_data.pop('items', [])
        order = DeliveryOrder.objects.create(**validated_data)
        for item_data in items_data:
            DeliveryOrderItem.objects.create(order=order, **item_data)
        return order

    def update(self, instance, validated_data):
        items_data = validated_data.pop('items', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if items_data is not None:
            instance.items.all().delete()
            for item_data in items_data:
                DeliveryOrderItem.objects.create(order=instance, **item_data)
        return instance


class DeliveryOrderListSerializer(serializers.ModelSerializer):
    """Lightweight read serializer for list views."""
    branch_name     = serializers.CharField(source='branch.name', read_only=True)
    status_label    = serializers.CharField(source='get_status_display', read_only=True)
    source_label    = serializers.CharField(source='get_source_type_display', read_only=True)
    driver_name     = serializers.SerializerMethodField()
    is_late         = serializers.BooleanField(read_only=True)
    total_with_fees = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = DeliveryOrder
        fields = [
            'id', 'order_number',
            'softech_doc_number5', 'softech_doc_date5', 'softech_doc_ref',
            'softech_crm_branch', 'softech_crm_order_no', 'softech_branch_code',
            'source_type', 'source_label',
            'branch', 'branch_name',
            'customer', 'customer_name', 'customer_phone',
            'delivery_area', 'delivery_governorate',
            'total_value', 'delivery_fees', 'total_with_fees',
            'payment_method',
            'status', 'status_label',
            'assigned_driver', 'driver_name',
            'ordered_at', 'dispatched_at', 'delivered_at',
            'is_late', 'sla_due_at',
            'created_at',
        ]

    def get_driver_name(self, obj):
        if obj.assigned_driver:
            return obj.assigned_driver.full_name
        return None


class DeliveryOrderSerializer(serializers.ModelSerializer):
    """Full read serializer with all nested data."""
    branch_name        = serializers.CharField(source='branch.name', read_only=True)
    status_label       = serializers.CharField(source='get_status_display', read_only=True)
    source_label       = serializers.CharField(source='get_source_type_display', read_only=True)
    payment_label      = serializers.CharField(source='get_payment_method_display', read_only=True)
    driver_name        = serializers.SerializerMethodField()
    current_assignment = serializers.SerializerMethodField()
    status_logs        = DeliveryStatusLogSerializer(many=True, read_only=True)
    items              = DeliveryOrderItemSerializer(many=True, read_only=True)
    cash_collection    = CashCollectionSerializer(read_only=True)
    is_late            = serializers.BooleanField(read_only=True)
    delivery_minutes   = serializers.IntegerField(read_only=True)
    total_with_fees    = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    suggested_driver_fee = serializers.FloatField(read_only=True)

    class Meta:
        model = DeliveryOrder
        fields = [
            'id', 'order_number',
            # SOFTECH references
            'softech_crm_branch', 'softech_crm_order_no',
            'softech_doc_number5', 'softech_doc_date5',   # pre-invoice staging doc
            'softech_doc_ref',                             # final invoice (0 = pending)
            'softech_branch_code', 'softech_order_usercode', 'softech_order_status',
            'source_type', 'source_label',
            'branch', 'branch_name',
            'customer', 'customer_name', 'customer_phone', 'customer_phone_alt',
            'location',
            'delivery_address', 'delivery_area', 'delivery_district',
            'delivery_governorate', 'delivery_landmark',
            'delivery_lat', 'delivery_lng', 'google_maps_url',
            'items_count', 'total_value', 'delivery_fees', 'total_with_fees',
            'payment_method', 'payment_label', 'collected_amount',
            'status', 'status_label',
            'cancel_reason', 'failure_reason',
            'assigned_driver', 'driver_name', 'current_assignment',
            'sla_due_at', 'ordered_at', 'assigned_at', 'driver_accepted_at',
            'dispatched_at', 'delivered_at', 'failed_at', 'closed_at',
            'notes', 'created_by', 'created_at', 'updated_at',
            'is_late', 'delivery_minutes',
            'status_logs', 'items', 'cash_collection',
            # Proof of delivery + route batching
            'pod_recipient_name', 'pod_note', 'pod_photo', 'pod_lat', 'pod_lng',
            'delivery_distance_km', 'suggested_driver_fee', 'pod_backfilled',
            'route', 'route_sequence',
        ]
        read_only_fields = ['order_number', 'created_at', 'updated_at']

    def get_driver_name(self, obj):
        if obj.assigned_driver:
            return obj.assigned_driver.full_name
        return None

    def get_current_assignment(self, obj):
        try:
            asgn = obj.assignments.filter(is_current=True).first()
            if asgn:
                return DeliveryAssignmentSerializer(asgn).data
        except Exception:
            pass
        return None


# ── Delivery Routes (batched runs) ──────────────────────────────────────────────

from .models import DeliveryRoute   # noqa: E402

class DeliveryRouteSerializer(serializers.ModelSerializer):
    driver_name     = serializers.CharField(source='driver.full_name', read_only=True)
    status_label    = serializers.CharField(source='get_status_display', read_only=True)
    stop_count      = serializers.IntegerField(read_only=True)
    delivered_count = serializers.IntegerField(read_only=True)
    expected_cash   = serializers.FloatField(read_only=True)
    orders          = serializers.SerializerMethodField()

    def get_orders(self, obj):
        rows = obj.orders.order_by('route_sequence', 'id')
        return [{
            'id': o.id, 'order_number': o.order_number, 'seq': o.route_sequence,
            'customer_name': o.customer_name, 'customer_phone': o.customer_phone,
            'address': o.delivery_address, 'area': o.delivery_area,
            'lat': float(o.delivery_lat) if o.delivery_lat else None,
            'lng': float(o.delivery_lng) if o.delivery_lng else None,
            'google_maps': o.google_maps_url,
            'total': float(o.total_with_fees), 'payment': o.payment_method,
            'status': o.status, 'status_label': o.get_status_display(),
        } for o in rows]

    class Meta:
        model  = DeliveryRoute
        fields = [
            'id', 'branch', 'driver', 'driver_name', 'route_date',
            'status', 'status_label', 'notes',
            'stop_count', 'delivered_count', 'expected_cash',
            'created_at', 'dispatched_at', 'orders',
        ]
        read_only_fields = ['created_at', 'dispatched_at']
