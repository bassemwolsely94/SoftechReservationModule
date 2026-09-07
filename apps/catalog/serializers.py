from rest_framework import serializers
from .models import Category, Item, ItemStock, ItemBarcode, EXCLUDED_STORE_CODES, \
    CatalogVariantGroup, VariantMember, ProductBundle, BundleItem


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
            'category', 'category_name', 'pack_price', 'unit_price',
            'medicine_type', 'requires_fridge', 'comment', 'is_active', 'is_stockable',
            'is_fast_moving', 'insurance_type', 'item_level', 'has_points',
            'pack_qty', 'branch_trans', 'supplier_trans', 'customer_trans', 'nosale_classif',
            'store_classif', 'store_classif_name',
            'stock_levels', 'total_stock', 'last_synced',
        ]

    def get_total_stock(self, obj):
        return float(sum(
            s.quantity_on_hand
            for s in obj.stock_levels.all()
            if s.softech_store_code not in EXCLUDED_STORE_CODES
        ))


class ItemSearchSerializer(serializers.ModelSerializer):
    """Lightweight serializer for search / autocomplete and the advanced search modal.
    Returns name, code, ALL barcodes, price, total stock, and supplier/producer info.
    all_barcodes: includes primary barcode (Item.barcode) + all active ItemBarcode entries.
    """
    category_name = serializers.CharField(source='category.name', read_only=True)
    total_stock   = serializers.SerializerMethodField()
    all_barcodes  = serializers.SerializerMethodField()

    class Meta:
        model = Item
        fields = [
            'id', 'softech_id', 'name', 'name_scientific', 'barcode',
            'all_barcodes',
            'pack_price', 'unit_price', 'cost_price',
            'category_name', 'requires_fridge',
            'is_stockable', 'is_fast_moving', 'insurance_type', 'item_level',
            'has_points', 'pack_qty', 'branch_trans', 'supplier_trans',
            'customer_trans', 'nosale_classif',
            'store_classif', 'store_classif_name',
            # Supplier / producer (for advanced search results table)
            'supplier_code', 'supplier_name',
            'producer_code', 'producer_name',
            # Additional detail fields (for advanced search)
            'family_code', 'family_name', 'family_name_ar',
            'medicine_type', 'medicine_type_name', 'medicine_type_name_ar',
            'shape_name', 'origin_name', 'effect_name',
            'unit_name', 'active_ingredients', 'phcode',
            'total_stock',
        ]

    def get_total_stock(self, obj):
        return float(sum(
            s.quantity_on_hand
            for s in obj.stock_levels.all()
            if s.softech_store_code not in EXCLUDED_STORE_CODES
        ))

    def get_all_barcodes(self, obj):
        """Union of primary barcode + active barcodes from ItemBarcode table.
        Excludes '0' — SOFTECH stores '0' in items.itembarcode as a placeholder
        when the real barcodes live in the itembarcode subsidiary table.
        Returns active barcodes first (mainbarcode='1' rows come first from sync ORDER BY).
        """
        # Valid primary barcode: non-empty, not '0', not all-zeros
        primary = obj.barcode.strip() if obj.barcode else ''
        seen = []
        if primary and primary not in ('0', '00', '000'):
            seen.append(primary)
        try:
            for ib in obj.barcodes.all():
                bc = ib.barcode.strip() if ib.barcode else ''
                if bc and bc not in ('0', '00', '000') and bc not in seen:
                    seen.append(bc)
        except Exception:
            pass
        return seen


# ── Variant groups ─────────────────────────────────────────────────────────────

class VariantMemberSerializer(serializers.ModelSerializer):
    item_name     = serializers.CharField(source='item.name', read_only=True)
    item_code     = serializers.CharField(source='item.softech_id', read_only=True)
    item_price    = serializers.DecimalField(source='item.pack_price', max_digits=10,
                                             decimal_places=2, read_only=True)

    class Meta:
        model  = VariantMember
        fields = ['id', 'item', 'item_name', 'item_code', 'item_price',
                  'variant_label', 'sort_order']


class VariantGroupSerializer(serializers.ModelSerializer):
    members      = VariantMemberSerializer(many=True, read_only=True)
    member_count = serializers.IntegerField(read_only=True)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model  = CatalogVariantGroup
        fields = ['id', 'name', 'name_ar', 'description',
                  'member_count', 'members', 'created_by_name',
                  'created_at', 'updated_at']
        read_only_fields = ['id', 'member_count', 'created_by_name',
                            'created_at', 'updated_at']

    def get_created_by_name(self, obj):
        return obj.created_by.user.get_full_name() if obj.created_by_id else ''


# ── Bundles ────────────────────────────────────────────────────────────────────

class BundleItemSerializer(serializers.ModelSerializer):
    item_name  = serializers.CharField(source='item.name', read_only=True)
    item_code  = serializers.CharField(source='item.softech_id', read_only=True)
    item_price = serializers.DecimalField(source='item.pack_price', max_digits=10,
                                          decimal_places=2, read_only=True)

    class Meta:
        model  = BundleItem
        fields = ['id', 'item', 'item_name', 'item_code', 'item_price', 'quantity']


class ProductBundleSerializer(serializers.ModelSerializer):
    items       = BundleItemSerializer(many=True, read_only=True)
    discount_type_label = serializers.CharField(source='get_discount_type_display', read_only=True)
    created_by_name     = serializers.SerializerMethodField()

    class Meta:
        model  = ProductBundle
        fields = ['id', 'name', 'name_ar', 'description', 'is_active',
                  'discount_type', 'discount_type_label', 'discount_value',
                  'items', 'created_by_name', 'created_at', 'updated_at']
        read_only_fields = ['id', 'discount_type_label', 'created_by_name',
                            'created_at', 'updated_at']

    def get_created_by_name(self, obj):
        return obj.created_by.user.get_full_name() if obj.created_by_id else ''
