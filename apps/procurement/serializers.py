"""
apps/procurement/serializers.py

Serializers for the Procurement Intelligence Platform.
"""
import time
from rest_framework import serializers
from .models import (
    PurchaseLine, SupplierProfile, SupplierItemMapping,
    ProcurementEngineRun, ProcurementSnapshot, BuyerPerformance,
    ProcurementAlert, SupplierSegmentation,
    SupplierCategory, SupplierClassificationRule,
)


# ── DB-driven category label/colour lookup (short-lived process cache) ─────────
_CAT_CACHE = {'ts': 0.0, 'labels': {}, 'colors': {}}
_CAT_TTL = 30  # seconds


def category_maps():
    """Return (labels, colors) dicts {code: name_ar/color}, cached ~30s.

    Falls back to the code itself when a category row is missing (e.g. legacy
    codes left on manual-override suppliers).
    """
    now = time.time()
    if now - _CAT_CACHE['ts'] > _CAT_TTL or not _CAT_CACHE['labels']:
        rows = list(SupplierCategory.objects.values('code', 'name_ar', 'color'))
        _CAT_CACHE['labels'] = {r['code']: r['name_ar'] for r in rows}
        _CAT_CACHE['colors'] = {r['code']: r['color'] for r in rows}
        _CAT_CACHE['ts'] = now
    return _CAT_CACHE['labels'], _CAT_CACHE['colors']


def category_label(code):
    labels, _ = category_maps()
    return labels.get(code, code or '—')


# ── PurchaseLine ──────────────────────────────────────────────────────────────

class PurchaseLineSerializer(serializers.ModelSerializer):
    item_name   = serializers.SerializerMethodField()
    branch_name = serializers.SerializerMethodField()
    direction   = serializers.SerializerMethodField()

    class Meta:
        model  = PurchaseLine
        fields = [
            'id', 'branch_code', 'branch_name', 'supplier_code', 'doc_number',
            'doc_date', 'item_code', 'item_name', 'doccode', 'is_return', 'direction',
            'raw_qty', 'raw_value', 'unit_price', 'cost_price',
            'net_qty', 'net_value', 'public_price', 'margin_pct',
            'buyer_code', 'doc_value', 'store_code', 'synced_at',
        ]
        read_only_fields = fields

    def get_item_name(self, obj):
        return obj.item.name if obj.item else ''

    def get_branch_name(self, obj):
        return obj.branch.name if obj.branch else ''

    def get_direction(self, obj):
        return 'مرتجع' if obj.is_return else 'شراء'


# ── SupplierProfile ───────────────────────────────────────────────────────────

class SupplierProfileSerializer(serializers.ModelSerializer):
    score_label = serializers.SerializerMethodField()

    class Meta:
        model  = SupplierProfile
        fields = [
            'id', 'supplier_code', 'supplier_name', 'classif_code',
            # Performance
            'net_purchase_value', 'net_purchase_qty', 'net_return_value', 'return_pct',
            'distinct_items', 'invoice_count', 'avg_margin_pct',
            'branches_supplied', 'purchase_frequency',
            # Windows
            'value_30d', 'value_90d', 'value_365d',
            # Scores
            'score_margin', 'score_availability', 'score_returns',
            'score_price_stability', 'total_score', 'score_label',
            # Dates
            'first_purchase_date', 'last_purchase_date', 'last_updated',
        ]
        read_only_fields = fields

    def get_score_label(self, obj):
        s = float(obj.total_score)
        if s >= 80:
            return 'ممتاز'
        if s >= 60:
            return 'جيد'
        if s >= 40:
            return 'مقبول'
        return 'ضعيف'


class SupplierProfileListSerializer(serializers.ModelSerializer):
    """Lightweight version for list views."""
    score_label = serializers.SerializerMethodField()

    class Meta:
        model  = SupplierProfile
        fields = [
            'id', 'supplier_code', 'supplier_name', 'classif_code',
            'net_purchase_value', 'value_30d', 'value_90d',
            'return_pct', 'avg_margin_pct', 'distinct_items',
            'invoice_count', 'total_score', 'score_label',
            'last_purchase_date',
        ]
        read_only_fields = fields

    def get_score_label(self, obj):
        s = float(obj.total_score)
        if s >= 80:
            return 'ممتاز'
        if s >= 60:
            return 'جيد'
        if s >= 40:
            return 'مقبول'
        return 'ضعيف'


# ── SupplierItemMapping ───────────────────────────────────────────────────────

