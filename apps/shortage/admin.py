from django.contrib import admin
from .models import ShortageList, ShortageItem


class ShortageItemInline(admin.TabularInline):
    model   = ShortageItem
    extra   = 0
    fields  = ('raw_name', 'item', 'quantity_needed', 'unit', 'match_score', 'is_confirmed', 'is_unmatched')
    readonly_fields = ('match_score',)


@admin.register(ShortageList)
class ShortageListAdmin(admin.ModelAdmin):
    list_display  = ('branch', 'status', 'source', 'created_by', 'created_at')
    list_filter   = ('status', 'branch', 'source')
    search_fields = ('title', 'notes')
    readonly_fields = ('created_at', 'updated_at')
    inlines       = [ShortageItemInline]
