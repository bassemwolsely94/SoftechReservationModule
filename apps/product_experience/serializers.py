"""
apps/product_experience/serializers.py

Serializers for the Product Experience Platform.
"""
from rest_framework import serializers
from apps.catalog.models import Item
from .models import (
    ProductMapping, ProductMedia, ProductContent, ProductAttribute,
    ProductSEO, ProductExperience, ProductRelation, ProductAvailabilityCache,
)


# ── ProductMedia ──────────────────────────────────────────────────────────────

class ProductMediaSerializer(serializers.ModelSerializer):
    url       = serializers.SerializerMethodField()
    thumb_url = serializers.SerializerMethodField()

    class Meta:
        model  = ProductMedia
        fields = [
            'id', 'media_type', 'url', 'thumb_url', 'alt_text',
            'order', 'is_primary', 'source', 'approved', 'created_at',
        ]
        read_only_fields = ['id', 'url', 'thumb_url', 'created_at']

    def get_url(self, obj):
        request = self.context.get('request')
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return obj.file.url if obj.file else ''

    def get_thumb_url(self, obj):
        request = self.context.get('request')
        if obj.thumbnail and request:
            return request.build_absolute_uri(obj.thumbnail.url)
        return obj.thumbnail.url if obj.thumbnail else self.get_url(obj)


class ProductMediaUploadSerializer(serializers.Serializer):
    """For handling multi-part file uploads."""
    file       = serializers.FileField()
    media_type = serializers.ChoiceField(choices=['image', 'video', 'pdf', 'manual'], default='image')
    alt_text   = serializers.CharField(max_length=255, required=False, allow_blank=True)
    order      = serializers.IntegerField(min_value=0, default=0)
    is_primary = serializers.BooleanField(default=False)


# ── ProductContent ────────────────────────────────────────────────────────────

class ProductContentSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ProductContent
        fields = [
            'display_name_ar', 'display_name_en',
            'short_description', 'long_description',
            'instructions', 'storage', 'usage',
            'contraindications', 'benefits',
            'marketing_text', 'keywords', 'faq',
            'adherence_icons', 'whatsapp_preview',
            'updated_at',
        ]
        read_only_fields = ['updated_at']


class ProductContentPublicSerializer(serializers.ModelSerializer):
    """Customer-facing — excludes marketing_text and internal fields."""
    class Meta:
        model  = ProductContent
        fields = [
            'display_name_ar', 'display_name_en',
            'short_description', 'long_description',
            'instructions', 'storage', 'usage',
            'benefits', 'faq', 'adherence_icons',
            'whatsapp_preview',
        ]


# ── ProductAttribute ──────────────────────────────────────────────────────────

class ProductAttributeSerializer(serializers.ModelSerializer):
    temperature_storage_display = serializers.CharField(
        source='get_temperature_storage_display', read_only=True,
    )

    class Meta:
        model  = ProductAttribute
        fields = [
            'strength', 'concentration', 'flavor', 'color',
            'size', 'pack_size_label', 'count_per_pack',
            'prescription_required',
            'temperature_storage', 'temperature_storage_display',
            'shelf_life_months', 'special_warnings',
            'updated_at',
        ]
        read_only_fields = ['updated_at', 'temperature_storage_display']


# ── ProductSEO ────────────────────────────────────────────────────────────────

class ProductSEOSerializer(serializers.ModelSerializer):
    og_image_url = serializers.SerializerMethodField()

    class Meta:
        model  = ProductSEO
        fields = [
            'slug', 'title_ar', 'title_en',
            'description_ar', 'description_en',
            'keywords', 'canonical', 'og_image_url',
            'updated_at',
        ]
        read_only_fields = ['updated_at', 'og_image_url']

    def get_og_image_url(self, obj):
        if obj.og_image:
            request = self.context.get('request')
            return request.build_absolute_uri(obj.og_image.url) if request else obj.og_image.url
        return ''


class ProductSEOWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ProductSEO
        fields = ['slug', 'title_ar', 'title_en', 'description_ar', 'description_en',
                  'keywords', 'canonical', 'og_image']


# ── ProductExperience ─────────────────────────────────────────────────────────

class ProductExperienceSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ProductExperience
        fields = [
            'views', 'shares', 'wishlist_adds',
            'reservations', 'refills', 'call_requests',
            'popularity_score', 'last_interaction',
        ]
        read_only_fields = fields


# ── ProductRelation ───────────────────────────────────────────────────────────

class ProductRelationSerializer(serializers.ModelSerializer):
    to_item_name     = serializers.CharField(source='to_item.name', read_only=True)
    to_item_barcode  = serializers.CharField(source='to_item.barcode', read_only=True)
    relation_type_display = serializers.CharField(source='get_relation_type_display', read_only=True)

    class Meta:
        model  = ProductRelation
        fields = [
            'id', 'to_item_id', 'to_item_name', 'to_item_barcode',
            'relation_type', 'relation_type_display', 'order', 'is_active', 'created_at',
        ]
        read_only_fields = ['id', 'created_at', 'to_item_name', 'to_item_barcode', 'relation_type_display']


class ProductRelationWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ProductRelation
        fields = ['to_item', 'relation_type', 'order', 'is_active']


# ── ProductAvailabilityCache ──────────────────────────────────────────────────

class ProductAvailabilitySerializer(serializers.Serializer):
    """
    Returns availability without exposing internal quantities.
    Customer sees: available / limited / unavailable.
    """
    branch_id       = serializers.IntegerField()
    branch_name     = serializers.CharField()
    branch_name_ar  = serializers.CharField()
    status          = serializers.CharField()
    status_display  = serializers.SerializerMethodField()

    def get_status_display(self, obj):
        labels = {'available': 'متاح', 'limited': 'كميات محدودة', 'unavailable': 'غير متاح'}
        return labels.get(obj.get('status', ''), '')


# ── Item base (for list views) ────────────────────────────────────────────────

class ItemBaseSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Item
        fields = [
            'softech_id', 'name', 'name_scientific', 'barcode',
            'pack_price', 'unit_price', 'shape_name_ar', 'origin_name_ar',
            'effect_name_ar', 'family_name_ar', 'supplier_name',
            'active_ingredients', 'requires_fridge', 'is_active',
        ]


# ── Product Card ──────────────────────────────────────────────────────────────

class ProductCardSerializer(serializers.ModelSerializer):
    """
    Reusable product card — used in reservations, call center, catalog, e-commerce.
    Single endpoint that assembles everything needed for a card UI component.
    """
    # Content
    display_name_ar    = serializers.SerializerMethodField()
    display_name_en    = serializers.SerializerMethodField()
    short_description  = serializers.SerializerMethodField()
    instructions       = serializers.SerializerMethodField()
    adherence_icons    = serializers.SerializerMethodField()
    whatsapp_preview   = serializers.SerializerMethodField()

    # Attributes
    strength           = serializers.SerializerMethodField()
    flavor             = serializers.SerializerMethodField()
    pack_size_label    = serializers.SerializerMethodField()
    count_per_pack     = serializers.SerializerMethodField()
    prescription_required = serializers.SerializerMethodField()
    temperature_storage = serializers.SerializerMethodField()

    # Media
    image_url          = serializers.SerializerMethodField()
    thumb_url          = serializers.SerializerMethodField()
    media_count        = serializers.SerializerMethodField()

    # Availability (abstracted)
    availability       = serializers.SerializerMethodField()

    # SEO
    slug               = serializers.SerializerMethodField()

    # Analytics
    popularity_score   = serializers.SerializerMethodField()

    # Operational fields
    is_chronic         = serializers.SerializerMethodField()
    margin_pct         = serializers.SerializerMethodField()

    class Meta:
        model  = Item
        fields = [
            'id', 'softech_id', 'name', 'name_scientific', 'barcode',
            'pack_price', 'unit_price', 'cost_price',
            'shape_name_ar', 'origin_name_ar', 'effect_name_ar', 'effect_code',
            'family_name_ar', 'supplier_name', 'producer_name',
            'active_ingredients', 'requires_fridge', 'is_active',
            'is_fast_moving', 'insurance_type', 'has_points',
            'medicine_type', 'medicine_type_name_ar',
            'last_synced',
            # Extended
            'display_name_ar', 'display_name_en', 'short_description',
            'instructions', 'adherence_icons', 'whatsapp_preview',
            'strength', 'flavor', 'pack_size_label', 'count_per_pack',
            'prescription_required', 'temperature_storage',
            'primary_image_url', 'image_url', 'thumb_url', 'media_count',
            'overall_availability', 'availability', 'slug', 'popularity_score',
            'is_chronic', 'margin_pct',
        ]

    # Alias used by frontend pages
    primary_image_url = serializers.SerializerMethodField()
    overall_availability = serializers.SerializerMethodField()

    def get_primary_image_url(self, obj):
        return self.get_image_url(obj)

    def get_overall_availability(self, obj):
        return self.get_availability(obj)

    def _content(self, obj):
        return getattr(obj, 'content', None)

    def _attr(self, obj):
        return getattr(obj, 'attributes', None)

    def _seo(self, obj):
        return getattr(obj, 'seo', None)

    def _exp(self, obj):
        return getattr(obj, 'experience', None)

    def get_display_name_ar(self, obj):
        c = self._content(obj)
        return (c.display_name_ar if c else None) or obj.name

    def get_display_name_en(self, obj):
        c = self._content(obj)
        return (c.display_name_en if c else None) or obj.name_scientific or ''

    def get_short_description(self, obj):
        c = self._content(obj)
        return c.short_description if c else ''

    def get_instructions(self, obj):
        c = self._content(obj)
        return c.instructions if c else ''

    def get_adherence_icons(self, obj):
        c = self._content(obj)
        return c.adherence_icons if c else []

    def get_whatsapp_preview(self, obj):
        c = self._content(obj)
        return c.whatsapp_preview if c else ''

    def get_strength(self, obj):
        a = self._attr(obj)
        return a.strength if a else ''

    def get_flavor(self, obj):
        a = self._attr(obj)
        return a.flavor if a else ''

    def get_pack_size_label(self, obj):
        a = self._attr(obj)
        return a.pack_size_label if a else ''

    def get_count_per_pack(self, obj):
        a = self._attr(obj)
        return a.count_per_pack if a else None

    def get_prescription_required(self, obj):
        a = self._attr(obj)
        return a.prescription_required if a else None

    def get_temperature_storage(self, obj):
        a = self._attr(obj)
        return a.temperature_storage if a else ''

    def get_image_url(self, obj):
        media = self._get_primary_media(obj)
        if media:
            request = self.context.get('request')
            return request.build_absolute_uri(media.file.url) if (request and media.file) else (media.file.url if media.file else '')
        return ''

    def get_thumb_url(self, obj):
        media = self._get_primary_media(obj)
        if media:
            request = self.context.get('request')
            url = media.thumbnail.url if media.thumbnail else (media.file.url if media.file else '')
            return request.build_absolute_uri(url) if (request and url) else url
        return ''

    def get_media_count(self, obj):
        # Use prefetch if available, else count
        if hasattr(obj, 'primary_media_list'):
            return len(obj.primary_media_list)
        return obj.media.filter(approved=True).count()

    def get_availability(self, obj):
        from .services import get_item_overall_availability
        return get_item_overall_availability(obj)

    def get_slug(self, obj):
        s = self._seo(obj)
        return s.slug if s else ''

    def get_popularity_score(self, obj):
        e = self._exp(obj)
        return e.popularity_score if e else 0

    def get_is_chronic(self, obj):
        return hasattr(obj, 'chronic_tag') and obj.chronic_tag is not None and obj.chronic_tag.is_active

    def get_margin_pct(self, obj):
        """Gross margin % = (pack_price - cost_price) / pack_price * 100. None when cost unknown."""
        if obj.pack_price and obj.cost_price and float(obj.pack_price) > 0:
            margin = (float(obj.pack_price) - float(obj.cost_price)) / float(obj.pack_price) * 100
            return round(margin, 1)
        return None

    def _get_primary_media(self, obj):
        if hasattr(obj, 'primary_media_list') and obj.primary_media_list:
            return obj.primary_media_list[0]
        return obj.media.filter(is_primary=True, approved=True).first()


