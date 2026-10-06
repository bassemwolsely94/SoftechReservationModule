"""
apps/product_experience/admin.py
"""
from django.contrib import admin
from django.utils.html import format_html
from .models import (
    ProductMapping, ProductMedia, ProductContent, ProductAttribute,
    ProductSEO, ProductExperience, ProductRelation,
    ProductAvailabilityCache, ProductReview,
)


# ── Inlines ────────────────────────────────────────────────────────────────────

class ProductMediaInline(admin.TabularInline):
    model      = ProductMedia
    extra      = 0
    fields     = ('media_type', 'thumb_preview', 'is_primary', 'approved', 'order', 'alt_text')
    readonly_fields = ('thumb_preview', 'created_at')

    def thumb_preview(self, obj):
        if obj.thumbnail:
            return format_html('<img src="{}" style="height:40px;border-radius:4px"/>', obj.thumbnail.url)
        if obj.file and obj.media_type == 'image':
            return format_html('<img src="{}" style="height:40px;border-radius:4px"/>', obj.file.url)
        return '—'
    thumb_preview.short_description = 'معاينة'


class ProductContentInline(admin.StackedInline):
    model      = ProductContent
    extra      = 0
    fields     = ('display_name_ar', 'display_name_en', 'short_description', 'instructions',
                  'storage', 'adherence_icons', 'whatsapp_preview')
    can_delete = False


class ProductAttributeInline(admin.StackedInline):
    model      = ProductAttribute
    extra      = 0
    fields     = ('strength', 'flavor', 'pack_size_label', 'count_per_pack',
                  'prescription_required', 'temperature_storage', 'special_warnings')
    can_delete = False


class ProductSEOInline(admin.StackedInline):
    model      = ProductSEO
    extra      = 0
    fields     = ('slug', 'title_ar', 'title_en', 'description_ar', 'keywords')
    can_delete = False


class ProductRelationFromInline(admin.TabularInline):
    model       = ProductRelation
    fk_name     = 'from_item'
    extra       = 0
    fields      = ('relation_type', 'to_item', 'order', 'is_active')


# ── ProductMedia standalone ───────────────────────────────────────────────────

@admin.register(ProductMedia)
class ProductMediaAdmin(admin.ModelAdmin):
    list_display  = ('item_code', 'media_type', 'thumb_preview', 'is_primary', 'approved', 'order', 'uploaded_by', 'created_at')
    list_filter   = ('media_type', 'approved', 'is_primary', 'source')
    search_fields = ('item__softech_id', 'item__name', 'alt_text')
    readonly_fields = ('thumb_preview', 'created_at')
    ordering      = ('item__softech_id', 'order')
    list_editable = ('approved', 'is_primary', 'order')

    def item_code(self, obj):
        return obj.item.softech_id
    item_code.short_description = 'كود الصنف'

    def thumb_preview(self, obj):
        url = obj.thumbnail.url if obj.thumbnail else (obj.file.url if obj.file and obj.media_type == 'image' else '')
        if url:
            return format_html('<img src="{}" style="height:50px;border-radius:6px"/>', url)
        return obj.media_type
    thumb_preview.short_description = 'صورة'


# ── ProductContent ────────────────────────────────────────────────────────────

@admin.register(ProductContent)
class ProductContentAdmin(admin.ModelAdmin):
    list_display  = ('item_code', 'item_name', 'display_name_ar', 'has_instructions', 'has_faq', 'updated_at')
    search_fields = ('item__softech_id', 'item__name', 'display_name_ar', 'keywords')
    readonly_fields = ('updated_at',)

    def item_code(self, obj): return obj.item.softech_id
    def item_name(self, obj): return obj.item.name[:40]
    def has_instructions(self, obj): return bool(obj.instructions)
    has_instructions.boolean = True
    def has_faq(self, obj): return bool(obj.faq)
    has_faq.boolean = True


# ── ProductAttribute ──────────────────────────────────────────────────────────

@admin.register(ProductAttribute)
class ProductAttributeAdmin(admin.ModelAdmin):
    list_display  = ('item_code', 'item_name', 'strength', 'flavor', 'prescription_required',
                     'temperature_storage', 'pack_size_label', 'count_per_pack')
    list_filter   = ('prescription_required', 'temperature_storage')
    search_fields = ('item__softech_id', 'item__name', 'strength', 'flavor')

    def item_code(self, obj): return obj.item.softech_id
    def item_name(self, obj): return obj.item.name[:40]


