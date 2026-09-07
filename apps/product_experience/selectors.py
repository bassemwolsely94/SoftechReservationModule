"""
apps/product_experience/selectors.py

Query layer — assembles product data from multiple models.
Handles: search, product card assembly, recommendations.
"""
from django.db.models import Q, Prefetch
from django.utils import timezone

from apps.catalog.models import Item


# ── Search ────────────────────────────────────────────────────────────────────

def search_products(query: str, filters: dict = None, limit: int = None, ordering: str = None):
    """
    Full product search across:
      - Item.name (Arabic/English)
      - Item.name_scientific
      - Item.barcode
      - Item.active_ingredients
      - Item.family_name_ar
      - Item.effect_name_ar / effect_name2_ar
      - ProductContent.display_name_ar, display_name_en, keywords
      - ProductAttribute (strength, flavor)

    Supports: Arabic, English, phonetic (via transliteration in keywords),
              barcode, medical family, ingredient.
    """
    qs = Item.objects.filter(is_active=True)

    if query:
        q = query.strip()
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(name_scientific__icontains=q)
            | Q(barcode__icontains=q)
            | Q(active_ingredients__icontains=q)
            | Q(family_name_ar__icontains=q)
            | Q(family_name__icontains=q)
            | Q(effect_name_ar__icontains=q)
            | Q(effect_name__icontains=q)
            | Q(effect_name2_ar__icontains=q)
            | Q(content__display_name_ar__icontains=q)
            | Q(content__display_name_en__icontains=q)
            | Q(content__keywords__icontains=q)
            | Q(attributes__strength__icontains=q)
            | Q(attributes__flavor__icontains=q)
            | Q(softech_id__icontains=q)
        ).distinct()

    if filters:
        if filters.get('category'):
            qs = qs.filter(category_id=filters['category'])
        if filters.get('shape_code'):
            qs = qs.filter(shape_code=filters['shape_code'])
        if filters.get('origin_code'):
            qs = qs.filter(origin_code=filters['origin_code'])
        if filters.get('requires_fridge') is not None:
            qs = qs.filter(requires_fridge=filters['requires_fridge'])
        if filters.get('prescription_required') is not None:
            qs = qs.filter(attributes__prescription_required=filters['prescription_required'])
        if filters.get('effect_code'):
            qs = qs.filter(
                Q(effect_code=filters['effect_code'])
                | Q(effect_code2=filters['effect_code'])
            )
        if filters.get('is_chronic'):
            qs = qs.filter(chronic_tag__isnull=False, chronic_tag__is_active=True)
        if filters.get('supplier_code'):
            qs = qs.filter(supplier_code=filters['supplier_code'])
        if filters.get('has_image'):
            qs = qs.filter(media__media_type='image', media__approved=True).distinct()
        if filters.get('is_fast_moving'):
            qs = qs.filter(is_fast_moving=True)
        if filters.get('insurance_type') not in (None, ''):
            qs = qs.filter(insurance_type=filters['insurance_type'])
        if filters.get('is_chronic'):
            qs = qs.filter(chronic_tag__isnull=False, chronic_tag__is_active=True)
        if filters.get('availability'):
            avail = filters['availability']
            if avail == 'available':
                qs = qs.filter(availability_cache__status='available').distinct()
            elif avail == 'limited':
                # limited but NOT available at any branch
                qs = (
                    qs.filter(availability_cache__status='limited')
                    .exclude(availability_cache__status='available')
                    .distinct()
                )
            elif avail == 'unavailable':
                # no cache entry with available/limited → fully unavailable
                qs = qs.exclude(
                    availability_cache__status__in=['available', 'limited']
                ).distinct()

    qs = (
        qs
        .select_related('category', 'content', 'attributes', 'seo', 'experience')
        .prefetch_related(
            Prefetch(
                'media',
                queryset=__import__(
                    'apps.product_experience.models', fromlist=['ProductMedia']
                ).ProductMedia.objects.filter(is_primary=True, approved=True),
                to_attr='primary_media_list',
            )
        )
    )
    order_map = {
        'popular':       ('-experience__popularity_score', 'name'),
        'newest':        ('-last_synced', 'name'),
        'price_asc':     ('pack_price', 'name'),
        'price_desc':    ('-pack_price', 'name'),
        'name_asc':      ('name',),
        'margin_desc':   ('-pack_price', 'name'),  # approximate; precise margin computed in Python
    }
    qs = qs.order_by(*order_map.get(ordering or 'popular', ('-experience__popularity_score', 'name')))
    if limit:
        qs = qs[:limit]
    return qs


def autocomplete_products(query: str, limit: int = 8):
    """
    Lightweight autocomplete — returns minimal fields for fast dropdown.
    """
    if not query or len(query) < 2:
        return []

    return list(
        Item.objects.filter(is_active=True).filter(
            Q(name__icontains=query)
            | Q(name_scientific__icontains=query)
            | Q(barcode__icontains=query)
            | Q(active_ingredients__icontains=query)
            | Q(content__display_name_ar__icontains=query)
        )
        .distinct()
        .values('softech_id', 'name', 'name_scientific', 'barcode')
        [:limit]
    )


# ── Product Card Assembly ─────────────────────────────────────────────────────

