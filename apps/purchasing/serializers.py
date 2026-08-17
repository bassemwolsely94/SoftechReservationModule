"""
apps/purchasing/serializers.py
"""
from rest_framework import serializers
from .models import (
    DemandCalculationRun,
    ItemDemandMetrics,
    ItemDemandAggregated,
    TransferRecommendationRun,
    TransferRecommendation,
    LostSalesRun,
)


class RunSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model  = DemandCalculationRun
        fields = [
            'id', 'started_at', 'finished_at', 'status', 'status_display',
            'calc_date', 'softech_available', 'data_through_date',
            'sync_lookback_days', 'rows_synced', 'rows_purged',
            'branches_processed', 'items_processed', 'rows_written',
            'duration_seconds', 'error_message', 'progress',
        ]
        read_only_fields = fields


class MetricsSerializer(serializers.ModelSerializer):
    item_id              = serializers.IntegerField(source='item.id',            read_only=True)
    item_name            = serializers.CharField(source='item.name',             read_only=True)
    item_code            = serializers.CharField(source='item.softech_id',       read_only=True)
    item_medicine_type      = serializers.CharField(source='item.medicine_type',         read_only=True, default='')
    item_medicine_type_name = serializers.CharField(source='item.medicine_type_name',    read_only=True, default='')
    item_medicine_type_ar   = serializers.CharField(source='item.medicine_type_name_ar', read_only=True, default='')
    item_supplier_code      = serializers.CharField(source='item.supplier_code',         read_only=True, default='')
    item_supplier_name      = serializers.CharField(source='item.supplier_name',         read_only=True, default='')
    item_family_code        = serializers.CharField(source='item.family_code',           read_only=True, default='')
    item_family_name        = serializers.CharField(source='item.family_name',           read_only=True, default='')
    item_category_id        = serializers.IntegerField(source='item.category_id',        read_only=True, allow_null=True)
    item_category_name      = serializers.SerializerMethodField()
    item_requires_fridge    = serializers.BooleanField(source='item.requires_fridge',    read_only=True)
    item_is_active          = serializers.BooleanField(source='item.is_active',          read_only=True)
    item_is_stockable       = serializers.BooleanField(source='item.is_stockable',       read_only=True)
    branch_id               = serializers.IntegerField(source='branch.id',               read_only=True)
    branch_name             = serializers.SerializerMethodField()
    stock_status            = serializers.CharField(read_only=True)
    stock_status_color      = serializers.CharField(read_only=True)
    needs_purchase          = serializers.BooleanField(read_only=True)
    cost_price            = serializers.DecimalField(source='item.cost_price', read_only=True, max_digits=10, decimal_places=3)
    std_gross_margin_pct  = serializers.SerializerMethodField()
    net_margin_pct        = serializers.SerializerMethodField()

    class Meta:
        model  = ItemDemandMetrics
        fields = [
            'id', 'calc_date',
            'item_id', 'item_name', 'item_code',
            'item_medicine_type', 'item_medicine_type_name', 'item_medicine_type_ar',
            'item_supplier_code', 'item_supplier_name',
            'item_family_code', 'item_family_name',
            'item_category_id', 'item_category_name',
            'item_requires_fridge', 'item_is_active', 'item_is_stockable',
            'branch_id', 'branch_name',
            # Raw window quantities
            'qty_30d', 'qty_90d', 'qty_365d',
            # Monthly rates (Excel-exact)
            'rate_30d', 'rate_90d', 'rate_365d', 'monthly_avg',
            # Invoice counts
            'invoices_30d', 'invoices_90d', 'invoices_365d',
            # Transaction counts + avg (MonthlyAvg3RatesofTRNsCount)
            'trns_30d', 'trns_90d', 'trns_365d', 'monthly_avg_trns',
            # Stock & coverage
            'safety_stock', 'current_stock', 'in_transit_qty', 'coverage_months',
            'pct_stock_of_total',
            # Decision fields
            'gap', 'priority', 'abc_class',
            # Value
            'pack_price', 'cost_price', 'monthly_value',
            # Actual revenue & margins
            'net_sales_revenue',
            'std_gross_margin_pct', 'net_margin_pct',
            # MODULE 13 — Lost Sales Intelligence
            'coverage_days', 'stockout_days_30d', 'bottleneck_days_30d',
            'lost_qty_30d', 'lost_revenue_30d', 'lost_margin_30d',
            'availability_rate_30d', 'root_cause',
            # UI helpers
            'last_sale_date', 'stock_status', 'stock_status_color', 'needs_purchase',
        ]
        read_only_fields = fields

    def get_branch_name(self, obj):
        return obj.branch.name_ar or obj.branch.name

    def get_item_category_name(self, obj):
        cat = obj.item.category
        if cat:
            return cat.name_ar or cat.name
        return ''

    def get_std_gross_margin_pct(self, obj):
        """Standard Gross Margin % = (pack_price - cost_price) / pack_price × 100"""
        try:
            pack = float(obj.item.pack_price or 0)
            cost = float(obj.item.cost_price or 0)
            if pack > 0 and cost > 0:
                return round((pack - cost) / pack * 100, 1)
        except (TypeError, ValueError):
            pass
        return None

    def get_net_margin_pct(self, obj):
        """
        Net Margin After Discount % = (avg_actual_price - cost_price) / pack_price × 100
        avg_actual_price = net_sales_revenue / qty_365d  (weighted by qty sold)
        """
        try:
            pack    = float(obj.item.pack_price or 0)
            cost    = float(obj.item.cost_price or 0)
            qty     = float(obj.qty_365d or 0)
            revenue = float(obj.net_sales_revenue or 0)
            if pack > 0 and cost > 0 and qty > 0 and revenue > 0:
                avg_actual = revenue / qty
                return round((avg_actual - cost) / pack * 100, 1)
        except (TypeError, ValueError):
            pass
        return None


