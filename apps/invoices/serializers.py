import decimal

from django.db import models as dj_models
from rest_framework import serializers
from .models import (SupplierInvoice, InvoiceLine, VendorProfile, VendorItemMapping,
                     InvoiceBatch, PurchaseOrder, PurchaseOrderLine)


class PurchaseOrderLineSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='item.name', read_only=True, default=None)

    class Meta:
        model  = PurchaseOrderLine
        fields = ['id', 'item', 'item_name', 'quantity', 'unit_price', 'notes']


class PurchaseOrderSerializer(serializers.ModelSerializer):
    lines        = PurchaseOrderLineSerializer(many=True, required=False)
    vendor_name  = serializers.CharField(source='vendor.name', read_only=True, default=None)
    branch_name  = serializers.CharField(source='branch.name_ar', read_only=True, default=None)
    line_count   = serializers.SerializerMethodField()

    class Meta:
        model  = PurchaseOrder
        fields = ['id', 'branch', 'branch_name', 'vendor', 'vendor_name', 'po_number',
                  'status', 'notes', 'lines', 'line_count', 'created_at', 'updated_at']

    def get_line_count(self, obj):
        return obj.lines.count()

    def create(self, validated):
        lines = validated.pop('lines', [])
        po = PurchaseOrder.objects.create(**validated)
        for ln in lines:
            PurchaseOrderLine.objects.create(po=po, **ln)
        return po

    def update(self, instance, validated):
        lines = validated.pop('lines', None)
        for k, v in validated.items():
            setattr(instance, k, v)
        instance.save()
        if lines is not None:
            instance.lines.all().delete()
            for ln in lines:
                PurchaseOrderLine.objects.create(po=instance, **ln)
        return instance


class VendorProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model  = VendorProfile
        fields = ['id', 'name', 'softech_personcode', 'is_main', 'aliases',
                  'typical_discount_pct', 'ocr_profile', 'notes', 'created_at']


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
            'discount_pct', 'extra_discount_pct', 'special_discount_pct', 'tax_from_cost',
            'unit_price', 'discount_amt', 'bonus_qty',
            'vat_pct', 'distributor_margin_amt', 'pharmacist_margin_amt',
            'line_total', 'match_score', 'ocr_confidence', 'match_review',
            'needs_pick', 'price_action', 'is_confirmed',
            'notes', 'order',
        ]
        # NOTE: SupplierInvoice.ocr_flags is surfaced on the detail serializer below
        read_only_fields = ['line_total']


class RoundedDecimalField(serializers.DecimalField):
    """Rounds (half-up) to the column's decimal places instead of rejecting.

    The SofTech grid engine back-solves discounts to 4 places (e.g. خصم أساسي
    18.9467 on a margin line) while the column keeps 3; strict validation refused
    the whole save with a 400, so the operator's edit was silently lost. The
    writer re-derives the discount from the saved net at push time, so storing it
    to 3 places changes nothing that reaches SOFTECH."""

    def to_internal_value(self, data):
        try:
            value = decimal.Decimal(str(data).strip())
        except (decimal.DecimalException, TypeError, ValueError):
            return super().to_internal_value(data)
        if value.is_finite() and self.decimal_places is not None:
            value = value.quantize(decimal.Decimal(1).scaleb(-self.decimal_places),
                                   rounding=decimal.ROUND_HALF_UP)
        return super().to_internal_value(value)


class InvoiceLineWriteSerializer(serializers.ModelSerializer):
    serializer_field_mapping = {
        **serializers.ModelSerializer.serializer_field_mapping,
        dj_models.DecimalField: RoundedDecimalField,
    }

    class Meta:
        model  = InvoiceLine
        fields = [
            'manual_name', 'manufacturer', 'vendor_item_code', 'batch_number', 'expiry_date',
            'item', 'quantity', 'public_price',
            'discount_pct', 'extra_discount_pct', 'special_discount_pct', 'tax_from_cost',
            'unit_price', 'discount_amt', 'bonus_qty',
            'vat_pct', 'distributor_margin_amt', 'pharmacist_margin_amt',
            'notes', 'is_confirmed', 'price_action', 'order',
        ]

    def validate_expiry_date(self, value):
        """A typed expiry is stored normalized (YYYY-MM-DD), accepting what SofTech
        accepts: . - / separators, day first, 2- or 4-digit year."""
        if not (value or '').strip():
            return value
        from .ocr import normalize_expiry
        iso = normalize_expiry(value)
        if not iso:
            raise serializers.ValidationError('تاريخ صلاحية غير مفهوم — اكتبه يوم/شهر/سنة')
        return iso


