from django.contrib import admin

from .models import PhoneLabel, PicAnalyticsAccess, PicDayFact, PicExclusion, PicRollup


class _ReadOnly(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PicDayFact)
class PicDayFactAdmin(_ReadOnly):
    list_display = ('pic', 'day', 'branch', 'salesperson', 'channel_bucket', 'invoices', 'net')
    list_filter = ('branch',)
    search_fields = ('=pic',)


@admin.register(PicRollup)
class PicRollupAdmin(_ReadOnly):
    list_display = ('pic', 'as_of', 'last_purchase', 'visits_12m', 'months_a', 'cycle_bucket', 'lifetime_net')
    search_fields = ('=pic',)


@admin.register(PicAnalyticsAccess)
class PicAnalyticsAccessAdmin(_ReadOnly):
    list_display = ('staff', 'granted_by', 'granted_at', 'revoked_at')


@admin.register(PhoneLabel)
class PhoneLabelAdmin(_ReadOnly):
    list_display = ('phone_key', 'label', 'created_by', 'created_at')
    search_fields = ('=phone_key',)


@admin.register(PicExclusion)
class PicExclusionAdmin(_ReadOnly):
    list_display = ('pic', 'reason', 'added_by', 'added_at', 'removed_at')
    search_fields = ('=pic',)
