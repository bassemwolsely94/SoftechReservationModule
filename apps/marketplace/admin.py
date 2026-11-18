from django.contrib import admin

from .models import (
    ChannelListing, ChannelStore, ExternalOrder, MarketplaceChannel, PushLog, SettlementBatch,
)


@admin.register(MarketplaceChannel)
class MarketplaceChannelAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'adapter', 'scope', 'is_active')
    list_filter = ('adapter', 'scope', 'is_active')
    exclude = ('credentials',)   # secrets never shown


@admin.register(ChannelStore)
class ChannelStoreAdmin(admin.ModelAdmin):
    list_display = ('channel', 'branch', 'external_store_id', 'delivery_mode', 'is_active')


@admin.register(ChannelListing)
class ChannelListingAdmin(admin.ModelAdmin):
    list_display = ('channel', 'item', 'approved', 'allow_fridge')
    list_filter = ('channel', 'approved')
    raw_id_fields = ('item', 'approved_by')


@admin.register(ExternalOrder)
class ExternalOrderAdmin(admin.ModelAdmin):
    list_display = ('channel', 'external_id', 'branch', 'status', 'created_at')
    list_filter = ('channel', 'status')
    exclude = ('raw_payload', 'customer_phone')   # phone is shown only through masked API output
    readonly_fields = [f.name for f in ExternalOrder._meta.fields
                       if f.name not in ('raw_payload', 'customer_phone')]


@admin.register(PushLog)
class PushLogAdmin(admin.ModelAdmin):
    list_display = ('channel', 'kind', 'dry_run', 'ok', 'at')
    list_filter = ('channel', 'kind', 'ok')


@admin.register(SettlementBatch)
class SettlementBatchAdmin(admin.ModelAdmin):
    list_display = ('channel', 'period_from', 'period_to', 'file_name', 'uploaded_at')
