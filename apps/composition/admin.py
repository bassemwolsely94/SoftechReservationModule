from django.contrib import admin

from .models import (
    SoftechIngredientRaw, SoftechIngredientClassRaw, IngredientParseCandidate,
)


@admin.register(SoftechIngredientClassRaw)
class SoftechIngredientClassRawAdmin(admin.ModelAdmin):
    list_display  = ('softech_code', 'name', 'synced_at')
    search_fields = ('softech_code', 'name')


@admin.register(SoftechIngredientRaw)
class SoftechIngredientRawAdmin(admin.ModelAdmin):
    list_display  = ('aicode', 'ainame', 'class_name', 'item_count', 'is_blocked', 'synced_at')
    search_fields = ('aicode', 'ainame', 'class_name')
    list_filter   = ('is_blocked',)


@admin.register(IngredientParseCandidate)
class IngredientParseCandidateAdmin(admin.ModelAdmin):
    list_display  = ('raw_aicode', 'raw_ainame', 'primary_molecule',
                     'proposed_class', 'class_confidence',
                     'is_combination', 'is_placeholder', 'confidence', 'status')
    list_filter   = ('status', 'is_combination', 'is_placeholder', 'proposed_class')
    search_fields = ('raw_aicode', 'raw_ainame')
    raw_id_fields = ('raw', 'proposed_class', 'canonical_ingredient')
    readonly_fields = ('raw', 'raw_aicode', 'raw_ainame', 'parsed_components',
                       'confidence', 'parser_version')