# ── Product Detail ────────────────────────────────────────────────────────────

class ProductDetailSerializer(ProductCardSerializer):
    """Full detail with all nested data."""
    content    = ProductContentPublicSerializer(read_only=True)
    attributes = ProductAttributeSerializer(read_only=True)
    seo        = ProductSEOSerializer(read_only=True)
    experience = ProductExperienceSerializer(read_only=True)
    all_media  = serializers.SerializerMethodField()
    relations  = serializers.SerializerMethodField()
    faq        = serializers.SerializerMethodField()

    class Meta(ProductCardSerializer.Meta):
        fields = ProductCardSerializer.Meta.fields + [
            'content', 'attributes', 'seo', 'experience',
            'all_media', 'relations', 'faq',
            'medicine_type_name_ar', 'unit_name', 'comment',
            'phcode',
        ]

    def get_all_media(self, obj):
        media_qs = obj.media.filter(approved=True).order_by('order', '-is_primary')
        return ProductMediaSerializer(media_qs, many=True, context=self.context).data

    def get_relations(self, obj):
        """
        Returns a flat list of relation dicts, each with a nested 'to_item' object.
        Frontend groups by relation_type itself.
        """
        request = self.context.get('request')
        result = []
        rels = (
            obj.relations_from
            .filter(is_active=True)
            .select_related('to_item', 'to_item__content')
            .prefetch_related('to_item__media')
            .order_by('relation_type', 'order')
        )
        for rel in rels:
            p = rel.to_item
            if not p.is_active:
                continue
            primary = next(
                (m for m in p.media.all() if m.is_primary and m.approved), None
            ) or next(
                (m for m in p.media.all() if m.media_type == 'image' and m.approved), None
            )
            if primary and primary.file:
                img = request.build_absolute_uri(primary.file.url) if request else primary.file.url
            else:
                img = ''
            content = getattr(p, 'content', None)
            result.append({
                'id':            rel.id,
                'relation_type': rel.relation_type,
                'order':         rel.order,
                'to_item': {
                    'id':               p.pk,
                    'softech_id':       p.softech_id,
                    'name':             p.name,
                    'display_name_ar':  (content.display_name_ar if content else '') or p.name,
                    'barcode':          p.barcode or '',
                    'primary_image_url': img,
                },
            })
        return result

    def get_faq(self, obj):
        c = getattr(obj, 'content', None)
        return c.faq if c else []


# ── ProductMapping ────────────────────────────────────────────────────────────

class ProductMappingSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ProductMapping
        fields = ['id', 'softech_id', 'external_code', 'barcode',
                  'is_primary', 'sync_status', 'last_synced', 'notes']
        read_only_fields = ['id']