# ── ProductSEO ────────────────────────────────────────────────────────────────

@admin.register(ProductSEO)
class ProductSEOAdmin(admin.ModelAdmin):
    list_display  = ('item_code', 'slug', 'title_ar', 'title_en', 'updated_at')
    search_fields = ('slug', 'item__softech_id', 'item__name', 'keywords')
    readonly_fields = ('updated_at',)

    def item_code(self, obj): return obj.item.softech_id


# ── ProductExperience ─────────────────────────────────────────────────────────

@admin.register(ProductExperience)
class ProductExperienceAdmin(admin.ModelAdmin):
    list_display  = ('item_code', 'item_name', 'popularity_score', 'views', 'shares',
                     'reservations', 'refills', 'call_requests', 'last_interaction')
    readonly_fields = ('popularity_score', 'last_interaction', 'updated_at')
    ordering      = ('-popularity_score',)

    def item_code(self, obj): return obj.item.softech_id
    def item_name(self, obj): return obj.item.name[:40]


# ── ProductRelation ───────────────────────────────────────────────────────────

@admin.register(ProductRelation)
class ProductRelationAdmin(admin.ModelAdmin):
    list_display  = ('from_item_code', 'relation_type', 'to_item_code', 'to_item_name', 'order', 'is_active', 'created_at')
    list_filter   = ('relation_type', 'is_active')
    search_fields = ('from_item__softech_id', 'from_item__name', 'to_item__softech_id', 'to_item__name')
    list_editable = ('order', 'is_active')

    def from_item_code(self, obj): return obj.from_item.softech_id
    from_item_code.short_description = 'من'
    def to_item_code(self, obj): return obj.to_item.softech_id
    to_item_code.short_description = 'إلى (كود)'
    def to_item_name(self, obj): return obj.to_item.name[:40]
    to_item_name.short_description = 'إلى (اسم)'


# ── ProductMapping ────────────────────────────────────────────────────────────

@admin.register(ProductMapping)
class ProductMappingAdmin(admin.ModelAdmin):
    list_display  = ('softech_id', 'item_name', 'external_code', 'barcode', 'is_primary', 'sync_status', 'last_synced')
    list_filter   = ('is_primary', 'sync_status')
    search_fields = ('softech_id', 'external_code', 'barcode', 'item__name')

    def item_name(self, obj): return obj.item.name[:40]


# ── ProductAvailabilityCache ──────────────────────────────────────────────────

@admin.register(ProductAvailabilityCache)
class ProductAvailabilityCacheAdmin(admin.ModelAdmin):
    list_display  = ('item_code', 'item_name', 'branch', 'status_badge', 'last_checked')
    list_filter   = ('status', 'branch')
    search_fields = ('item__softech_id', 'item__name')
    readonly_fields = ('last_checked',)

    def item_code(self, obj): return obj.item.softech_id
    def item_name(self, obj): return obj.item.name[:40]

    def status_badge(self, obj):
        colors = {'available': '#10b981', 'limited': '#f59e0b', 'unavailable': '#ef4444'}
        color = colors.get(obj.status, '#6b7280')
        labels = {'available': 'متاح', 'limited': 'محدود', 'unavailable': 'غير متاح'}
        return format_html(
            '<span style="background:{};color:white;padding:2px 8px;border-radius:4px">{}</span>',
            color, labels.get(obj.status, obj.status),
        )
    status_badge.short_description = 'الحالة'


# ── ProductReview (disabled) ──────────────────────────────────────────────────

@admin.register(ProductReview)
class ProductReviewAdmin(admin.ModelAdmin):
    list_display  = ('item_code', 'customer_name', 'rating', 'is_approved', 'is_active', 'created_at')
    list_filter   = ('is_active', 'is_approved', 'rating')
    search_fields = ('item__softech_id', 'customer_name', 'title')
    readonly_fields = ('created_at',)

    def item_code(self, obj): return obj.item.softech_id

    def get_queryset(self, request):
        return super().get_queryset(request)  # show all, even disabled

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['subtitle'] = '⚠️ المراجعات معطلة حتى إطلاق التجارة الإلكترونية'
        return super().changelist_view(request, extra_context=extra_context)
