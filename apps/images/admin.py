from django.contrib import admin
from django.utils.html import format_html
from .models import ImageCandidate, ImageSearchJob, ImageSource, ProductNormalization


@admin.register(ProductNormalization)
class ProductNormalizationAdmin(admin.ModelAdmin):
    list_display  = ('item', 'brand', 'strength', 'dosage_form', 'pack_size', 'parse_confidence', 'updated_at')
    search_fields = ('item__name', 'item__softech_id', 'brand', 'canonical_name')
    readonly_fields = ('updated_at',)
    list_filter   = ('dosage_form',)


@admin.register(ImageSearchJob)
class ImageSearchJobAdmin(admin.ModelAdmin):
    list_display  = ('pk', 'item', 'status', 'priority', 'candidates_found',
                     'candidates_scored', 'best_score', 'created_at')
    list_filter   = ('status', 'priority', 'current_stage')
    search_fields = ('item__name', 'item__softech_id')
    readonly_fields = ('started_at', 'finished_at', 'created_at', 'attempt_count')
    ordering       = ('-created_at',)


@admin.register(ImageCandidate)
class ImageCandidateAdmin(admin.ModelAdmin):
    list_display  = ('pk', 'item', 'source_type', 'total_score', 'quality_score',
                     'confidence_score', 'status', 'preview', 'created_at')
    list_filter   = ('status', 'source_type')
    search_fields = ('item__name', 'item__softech_id', 'source_url')
    readonly_fields = ('phash', 'score_breakdown', 'created_at', 'reviewed_at', 'preview_large')
    ordering       = ('-total_score',)

    def preview(self, obj):
        url = obj.local_file.url if obj.local_file else obj.source_url
        if url:
            return format_html('<img src="{}" style="height:50px;border-radius:4px">', url)
        return '—'
    preview.short_description = 'معاينة'

    def preview_large(self, obj):
        url = obj.local_file.url if obj.local_file else obj.source_url
        if url:
            return format_html('<img src="{}" style="max-width:300px;border-radius:8px">', url)
        return '—'
    preview_large.short_description = 'الصورة'


@admin.register(ImageSource)
class ImageSourceAdmin(admin.ModelAdmin):
    list_display  = ('name', 'source_type', 'priority', 'is_active',
                     'rate_limit_rpm', 'success_rate_display', 'last_used_at')
    list_filter   = ('is_active', 'source_type')
    ordering      = ('priority',)

    def success_rate_display(self, obj):
        return f'{obj.success_rate * 100:.1f}%'
    success_rate_display.short_description = 'معدل النجاح'
