from django.contrib import admin
from .models import Category, Item, ItemStock, ChronicMedication


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['softech_id', 'name', 'name_ar']
    search_fields = ['name', 'name_ar', 'softech_id']


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ['softech_id', 'name', 'category', 'unit_sale_price', 'phcode', 'requires_fridge', 'is_active']
    list_filter = ['category', 'requires_fridge', 'medicine_type', 'is_active']
    search_fields = ['name', 'name_scientific', 'softech_id', 'barcode', 'phcode']
    list_editable = ['is_active']
    readonly_fields = ['last_synced']


@admin.register(ItemStock)
class ItemStockAdmin(admin.ModelAdmin):
    list_display = ['item', 'branch', 'quantity_on_hand', 'monthly_qty', 'last_synced']
    list_filter = ['branch']
    search_fields = ['item__name', 'item__softech_id']
    readonly_fields = ['last_synced']


@admin.register(ChronicMedication)
class ChronicMedicationAdmin(admin.ModelAdmin):
    list_display = ['item', 'category_label', 'is_active', 'tagged_at']
    list_filter = ['category_label', 'is_active']
    search_fields = ['item__name', 'item__softech_id', 'category_label']
    list_editable = ['is_active']
    readonly_fields = ['tagged_at', 'updated_at']
