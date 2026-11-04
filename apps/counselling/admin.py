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

    # approved versions are the record of what customers were shown: never edited or deleted
    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CounsellingContentItem)
class CounsellingContentItemAdmin(admin.ModelAdmin):
    """Read-only: linking / unlinking goes through the audited review screen (services.link_items)."""
    list_display = ('content', 'item', 'linked_by', 'linked_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