class SupplierInvoiceListSerializer(serializers.ModelSerializer):
    branch_name     = serializers.CharField(source='branch.name_ar', read_only=True)
    vendor_name     = serializers.CharField(source='vendor.name', read_only=True, default=None)
    vendor_personcode = serializers.CharField(source='vendor.softech_personcode', read_only=True, default='')
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True, default=None)
    status_label    = serializers.SerializerMethodField()
    line_count      = serializers.SerializerMethodField()
    confirmed_count = serializers.SerializerMethodField()
    attention_count = serializers.SerializerMethodField()
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

    def get_attention_count(self, obj):
        return getattr(obj, 'attention_count', None)

    def get_source_image_url(self, obj):
        if obj.source_image:
            request = self.context.get('request')
            return request.build_absolute_uri(obj.source_image.url) if request else obj.source_image.url
        return None

    class Meta:
        model  = SupplierInvoice
        fields = [
            'id', 'branch', 'branch_name',
            'vendor', 'vendor_name', 'vendor_personcode',
            'status', 'status_label', 'doc_kind',
            'supplier_name', 'invoice_number', 'invoice_date', 'currency',
            'global_discount_pct', 'global_discount_amt', 'declared_total',
            'softech_branchcode', 'softech_docnumber', 'softech_docdate', 'return_of_docnumber',
            'source_image_url', 'ocr_flags', 'source_pages',
            'created_by_name', 'notes', 'erp_error',
            'line_count', 'confirmed_count', 'attention_count',
            'dup_check', 'dup_checked_at',
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


# ── Multi-invoice bundle ────────────────────────────────────────────────────────

class InvoiceBatchListSerializer(serializers.ModelSerializer):
    branch_name     = serializers.CharField(source='branch.name_ar', read_only=True)
    vendor_name     = serializers.CharField(source='vendor.name', read_only=True, default=None)
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True, default=None)
    status_label    = serializers.SerializerMethodField()
    invoice_count   = serializers.SerializerMethodField()

    STATUS_LABELS = dict(InvoiceBatch.STATUS)

    def get_status_label(self, obj):
        return self.STATUS_LABELS.get(obj.status, obj.status)

    def get_invoice_count(self, obj):
        return getattr(obj, 'invoice_count', obj.invoices.count())

    class Meta:
        model  = InvoiceBatch
        fields = [
            'id', 'branch', 'branch_name', 'vendor', 'vendor_name', 'doc_kind', 'ocr_engine',
            'status', 'status_label', 'page_count', 'detected_count', 'processed_count', 'invoice_count',
            'flags', 'error', 'created_by_name', 'created_at', 'updated_at',
        ]


class InvoiceBatchDetailSerializer(InvoiceBatchListSerializer):
    invoices     = SupplierInvoiceListSerializer(many=True, read_only=True)
    source_file_url = serializers.SerializerMethodField()

    def get_source_file_url(self, obj):
        if obj.source_file:
            request = self.context.get('request')
            return request.build_absolute_uri(obj.source_file.url) if request else obj.source_file.url
        return None

    class Meta(InvoiceBatchListSerializer.Meta):
        fields = InvoiceBatchListSerializer.Meta.fields + [
            'split_summary', 'source_file_url', 'invoices',
        ]


class InvoiceBatchCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = InvoiceBatch
        fields = ['branch', 'vendor', 'doc_kind', 'ocr_engine', 'source_file']