def get_product_card_data(item) -> dict:
    """
    Assemble complete product card data from all related models.
    Used by: reservations, call center, catalog listing, future e-commerce.
    Returns a structured dict (not serialized — let the serializer do that).
    """
    from .services import get_item_overall_availability

    content    = getattr(item, 'content', None)
    attributes = getattr(item, 'attributes', None)
    seo        = getattr(item, 'seo', None)
    experience = getattr(item, 'experience', None)

    # Primary image
    primary_media = item.media.filter(is_primary=True, approved=True).first()
    if not primary_media:
        primary_media = item.media.filter(media_type='image', approved=True).order_by('order').first()

    # Availability
    availability = get_item_overall_availability(item)

    # Active relations
    relations = {}
    for rt_key, _ in __import__(
        'apps.product_experience.models', fromlist=['RELATION_TYPES']
    ).RELATION_TYPES:
        rels = item.relations_from.filter(relation_type=rt_key, is_active=True).select_related('to_item')
        if rels.exists():
            relations[rt_key] = [
                {
                    'softech_id': r.to_item.softech_id,
                    'name': r.to_item.name,
                    'barcode': r.to_item.barcode,
                }
                for r in rels[:5]
            ]

    return {
        'softech_id':    item.softech_id,
        'name':          item.name,
        'name_scientific': item.name_scientific,
        'barcode':       item.barcode,
        'pack_price':    str(item.pack_price),
        'unit_price':    str(item.unit_price),
        'shape_name_ar': item.shape_name_ar,
        'origin_name_ar': item.origin_name_ar,
        'effect_name_ar': item.effect_name_ar,
        'active_ingredients': item.active_ingredients,
        'supplier_name': item.supplier_name,
        'producer_name': item.producer_name,
        'family_name_ar': item.family_name_ar,
        'requires_fridge': item.requires_fridge,
        'is_active':     item.is_active,

        # Content
        'display_name_ar': content.display_name_ar if content else '',
        'display_name_en': content.display_name_en if content else '',
        'short_description': content.short_description if content else '',
        'instructions':  content.instructions if content else '',
        'adherence_icons': content.adherence_icons if content else [],
        'whatsapp_preview': content.whatsapp_preview if content else '',

        # Attributes
        'strength':      attributes.strength if attributes else '',
        'flavor':        attributes.flavor if attributes else '',
        'pack_size_label': attributes.pack_size_label if attributes else '',
        'count_per_pack': attributes.count_per_pack if attributes else None,
        'prescription_required': attributes.prescription_required if attributes else None,
        'temperature_storage': attributes.temperature_storage if attributes else '',

        # Media
        'image_url':     primary_media.url if primary_media else '',
        'thumb_url':     primary_media.thumb_url if primary_media else '',

        # Availability (abstracted — no quantities)
        'availability':  availability,

        # SEO
        'slug':          seo.slug if seo else '',

        # Analytics
        'popularity_score': experience.popularity_score if experience else 0,

        # Relations
        'relations':     relations,
    }


# ── Recommendations ───────────────────────────────────────────────────────────

def get_recommendations(item, customer=None, limit: int = 6) -> list:
    """
    Personalized recommendations based on:
    1. Curated ProductRelation (recommended, companion, starter_pack)
    2. Same therapeutic family (effect_code)
    3. Popularity score

    Only uses actual data. No ML, no conversion metrics.
    """
    rec_items = set()
    result = []

    # 1. Curated relations
    for relation in item.relations_from.filter(
        is_active=True,
        relation_type__in=['recommended', 'companion', 'frequently_bought']
    ).select_related('to_item')[:limit]:
        if relation.to_item.is_active and relation.to_item.pk not in rec_items:
            rec_items.add(relation.to_item.pk)
            result.append(relation.to_item)

    # 2. Same therapeutic family (fill remaining slots)
    if len(result) < limit and item.effect_code:
        family_qs = (
            Item.objects.filter(
                is_active=True,
                effect_code=item.effect_code,
            )
            .exclude(pk=item.pk)
            .exclude(pk__in=rec_items)
            .select_related('content', 'experience')
            .order_by('-experience__popularity_score')
            [:(limit - len(result))]
        )
        for i in family_qs:
            rec_items.add(i.pk)
            result.append(i)

    # 3. Same family fallback
    if len(result) < limit and item.family_code:
        fallback = (
            Item.objects.filter(
                is_active=True,
                family_code=item.family_code,
            )
            .exclude(pk=item.pk)
            .exclude(pk__in=rec_items)
            .select_related('content', 'experience')
            .order_by('-experience__popularity_score')
            [:(limit - len(result))]
        )
        result.extend(fallback)

    return result[:limit]


def get_substitutes(item) -> list:
    """Get substitute products for an item."""
    return list(
        item.relations_from.filter(
            relation_type='substitute', is_active=True,
        ).select_related('to_item__content', 'to_item__experience')
        .values_list('to_item', flat=True)
    )


def get_popular_products(limit: int = 20) -> object:
    """Top products by popularity score."""
    return (
        Item.objects.filter(is_active=True)
        .select_related('content', 'experience', 'attributes')
        .prefetch_related('media')
        .order_by('-experience__popularity_score', 'name')
        [:limit]
    )
