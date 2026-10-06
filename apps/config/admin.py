from django.contrib import admin
from .models import SystemSetting, DropdownOption, PharmacyProfile


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


@admin.register(PharmacyProfile)
class PharmacyProfileAdmin(admin.ModelAdmin):
    """
    Singleton admin — always edits pk=1.
    Lists a single row; clicking it opens the edit form.
    """
    list_display    = ('name_ar', 'name_en', 'website', 'whatsapp_number', 'updated_at')
    readonly_fields = ('updated_at',)
    fieldsets = [
        ('الهوية', {'fields': ('name_ar', 'name_en', 'tagline_ar')}),
        ('التواصل', {'fields': ('website', 'whatsapp_number', 'call_center_numbers')}),
        ('تذييل الإيصال', {'fields': ('extra_footer_ar',)}),
        ('معلومات', {'fields': ('updated_at',)}),
    ]

    def has_add_permission(self, request):
        # Block adding if singleton already exists
        return not PharmacyProfile.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
