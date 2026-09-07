from rest_framework import serializers
from .models import (
    SeasonalityIndex, ForecastRun, ForecastAccuracy,
    ForecastScenario, ForecastFactor, ForecastResult, KpiActualRollup,
    BacktestRun, BacktestResult,
)


class SeasonalityIndexSerializer(serializers.ModelSerializer):
    item_name     = serializers.CharField(source='item.name',     read_only=True, default='')
    category_name = serializers.CharField(source='category.name', read_only=True, default='')

    class Meta:
        model  = SeasonalityIndex
        fields = [
            'id', 'item', 'item_name', 'category', 'category_name',
            'month', 'index_value', 'computed_from_years', 'computed_at',
        ]
        read_only_fields = ['computed_at']


class ForecastRunSerializer(serializers.ModelSerializer):
    triggered_by_name = serializers.CharField(source='triggered_by.full_name', read_only=True, default='')
    duration_seconds  = serializers.SerializerMethodField()

    class Meta:
        model  = ForecastRun
        fields = [
            'id', 'started_at', 'completed_at', 'status',
            'items_processed', 'triggered_by', 'triggered_by_name',
            'parameters', 'error', 'duration_seconds',
        ]
        read_only_fields = ['started_at', 'completed_at', 'status', 'items_processed', 'error']

    def get_duration_seconds(self, obj) -> float | None:
        if obj.completed_at and obj.started_at:
            return (obj.completed_at - obj.started_at).total_seconds()
        return None


class ForecastAccuracySerializer(serializers.ModelSerializer):
    item_name   = serializers.CharField(source='item.name',   read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True)

    class Meta:
        model  = ForecastAccuracy
        fields = [
            'id', 'item', 'item_name', 'branch', 'branch_name',
            'forecast_date', 'forecast_30d', 'actual_30d', 'mape', 'mae',
        ]
        read_only_fields = ['mape', 'mae']


# ── Forecast engine (doc 16, Phase 3) ─────────────────────────────────────────

class ForecastFactorSerializer(serializers.ModelSerializer):
    metric_label = serializers.SerializerMethodField()

    def get_metric_label(self, obj):
        return KpiActualRollup.METRIC_LABELS.get(obj.metric, obj.metric)

    class Meta:
        model  = ForecastFactor
        fields = ['id', 'metric', 'metric_label', 'growth_goal',
                  'w_lm', 'w_pm', 'w_yoy', 'seasonality_index']


class ForecastResultSerializer(serializers.ModelSerializer):
    metric_label = serializers.SerializerMethodField()
    branch_name  = serializers.SerializerMethodField()

    def get_metric_label(self, obj):
        return KpiActualRollup.METRIC_LABELS.get(obj.metric, obj.metric)

    def get_branch_name(self, obj):
        # generic scope label (branch name / salesperson / category / chain)
        return obj.scope_label or (getattr(obj.branch, 'name_ar', '') or
                                   getattr(obj.branch, 'name', '') if obj.branch_id else 'الإجمالى')

    class Meta:
        model  = ForecastResult
        fields = ['id', 'branch', 'scope_key', 'scope_label', 'branch_name', 'metric', 'metric_label',
                  'base_value', 'lm_value', 'pm_value', 'model_a', 'model_b',
                  'forecast_value', 'target_value', 'branch_share']


class ForecastScenarioSerializer(serializers.ModelSerializer):
    factors      = ForecastFactorSerializer(many=True, read_only=True)
    model_label  = serializers.CharField(source='get_model_display', read_only=True)
    scope_label  = serializers.CharField(source='get_scope_type_display', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True, default='')

    class Meta:
        model  = ForecastScenario
        fields = [
            'id', 'name', 'year', 'month', 'scope_type', 'scope_label', 'model', 'model_label',
            'incentive_threshold', 'benchmark_growth', 'inflation', 'promotion_lift',
            'status', 'status_label', 'notes', 'factors',
            'created_by', 'created_by_name', 'created_at', 'generated_at', 'committed_at',
        ]
        read_only_fields = ['status', 'created_by', 'created_at', 'generated_at', 'committed_at']


class BacktestResultSerializer(serializers.ModelSerializer):
    metric_label = serializers.SerializerMethodField()
    model_label  = serializers.CharField(source='get_model_display', read_only=True)

    def get_metric_label(self, obj):
        return KpiActualRollup.METRIC_LABELS.get(obj.metric, obj.metric)

    class Meta:
        model  = BacktestResult
        fields = ['id', 'metric', 'metric_label', 'model', 'model_label', 'n_points',
                  'mape', 'wape', 'bias', 'rmse', 'is_winner', 'factor_snapshot']


class BacktestRunSerializer(serializers.ModelSerializer):
    results = BacktestResultSerializer(many=True, read_only=True)
    winners = serializers.SerializerMethodField()

    def get_winners(self, obj):
        return {r.metric: r.model for r in obj.results.all() if r.is_winner}

    class Meta:
        model  = BacktestRun
        fields = [
            'id', 'created_at', 'window_start_year', 'window_start_month',
            'window_end_year', 'window_end_month', 'n_months',
            'benchmark_growth', 'incentive_threshold', 'inflation', 'promotion_lift',
            'scenario', 'results', 'winners',
        ]
