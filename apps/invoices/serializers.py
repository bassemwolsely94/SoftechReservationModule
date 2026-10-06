from rest_framework import serializers
from .models import SupplierInvoice, InvoiceLine, VendorProfile, VendorItemMapping


class VendorProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model  = VendorProfile
        fields = ['id', 'name', 'softech_personcode', 'is_main', 'aliases',
                  'typical_discount_pct', 'notes', 'created_at']


class InvoiceLineSerializer(serializers.ModelSerializer):
    item_name       = serializers.CharField(source='item.name', read_only=True, default=None)
    item_softech_id = serializers.CharField(source='item.softech_id', read_only=True, default=None)
    item_sale_price = serializers.SerializerMethodField()

    def get_item_sale_price(self, obj):
        return float(obj.item.unit_price) if obj.item_id else None

    class Meta:
        model  = InvoiceLine
        fields = [
            'id', 'raw_text', 'manual_name',
            'manufacturer', 'vendor_item_code', 'batch_number', 'expiry_date',
            'item', 'item_name', 'item_softech_id', 'item_sale_price',
            'quantity', 'public_price',
            'discount_pct', 'extra_discount_pct',
            'unit_price', 'discount_amt',
            'vat_pct', 'distributor_margin_amt', 'pharmacist_margin_amt',
            'line_total', 'match_score', 'ocr_confidence', 'match_review', 'is_confirmed',
            'notes', 'order',
        ]
        read_only_fields = ['line_total']


class InvoiceLineWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model  = InvoiceLine
        fields = [
            'manual_name', 'manufacturer', 'vendor_item_code', 'batch_number', 'expiry_date',
            'item', 'quantity', 'public_price',
            'discount_pct', 'extra_discount_pct',
            'unit_price', 'discount_amt',
            'vat_pct', 'distributor_margin_amt', 'pharmacist_margin_amt',
            'notes', 'is_confirmed', 'order',
        ]


class SupplierInvoiceListSerializer(serializers.ModelSerializer):
    branch_name     = serializers.CharField(source='branch.name_ar', read_only=True)
    vendor_name     = serializers.CharField(source='vendor.name', read_only=True, default=None)
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True, default=None)
    status_label    = serializers.SerializerMethodField()
    line_count      = serializers.SerializerMethodField()
    confirmed_count = serializers.SerializerMethodField()
    source_image_url= serializers.SerializerMethodField()

    STATUS_LABELS = {
        'pending':     'في الانتظار',
        'processing':  'جاري المعالجة',
        'review':      'قيد المراجعة',
        'confirmed':   'مُأكَّدة',
        'rejected':    'مرفوضة',
        'queued':      'بانتظار الترحيل',
        'pushing':     'جارٍ الترحيل',
        'finalized':   'مُرحَّلة إلى ERP',
        'push_failed': 'فشل الترحيل',
    }

    def get_status_label(self, obj):
        return self.STATUS_LABELS.get(obj.status, obj.status)

    def get_line_count(self, obj):
        return getattr(obj, 'line_count', obj.lines.count())

    def get_confirmed_count(self, obj):
        return getattr(obj, 'confirmed_count', obj.lines.filter(is_confirmed=True).count())

    def get_source_image_url(self, obj):
        if obj.source_image:
            request = self.context.get('request')
            return request.build_absolute_uri(obj.source_image.url) if request else obj.source_image.url
        return None

    class Meta:
        model  = SupplierInvoice
        fields = [
            'id', 'branch', 'branch_name',
            'vendor', 'vendor_name',
            'status', 'status_label', 'doc_kind',
            'supplier_name', 'invoice_number', 'invoice_date', 'currency',
            'global_discount_pct', 'global_discount_amt', 'declared_total',
            'softech_branchcode', 'softech_docnumber', 'softech_docdate', 'return_of_docnumber',
            'source_image_url',
            'created_by_name', 'notes', 'erp_error',
            'line_count', 'confirmed_count',
            'created_at', 'updated_at',
        ]


class SupplierInvoiceDetailSerializer(SupplierInvoiceListSerializer):
    lines            = InvoiceLineSerializer(many=True, read_only=True)
    total_before_discount = serializers.FloatField(read_only=True)
    total_after_discount  = serializers.FloatField(read_only=True)

    class Meta(SupplierInvoiceListSerializer.Meta):
        fields = SupplierInvoiceListSerializer.Meta.fields + [
            'raw_ocr_text', 'lines',
            'total_before_discount', 'total_after_discount',
        ]


class SupplierInvoiceCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = SupplierInvoice
        fields = [
            'branch', 'vendor', 'doc_kind', 'supplier_name', 'invoice_number', 'invoice_date',
            'currency', 'global_discount_pct', 'global_discount_amt',
            'return_of_docnumber', 'source_image', 'notes',
        ]
