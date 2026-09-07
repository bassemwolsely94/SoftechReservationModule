from django.contrib import admin
from .models import (
    SeasonalityIndex, ForecastRun, ForecastAccuracy,
    ChannelBucketMap, BeautyClassRule, KpiActualRollup,
    ForecastScenario, ForecastFactor, ForecastResult,
    BacktestRun, BacktestResult, CallCenterConfig, UnitCountExclusion,
    MetricGuardrail,
)


@admin.register(SeasonalityIndex)
class SeasonalityIndexAdmin(admin.ModelAdmin):
    list_display  = ['item', 'category', 'month', 'index_value', 'computed_from_years', 'computed_at']
    list_filter   = ['month']
    search_fields = ['item__name', 'category__name']


@admin.register(ForecastRun)
class ForecastRunAdmin(admin.ModelAdmin):
    list_display  = ['id', 'started_at', 'status', 'items_processed', 'triggered_by']
    list_filter   = ['status']
    readonly_fields = ['started_at', 'completed_at', 'items_processed', 'error']


@admin.register(ForecastAccuracy)
class ForecastAccuracyAdmin(admin.ModelAdmin):
    list_display  = ['item', 'branch', 'forecast_date', 'forecast_30d', 'actual_30d', 'mape']
    list_filter   = ['branch']
    search_fields = ['item__name']


@admin.register(ChannelBucketMap)
class ChannelBucketMapAdmin(admin.ModelAdmin):
    list_display  = ['person_type', 'channel', 'label', 'bucket', 'subtype',
                     'counts_customer', 'include_in_profit', 'active']
    list_filter   = ['bucket', 'subtype', 'active', 'person_type']
    list_editable = ['bucket', 'subtype', 'counts_customer', 'include_in_profit', 'active']
    search_fields = ['channel', 'label']


@admin.register(BeautyClassRule)
class BeautyClassRuleAdmin(admin.ModelAdmin):
    list_display  = ['medicine_type', 'label', 'active']
    list_editable = ['active']


@admin.register(KpiActualRollup)
class KpiActualRollupAdmin(admin.ModelAdmin):
    list_display  = ['branch', 'year', 'month', 'metric', 'value', 'computed_at']
    list_filter   = ['year', 'month', 'metric', 'branch']
    readonly_fields = ['computed_at']


class ForecastFactorInline(admin.TabularInline):
    model = ForecastFactor
    extra = 0


@admin.register(ForecastScenario)
class ForecastScenarioAdmin(admin.ModelAdmin):
    list_display  = ['name', 'year', 'month', 'model', 'status',
                     'benchmark_growth', 'incentive_threshold', 'created_at']
    list_filter   = ['status', 'model', 'year']
    inlines       = [ForecastFactorInline]
    readonly_fields = ['generated_at', 'committed_at', 'created_at']


@admin.register(ForecastResult)
class ForecastResultAdmin(admin.ModelAdmin):
    list_display  = ['scenario', 'branch', 'metric', 'base_value',
                     'model_a', 'model_b', 'forecast_value', 'target_value']
    list_filter   = ['scenario', 'metric']


class BacktestResultInline(admin.TabularInline):
    model = BacktestResult
    extra = 0
    readonly_fields = ['metric', 'model', 'n_points', 'mape', 'wape', 'bias', 'rmse', 'is_winner']


@admin.register(BacktestRun)
class BacktestRunAdmin(admin.ModelAdmin):
    list_display  = ['id', 'created_at', 'n_months', 'benchmark_growth', 'scenario']
    inlines       = [BacktestResultInline]
    readonly_fields = ['created_at']


@admin.register(BacktestResult)
class BacktestResultAdmin(admin.ModelAdmin):
    list_display  = ['run', 'metric', 'model', 'mape', 'wape', 'bias', 'is_winner']
    list_filter   = ['metric', 'model', 'is_winner']


@admin.register(CallCenterConfig)
class CallCenterConfigAdmin(admin.ModelAdmin):
    list_display  = ['id', 'sales_agent_usercodes', 'call_agent_extensions', 'cdr_enabled', 'updated_at']


@admin.register(UnitCountExclusion)
class UnitCountExclusionAdmin(admin.ModelAdmin):
    list_display  = ['item', 'note', 'active', 'created_at']
    list_filter   = ['active']
    search_fields = ['item__name', 'item__softech_id', 'note']
    raw_id_fields = ['item']


@admin.register(MetricGuardrail)
class MetricGuardrailAdmin(admin.ModelAdmin):
    list_display  = ['label', 'scope_type', 'reward_metric', 'guardrail_metric',
                     'operator', 'threshold', 'active']
    list_filter   = ['scope_type', 'active', 'guardrail_metric']
    list_editable = ['active']