class AggregatedSerializer(serializers.ModelSerializer):
    item_id                 = serializers.IntegerField(source='item.id',                 read_only=True)
    item_name               = serializers.CharField(source='item.name',                  read_only=True)
    item_code               = serializers.CharField(source='item.softech_id',            read_only=True)
    item_medicine_type      = serializers.CharField(source='item.medicine_type',         read_only=True, default='')
    item_medicine_type_name = serializers.CharField(source='item.medicine_type_name',    read_only=True, default='')
    item_medicine_type_ar   = serializers.CharField(source='item.medicine_type_name_ar', read_only=True, default='')
    item_supplier_code      = serializers.CharField(source='item.supplier_code',         read_only=True, default='')
    item_supplier_name      = serializers.CharField(source='item.supplier_name',         read_only=True, default='')
    item_family_code        = serializers.CharField(source='item.family_code',           read_only=True, default='')
    item_family_name        = serializers.CharField(source='item.family_name',           read_only=True, default='')
    item_category_id        = serializers.IntegerField(source='item.category_id',        read_only=True, allow_null=True)
    item_category_name      = serializers.SerializerMethodField()
    item_requires_fridge    = serializers.BooleanField(source='item.requires_fridge',    read_only=True)
    item_is_active          = serializers.BooleanField(source='item.is_active',          read_only=True)
    item_is_stockable       = serializers.BooleanField(source='item.is_stockable',       read_only=True)
    cost_price           = serializers.DecimalField(source='item.cost_price', read_only=True, max_digits=10, decimal_places=3)
    std_gross_margin_pct = serializers.SerializerMethodField()
    net_margin_pct       = serializers.SerializerMethodField()

    class Meta:
        model  = ItemDemandAggregated
        fields = [
            'id', 'calc_date',
            'item_id', 'item_name', 'item_code',
            'item_medicine_type', 'item_medicine_type_name', 'item_medicine_type_ar',
            'item_supplier_code', 'item_supplier_name',
            'item_family_code', 'item_family_name',
            'item_category_id', 'item_category_name',
            'item_requires_fridge', 'item_is_active', 'item_is_stockable',
            'total_qty_30d', 'total_qty_90d', 'total_qty_365d',
            'total_monthly_avg', 'total_current_stock', 'total_in_transit',
            'total_monthly_value', 'total_gap',
            'abc_class', 'cumulative_pct',
            'branches_with_sales', 'branches_with_gap',
            'pack_price', 'cost_price',
            'total_net_sales_revenue',
            'std_gross_margin_pct', 'net_margin_pct',
            # MODULE 13 — Lost Sales (network rollup)
            'total_lost_qty_30d', 'total_lost_revenue_30d', 'total_lost_margin_30d',
            'network_availability_rate_30d',
        ]
        read_only_fields = fields

    def get_item_category_name(self, obj):
        cat = obj.item.category
        if cat:
            return cat.name_ar or cat.name
        return ''

    def get_std_gross_margin_pct(self, obj):
        """Standard Gross Margin % = (pack_price - cost_price) / pack_price × 100"""
        try:
            pack = float(obj.item.pack_price or 0)
            cost = float(obj.item.cost_price or 0)
            if pack > 0 and cost > 0:
                return round((pack - cost) / pack * 100, 1)
        except (TypeError, ValueError):
            pass
        return None

    def get_net_margin_pct(self, obj):
        """Net Margin % = (avg_actual_price - cost_price) / pack_price × 100 (network-level)"""
        try:
            pack    = float(obj.item.pack_price or 0)
            cost    = float(obj.item.cost_price or 0)
            qty     = float(obj.total_qty_365d or 0)
            revenue = float(obj.total_net_sales_revenue or 0)
            if pack > 0 and cost > 0 and qty > 0 and revenue > 0:
                avg_actual = revenue / qty
                return round((avg_actual - cost) / pack * 100, 1)
        except (TypeError, ValueError):
            pass
        return None


# ── MODULE 13 — Lost Sales Run ────────────────────────────────────────────────

class LostSalesRunSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model  = LostSalesRun
        fields = [
            'id', 'demand_run_id', 'status', 'status_display',
            'started_at', 'finished_at', 'error_message',
            'items_affected', 'branch_item_pairs',
            'total_lost_revenue', 'total_lost_margin',
            'root_cause_breakdown',
        ]
        read_only_fields = fields


