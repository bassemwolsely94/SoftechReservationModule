from django.contrib import admin
from .models import StaffProfile


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display  = ['user', 'role', 'branch', 'phone', 'is_active']
    list_filter   = ['role', 'branch', 'is_active']
    search_fields = ['user__username', 'user__first_name', 'user__last_name']
    list_editable = ['role', 'is_active']
    raw_id_fields = ['user', 'branch']