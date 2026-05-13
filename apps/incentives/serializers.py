"""
apps/incentives/serializers.py
"""
from rest_framework import serializers
from .models import IncentiveProgram, IncentiveRule, IncentiveTransaction, IncentiveSettlement


# ── Rules ─────────────────────────────────────────────────────────────────────

class IncentiveRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model  = IncentiveRule
        fields = [
            'id', 'program', 'rule_name',
            'item_code', 'item_name', 'category_code',
            'incentive_type', 'incentive_value', 'min_qty',
            'person_code_filter', 'expiry_within_days', 'priority',
            'is_active', 'created_at',
        ]
        read_only_fields = ['created_at']


class IncentiveRuleInlineSerializer(serializers.ModelSerializer):
    """Compact rule info embedded inside program detail."""
    class Meta:
        model  = IncentiveRule
        fields = [
            'id', 'rule_name', 'item_code', 'item_name', 'category_code',
            'incentive_type', 'incentive_value', 'min_qty',
            'person_code_filter', 'expiry_within_days', 'priority', 'is_active',
        ]


# ── Programs ──────────────────────────────────────────────────────────────────

class IncentiveProgramListSerializer(serializers.ModelSerializer):
    rule_count   = serializers.IntegerField(read_only=True, default=0)
    created_by_name = serializers.CharField(
        source='created_by.full_name', read_only=True, default='',
    )

    class Meta:
        model  = IncentiveProgram
        fields = [
            'id', 'name', 'description',
            'start_date', 'end_date', 'calculation_period',
            'is_active', 'rule_count', 'created_by_name', 'created_at',
        ]


class IncentiveProgramDetailSerializer(serializers.ModelSerializer):
    rules = IncentiveRuleInlineSerializer(many=True, read_only=True)
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
            'id',                                              # read-only, needed by frontend after create
            'name', 'description',
            'start_date', 'end_date', 'calculation_period', 'is_active',
        ]
        read_only_fields = ['id']


# ── Transactions ──────────────────────────────────────────────────────────────

class IncentiveTransactionSerializer(serializers.ModelSerializer):
    rule_name = serializers.CharField(source='rule.rule_name', read_only=True, default='')
    user_name = serializers.CharField(source='user.full_name', read_only=True)

    class Meta:
        model  = IncentiveTransaction
        fields = [
            'id', 'program', 'rule', 'rule_name', 'user', 'user_name',
            'item_code', 'item_name', 'doc_no', 'doc_type', 'ref_doc_no',
            'quantity', 'unit_price', 'incentive_amount', 'is_reversed',
            'period_start', 'period_end', 'erp_date', 'branch_code', 'created_at',
        ]


# ── Settlements ───────────────────────────────────────────────────────────────

class IncentiveSettlementSerializer(serializers.ModelSerializer):
    user_name        = serializers.CharField(source='user.full_name', read_only=True)
    program_name     = serializers.CharField(source='program.name', read_only=True)
    finalized_by_name = serializers.CharField(
        source='finalized_by.full_name', read_only=True, default='',
    )

    class Meta:
        model  = IncentiveSettlement
        fields = [
            'id', 'program', 'program_name', 'user', 'user_name',
            'period_start', 'period_end',
            'total_incentive', 'transaction_count',
            'is_finalized', 'finalized_at', 'finalized_by', 'finalized_by_name',
            'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'total_incentive', 'transaction_count',
            'is_finalized', 'finalized_at', 'finalized_by',
            'created_at', 'updated_at',
        ]
