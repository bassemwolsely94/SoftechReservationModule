from django.contrib import admin
from .models import SystemSetting, DropdownOption


@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    list_display   = ('key', 'label', 'value', 'value_type', 'category', 'is_public', 'updated_at')
    list_filter    = ('category', 'value_type', 'is_public')
    search_fields  = ('key', 'label', 'description')
    readonly_fields = ('updated_at',)
    ordering       = ('category', 'key')


@admin.register(DropdownOption)
class DropdownOptionAdmin(admin.ModelAdmin):
    list_display  = ('dropdown_key', 'label', 'value', 'icon', 'order', 'is_active', 'is_system')
    list_filter   = ('dropdown_key', 'is_active', 'is_system')
    search_fields = ('label', 'value', 'dropdown_key')
    ordering      = ('dropdown_key', 'order')
    list_editable = ('order', 'is_active')
