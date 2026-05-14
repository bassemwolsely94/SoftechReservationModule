from django.contrib import admin
from .models import StaffProfile, UserBranchAccess, RoleModuleAccess, ERPUser, UserActivityLog


@admin.register(ERPUser)
class ERPUserAdmin(admin.ModelAdmin):
    list_display  = ['username', 'full_name', 'branch_code', 'is_active', 'synced_at']
    list_filter   = ['is_active']
    search_fields = ['username', 'full_name', 'user_id']
    readonly_fields = ['synced_at']


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display  = ['user', 'role', 'branch', 'access_all_branches', 'phone', 'is_active', 'created_at']
    list_filter   = ['role', 'branch', 'is_active', 'access_all_branches']
    search_fields = ['user__username', 'user__first_name', 'user__last_name', 'softech_username']
    list_editable = ['role', 'is_active', 'access_all_branches']
    raw_id_fields = ['user', 'branch', 'erp_user']
    readonly_fields = ['created_at', 'updated_at']
    filter_horizontal = ['allowed_branches', 'restricted_branches']
    fieldsets = [
        ('الحساب', {
            'fields': ('user', 'erp_user', 'softech_username', 'softech_user_id', 'phone'),
        }),
        ('الصلاحيات', {
            'fields': ('role', 'is_active', 'branch', 'access_all_branches',
                       'allowed_branches', 'restricted_branches'),
        }),
        ('رؤية البيانات', {
            'fields': ('can_see_all_customers', 'can_see_customer_phone'),
        }),
        ('التواريخ', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    ]


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


@admin.register(UserActivityLog)
class UserActivityLogAdmin(admin.ModelAdmin):
    list_display  = ['action', 'target_user', 'changed_by', 'ip_address', 'created_at']
    list_filter   = ['action']
    search_fields = ['target_user__user__username', 'changed_by__user__username']
    readonly_fields = ['target_user', 'changed_by', 'action', 'old_value', 'new_value',
                       'note', 'ip_address', 'created_at']
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
