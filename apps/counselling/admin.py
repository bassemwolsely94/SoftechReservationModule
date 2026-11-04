from django.contrib import admin

from .models import CounsellingContent, CounsellingContentItem, CounsellingContentVersion


@admin.register(CounsellingContent)
class CounsellingContentAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'status', 'source', 'version', 'approved_by', 'updated_at')
    list_filter = ('status', 'source')
    search_fields = ('title',)
    readonly_fields = ('status', 'version', 'approved_version', 'approved_by', 'approved_at')


@admin.register(CounsellingContentVersion)
class CounsellingContentVersionAdmin(admin.ModelAdmin):
    list_display = ('content', 'version', 'approved_by', 'approved_at')

    def has_change_permission(self, request, obj=None):
        return False


admin.site.register(CounsellingContentItem)
