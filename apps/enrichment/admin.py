from django.contrib import admin
from django.utils.html import format_html
from .models import ItemEnrichment, EnrichmentSuggestion, EnrichmentBatch, EnrichmentApprovalLog


@admin.register(ItemEnrichment)
class ItemEnrichmentAdmin(admin.ModelAdmin):
    list_display  = ['item', 'completeness_bar', 'is_published', 'last_enriched_at']
    list_filter   = ['is_published', 'item__category']
    search_fields = ['item__name', 'item__softech_id']
    readonly_fields = ['completeness_score', 'last_enriched_at', 'created_at', 'updated_at']
    ordering = ['completeness_score']

    @admin.display(description='اكتمال %')
    def completeness_bar(self, obj):
        pct = obj.completeness_score
        color = '#22c55e' if pct >= 80 else '#f59e0b' if pct >= 40 else '#ef4444'
        return format_html(
            '<div style="width:120px;background:#e5e7eb;border-radius:4px">'
            '<div style="width:{pct}%;background:{color};height:12px;border-radius:4px"></div>'
            '</div><small>{pct}%</small>',
            pct=pct, color=color,
        )


@admin.register(EnrichmentSuggestion)
class EnrichmentSuggestionAdmin(admin.ModelAdmin):
    list_display  = ['item', 'field_name', 'source', 'confidence', 'status', 'created_at']
    list_filter   = ['status', 'source', 'field_name']
    search_fields = ['item__name', 'item__softech_id', 'suggested_value']
    readonly_fields = ['created_at', 'reviewed_at']
    ordering = ['-confidence']


@admin.register(EnrichmentBatch)
class EnrichmentBatchAdmin(admin.ModelAdmin):
    list_display  = ['id', 'name', 'scope_type', 'status', 'processed_items', 'total_items', 'created_at']
    list_filter   = ['status', 'scope_type']
    readonly_fields = ['started_at', 'finished_at', 'created_at', 'error_log',
                       'total_items', 'processed_items', 'suggestions_generated',
                       'auto_published', 'error_count']


@admin.register(EnrichmentApprovalLog)
class EnrichmentApprovalLogAdmin(admin.ModelAdmin):
    list_display  = ['item', 'field_name', 'source', 'outcome', 'reviewer', 'reviewed_at']
    list_filter   = ['outcome', 'source', 'field_name']
    search_fields = ['item__name', 'item__softech_id']
    readonly_fields = ['reviewed_at']
