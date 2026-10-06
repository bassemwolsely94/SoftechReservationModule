from rest_framework import serializers
from apps.loyalty.models import (
    LoyaltyAccount, LoyaltyTier, PointTransaction,
    RewardCatalog, RedemptionRequest, SoftechPointsLog,
)


class LoyaltyTierSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoyaltyTier
        fields = ['id', 'name', 'name_ar', 'order', 'min_points', 'color', 'icon',
                  'earn_multiplier', 'benefits_description']


class PointTransactionSerializer(serializers.ModelSerializer):
    transaction_type_display = serializers.CharField(source='get_transaction_type_display', read_only=True)

    class Meta:
        model = PointTransaction
        fields = ['id', 'points', 'transaction_type', 'transaction_type_display',
                  'source_type', 'reason', 'notes', 'balance_after', 'created_at']


class LoyaltyAccountSerializer(serializers.ModelSerializer):
    tier              = LoyaltyTierSerializer(read_only=True)
    customer_name     = serializers.SerializerMethodField()
    softech_pic       = serializers.SerializerMethodField()

    class Meta:
        model = LoyaltyAccount
        fields = ['id', 'customer', 'customer_name', 'softech_pic', 'tier',
                  'softech_points_balance',
                  'points_balance', 'points_lifetime', 'points_redeemed',
                  'is_active', 'created_at', 'updated_at']

    def get_customer_name(self, obj):
        return obj.customer.name if obj.customer_id else None

    def get_softech_pic(self, obj):
        return obj.customer.softech_pic if obj.customer_id else None


class RewardCatalogSerializer(serializers.ModelSerializer):
    is_available = serializers.BooleanField(read_only=True)
    min_tier     = LoyaltyTierSerializer(read_only=True)

    class Meta:
        model = RewardCatalog
        fields = ['id', 'name', 'name_ar', 'reward_type', 'points_cost',
                  'description', 'reward_data', 'min_tier', 'is_available',
                  'valid_from', 'valid_to', 'redeemed_count']


class RedemptionRequestSerializer(serializers.ModelSerializer):
    reward_name  = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = RedemptionRequest
        fields = ['id', 'account', 'reward', 'reward_name', 'points_spent',
                  'status', 'status_display', 'notes', 'voucher',
                  'approved_at', 'fulfilled_at', 'created_at']

    def get_reward_name(self, obj):
        return obj.reward.name_ar or obj.reward.name


class SoftechPointsLogSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model  = SoftechPointsLog
        fields = [
            'id', 'softech_pic', 'delta', 'reason',
            'balance_before', 'balance_after',
            'success', 'error_message',
            'created_by_name', 'created_at',
        ]

    def get_created_by_name(self, obj):
        if not obj.created_by_id:
            return None
        sp = obj.created_by
        full = sp.user.get_full_name() if sp.user_id else ''
        return full or (sp.user.username if sp.user_id else None)