class SupplierItemMappingSerializer(serializers.ModelSerializer):
    accuracy_pct = serializers.SerializerMethodField()

    class Meta:
        model  = SupplierItemMapping
        fields = [
            'id', 'supplier_code', 'supplier_name', 'item_code', 'item_name',
            'purchase_count', 'last_purchase_date', 'first_purchase_date',
            'net_qty_total', 'net_value_total',
            'min_price', 'max_price', 'avg_price', 'last_price', 'price_drift_pct',
            'confidence_score', 'is_primary',
            'ocr_match_count', 'ocr_correction_count', 'accuracy_pct',
            'last_updated',
        ]
        read_only_fields = fields

    def get_accuracy_pct(self, obj):
        total = obj.ocr_match_count + obj.ocr_correction_count
        if total == 0:
            return None
        return round(obj.ocr_match_count / total * 100, 1)


# ── ProcurementEngineRun ──────────────────────────────────────────────────────

class ProcurementEngineRunSerializer(serializers.ModelSerializer):
    duration_seconds = serializers.SerializerMethodField()

    class Meta:
        model  = ProcurementEngineRun
        fields = [
            'id', 'started_at', 'finished_at', 'status', 'period_days',
            'lines_synced', 'lines_upserted', 'suppliers_updated',
            'mappings_updated', 'alerts_generated',
            'error_message', 'triggered_by', 'duration_seconds',
        ]
        read_only_fields = fields

    def get_duration_seconds(self, obj):
        if obj.finished_at and obj.started_at:
            return round((obj.finished_at - obj.started_at).total_seconds())
        return None


# ── ProcurementSnapshot ───────────────────────────────────────────────────────

class ProcurementSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ProcurementSnapshot
        fields = [
            'id', 'snapshot_date',
            # Values
            'net_purchase_value_30d', 'net_purchase_value_90d', 'net_purchase_value_365d',
            # Quantities
            'net_purchase_qty_30d', 'net_purchase_qty_90d', 'net_purchase_qty_365d',
            # Items
            'distinct_items_30d', 'distinct_items_90d', 'distinct_items_365d',
            # Suppliers
            'distinct_suppliers_30d', 'distinct_suppliers_90d', 'distinct_suppliers_365d',
            # Invoices
            'invoice_count_30d', 'invoice_count_90d', 'invoice_count_365d',
            # Margins
            'avg_margin_pct_30d', 'avg_margin_pct_90d', 'avg_margin_pct_365d',
            # Returns
            'return_value_30d', 'return_pct_30d',
            # Concentration
            'top3_supplier_pct_365d',
            # Growth
            'purchase_growth_pct_mom', 'purchase_growth_pct_yoy',
            'created_at',
        ]
        read_only_fields = fields


# ── BuyerPerformance ──────────────────────────────────────────────────────────

class BuyerPerformanceSerializer(serializers.ModelSerializer):
    score_label = serializers.SerializerMethodField()

    class Meta:
        model  = BuyerPerformance
        fields = [
            'id', 'buyer_code', 'buyer_name', 'period_start', 'period_end',
            'net_purchase_value', 'invoice_count', 'distinct_items',
            'distinct_suppliers', 'avg_margin_pct', 'return_pct',
            'estimated_savings', 'procurement_score', 'score_label',
            'created_at',
        ]
        read_only_fields = fields

    def get_score_label(self, obj):
        s = float(obj.procurement_score)
        if s >= 80:
            return 'ممتاز'
        if s >= 60:
            return 'جيد'
        if s >= 40:
            return 'مقبول'
        return 'ضعيف'


# ── ProcurementAlert ──────────────────────────────────────────────────────────

class ProcurementAlertSerializer(serializers.ModelSerializer):
    alert_type_display = serializers.CharField(source='get_alert_type_display', read_only=True)
    severity_display   = serializers.CharField(source='get_severity_display',   read_only=True)

    class Meta:
        model  = ProcurementAlert
        fields = [
            'id', 'alert_type', 'alert_type_display', 'severity', 'severity_display',
            'entity_type', 'entity_code', 'entity_name',
            'title', 'message', 'metric_value', 'threshold',
            'detected_at', 'is_resolved', 'resolved_at', 'resolved_by', 'resolution_notes',
        ]
        read_only_fields = [f for f in fields if f not in ('is_resolved', 'resolved_by', 'resolution_notes')]


class ProcurementAlertResolveSerializer(serializers.Serializer):
    resolved_by     = serializers.CharField(max_length=100, required=True)
    resolution_notes = serializers.CharField(required=False, allow_blank=True, default='')


# ── v2: SupplierSegmentation ──────────────────────────────────────────────────

class SupplierSegmentationSerializer(serializers.ModelSerializer):
    supplier_category_display = serializers.SerializerMethodField()

    def get_supplier_category_display(self, obj):
        return category_label(obj.supplier_category)

    class Meta:
        model  = SupplierSegmentation
        fields = [
            'id', 'supplier_code', 'supplier_name',
            'supplier_category', 'supplier_category_display',
            'ptcode', 'ptclassifcode', 'persontype', 'persontypeclassif',
            'auto_classified', 'manual_override', 'notes',
            'purchase_value_365d', 'invoice_count_365d',
            'foc_rate_pct', 'return_pct',
            'classified_at',
        ]
        read_only_fields = [
            f for f in fields
            if f not in ('supplier_category', 'manual_override', 'notes')
        ]


