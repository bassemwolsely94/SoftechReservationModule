from rest_framework import serializers
from .models import Category, Item, ItemStock


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'softech_id', 'name', 'name_ar']


class ItemStockSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    branch_name_ar = serializers.CharField(source='branch.name_ar', read_only=True)
    stock_status = serializers.CharField(read_only=True)
    stock_status_label = serializers.CharField(read_only=True)

    class Meta:
        model = ItemStock
        fields = ['id', 'branch', 'branch_name', 'branch_name_ar',
                  'quantity_on_hand', 'monthly_qty', 'on_order_qty',
                  'stock_status', 'stock_status_label', 'last_synced']


class ItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    stock_levels = ItemStockSerializer(many=True, read_only=True)
    total_stock = serializers.SerializerMethodField()

    class Meta:
        model = Item
        fields = [
            'id', 'softech_id', 'name', 'name_scientific', 'barcode',
            'category', 'category_name', 'unit_price', 'unit_sale_price',
            'medicine_type', 'requires_fridge', 'comment', 'is_active',
            'stock_levels', 'total_stock', 'last_synced',
        ]

    def get_total_stock(self, obj):
        return float(sum(s.quantity_on_hand for s in obj.stock_levels.all()))


class ItemSearchSerializer(serializers.ModelSerializer):
    """Lightweight serializer for search / autocomplete"""
    category_name = serializers.CharField(source='category.name', read_only=True)
    total_stock = serializers.SerializerMethodField()

    class Meta:
        model = Item
        fields = ['id', 'softech_id', 'name', 'name_scientific', 'barcode',
                  'unit_price', 'category_name', 'requires_fridge', 'total_stock']

    def get_total_stock(self, obj):
        return float(sum(s.quantity_on_hand for s in obj.stock_levels.all()))
