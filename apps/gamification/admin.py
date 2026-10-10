from django.contrib import admin

from .models import (Badge, DailyScore, GamificationChange, Level, LevelHistory, PlayerProfile,
                     PointEvent, PointRule, Redemption, Reward, StaffBadge,
                     Champion, ChampionMonth)


@admin.register(PointRule)
class PointRuleAdmin(admin.ModelAdmin):
    list_display = ('key', 'name_ar', 'category', 'points', 'daily_cap', 'is_active')
    list_filter = ('category', 'is_active')
    search_fields = ('key', 'name_ar', 'name_en')


@admin.register(Level)
class LevelAdmin(admin.ModelAdmin):
    list_display = ('number', 'title_ar', 'title_en', 'min_xp', 'icon')


@admin.register(Badge)
class BadgeAdmin(admin.ModelAdmin):
    list_display = ('key', 'name_ar', 'criteria', 'rule_key', 'threshold', 'is_active')


@admin.register(PointEvent)
class PointEventAdmin(admin.ModelAdmin):
    list_display = ('staff', 'rule_key', 'points', 'day', 'source_key')
    list_filter = ('category', 'rule_key')
    search_fields = ('source_key', 'staff__user__username')
    readonly_fields = [f.name for f in PointEvent._meta.fields]

    def has_change_permission(self, request, obj=None):   # append-only ledger
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PlayerProfile)
class PlayerProfileAdmin(admin.ModelAdmin):
    list_display = ('staff', 'xp', 'net_points', 'level', 'current_streak', 'best_streak')


admin.site.register(DailyScore)
admin.site.register(StaffBadge)
admin.site.register(LevelHistory)
admin.site.register(GamificationChange)


@admin.register(Reward)
class RewardAdmin(admin.ModelAdmin):
    list_display = ('name_ar', 'category', 'cost', 'stock', 'min_level', 'is_active')
    list_filter = ('category', 'is_active')


@admin.register(Redemption)
class RedemptionAdmin(admin.ModelAdmin):
    list_display = ('staff', 'reward', 'cost', 'status', 'created_at')
    list_filter = ('status',)
    readonly_fields = [f.name for f in Redemption._meta.fields]

    def has_change_permission(self, request, obj=None):   # moves only through the app
        return False


@admin.register(ChampionMonth)
class ChampionMonthAdmin(admin.ModelAdmin):
    list_display = ('month', 'crowned_at', 'crowned_by', 'summary')


@admin.register(Champion)
class ChampionAdmin(admin.ModelAdmin):
    list_display = ('month', 'kind', 'role', 'branch', 'staff', 'rank', 'net', 'bonus', 'revoked')
    list_filter = ('kind', 'revoked', 'month')
    readonly_fields = [f.name for f in Champion._meta.fields]

    def has_change_permission(self, request, obj=None):   # revoke through the app (reverses the bonus)
        return False
