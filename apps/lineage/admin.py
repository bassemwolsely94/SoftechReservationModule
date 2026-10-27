from django.contrib import admin

from .models import DocumentEdge, DocumentRef


@admin.register(DocumentRef)
class DocumentRefAdmin(admin.ModelAdmin):
    list_display = ('doc_kind', 'branchcode', 'doccode', 'docnumber', 'docdate', 'amount', 'party_code', 'phcode')
    list_filter = ('doc_kind', 'branchcode')
    search_fields = ('docnumber', 'phcode', 'party_code')


@admin.register(DocumentEdge)
class DocumentEdgeAdmin(admin.ModelAdmin):
    list_display = ('from_ref', 'relation', 'to_ref', 'amount', 'origin', 'status', 'confidence')
    list_filter = ('relation', 'origin', 'status')
    raw_id_fields = ('from_ref', 'to_ref', 'decided_by')
