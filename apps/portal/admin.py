from django.contrib import admin

from .models import PortalLogin


@admin.register(PortalLogin)
class PortalLoginAdmin(admin.ModelAdmin):
    """Customer-portal logins. «إنهاء كل جلسات العميل» ends every session and unused link of the
    selected rows' customers — a lost phone, or the customer asks (Batch 6, W-5)."""
    list_display = ('customer', 'created_at', 'used_at', 'revoked_at')
    list_filter = ('revoked_at',)
    search_fields = ('customer__name', 'customer__softech_pic', 'customer__phone')
    raw_id_fields = ('customer',)
    fields = readonly_fields = ('customer', 'created_at', 'used_at', 'revoked_at')   # no nonce / session key
    actions = ['revoke_customers']

    @admin.action(description='إنهاء كل جلسات العميل')
    def revoke_customers(self, request, queryset):
        ended = sum(PortalLogin.revoke_all(c) for c in {row.customer for row in queryset})
        self.message_user(request, f'أُنهيت {ended} جلسة / رابط')

    def has_add_permission(self, request):
        return False
