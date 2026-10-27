from django.contrib import admin
from apps.referral.models import ReferralCode, ReferralLead, ReferralEvent, FraudSignal


class ReferralLeadInline(admin.TabularInline):
    model        = ReferralLead
    extra        = 0
    readonly_fields = ['lead_name', 'lead_phone', 'status', 'fraud_score', 'created_at']
    can_delete   = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ReferralCode)
class ReferralCodeAdmin(admin.ModelAdmin):
    list_display  = ['customer', 'code', 'is_active', 'total_leads',
                     'validated_leads', 'total_points_earned']
    search_fields = ['customer__name', 'code']
    inlines       = [ReferralLeadInline]


class ReferralEventInline(admin.TabularInline):
    model       = ReferralEvent
    extra       = 0
    readonly_fields = ['event_type', 'message', 'created_by', 'created_at']
    can_delete  = False

    def has_add_permission(self, request, obj=None):
        return False


class FraudSignalInline(admin.TabularInline):
    model      = FraudSignal
    extra      = 0
    readonly_fields = ['signal_type', 'score_delta', 'detail', 'detected_at']
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ReferralLead)
class ReferralLeadAdmin(admin.ModelAdmin):
    list_display  = ['lead_name', 'lead_phone', 'referrer', 'status',
                     'fraud_score', 'created_at']
    list_filter   = ['status', 'relationship']
    search_fields = ['lead_name', 'lead_phone', 'referrer__name']
    readonly_fields = ['fraud_score', 'fraud_flags', 'otp_attempts',
                       'validated_at', 'rewarded_at']
    inlines       = [ReferralEventInline, FraudSignalInline]


@admin.register(ReferralEvent)
class ReferralEventAdmin(admin.ModelAdmin):
    list_display  = ['lead', 'event_type', 'message', 'created_at']
    list_filter   = ['event_type']
    readonly_fields = ['lead', 'event_type', 'message', 'created_by', 'created_at', 'meta']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
