from django.contrib import admin
from .models import SupplierInvoice, InvoiceLine


class InvoiceLineInline(admin.TabularInline):
    model       = InvoiceLine
    extra       = 0
    fields      = ('manual_name', 'item', 'quantity', 'unit_price', 'discount_pct', 'line_total', 'is_confirmed')
    readonly_fields = ('line_total',)


@admin.register(SupplierInvoice)
class SupplierInvoiceAdmin(admin.ModelAdmin):
    list_display  = ('supplier_name', 'invoice_number', 'invoice_date', 'branch', 'status', 'created_at')
    list_filter   = ('status', 'branch')
    search_fields = ('supplier_name', 'invoice_number')
    readonly_fields = ('created_at', 'updated_at', 'raw_ocr_text')
    inlines       = [InvoiceLineInline]
