from rest_framework import serializers
from .models import ShortageList, ShortageItem


class ShortageItemSerializer(serializers.ModelSerializer):
    item_name        = serializers.SerializerMethodField()
    item_softech_id  = serializers.SerializerMethodField()
    item_sale_price  = serializers.SerializerMethodField()

    def get_item_name(self, obj):
        return obj.item.name if obj.item_id else None

    def get_item_softech_id(self, obj):
        return obj.item.softech_id if obj.item_id else None

    def get_item_sale_price(self, obj):
        return float(obj.item.unit_price) if obj.item_id else None

    class Meta:
        model  = ShortageItem
        fields = [
            'id', 'raw_name',
            'item', 'item_name', 'item_softech_id', 'item_sale_price',
            'quantity_needed', 'unit', 'notes',
            'match_score', 'is_confirmed', 'is_unmatched',
            'created_at',
        ]
        read_only_fields = ['created_at']


class ShortageItemWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ShortageItem
        fields = ['raw_name', 'quantity_needed', 'unit', 'notes', 'item']


class ShortageItemUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ShortageItem
        fields = ['raw_name', 'quantity_needed', 'unit', 'notes',
                  'item', 'is_confirmed', 'is_unmatched']


class ShortageListSerializer(serializers.ModelSerializer):
    branch_name     = serializers.CharField(source='branch.name_ar', read_only=True)
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True)
    status_label    = serializers.SerializerMethodField()
    item_count      = serializers.SerializerMethodField()
    matched_count   = serializers.SerializerMethodField()
    source_image_url = serializers.SerializerMethodField()

    STATUS_LABELS = {'open': 'مفتوحة', 'submitted': 'مُرسَلة', 'resolved': 'محلولة'}

    def get_status_label(self, obj):
        return self.STATUS_LABELS.get(obj.status, obj.status)

    def get_item_count(self, obj):
        return getattr(obj, 'item_count', obj.items.count())

    def get_matched_count(self, obj):
        return getattr(obj, 'matched_count', obj.items.filter(item__isnull=False).count())

    def get_source_image_url(self, obj):
        if obj.source_image:
            request = self.context.get('request')
            return request.build_absolute_uri(obj.source_image.url) if request else obj.source_image.url
        return None

    class Meta:
        model  = ShortageList
        fields = [
            'id', 'branch', 'branch_name',
            'status', 'status_label',
            'title', 'notes', 'source',
            'source_image_url',
            'created_by_name',
            'item_count', 'matched_count',
            'created_at', 'updated_at',
        ]


class ShortageListDetailSerializer(ShortageListSerializer):
    items = ShortageItemSerializer(many=True, read_only=True)

    class Meta(ShortageListSerializer.Meta):
        fields = ShortageListSerializer.Meta.fields + ['items']


class ShortageListCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ShortageList
        fields = ['branch', 'title', 'notes']
