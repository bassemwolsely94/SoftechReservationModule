from django.contrib import admin

from .models import HelpOverride, HelpRevision, HelpFeedback, HelpEvent, HelpTrainingOverride


@admin.register(HelpOverride)
class HelpOverrideAdmin(admin.ModelAdmin):
    list_display = ('screen_key', 'updated_by', 'updated_at')
    search_fields = ('screen_key',)


@admin.register(HelpRevision)
class HelpRevisionAdmin(admin.ModelAdmin):
    list_display = ('screen_key', 'action', 'staff', 'note', 'created_at')
    list_filter = ('action',)
    search_fields = ('screen_key', 'note')

    def has_change_permission(self, request, obj=None):
        return False   # immutable history


@admin.register(HelpFeedback)
class HelpFeedbackAdmin(admin.ModelAdmin):
    list_display = ('screen_key', 'tab', 'helpful', 'role', 'resolved', 'created_at')
    list_filter = ('helpful', 'resolved', 'role')
    search_fields = ('screen_key', 'comment')


@admin.register(HelpEvent)
class HelpEventAdmin(admin.ModelAdmin):
    list_display = ('kind', 'screen_key', 'tab', 'query', 'role', 'created_at')
    list_filter = ('kind', 'role')


@admin.register(HelpTrainingOverride)
class HelpTrainingOverrideAdmin(admin.ModelAdmin):
    list_display = ('kind', 'key', 'updated_by', 'updated_at')
    list_filter = ('kind',)
