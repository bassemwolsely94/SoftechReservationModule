from django.contrib import admin
from apps.loyalty.models import (
    LoyaltyTier, LoyaltyAccount, PointTransaction,
    RewardCatalog, RedemptionRequest, SoftechPointsLog,
)


@admin.register(LoyaltyTier)
class LoyaltyTierAdmin(admin.ModelAdmin):
    list_display = ['icon', 'name_ar', 'order', 'min_points', 'earn_multiplier']
    ordering     = ['order']


class PointTransactionInline(admin.TabularInline):
    model         = PointTransaction
    extra         = 0
    readonly_fields = ['points', 'transaction_type', 'source_type', 'reason',
                       'balance_after', 'created_at']
    can_delete    = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(LoyaltyAccount)
class LoyaltyAccountAdmin(admin.ModelAdmin):
    list_display   = ['customer', 'tier', 'softech_points_balance', 'points_balance',
                      'points_lifetime', 'points_redeemed', 'is_active']
    list_filter    = ['tier', 'is_active']
    search_fields  = ['customer__name', 'customer__phone', 'customer__softech_pic']
    raw_id_fields  = ['customer']
    readonly_fields = ['softech_points_balance', 'points_balance', 'points_lifetime', 'points_redeemed']
    inlines        = [PointTransactionInline]


@admin.register(PointTransaction)
class PointTransactionAdmin(admin.ModelAdmin):
    list_display  = ['account', 'points', 'transaction_type', 'source_type',
                     'reason', 'balance_after', 'created_at']
    list_filter   = ['transaction_type', 'source_type']
    search_fields = ['account__customer__name', 'reason']
    readonly_fields = list_display

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RewardCatalog)
class RewardCatalogAdmin(admin.ModelAdmin):
    list_display = ['name_ar', 'reward_type', 'points_cost', 'is_active',
                    'redeemed_count', 'is_available']
    list_filter  = ['reward_type', 'is_active']


@admin.register(RedemptionRequest)
class RedemptionRequestAdmin(admin.ModelAdmin):
    list_display  = ['account', 'reward', 'points_spent', 'status',
                     'approved_by', 'created_at']
    list_filter   = ['status']
    raw_id_fields = ['account', 'reward', 'approved_by', 'voucher']
    readonly_fields = ['created_at', 'approved_at', 'fulfilled_at']


@admin.register(SoftechPointsLog)
class SoftechPointsLogAdmin(admin.ModelAdmin):
    list_display  = ['softech_pic', 'customer', 'delta', 'balance_before',
                     'balance_after', 'success', 'created_by', 'created_at']
    list_filter   = ['success']
    search_fields = ['softech_pic', 'customer__name', 'reason']
    readonly_fields = [f.name for f in SoftechPointsLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
