from django.contrib import admin

from .models import UsagePreset, UsageSheet


@admin.register(UsagePreset)
class UsagePresetAdmin(admin.ModelAdmin):
    list_display = ('kind', 'text', 'sort_order', 'is_active')
    list_filter = ('kind', 'is_active')


@admin.register(UsageSheet)
class UsageSheetAdmin(admin.ModelAdmin):
    list_display = ('softech_invoice_id', 'branch', 'print_count', 'last_printed_at')
    search_fields = ('softech_invoice_id', 'docnumber')
    readonly_fields = [f.name for f in UsageSheet._meta.fields]
