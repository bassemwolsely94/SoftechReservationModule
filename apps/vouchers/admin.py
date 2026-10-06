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


from .models import CouponBatch, CouponSerial  # noqa: E402


@admin.register(CouponBatch)
class CouponBatchAdmin(admin.ModelAdmin):
    list_display  = ('id', 'source', 'status', 'size', 'serial_from', 'serial_to',
                     'expiry_from', 'expiry_to', 'created_by', 'created_at')
    list_filter   = ('source', 'status')
    readonly_fields = [f.name for f in CouponBatch._meta.fields]


@admin.register(CouponSerial)
class CouponSerialAdmin(admin.ModelAdmin):
    list_display  = ('serial', 'number', 'source', 'status', 'stage', 'points_docnumber', 'served_docnumber',
                     'issued_pic', 'redeemed_branch', 'redeemed_at', 'batch')
    list_filter   = ('source', 'status', 'stage', 'redeemed_branch')
    search_fields = ('serial', 'code', '=number')
    readonly_fields = [f.name for f in CouponSerial._meta.fields]


from .models import CouponEvent  # noqa: E402


@admin.register(CouponEvent)
class CouponEventAdmin(admin.ModelAdmin):
    list_display  = ('docdate', 'raw_serial', 'kind', 'leg', 'branchcode', 'doccode', 'docnumber',
                     'customer_pic', 'qty')
    list_filter   = ('kind', 'leg', 'branchcode')
    search_fields = ('raw_serial', 'customer_pic', '=docnumber')
    readonly_fields = [f.name for f in CouponEvent._meta.fields]
