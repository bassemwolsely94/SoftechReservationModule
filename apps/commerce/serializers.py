from rest_framework import serializers

from .models import (
    DocumentType, Recipient, RecipientLocation,
    CommerceDocument, DocumentLine, AllocationCell,
)


class DocumentTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model  = DocumentType
        fields = ['id', 'code', 'name', 'number_prefix', 'pricing_profile',
                  'is_allocation', 'lifecycle', 'default_vat_rate', 'is_active']


class RecipientLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model  = RecipientLocation
        fields = ['id', 'recipient', 'name', 'code', 'address', 'sort_order', 'is_active']
        read_only_fields = ['recipient']


class RecipientSerializer(serializers.ModelSerializer):
    locations = RecipientLocationSerializer(many=True, read_only=True)

    class Meta:
        model  = Recipient
        fields = ['id', 'name', 'kind', 'phone', 'address', 'tax_id', 'notes',
                  'is_active', 'locations', 'created_at']
        read_only_fields = ['created_at']


class DocumentLineSerializer(serializers.ModelSerializer):
    # VAT-inclusive derivations (computed against the parent document's rate)
    line_total  = serializers.SerializerMethodField()
    vat_amount  = serializers.SerializerMethodField()
    base_amount = serializers.SerializerMethodField()

    class Meta:
        model  = DocumentLine
        fields = ['id', 'document', 'sort_order', 'item_code', 'item_name',
                  'unit_price', 'quantity', 'vat_applicable', 'notes',
                  'line_total', 'vat_amount', 'base_amount']
        read_only_fields = ['document']

    def _rate(self, obj):
        return obj.document.vat_rate if obj.document_id else 0

    def get_line_total(self, obj):  return float(obj.line_total)
    def get_vat_amount(self, obj):  return float(obj.vat_amount(self._rate(obj)))
    def get_base_amount(self, obj): return float(obj.base_amount(self._rate(obj)))


class CommerceDocumentSerializer(serializers.ModelSerializer):
    lines          = DocumentLineSerializer(many=True, read_only=True)
    type_name      = serializers.CharField(source='doc_type.name', read_only=True)
    type_code      = serializers.CharField(source='doc_type.code', read_only=True)
    is_allocation  = serializers.BooleanField(source='doc_type.is_allocation', read_only=True)
    recipient_name = serializers.CharField(source='recipient.name', read_only=True, default=None)

    class Meta:
        model  = CommerceDocument
        fields = ['id', 'doc_type', 'type_name', 'type_code', 'is_allocation',
                  'recipient', 'recipient_name', 'number', 'doc_date', 'valid_until',
                  'status', 'vat_rate', 'subtotal_ex_vat', 'vat_total', 'total',
                  'notes', 'lines', 'created_at', 'updated_at']
        read_only_fields = ['number', 'subtotal_ex_vat', 'vat_total', 'total',
                            'created_at', 'updated_at']


class CommerceDocumentListSerializer(serializers.ModelSerializer):
    type_name      = serializers.CharField(source='doc_type.name', read_only=True)
    type_code      = serializers.CharField(source='doc_type.code', read_only=True)
    recipient_name = serializers.CharField(source='recipient.name', read_only=True, default=None)
    line_count     = serializers.IntegerField(source='lines.count', read_only=True)

    class Meta:
        model  = CommerceDocument
        fields = ['id', 'doc_type', 'type_name', 'type_code', 'recipient', 'recipient_name',
                  'number', 'doc_date', 'status', 'total', 'vat_total', 'line_count', 'created_at']
