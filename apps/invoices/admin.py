from django.contrib import admin
from .models import VendorProfile, VendorItemMapping, SupplierInvoice, InvoiceLine


@admin.register(VendorProfile)
class VendorProfileAdmin(admin.ModelAdmin):
    list_display  = ('name', 'softech_personcode', 'is_main', 'typical_discount_pct', 'created_at')
    list_editable = ('is_main',)          # toggle official/main suppliers inline
    list_filter   = ('is_main',)
    search_fields = ('name', 'aliases', 'softech_personcode')


@admin.register(VendorItemMapping)
class VendorItemMappingAdmin(admin.ModelAdmin):
    list_display  = ('raw_name_normalized', 'item', 'vendor', 'use_count', 'created_at')
    list_filter   = ('vendor',)
    search_fields = ('raw_name_normalized', 'item__name')
    readonly_fields = ('created_at', 'updated_at')


class InvoiceLineInline(admin.TabularInline):
    model           = InvoiceLine
    extra           = 0
    fields          = ('manual_name', 'item', 'quantity', 'unit_price',
                       'discount_pct', 'line_total', 'is_confirmed')
    readonly_fields = ('line_total',)


@admin.register(SupplierInvoice)
class SupplierInvoiceAdmin(admin.ModelAdmin):
    list_display    = ('supplier_name', 'invoice_number', 'invoice_date',
                       'branch', 'vendor', 'status', 'created_at')
    list_filter     = ('status', 'branch')
    search_fields   = ('supplier_name', 'invoice_number')
    readonly_fields = ('created_at', 'updated_at', 'raw_ocr_text')
    inlines         = [InvoiceLineInline]
