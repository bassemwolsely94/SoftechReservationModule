"""
apps/procurement/admin.py
"""
from django.contrib import admin
from django.utils.html import format_html
from .models import (
    PurchaseLine, SupplierProfile, SupplierItemMapping,
    ProcurementEngineRun, ProcurementSnapshot, BuyerPerformance,
    ProcurementAlert, SupplierSegmentation,
    SupplierCategory, SupplierClassificationRule,
)


@admin.register(ProcurementEngineRun)
class ProcurementEngineRunAdmin(admin.ModelAdmin):
    list_display  = ('id', 'status', 'period_days', 'lines_synced', 'lines_upserted',
                     'suppliers_updated', 'mappings_updated', 'alerts_generated',
                     'triggered_by', 'started_at', 'finished_at')
    list_filter   = ('status',)
    readonly_fields = ('started_at', 'finished_at', 'status', 'error_message')
    ordering      = ('-started_at',)


@admin.register(SupplierProfile)
class SupplierProfileAdmin(admin.ModelAdmin):
    list_display  = ('supplier_code', 'supplier_name', 'classif_code',
                     'total_score', 'avg_margin_pct', 'return_pct',
                     'invoice_count', 'distinct_items', 'last_purchase_date')
    list_filter   = ('classif_code',)
    search_fields = ('supplier_code', 'supplier_name')
    readonly_fields = ('last_updated',)
    ordering      = ('-total_score',)


@admin.register(SupplierItemMapping)
class SupplierItemMappingAdmin(admin.ModelAdmin):
    list_display  = ('supplier_code', 'supplier_name', 'item_code', 'item_name',
                     'purchase_count', 'confidence_score', 'is_primary',
                     'avg_price', 'price_drift_pct', 'last_purchase_date')
    list_filter   = ('is_primary',)
    search_fields = ('supplier_code', 'supplier_name', 'item_code', 'item_name')
    readonly_fields = ('last_updated',)
    ordering      = ('-purchase_count',)


@admin.register(PurchaseLine)
class PurchaseLineAdmin(admin.ModelAdmin):
    list_display  = ('doc_number', 'doc_date', 'supplier_code', 'item_code',
                     'branch_code', 'doccode', 'is_return',
                     'raw_qty', 'net_value', 'margin_pct', 'buyer_code')
    list_filter   = ('is_return', 'doccode', 'doc_date')
    search_fields = ('doc_number', 'supplier_code', 'item_code', 'buyer_code')
    readonly_fields = ('synced_at',)
    ordering      = ('-doc_date',)
    date_hierarchy = 'doc_date'


@admin.register(ProcurementSnapshot)
class ProcurementSnapshotAdmin(admin.ModelAdmin):
    list_display  = ('snapshot_date', 'net_purchase_value_30d', 'net_purchase_value_365d',
                     'avg_margin_pct_30d', 'return_pct_30d',
                     'distinct_suppliers_365d', 'purchase_growth_pct_mom')
    readonly_fields = ('created_at',)
    ordering      = ('-snapshot_date',)


@admin.register(BuyerPerformance)
class BuyerPerformanceAdmin(admin.ModelAdmin):
    list_display  = ('buyer_code', 'buyer_name', 'period_start', 'period_end',
                     'net_purchase_value', 'invoice_count', 'avg_margin_pct',
                     'return_pct', 'procurement_score')
    readonly_fields = ('created_at',)
    ordering      = ('-procurement_score',)


@admin.register(ProcurementAlert)
class ProcurementAlertAdmin(admin.ModelAdmin):
    list_display  = ('severity_badge', 'alert_type', 'entity_type', 'entity_code',
                     'entity_name', 'title', 'metric_value', 'is_resolved', 'detected_at')
    list_filter   = ('severity', 'alert_type', 'is_resolved', 'entity_type')
    search_fields = ('entity_code', 'entity_name', 'title')
    readonly_fields = ('detected_at', 'resolved_at')
    ordering      = ('-detected_at',)

    @admin.display(description='Severity')
    def severity_badge(self, obj):
        colors = {'critical': '#dc2626', 'warning': '#d97706', 'info': '#2563eb'}
        color = colors.get(obj.severity, '#6b7280')
        return format_html(
            '<span style="background:{};color:white;padding:2px 8px;border-radius:4px;">{}</span>',
            color, obj.get_severity_display()
        )


class SupplierClassificationRuleInline(admin.TabularInline):
    model = SupplierClassificationRule
    extra = 0
    fields = ('ptcode', 'ptclassifcode', 'priority', 'is_active', 'notes')


@admin.register(SupplierCategory)
class SupplierCategoryAdmin(admin.ModelAdmin):
    list_display  = ('sort_order', 'code', 'name_ar', 'name_en', 'color',
                     'is_active', 'is_fallback', 'rule_count')
    list_filter   = ('is_active', 'is_fallback')
    search_fields = ('code', 'name_ar', 'name_en')
    ordering      = ('sort_order', 'code')
    inlines       = [SupplierClassificationRuleInline]

    @admin.display(description='Rules')
    def rule_count(self, obj):
        return obj.rules.count()


@admin.register(SupplierClassificationRule)
class SupplierClassificationRuleAdmin(admin.ModelAdmin):
    list_display  = ('ptcode', 'ptclassifcode', 'category', 'priority', 'is_active', 'notes')
    list_filter   = ('is_active', 'category', 'ptcode')
    search_fields = ('ptcode', 'ptclassifcode', 'notes')
    ordering      = ('ptcode', 'ptclassifcode')
    autocomplete_fields = ()


@admin.register(SupplierSegmentation)
class SupplierSegmentationAdmin(admin.ModelAdmin):
    list_display  = ('supplier_code', 'supplier_name', 'supplier_category',
                     'ptcode', 'ptclassifcode', 'manual_override',
                     'purchase_value_365d', 'foc_rate_pct')
    list_filter   = ('supplier_category', 'manual_override', 'auto_classified')
    search_fields = ('supplier_code', 'supplier_name', 'ptcode', 'ptclassifcode')
    readonly_fields = ('classified_at',)
    ordering      = ('supplier_category', 'supplier_code')
