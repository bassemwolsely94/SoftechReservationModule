from django.contrib import admin
from .models import StaffProfile, UserBranchAccess, RoleModuleAccess


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display  = ['user', 'role', 'branch', 'has_global_access', 'phone', 'is_active']
    list_filter   = ['role', 'branch', 'is_active', 'has_global_access']
    search_fields = ['user__username', 'user__first_name', 'user__last_name']
    list_editable = ['role', 'is_active', 'has_global_access']
    raw_id_fields = ['user', 'branch']


@admin.register(UserBranchAccess)
class UserBranchAccessAdmin(admin.ModelAdmin):
    list_display  = ['staff', 'branch', 'granted_by', 'granted_at']
    list_filter   = ['branch']
    search_fields = ['staff__user__username', 'branch__name']
    raw_id_fields = ['staff', 'branch', 'granted_by']
    readonly_fields = ['granted_at']


@admin.register(RoleModuleAccess)
class RoleModuleAccessAdmin(admin.ModelAdmin):
    list_display  = ['role', 'module', 'action', 'is_allowed', 'updated_by', 'updated_at']
    list_filter   = ['role', 'module', 'is_allowed']
    list_editable = ['is_allowed']
    ordering      = ['role', 'module', 'action']

    def save_model(self, request, obj, form, change):
        profile = getattr(request.user, 'staff_profile', None)
        obj.updated_by = profile
        super().save_model(request, obj, form, change)