# ── v2: Enhanced PurchaseLine (with FOC + tax + return type) ─────────────────

class PurchaseLineEnhancedSerializer(serializers.ModelSerializer):
    item_name              = serializers.SerializerMethodField()
    branch_name            = serializers.SerializerMethodField()
    direction              = serializers.SerializerMethodField()
    supplier_category_display = serializers.SerializerMethodField()

    class Meta:
        model  = PurchaseLine
        fields = [
            'id', 'branch_code', 'branch_name', 'supplier_code', 'doc_number',
            'doc_date', 'item_code', 'item_name', 'doccode', 'is_return', 'direction',
            'raw_qty', 'raw_value', 'unit_price', 'cost_price',
            'net_qty', 'net_value', 'public_price', 'margin_pct',
            'buyer_code', 'doc_value', 'store_code',
            # v2 fields
            'is_foc', 'foc_type', 'bonus_qty',
            'vat_value', 'tax_rate_pct', 'effective_cost',
            'return_type',
            'supplier_category', 'supplier_category_display',
            'synced_at',
        ]
        read_only_fields = fields

    def get_item_name(self, obj):
        return obj.item.name if obj.item else ''

    def get_branch_name(self, obj):
        return obj.branch.name if obj.branch else ''

    def get_direction(self, obj):
        return 'مرتجع' if obj.is_return else 'شراء'

    def get_supplier_category_display(self, obj):
        return category_label(obj.supplier_category)


# ── v3: Admin-managed categories + classification rules ──────────────────────

class SupplierCategorySerializer(serializers.ModelSerializer):
    rule_count     = serializers.SerializerMethodField()
    supplier_count = serializers.SerializerMethodField()

    class Meta:
        model  = SupplierCategory
        fields = [
            'id', 'code', 'name_ar', 'name_en', 'color',
            'sort_order', 'is_active', 'is_fallback', 'notes',
            'rule_count', 'supplier_count',
        ]

    def get_rule_count(self, obj):
        return obj.rules.count()

    def get_supplier_count(self, obj):
        # cheap denormalized count from the segmentation cache
        return SupplierSegmentation.objects.filter(supplier_category=obj.code).count()


class SupplierClassificationRuleSerializer(serializers.ModelSerializer):
    category_code = serializers.CharField(source='category.code', read_only=True)
    category_name = serializers.CharField(source='category.name_ar', read_only=True)

    class Meta:
        model  = SupplierClassificationRule
        fields = [
            'id', 'ptcode', 'ptclassifcode',
            'category', 'category_code', 'category_name',
            'priority', 'is_active', 'notes',
        ]


# ── v2: Enhanced SupplierProfile (includes v2 score fields) ──────────────────

class SupplierProfileEnhancedSerializer(serializers.ModelSerializer):
    score_label          = serializers.SerializerMethodField()
    enhanced_score_label = serializers.SerializerMethodField()
    supplier_category_display = serializers.SerializerMethodField()

    class Meta:
        model  = SupplierProfile
        fields = [
            'id', 'supplier_code', 'supplier_name', 'classif_code',
            'supplier_category', 'supplier_category_display',
            # Performance
            'net_purchase_value', 'net_purchase_qty', 'net_return_value', 'return_pct',
            'distinct_items', 'invoice_count', 'avg_margin_pct',
            'branches_supplied', 'purchase_frequency',
            # Windows
            'value_30d', 'value_90d', 'value_365d',
            # Classic scores
            'score_margin', 'score_availability', 'score_returns',
            'score_price_stability', 'total_score', 'score_label',
            # v2 scores
            'score_effective_cost', 'score_foc_benefit', 'score_tax_efficiency',
            'enhanced_total_score', 'enhanced_score_label',
            # v2 stats
            'foc_rate_pct', 'avg_tax_burden_pct',
            # Dates
            'first_purchase_date', 'last_purchase_date', 'last_updated',
        ]
        read_only_fields = fields

    def get_score_label(self, obj):
        s = float(obj.total_score)
        if s >= 80: return 'ممتاز'
        if s >= 60: return 'جيد'
        if s >= 40: return 'مقبول'
        return 'ضعيف'

    def get_enhanced_score_label(self, obj):
        s = float(obj.enhanced_total_score)
        if s >= 80: return 'ممتاز'
        if s >= 60: return 'جيد'
        if s >= 40: return 'مقبول'
        return 'ضعيف'

    def get_supplier_category_display(self, obj):
        return category_label(obj.supplier_category)
