from rest_framework import serializers

from .models import Offer, OfferApplication


class OfferSerializer(serializers.ModelSerializer):
    offer_type_label = serializers.CharField(source='get_offer_type_display', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = Offer
        fields = [
            'id', 'name', 'name_ar', 'description', 'offer_type', 'offer_type_label',
            'status', 'status_label', 'authorization_source', 'bxgy_scope',
            'value', 'max_discount_amount',
            'buy_qty', 'get_qty', 'get_discount_percent', 'qty_tiers',
            'gift_item', 'bundle_price',
            'target_all', 'items', 'categories', 'tags', 'classification_filters',
            'target_spec', 'excluded_items', 'require_stock',
            'segments', 'branches', 'channels', 'min_basket_amount', 'min_qty',
            'starts_at', 'ends_at', 'stackable', 'priority', 'is_clearance',
            'requires_approval', 'max_uses_total', 'max_uses_per_customer',
            'item_count', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_item_count(self, obj):
        return obj.items.count()


class OfferApplicationSerializer(serializers.ModelSerializer):
    offer_name = serializers.CharField(source='offer.name', read_only=True)

    class Meta:
        model = OfferApplication
        fields = ['id', 'offer', 'offer_name', 'customer', 'branch', 'pos_order',
                  'discount_amount', 'was_applied', 'reason', 'detail', 'created_at']
        read_only_fields = fields
