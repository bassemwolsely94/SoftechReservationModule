from django.contrib import admin

from .models import Crew, CrewManualMember, CrewRule


class _ReadOnly(admin.ModelAdmin):
    """Read-only: crews change only through the audited /crews API (dated rows, never edited)."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Crew)
class CrewAdmin(_ReadOnly):
    list_display = ('name', 'type', 'is_archived', 'updated_at')
    list_filter = ('type', 'is_archived')
    search_fields = ('name',)


@admin.register(CrewRule)
class CrewRuleAdmin(_ReadOnly):
    list_display = ('crew', 'job_titles', 'valid_from', 'valid_to', 'voided_at')


@admin.register(CrewManualMember)
class CrewManualMemberAdmin(_ReadOnly):
    list_display = ('crew', 'mode', 'employee', 'softech_usercode', 'pbx_extension', 'valid_from',
                    'valid_to', 'voided_at')
