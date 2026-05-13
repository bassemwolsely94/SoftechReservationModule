from rest_framework import serializers
from .models import StockCountSession, StockCountLine


class StockCountLineSerializer(serializers.ModelSerializer):
    item_name        = serializers.SerializerMethodField()
    item_softech_id  = serializers.SerializerMethodField()
    item_scientific  = serializers.SerializerMethodField()
    item_sale_price  = serializers.SerializerMethodField()

    def get_item_name(self, obj):
        return obj.item.name if obj.item_id else obj.manual_item_name

    def get_item_softech_id(self, obj):
        return obj.item.softech_id if obj.item_id else None

    def get_item_scientific(self, obj):
        return obj.item.name_scientific if obj.item_id else None

    def get_item_sale_price(self, obj):
        return float(obj.item.unit_price) if obj.item_id else None

    class Meta:
        model  = StockCountLine
        fields = [
            'id', 'item', 'item_name', 'item_softech_id', 'item_scientific', 'item_sale_price',
            'manual_item_name',
            'system_qty', 'erp_transqty',
            'counted_qty', 'difference', 'has_discrepancy',
            'notes', 'updated_at',
        ]
        read_only_fields = ['difference', 'has_discrepancy', 'updated_at']


class StockCountLineUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = StockCountLine
        fields = ['counted_qty', 'notes']


class StockCountSessionListSerializer(serializers.ModelSerializer):
    branch_name    = serializers.CharField(source='branch.name_ar', read_only=True)
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True)
    status_label   = serializers.SerializerMethodField()
    total_lines    = serializers.IntegerField(read_only=True)
    discrepancy_count = serializers.IntegerField(read_only=True)

    STATUS_LABELS = {'open': 'قيد الجرد', 'completed': 'مكتمل', 'cancelled': 'ملغى'}

    def get_status_label(self, obj):
        return self.STATUS_LABELS.get(obj.status, obj.status)

    class Meta:
        model  = StockCountSession
        fields = [
            'id', 'branch', 'branch_name',
            'status', 'status_label',
            'count_date', 'notes',
            'erp_doc_code', 'erp_doc_number',
            'created_by_name',
            'total_lines', 'discrepancy_count',
            'created_at', 'completed_at',
        ]


class StockCountSessionDetailSerializer(StockCountSessionListSerializer):
    lines = StockCountLineSerializer(many=True, read_only=True)

    class Meta(StockCountSessionListSerializer.Meta):
        fields = StockCountSessionListSerializer.Meta.fields + ['lines']


class StockCountSessionCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = StockCountSession
        fields = ['branch', 'count_date', 'notes', 'erp_doc_code', 'erp_doc_number']
