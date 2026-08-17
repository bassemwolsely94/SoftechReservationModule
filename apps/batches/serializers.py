from rest_framework import serializers
from .models import StockBatch, BatchMovement, NearExpiryAlert


class BatchMovementSerializer(serializers.ModelSerializer):
    movement_type_display = serializers.CharField(source='get_movement_type_display', read_only=True)
    performed_by_name     = serializers.CharField(source='performed_by.full_name', read_only=True)

    class Meta:
        model  = BatchMovement
        fields = [
            'id', 'movement_type', 'movement_type_display',
            'qty_change', 'qty_after',
            'performed_by', 'performed_by_name',
            'reference_type', 'reference_id',
            'notes', 'created_at',
        ]


class StockBatchSerializer(serializers.ModelSerializer):
    item_name        = serializers.CharField(source='item.name', read_only=True)
    branch_name      = serializers.CharField(source='branch.name_ar', read_only=True)
    vendor_name      = serializers.CharField(source='vendor.name', read_only=True)
    received_by_name = serializers.CharField(source='received_by.full_name', read_only=True)
    days_to_expiry   = serializers.IntegerField(read_only=True)
    expiry_value     = serializers.FloatField(read_only=True)
    movements        = BatchMovementSerializer(many=True, read_only=True)

    class Meta:
        model  = StockBatch
        fields = [
            'id', 'item', 'item_name', 'branch', 'branch_name',
            'batch_number', 'expiry_date', 'days_to_expiry',
            'vendor', 'vendor_name', 'invoice', 'invoice_number', 'manufacturer',
            'purchase_price', 'original_qty', 'current_qty', 'expiry_value',
            'storage_condition', 'is_quarantined', 'quarantine_reason', 'is_expired',
            'received_by', 'received_by_name', 'received_at',
            'created_at', 'updated_at',
            'movements',
        ]
        read_only_fields = fields


class StockBatchListSerializer(serializers.ModelSerializer):
    item_name      = serializers.CharField(source='item.name', read_only=True)
    branch_name    = serializers.CharField(source='branch.name_ar', read_only=True)
    vendor_name    = serializers.CharField(source='vendor.name', read_only=True)
    days_to_expiry = serializers.IntegerField(read_only=True)
    expiry_value   = serializers.FloatField(read_only=True)

    class Meta:
        model  = StockBatch
        fields = [
            'id', 'item', 'item_name', 'branch', 'branch_name',
            'batch_number', 'expiry_date', 'days_to_expiry',
            'vendor_name', 'purchase_price', 'current_qty', 'expiry_value',
            'is_quarantined', 'is_expired',
        ]


class NearExpiryAlertSerializer(serializers.ModelSerializer):
    batch_number   = serializers.CharField(source='batch.batch_number', read_only=True)
    item_name      = serializers.CharField(source='batch.item.name', read_only=True)
    branch_name    = serializers.CharField(source='batch.branch.name_ar', read_only=True)
    vendor_name    = serializers.CharField(source='batch.vendor.name', read_only=True)
    expiry_date    = serializers.DateField(source='batch.expiry_date', read_only=True)
    current_qty    = serializers.DecimalField(source='batch.current_qty', max_digits=12, decimal_places=3, read_only=True)
    expiry_value   = serializers.FloatField(source='batch.expiry_value', read_only=True)
    threshold_display = serializers.CharField(source='get_threshold_days_display', read_only=True)

    class Meta:
        model  = NearExpiryAlert
        fields = [
            'id', 'batch', 'batch_number', 'item_name', 'branch_name',
            'vendor_name', 'expiry_date', 'current_qty', 'expiry_value',
            'threshold_days', 'threshold_display',
            'alerted_at', 'resolved_at', 'resolution',
        ]


class FEFORecommendationSerializer(serializers.ModelSerializer):
    """Lightweight batch list for FEFO dispatch guidance."""
    item_name    = serializers.CharField(source='item.name', read_only=True)
    days_to_expiry = serializers.IntegerField(read_only=True)

    class Meta:
        model  = StockBatch
        fields = ['id', 'batch_number', 'expiry_date', 'days_to_expiry', 'current_qty', 'item_name']
