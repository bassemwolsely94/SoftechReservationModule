"""
apps/incentives/serializers.py  —  v4
"""
from rest_framework import serializers
from .models import (
    IncentiveProgram, IncentiveRule, IncentiveRuleItem,
    IncentiveTransaction, IncentiveSettlement,
    AdjustmentEntry, IncentiveCalculationLog,
)


# ── Rule Items ────────────────────────────────────────────────────────────────

class IncentiveRuleItemSerializer(serializers.ModelSerializer):
    class Meta:
        model  = IncentiveRuleItem
        fields = ['id', 'rule', 'item_code', 'item_name', 'incentive_override', 'created_at']
        read_only_fields = ['created_at']
        extra_kwargs = {'rule': {'required': False}}


# ── Rules ─────────────────────────────────────────────────────────────────────

class IncentiveRuleSerializer(serializers.ModelSerializer):
    rule_items = IncentiveRuleItemSerializer(many=True, read_only=True)
    item_count = serializers.SerializerMethodField()
    is_near_expiry_rule = serializers.SerializerMethodField()

    def get_item_count(self, obj):
        cache = getattr(obj, '_prefetched_objects_cache', {})
        if 'rule_items' in cache:
            return len(cache['rule_items'])
        return obj.rule_items.count()

    def get_is_near_expiry_rule(self, obj):
        """True if this rule uses any near-expiry filter."""
        return bool(
            obj.expiry_within_days
            or obj.is_imported_filter != 'any'
            or obj.origin_codes
            or obj.margin_min is not None
            or obj.margin_max is not None
            or obj.pack_price_min is not None
            or obj.pack_price_max is not None
        )

    class Meta:
        model  = IncentiveRule
        fields = [
            'id', 'program', 'rule_name',
            'item_code', 'item_name', 'category_code',
            'incentive_type', 'incentive_value',
            'slab_config',
            'min_qty', 'min_total_qty_in_period',
            'person_code_filter', 'branch_filter',
            'time_window_start', 'time_window_end',
            # ── Near-expiry filter fields ───────────────────────────────
            'expiry_within_days',
            'is_imported_filter',
            'origin_codes',
            'margin_min', 'margin_max',
            'pack_price_min', 'pack_price_max',
            # ── Target-based fields (Feature 2) ────────────────────────
            'target_qty', 'target_tiers',
            # ───────────────────────────────────────────────────────────
            'priority', 'is_active',
            'is_near_expiry_rule',
            'created_at', 'rule_items', 'item_count',
        ]
        read_only_fields = ['created_at', 'is_near_expiry_rule']


class IncentiveRuleInlineSerializer(serializers.ModelSerializer):
    """Compact rule info embedded inside program detail."""
    item_count = serializers.SerializerMethodField()
    is_near_expiry_rule = serializers.SerializerMethodField()

    def get_item_count(self, obj):
        return obj.rule_items.count()

    def get_is_near_expiry_rule(self, obj):
        return bool(
            obj.expiry_within_days
            or obj.is_imported_filter != 'any'
            or obj.origin_codes
            or obj.margin_min is not None
            or obj.margin_max is not None
            or obj.pack_price_min is not None
            or obj.pack_price_max is not None
        )

    class Meta:
        model  = IncentiveRule
        fields = [
            'id', 'rule_name', 'item_code', 'item_name', 'category_code',
            'incentive_type', 'incentive_value', 'slab_config',
            'min_qty', 'min_total_qty_in_period',
            'person_code_filter', 'branch_filter',
            'time_window_start', 'time_window_end',
            'expiry_within_days', 'is_imported_filter', 'origin_codes',
            'margin_min', 'margin_max',
            'pack_price_min', 'pack_price_max',
            'target_qty', 'target_tiers',
            'priority', 'is_active',
            'is_near_expiry_rule', 'item_count',
        ]


# ── Programs ──────────────────────────────────────────────────────────────────

class IncentiveProgramListSerializer(serializers.ModelSerializer):
    rule_count      = serializers.IntegerField(read_only=True, default=0)
    created_by_name = serializers.CharField(
        source='created_by.full_name', read_only=True, default='',
    )
    is_sponsored = serializers.SerializerMethodField()

    def get_is_sponsored(self, obj):
        return bool(obj.sponsor_name)

    class Meta:
        model  = IncentiveProgram
        fields = [
            'id', 'name', 'description',
            'start_date', 'end_date', 'calculation_period',
            'is_active', 'rule_count', 'created_by_name', 'created_at',
            'sponsor_name', 'sponsor_contribution_pct', 'is_sponsored',
        ]


class IncentiveProgramDetailSerializer(serializers.ModelSerializer):
    rules           = IncentiveRuleInlineSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(
        source='created_by.full_name', read_only=True, default='',
    )

    class Meta:
        model  = IncentiveProgram
        fields = [
            'id', 'name', 'description',
            'start_date', 'end_date', 'calculation_period',
            'is_active', 'rules', 'created_by_name', 'created_at', 'updated_at',
        ]


class IncentiveProgramCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = IncentiveProgram
        fields = [
            'id', 'name', 'description',
            'start_date', 'end_date', 'calculation_period', 'is_active',
            'sponsor_name', 'sponsor_contribution_pct',
        ]
        read_only_fields = ['id']


# ── Transactions ──────────────────────────────────────────────────────────────

class IncentiveTransactionSerializer(serializers.ModelSerializer):
    rule_name = serializers.CharField(source='rule.rule_name', read_only=True, default='')
    user_name = serializers.CharField(source='user.full_name', read_only=True)
    expiry_bucket = serializers.SerializerMethodField()

    def get_expiry_bucket(self, obj):
        """Return the expiry bucket label for this transaction (if near-expiry rule)."""
        days = obj.expiry_days_remaining
        if days is None:
            return None
        if days <= 30:
            return '0-30'
        if days <= 60:
            return '31-60'
        if days <= 90:
            return '61-90'
        if days <= 180:
            return '91-180'
        return '181+'

    class Meta:
        model  = IncentiveTransaction
        fields = [
            'id', 'program', 'rule', 'rule_name', 'user', 'user_name',
            'item_code', 'item_name', 'doc_no', 'doc_type', 'ref_doc_no',
            'quantity', 'unit_price', 'incentive_amount', 'is_reversed',
            'is_cross_period_return',
            'expiry_date', 'expiry_days_remaining', 'expiry_bucket',
            'period_start', 'period_end', 'erp_date', 'branch_code', 'created_at',
        ]


# ── Adjustment Entries ────────────────────────────────────────────────────────

class AdjustmentEntrySerializer(serializers.ModelSerializer):
    user_name       = serializers.CharField(source='user.full_name', read_only=True)
    program_name    = serializers.CharField(source='program.name', read_only=True)
    created_by_name = serializers.CharField(
        source='created_by.full_name', read_only=True, default='',
    )

    class Meta:
        model  = AdjustmentEntry
        fields = [
            'id', 'program', 'program_name',
            'user', 'user_name',
            'period_start', 'period_end',
            'amount', 'reason',
            'created_by', 'created_by_name',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_by', 'created_at', 'updated_at']


# ── Settlements ───────────────────────────────────────────────────────────────

class IncentiveSettlementSerializer(serializers.ModelSerializer):
    user_name         = serializers.CharField(source='user.full_name', read_only=True)
    program_name      = serializers.CharField(source='program.name', read_only=True)
    finalized_by_name = serializers.CharField(
        source='finalized_by.full_name', read_only=True, default='',
    )

    class Meta:
        model  = IncentiveSettlement
        fields = [
            'id', 'program', 'program_name', 'user', 'user_name',
            'period_start', 'period_end',
            'total_incentive', 'total_adjustments', 'final_payout',
            'transaction_count',
            'is_finalized', 'finalized_at', 'finalized_by', 'finalized_by_name',
            'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'total_incentive', 'total_adjustments', 'final_payout',
            'transaction_count',
            'is_finalized', 'finalized_at', 'finalized_by',
            'created_at', 'updated_at',
        ]


# ── Calculation Log ───────────────────────────────────────────────────────────

class IncentiveCalculationLogSerializer(serializers.ModelSerializer):
    program_name      = serializers.CharField(source='program.name', read_only=True)
    triggered_by_name = serializers.CharField(
        source='triggered_by.full_name', read_only=True, default='',
    )
    mode_label   = serializers.CharField(source='get_mode_display',   read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model  = IncentiveCalculationLog
        fields = [
            'id', 'program', 'program_name',
            'triggered_by', 'triggered_by_name',
            'period_start', 'period_end',
            'mode', 'mode_label', 'status', 'status_label',
            'transactions_created', 'skipped_person_codes',
            'user_summaries', 'error_detail',
            'started_at', 'finished_at', 'duration_seconds',
        ]


# ── Sales Targets & Goals ────────────────────────────────────────────────────────

from .models import SalesTarget   # noqa: E402

class SalesTargetSerializer(serializers.ModelSerializer):
    attainment   = serializers.SerializerMethodField()
    scope_label  = serializers.CharField(source='get_scope_type_display', read_only=True)
    metric_label = serializers.CharField(source='get_metric_display', read_only=True)
    branch_name  = serializers.SerializerMethodField()
    category_name = serializers.SerializerMethodField()

    def get_attainment(self, obj):
        return obj.attainment()

    def get_branch_name(self, obj):
        if not obj.branch_id:
            return None
        return getattr(obj.branch, 'display_name', None) or getattr(obj.branch, 'name', None)

    def get_category_name(self, obj):
        return getattr(obj.category, 'name', None) if obj.category_id else None

    class Meta:
        model  = SalesTarget
        fields = [
            'id', 'label', 'scope_type', 'scope_label',
            'branch', 'branch_name', 'softech_user', 'category', 'category_name',
            'metric', 'metric_label', 'period_start', 'period_end',
            'target_value', 'attainment', 'created_at',
        ]
        read_only_fields = ['created_at']
