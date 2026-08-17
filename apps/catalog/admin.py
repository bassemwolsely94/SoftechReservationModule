from django.contrib import admin
from .models import (Category, Item, ItemStock, ItemBarcode, ChronicMedication,
                     ItemAlias)


@admin.register(ItemAlias)
class ItemAliasAdmin(admin.ModelAdmin):
    list_display  = ('normalized', 'item', 'vendor_code', 'source', 'use_count', 'updated_at')
    search_fields = ('normalized', 'sample_raw', 'item__name', 'item__softech_id', 'vendor_code')
    list_filter   = ('source',)
    raw_id_fields = ('item',)
    ordering      = ('-use_count',)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['softech_id', 'name', 'name_ar']
    search_fields = ['name', 'name_ar', 'softech_id']


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = [
        'softech_id', 'name', 'category', 'pack_price', 'unit_price',
        'medicine_type', 'insurance_type', 'requires_fridge',
        'is_fast_moving', 'item_level', 'has_points',
        'branch_trans', 'supplier_trans', 'customer_trans',
        'store_classif', 'is_active', 'is_stockable',
    ]
    list_filter = [
        'category', 'requires_fridge', 'medicine_type', 'is_active', 'is_stockable',
        'is_fast_moving', 'insurance_type', 'item_level', 'has_points',
        'branch_trans', 'supplier_trans', 'customer_trans', 'store_classif',
    ]
    search_fields = ['name', 'name_scientific', 'softech_id', 'barcode', 'phcode']
    list_editable = ['is_active', 'is_stockable']
    readonly_fields = ['last_synced']


@admin.register(ItemStock)
class ItemStockAdmin(admin.ModelAdmin):
    list_display = ['item', 'branch', 'quantity_on_hand', 'monthly_qty', 'last_synced']
    list_filter = ['branch']
    search_fields = ['item__name', 'item__softech_id']
    readonly_fields = ['last_synced']


@admin.register(ItemBarcode)
class ItemBarcodeAdmin(admin.ModelAdmin):
    list_display  = ['item', 'barcode', 'is_active']
    list_filter   = ['is_active']
    search_fields = ['barcode', 'item__name', 'item__softech_id']
    list_editable = ['is_active']
    raw_id_fields = ['item']


@admin.register(ChronicMedication)
class ChronicMedicationAdmin(admin.ModelAdmin):
    list_display = ['item', 'category_label', 'is_active', 'tagged_at']
    list_filter = ['category_label', 'is_active']
    search_fields = ['item__name', 'item__softech_id', 'category_label']
    list_editable = ['is_active']
    readonly_fields = ['tagged_at', 'updated_at']
