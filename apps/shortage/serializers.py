from rest_framework import serializers
from .models import ShortageList, ShortageItem


class ShortageItemSerializer(serializers.ModelSerializer):
    item_name        = serializers.SerializerMethodField()
    item_softech_id  = serializers.SerializerMethodField()
    item_sale_price  = serializers.SerializerMethodField()
    confirmed_by_name = serializers.SerializerMethodField()
    source_label     = serializers.SerializerMethodField()

    _SOURCE_LABELS = {'manual': 'يدوي', 'voice': 'صوتي',
                      'ocr': 'OCR', 'bulk': 'استيراد نصي'}

    def get_item_name(self, obj):
        return obj.item.name if obj.item_id else None

    def get_item_softech_id(self, obj):
        return obj.item.softech_id if obj.item_id else None

    def get_item_sale_price(self, obj):
        return float(obj.item.pack_price or obj.item.unit_price) if obj.item_id else None

    def get_confirmed_by_name(self, obj):
        if obj.confirmed_by_id:
            u = obj.confirmed_by.user
            name = f'{u.first_name} {u.last_name}'.strip()
            return name or obj.confirmed_by.softech_username or f'#{obj.confirmed_by_id}'
        return None

    def get_source_label(self, obj):
        return self._SOURCE_LABELS.get(obj.source, obj.source)

    class Meta:
        model  = ShortageItem
        fields = [
            'id', 'raw_name',
            'item', 'item_name', 'item_softech_id', 'item_sale_price',
            'quantity_needed', 'unit', 'notes',
            'source', 'source_label',
            'match_score', 'is_confirmed', 'is_unmatched',
            'confirmed_by', 'confirmed_by_name', 'confirmed_at',
            'created_at',
        ]
        read_only_fields = ['created_at', 'confirmed_at']


class ShortageItemWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ShortageItem
        fields = ['raw_name', 'quantity_needed', 'unit', 'notes', 'item', 'source']


class ShortageItemUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ShortageItem
        fields = ['raw_name', 'quantity_needed', 'unit', 'notes',
                  'item', 'is_confirmed', 'is_unmatched', 'source']


class ShortageListSerializer(serializers.ModelSerializer):
    branch_name      = serializers.CharField(source='branch.name_ar', read_only=True)
    created_by_name  = serializers.SerializerMethodField()
    status_label     = serializers.SerializerMethodField()
    item_count       = serializers.SerializerMethodField()
    matched_count    = serializers.SerializerMethodField()
    confirmed_count  = serializers.SerializerMethodField()
    unmatched_count  = serializers.SerializerMethodField()
    source_image_url = serializers.SerializerMethodField()

    STATUS_LABELS = {'open': 'مفتوحة', 'submitted': 'مُرسَلة', 'resolved': 'محلولة'}

    def get_status_label(self, obj):
        return self.STATUS_LABELS.get(obj.status, obj.status)

    def get_created_by_name(self, obj):
        if not obj.created_by_id:
            return None
        u = obj.created_by.user
        return f'{u.first_name} {u.last_name}'.strip() or obj.created_by.softech_username

    def get_item_count(self, obj):
        return getattr(obj, 'item_count', obj.items.count())

    def get_matched_count(self, obj):
        return getattr(obj, 'matched_count', obj.items.filter(item__isnull=False).count())

    def get_confirmed_count(self, obj):
        return getattr(obj, 'confirmed_count', obj.items.filter(is_confirmed=True).count())

    def get_unmatched_count(self, obj):
        return getattr(obj, 'unmatched_count', obj.items.filter(is_unmatched=True).count())

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
            'item_count', 'matched_count', 'confirmed_count', 'unmatched_count',
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
