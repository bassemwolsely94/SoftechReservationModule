from django.contrib import admin

from .models import (
    DocumentType, Recipient, RecipientLocation,
    CommerceDocument, DocumentLine, AllocationCell,
)


@admin.register(DocumentType)
class DocumentTypeAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'number_prefix', 'pricing_profile', 'is_allocation', 'is_active')
    list_filter  = ('pricing_profile', 'is_allocation', 'is_active')


class RecipientLocationInline(admin.TabularInline):
    model = RecipientLocation
    extra = 0


@admin.register(Recipient)
class RecipientAdmin(admin.ModelAdmin):
    list_display = ('name', 'kind', 'phone', 'is_active')
    list_filter  = ('kind', 'is_active')
    search_fields = ('name', 'phone', 'tax_id')
    inlines = [RecipientLocationInline]


class DocumentLineInline(admin.TabularInline):
    model = DocumentLine
    extra = 0


@admin.register(CommerceDocument)
class CommerceDocumentAdmin(admin.ModelAdmin):
    list_display = ('number', 'doc_type', 'recipient', 'doc_date', 'status', 'total', 'vat_total')
    list_filter  = ('doc_type', 'status')
    search_fields = ('number',)
    inlines = [DocumentLineInline]


@admin.register(AllocationCell)
class AllocationCellAdmin(admin.ModelAdmin):
    list_display = ('line', 'location', 'quantity')
