from django.contrib import admin
from .models import (
    DemandCalculationRun, ItemDemandMetrics, ItemDemandAggregated,
    EngineConfig, LostSalesRun,
)


@admin.register(EngineConfig)
class EngineConfigAdmin(admin.ModelAdmin):
    """
    Singleton config — always pk=1.  All parameter changes take effect on the NEXT run.

    MODULE 13 Lost Sales parameters are the most commonly tuned.
    See the field help_text in each section for guidance.
    """
    fieldsets = (
        ('⚖️  أوزان المتوسط الشهري', {
            'description': (
                'تحدد كيف يُحسب المتوسط الشهري من المعدلات الثلاثة. '
                'يجب أن يكون مجموعها 1.0.'
            ),
            'fields': ('weight_30d', 'weight_90d', 'weight_365d'),
        }),
        ('🛡️  كمية الأمان', {
            'fields': (
                'ss_high_threshold', 'ss_multiplier',
                'ss_tier_mid', 'ss_tier_low', 'ss_tier_vlow',
            ),
        }),
        ('📊  تصنيف ABC', {
            'fields': ('abc_a_threshold', 'abc_b_threshold'),
        }),
        ('💸  إعدادات المبيعات الضائعة — MODULE 13', {
            'description': (
                '<b>ls_bulk_sale_coverage_pct</b> (الأهم): '
                'يمنع تصنيف المبيعات الكبيرة (مستشفيات، مرضى مزمنون) كأيام نفاد مخزون. '
                'مثال: OMNITROPE تُباع 80 وحدة في 3 فواتير — بدون هذا يُحسب 27 يوم نفاد خاطئ. '
                '<br><b>ls_min_daily_demand</b>: يُستثنى الأصناف الأبطأ من هذا الحد. '
                '<br><b>ls_forecast_spike_ratio</b>: نسبة الارتفاع عن معدل السنة لتصنيف "توقعات". '
                '<br><b>ls_bottleneck_days</b>: أيام التغطية التي نعتبر دونها الصنف في خطر.'
            ),
            'fields': (
                'ls_bulk_sale_coverage_pct',
                'ls_min_daily_demand',
                'ls_forecast_spike_ratio',
                'ls_bottleneck_days',
            ),
        }),
        ('🕐  تاريخ التحديث', {
            'fields': ('updated_at',),
        }),
    )
    readonly_fields = ('updated_at',)

    def has_add_permission(self, request):
        return not EngineConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LostSalesRun)
class LostSalesRunAdmin(admin.ModelAdmin):
    list_display  = [
        'id', 'demand_run', 'status', 'branch_item_pairs',
        'items_affected', 'total_lost_revenue', 'total_lost_margin',
        'started_at', 'finished_at',
    ]
    list_filter   = ['status']
    readonly_fields = [
        'demand_run', 'status', 'started_at', 'finished_at',
        'error_message', 'items_affected', 'branch_item_pairs',
        'total_lost_revenue', 'total_lost_margin', 'root_cause_breakdown',
    ]
    ordering = ['-started_at']


@admin.register(DemandCalculationRun)
class DemandCalculationRunAdmin(admin.ModelAdmin):
    list_display  = ['id', 'calc_date', 'status', 'items_processed', 'rows_written',
                     'softech_available', 'duration_seconds', 'started_at']
    list_filter   = ['status', 'softech_available', 'calc_date']
    readonly_fields = [
        'started_at', 'finished_at', 'status', 'calc_date',
        'branches_processed', 'items_processed', 'rows_written',
        'softech_available', 'duration_seconds', 'error_message',
    ]
    ordering = ['-started_at']


@admin.register(ItemDemandMetrics)
class ItemDemandMetricsAdmin(admin.ModelAdmin):
    list_display  = [
        'item', 'branch', 'abc_class', 'monthly_avg', 'safety_stock',
        'current_stock', 'gap', 'priority', 'calc_date',
    ]
    list_filter   = ['abc_class', 'branch', 'calc_date', 'run']
    search_fields = ['item__name', 'item__softech_id']
    ordering      = ['-priority']
    raw_id_fields = ['item', 'branch', 'run']
    readonly_fields = [
        'calc_date', 'qty_30d', 'qty_90d', 'qty_365d',
        'rate_30d', 'rate_90d', 'rate_365d', 'monthly_avg',
        'safety_stock', 'current_stock', 'coverage_months',
        'gap', 'priority', 'abc_class', 'pack_price', 'monthly_value',
        'last_sale_date',
    ]


@admin.register(ItemDemandAggregated)
class ItemDemandAggregatedAdmin(admin.ModelAdmin):
    list_display  = [
        'item', 'abc_class', 'total_monthly_avg', 'total_current_stock',
        'total_gap', 'total_monthly_value', 'cumulative_pct', 'calc_date',
    ]
    list_filter   = ['abc_class', 'calc_date', 'run']
    search_fields = ['item__name', 'item__softech_id']
    ordering      = ['-total_monthly_value']
    raw_id_fields = ['item', 'run']
    readonly_fields = [
        'calc_date', 'total_qty_30d', 'total_qty_90d', 'total_qty_365d',
        'total_monthly_avg', 'total_current_stock', 'total_monthly_value',
        'total_gap', 'abc_class', 'cumulative_pct',
        'branches_with_sales', 'branches_with_gap', 'pack_price',
    ]
