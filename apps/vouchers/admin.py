from django.contrib import admin
from .models import Voucher, VoucherOTP, VoucherRedemption


class VoucherOTPInline(admin.TabularInline):
    model  = VoucherOTP
    extra  = 0
    fields = ('phone', 'is_used', 'expires_at', 'created_at', 'sent_via')
    readonly_fields = ('code_hash', 'created_at', 'expires_at')


class VoucherRedemptionInline(admin.TabularInline):
    model  = VoucherRedemption
    extra  = 0
    fields = ('redeemed_by', 'branch', 'redeemed_at', 'notes')
    readonly_fields = ('redeemed_at',)


@admin.register(Voucher)
class VoucherAdmin(admin.ModelAdmin):
    list_display  = ('code', 'title', 'voucher_type', 'status', 'times_used', 'max_uses', 'valid_until', 'customer')
    list_filter   = ('status', 'voucher_type')
    search_fields = ('code', 'title')
    readonly_fields = ('code', 'created_at', 'updated_at')
    inlines       = [VoucherOTPInline, VoucherRedemptionInline]


@admin.register(VoucherOTP)
class VoucherOTPAdmin(admin.ModelAdmin):
    list_display  = ('voucher', 'phone', 'is_used', 'expires_at', 'created_at')
    list_filter   = ('is_used',)
    readonly_fields = ('code_hash', 'created_at')