# ── MODULE 2 — Transfer Recommendations ──────────────────────────────────────

class TransferRecommendationRunSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model  = TransferRecommendationRun
        fields = [
            'id', 'demand_run_id', 'status', 'status_display',
            'started_at', 'finished_at', 'error_message',
            'total_recommendations', 'total_items_covered', 'total_transfer_value',
        ]
        read_only_fields = fields


class TransferRecommendationSerializer(serializers.ModelSerializer):
    # Adoption tracking — how many TransferRequests were created from this recommendation
    actioned_requests_count = serializers.SerializerMethodField()
    is_actioned             = serializers.SerializerMethodField()
    item_id                 = serializers.IntegerField(source='item.id',                 read_only=True)
    item_name               = serializers.CharField(source='item.name',                  read_only=True)
    item_code               = serializers.CharField(source='item.softech_id',            read_only=True)
    item_medicine_type      = serializers.CharField(source='item.medicine_type',         read_only=True, default='')
    item_medicine_type_name = serializers.CharField(source='item.medicine_type_name',    read_only=True, default='')
    item_medicine_type_ar   = serializers.CharField(source='item.medicine_type_name_ar', read_only=True, default='')
    item_supplier_code      = serializers.CharField(source='item.supplier_code',         read_only=True, default='')
    item_supplier_name      = serializers.CharField(source='item.supplier_name',         read_only=True, default='')
    item_family_code        = serializers.CharField(source='item.family_code',           read_only=True, default='')
    item_family_name        = serializers.CharField(source='item.family_name',           read_only=True, default='')
    item_category_id        = serializers.IntegerField(source='item.category_id',        read_only=True, allow_null=True)
    item_category_name      = serializers.SerializerMethodField()
    item_requires_fridge    = serializers.BooleanField(source='item.requires_fridge',    read_only=True)
    item_is_active          = serializers.BooleanField(source='item.is_active',          read_only=True)
    item_is_stockable       = serializers.BooleanField(source='item.is_stockable',       read_only=True)
    from_branch_id          = serializers.IntegerField(source='from_branch.id',          read_only=True)
    from_branch_name        = serializers.SerializerMethodField()
    to_branch_id            = serializers.IntegerField(source='to_branch.id',            read_only=True)
    to_branch_name          = serializers.SerializerMethodField()
    status_display          = serializers.CharField(source='get_status_display',         read_only=True)
    abc_class_display       = serializers.SerializerMethodField()
    cost_price           = serializers.DecimalField(source='item.cost_price', read_only=True, max_digits=10, decimal_places=3)
    std_gross_margin_pct = serializers.SerializerMethodField()

    class Meta:
        model  = TransferRecommendation
        fields = [
            'id', 'created_at',
            # Item
            'item_id', 'item_name', 'item_code',
            'item_medicine_type', 'item_medicine_type_name', 'item_medicine_type_ar',
            'item_supplier_code', 'item_supplier_name',
            'item_family_code', 'item_family_name',
            'item_category_id', 'item_category_name',
            'item_requires_fridge', 'item_is_active', 'item_is_stockable',
            # Branches
            'from_branch_id', 'from_branch_name',
            'to_branch_id',   'to_branch_name',
            # Transfer quantities
            'quantity', 'pack_price', 'cost_price', 'estimated_value',
            # Margin
            'std_gross_margin_pct',
            # Priority
            'priority_score',
            # Source snapshot
            'from_stock', 'from_safety', 'from_surplus', 'from_monthly_avg',
            # Destination snapshot
            'to_stock', 'to_gap', 'to_monthly_avg', 'to_priority',
            # Classification
            'abc_class', 'abc_class_display',
            # Review
            'status', 'status_display', 'notes', 'reviewed_at',
            # Adoption tracking (linked TransferRequests)
            'actioned_requests_count', 'is_actioned',
        ]
        read_only_fields = [f for f in fields if f != 'notes']

    def get_from_branch_name(self, obj):
        return obj.from_branch.name_ar or obj.from_branch.name

    def get_to_branch_name(self, obj):
        return obj.to_branch.name_ar or obj.to_branch.name

    def get_abc_class_display(self, obj):
        return dict(TransferRecommendation.ABC_CHOICES).get(obj.abc_class, obj.abc_class)

    def get_item_category_name(self, obj):
        cat = obj.item.category
        if cat:
            return cat.name_ar or cat.name
        return ''

    def get_std_gross_margin_pct(self, obj):
        """Standard Gross Margin % = (pack_price - cost_price) / pack_price × 100"""
        try:
            pack = float(obj.item.pack_price or 0)
            cost = float(obj.item.cost_price or 0)
            if pack > 0 and cost > 0:
                return round((pack - cost) / pack * 100, 1)
        except (TypeError, ValueError):
            pass
        return None

    def get_actioned_requests_count(self, obj):
        """Number of TransferRequests created to action this recommendation."""
        try:
            return obj.transfer_requests.count()
        except Exception:
            return 0

    def get_is_actioned(self, obj):
        """True if at least one TransferRequest was created from this recommendation."""
        try:
            return obj.transfer_requests.exists()
        except Exception:
            return False
