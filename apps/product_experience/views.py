"""
apps/product_experience/views.py

Commerce Catalog + Product Experience Platform — API views.
"""
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response

from django.shortcuts import get_object_or_404
from django.db import transaction

from apps.catalog.models import Item
from .models import (
    ProductMedia, ProductContent, ProductAttribute,
    ProductSEO, ProductRelation, ProductMapping,
)
from .serializers import (
    ProductCardSerializer, ProductDetailSerializer,
    ProductMediaSerializer, ProductMediaUploadSerializer,
    ProductContentSerializer, ProductAttributeSerializer,
    ProductSEOSerializer, ProductSEOWriteSerializer,
    ProductRelationSerializer, ProductRelationWriteSerializer,
    ProductMappingSerializer, ItemBaseSerializer,
)
from .permissions import IsContentManager, IsAdminOrReadOnly
from .services import (
    get_item_availability, get_item_overall_availability,
    track_interaction, initialize_product_experience,
    generate_share_card, ensure_product_content,
    ensure_product_attribute, ensure_product_seo, generate_thumbnail,
)
from .selectors import search_products, autocomplete_products, get_recommendations, get_popular_products


# ── Helper ────────────────────────────────────────────────────────────────────

def _get_item(softech_id: str) -> Item:
    return get_object_or_404(Item, softech_id=softech_id, is_active=True)


def _get_item_any(softech_id: str) -> Item:
    """Allow inactive items in admin contexts."""
    return get_object_or_404(Item, softech_id=softech_id)


# ── Product List ──────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def product_list(request):
    """
    Paginated product list with search + filter.
    Query params: q, category, shape_code, origin_code, requires_fridge,
                  is_chronic, prescription_required, effect_code, has_image,
                  supplier_code, page, page_size
    """
    q = request.query_params.get('q', '').strip()
    ordering = request.query_params.get('ordering', 'popular')
    filters = {
        'availability':        request.query_params.get('availability'),
        'category':            request.query_params.get('category'),
        'shape_code':          request.query_params.get('shape_code'),
        'origin_code':         request.query_params.get('origin_code'),
        'effect_code':         request.query_params.get('effect_code'),
        'supplier_code':       request.query_params.get('supplier_code'),
        'requires_fridge':     request.query_params.get('requires_fridge'),
        'is_chronic':          request.query_params.get('is_chronic'),
        'is_fast_moving':      request.query_params.get('is_fast_moving'),
        'insurance_type':      request.query_params.get('insurance_type'),
        'has_image':           request.query_params.get('has_image'),
        'prescription_required': request.query_params.get('prescription_required'),
    }
    # Clean None / empty
    filters = {k: v for k, v in filters.items() if v not in (None, '', 'null')}
    # Booleans
    for bool_key in ('requires_fridge', 'is_chronic', 'is_fast_moving', 'has_image'):
        if bool_key in filters:
            filters[bool_key] = filters[bool_key].lower() in ('1', 'true', 'yes')
    if 'prescription_required' in filters:
        val = filters['prescription_required'].lower()
        coerced = None if val == 'null' else val in ('1', 'true', 'yes')
        if coerced is None:
            del filters['prescription_required']
        else:
            filters['prescription_required'] = coerced

    try:
        page_size = min(int(request.query_params.get('page_size', 20)), 100)
        page      = max(int(request.query_params.get('page', 1)), 1)
    except (TypeError, ValueError):
        page_size, page = 20, 1

    # No search query and no filters → return empty prompt state.
    # The full 37,500-item catalog is only traversable via search, UNLESS the
    # caller explicitly opts into browsing (browse=1) — used by the "Recent"
    # tab which paginates the whole catalog ordered by last_synced.
    browse = request.query_params.get('browse') in ('1', 'true', 'yes')
    if not q and not filters and not browse:
        return Response({
            'count':          0,
            'page':           1,
            'page_size':      page_size,
            'results':        [],
            'requires_search': True,
        })

    qs     = search_products(q, filters, ordering=ordering)
    total  = qs.count()
    offset = (page - 1) * page_size
    paged  = list(qs[offset: offset + page_size])

    serializer = ProductCardSerializer(paged, many=True, context={'request': request})
    return Response({
        'count':     total,
        'page':      page,
        'page_size': page_size,
        'results':   serializer.data,
    })


# ── Product Search (autocomplete) ─────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def product_search(request):
    """
    Fast autocomplete search. Returns minimal fields.
    ?q=<query>&limit=10
    """
    q = request.query_params.get('q', '').strip()
    limit = min(int(request.query_params.get('limit', 8)), 20)
    results = autocomplete_products(q, limit=limit)
    return Response({'results': results, 'count': len(results)})


# ── Product Detail ────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def product_detail(request, softech_id):
    """
    Full product detail — all nested data.
    Automatically tracks a view interaction.
    """
    item = _get_item(softech_id)
    # Ensure experience records exist (lazy init)
    initialize_product_experience(item)
    # Track view (async-safe increment)
    track_interaction(item, 'views')
    serializer = ProductDetailSerializer(item, context={'request': request})
    return Response(serializer.data)


# ── Product Card (lightweight, for embedding) ─────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def product_card(request, softech_id):
    """
    Lightweight product card — used by reservations, call center.
    Does NOT track a view.
    """
    item = _get_item(softech_id)
    serializer = ProductCardSerializer(item, context={'request': request})
    return Response(serializer.data)


# ── Availability ──────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def product_availability(request, softech_id):
    """
    Availability per branch.
    NEVER exposes raw quantities — returns available/limited/unavailable only.
    """
    item = _get_item(softech_id)
    branch_id = request.query_params.get('branch')
    branch = None
    if branch_id:
        from apps.branches.models import Branch
        branch = get_object_or_404(Branch, pk=branch_id)

    availability = get_item_availability(item, branch=branch)
    overall      = get_item_overall_availability(item)

    return Response({
        'softech_id':   softech_id,
        'overall':      overall,
        'overall_label': {'available': 'متاح', 'limited': 'كميات محدودة', 'unavailable': 'غير متاح'}.get(overall, ''),
        'branches':     availability,
    })


# ── Media ─────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def product_media_list(request, softech_id):
    """List all approved media for a product."""
    item = _get_item(softech_id)
    media_qs = item.media.filter(approved=True).order_by('order', '-is_primary')
    return Response(ProductMediaSerializer(media_qs, many=True, context={'request': request}).data)


@api_view(['POST'])
@permission_classes([IsContentManager])
@parser_classes([MultiPartParser, FormParser])
def product_media_upload(request, softech_id):
    """
    Upload a new media file for a product.
    Admin/purchasing only. Auto-generates thumbnail for images.
    """
    item = _get_item_any(softech_id)
    upload_ser = ProductMediaUploadSerializer(data=request.data)
    upload_ser.is_valid(raise_exception=True)

    with transaction.atomic():
        media = ProductMedia(
            item        = item,
            media_type  = upload_ser.validated_data['media_type'],
            file        = upload_ser.validated_data['file'],
            alt_text    = upload_ser.validated_data.get('alt_text', ''),
            order       = upload_ser.validated_data.get('order', 0),
            is_primary  = upload_ser.validated_data.get('is_primary', False),
            source      = 'manual_upload',
            approved    = True,
            uploaded_by = request.user,
        )
        media.save()
        # Generate thumbnail inline (fast for small images)
        if media.media_type == 'image':
            generate_thumbnail(media)
            if media.thumbnail:
                type(media).objects.filter(pk=media.pk).update(thumbnail=media.thumbnail)

        # If is_primary, unset others
        if media.is_primary:
            ProductMedia.objects.filter(item=item, is_primary=True).exclude(pk=media.pk).update(is_primary=False)

    return Response(
        ProductMediaSerializer(media, context={'request': request}).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsContentManager])
def product_media_detail(request, softech_id, media_pk):
    """Update (approve/reorder/set primary) or delete a media item."""
    item  = _get_item_any(softech_id)
    media = get_object_or_404(ProductMedia, pk=media_pk, item=item)

    if request.method == 'DELETE':
        # Remove file from storage
        if media.file:
            try:
                media.file.delete(save=False)
            except Exception:
                pass
        if media.thumbnail:
            try:
                media.thumbnail.delete(save=False)
            except Exception:
                pass
        media.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # PATCH
    for field in ('alt_text', 'order', 'is_primary', 'approved'):
        if field in request.data:
            setattr(media, field, request.data[field])
    media.save()
    if media.is_primary:
        ProductMedia.objects.filter(item=item, is_primary=True).exclude(pk=media.pk).update(is_primary=False)
    return Response(ProductMediaSerializer(media, context={'request': request}).data)


# ── Content ───────────────────────────────────────────────────────────────────

@api_view(['GET', 'PUT', 'PATCH'])
@permission_classes([IsContentManager])
def product_content(request, softech_id):
    """Get or update product content. Writes require admin/purchasing role."""
    item = _get_item_any(softech_id)
    content = ensure_product_content(item)

    if request.method == 'GET':
        return Response(ProductContentSerializer(content).data)

    serializer = ProductContentSerializer(content, data=request.data, partial=(request.method == 'PATCH'))
    serializer.is_valid(raise_exception=True)
    instance = serializer.save(last_updated_by=request.user)
    return Response(ProductContentSerializer(instance).data)


# ── Attributes ────────────────────────────────────────────────────────────────

@api_view(['GET', 'PUT', 'PATCH'])
@permission_classes([IsContentManager])
def product_attributes(request, softech_id):
    """Get or update product attributes."""
    item = _get_item_any(softech_id)
    attr = ensure_product_attribute(item)

    if request.method == 'GET':
        return Response(ProductAttributeSerializer(attr).data)

    serializer = ProductAttributeSerializer(attr, data=request.data, partial=(request.method == 'PATCH'))
    serializer.is_valid(raise_exception=True)
    instance = serializer.save()
    return Response(ProductAttributeSerializer(instance).data)


# ── SEO ───────────────────────────────────────────────────────────────────────

@api_view(['GET', 'PUT', 'PATCH'])
@permission_classes([IsAdminOrReadOnly])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def product_seo(request, softech_id):
    """Get or update SEO metadata."""
    item = _get_item_any(softech_id)
    seo  = ensure_product_seo(item)

    if request.method == 'GET':
        return Response(ProductSEOSerializer(seo, context={'request': request}).data)

    serializer = ProductSEOWriteSerializer(seo, data=request.data, partial=(request.method == 'PATCH'))
    serializer.is_valid(raise_exception=True)
    instance = serializer.save()
    return Response(ProductSEOSerializer(instance, context={'request': request}).data)


# ── Relations ─────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def product_related(request, softech_id):
    """Get related products by type."""
    item = _get_item(softech_id)
    relation_type = request.query_params.get('type', '')

    qs = item.relations_from.filter(is_active=True).select_related('to_item')
    if relation_type:
        qs = qs.filter(relation_type=relation_type)

    return Response(ProductRelationSerializer(qs, many=True).data)


@api_view(['POST'])
@permission_classes([IsContentManager])
def product_add_relation(request, softech_id):
    """Add a new product relation."""
    item = _get_item_any(softech_id)
    serializer = ProductRelationWriteSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    relation = serializer.save(from_item=item, added_by=request.user)
    return Response(ProductRelationSerializer(relation).data, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([IsContentManager])
def product_remove_relation(request, softech_id, relation_pk):
    """Remove a product relation."""
    item = _get_item_any(softech_id)
    relation = get_object_or_404(ProductRelation, pk=relation_pk, from_item=item)
    relation.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


# ── Recommendations ───────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def product_recommend(request, softech_id):
    """Get personalized recommendations for a product."""
    item = _get_item(softech_id)
    limit = min(int(request.query_params.get('limit', 6)), 12)
    items = get_recommendations(item, limit=limit)
    return Response(ProductCardSerializer(items, many=True, context={'request': request}).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def popular_products(request):
    """Top products by popularity score."""
    limit = min(int(request.query_params.get('limit', 20)), 50)
    items = get_popular_products(limit=limit)
    return Response(ProductCardSerializer(items, many=True, context={'request': request}).data)


# ── Interaction tracking ──────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def product_track(request, softech_id):
    """
    Track a product interaction.
    Body: {"type": "views|shares|wishlist_adds|reservations|refills|call_requests"}
    """
    item = _get_item(softech_id)
    interaction_type = request.data.get('type', 'views')
    valid = {'views', 'shares', 'wishlist_adds', 'reservations', 'refills', 'call_requests'}
    if interaction_type not in valid:
        return Response({'detail': f'Invalid type. Must be one of: {", ".join(valid)}'}, status=400)
    track_interaction(item, interaction_type)
    return Response({'tracked': interaction_type, 'softech_id': softech_id})


# ── Share card ────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def product_share(request, softech_id):
    """
    Generate share card data for WhatsApp / social media.
    Tracks a share interaction.
    """
    item = _get_item(softech_id)
    card = generate_share_card(item)
    track_interaction(item, 'shares')
    return Response(card)


# ── Lookup by slug ────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def product_by_slug(request, slug):
    """Get product detail by SEO slug."""
    seo  = get_object_or_404(ProductSEO, slug=slug)
    item = seo.item
    initialize_product_experience(item)
    track_interaction(item, 'views')
    return Response(ProductDetailSerializer(item, context={'request': request}).data)


# ── Lookup by barcode ─────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def product_by_barcode(request, barcode):
    """Get product by barcode scan."""
    item = get_object_or_404(Item, barcode=barcode, is_active=True)
    return Response(ProductCardSerializer(item, context={'request': request}).data)


# ── Filter options ────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def product_filter_options(request):
    """
    Return available filter values for the catalog filter panel.
    """
    from apps.catalog.models import Category
    categories = [
        {'code': str(c['id']), 'name': c['name_ar'] or c['name']}
        for c in Category.objects.values('id', 'name', 'name_ar').order_by('name_ar')
        if c['name_ar'] or c['name']
    ]
    # For each code we want the best available name — prefer AR, fallback to EN.
    # Exclude entries where BOTH names are blank so codes never appear as labels.
    shapes_raw = {}
    for r in (
        Item.objects.filter(is_active=True, shape_code__gt='')
        .values('shape_code', 'shape_name_ar', 'shape_name').distinct()
    ):
        code = r['shape_code']
        name = r['shape_name_ar'] or r['shape_name'] or ''
        if code not in shapes_raw and name:
            shapes_raw[code] = name
    shapes = sorted(
        [{'code': c, 'name': n} for c, n in shapes_raw.items()],
        key=lambda x: x['name'],
    )

    effects_raw = {}
    for r in (
        Item.objects.filter(is_active=True, effect_code__gt='')
        .values('effect_code', 'effect_name_ar', 'effect_name').distinct()
    ):
        code = r['effect_code']
        name = r['effect_name_ar'] or r['effect_name'] or ''
        if code not in effects_raw and name:
            effects_raw[code] = name
    effects = sorted(
        [{'code': c, 'name': n} for c, n in effects_raw.items()],
        key=lambda x: x['name'],
    )

    origins_raw = {}
    for r in (
        Item.objects.filter(is_active=True, origin_code__gt='')
        .values('origin_code', 'origin_name_ar', 'origin_name').distinct()
    ):
        code = r['origin_code']
        name = r['origin_name_ar'] or r['origin_name'] or ''
        if code not in origins_raw and name:
            origins_raw[code] = name
    origins = sorted(
        [{'code': c, 'name': n} for c, n in origins_raw.items()],
        key=lambda x: x['name'],
    )
    return Response({
        'categories': categories,
        'shapes':     shapes,
        'effects':    effects,
        'origins':    origins,
    })


# ── Admin: bulk init experience ───────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAdminUser])
def bulk_initialize(request):
    """
    Initialize ProductContent/Attribute/SEO/Experience for all active items.
    Admin only — run once after first deployment.
    """
    items = Item.objects.filter(is_active=True)
    total = 0
    for item in items:
        initialize_product_experience(item)
        total += 1
    return Response({'initialized': total}, status=status.HTTP_200_OK)


# ── Similar items (same therapeutic class) ────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def product_similar(request, softech_id):
    """
    GET /api/products/{softech_id}/similar/
    Returns items in the same therapeutic category (effect_code).
    Also falls back to same family_code when effect is absent.
    """
    item = _get_item(softech_id)
    limit = min(int(request.query_params.get('limit', 12)), 24)

    qs = Item.objects.filter(is_active=True).exclude(pk=item.pk)

    if item.effect_code:
        qs = qs.filter(effect_code=item.effect_code)
    elif item.family_code:
        qs = qs.filter(family_code=item.family_code)
    else:
        return Response({'results': [], 'count': 0})

    from django.db.models import Prefetch as _Prefetch
    qs = (
        qs
        .select_related('content', 'attributes', 'seo', 'experience')
        .prefetch_related(
            _Prefetch(
                'media',
                queryset=ProductMedia.objects.filter(is_primary=True, approved=True),
                to_attr='primary_media_list',
            )
        )
        .order_by('-experience__popularity_score', 'name')
        [:limit]
    )

    items = list(qs)
    return Response({
        'results':    ProductCardSerializer(items, many=True, context={'request': request}).data,
        'count':      len(items),
        'grouped_by': item.effect_name_ar or item.family_name_ar or '',
    })


# ── Demand crosslink ──────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def product_demand(request, softech_id):
    """
    GET /api/products/{softech_id}/demand/
    Returns open demand records + open shortage entries for this item.
    Gives operations staff immediate visibility into demand signals.
    """
    item = _get_item(softech_id)

    # Open demand records
    try:
        from apps.demand.models import DemandItem
        demand_rows = (
            DemandItem.objects
            .filter(item=item)
            .exclude(demand__status__in=['fulfilled', 'lost', 'cancelled'])
            .select_related('demand', 'demand__branch', 'demand__customer')
            .order_by('-demand__created_at')[:20]
        )
        demands = [
            {
                'demand_number':   d.demand.demand_number,
                'status':          d.demand.status,
                'branch':          d.demand.branch.name_ar if d.demand.branch else '',
                'customer_name':   d.demand.customer_name or '',
                'quantity':        float(d.quantity) if d.quantity else 1,
                'created_at':      d.demand.created_at.isoformat(),
            }
            for d in demand_rows
        ]
    except Exception:
        demands = []

    # Open shortage entries
    try:
        from apps.shortage.models import ShortageItem
        shortage_rows = (
            ShortageItem.objects
            .filter(item=item, shortage__status='open')
            .select_related('shortage', 'shortage__branch')
            .order_by('-shortage__created_at')[:10]
        )
        shortages = [
            {
                'branch':          s.shortage.branch.name_ar if s.shortage.branch else '',
                'quantity_needed': float(s.quantity_needed) if s.quantity_needed else 0,
                'created_at':      s.shortage.created_at.isoformat(),
            }
            for s in shortage_rows
        ]
    except Exception:
        shortages = []

    return Response({
        'demands':   demands,
        'shortages': shortages,
        'total_open_demands':   len(demands),
        'total_open_shortages': len(shortages),
    })


# ── Price list export (Excel) ─────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def product_export(request):
    """
    GET /api/products/export/
    Applies same filters as product_list and returns an Excel (.xlsx) download.
    Max 10,000 rows.
    """
    import io
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        return Response({'detail': 'openpyxl غير مثبت'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    from django.http import HttpResponse

    q = request.query_params.get('q', '').strip()
    filters_raw = {
        'availability':   request.query_params.get('availability'),
        'category':       request.query_params.get('category'),
        'shape_code':     request.query_params.get('shape_code'),
        'effect_code':    request.query_params.get('effect_code'),
        'supplier_code':  request.query_params.get('supplier_code'),
        'requires_fridge': request.query_params.get('requires_fridge'),
        'is_chronic':     request.query_params.get('is_chronic'),
        'is_fast_moving': request.query_params.get('is_fast_moving'),
        'insurance_type': request.query_params.get('insurance_type'),
    }
    filters = {k: v for k, v in filters_raw.items() if v not in (None, '', 'null')}
    for bk in ('requires_fridge', 'is_chronic', 'is_fast_moving'):
        if bk in filters:
            filters[bk] = filters[bk].lower() in ('1', 'true', 'yes')

    qs = search_products(q, filters or None, limit=10_000)

    INSURANCE_LABELS = {'0': 'غير خاضع', '1': 'طلبية', '2': 'TPA', '3': 'تكافل', '4': 'أخرى'}

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'قائمة الأسعار'
    ws.sheet_view.rightToLeft = True

    header_fill = PatternFill('solid', fgColor='1A56DB')
    header_font = Font(bold=True, color='FFFFFF', size=11)
    headers = [
        'كود SOFTECH', 'اسم المنتج', 'الاسم العلمي', 'الباركود',
        'سعر العبوة', 'سعر الوحدة', 'سعر الشراء', 'هامش الربح %',
        'التصنيف العلاجي', 'الشكل الصيدلي', 'المورد', 'الشركة المنتجة',
        'بلد المنشأ', 'تأمين صحي', 'ثلاجة', 'سريع التداول', 'مزمن',
        'آخر مزامنة',
    ]
    ws.append(headers)
    for col, _ in enumerate(headers, 1):
        cell = ws.cell(1, col)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center')

    for item in qs:
        margin = None
        if item.pack_price and item.cost_price and float(item.pack_price) > 0:
            margin = round((float(item.pack_price) - float(item.cost_price)) / float(item.pack_price) * 100, 1)
        is_chronic = hasattr(item, 'chronic_tag') and item.chronic_tag is not None
        ws.append([
            item.softech_id,
            item.name,
            item.name_scientific or '',
            item.barcode or '',
            float(item.pack_price),
            float(item.unit_price),
            float(item.cost_price),
            margin,
            item.effect_name_ar or '',
            item.shape_name_ar or '',
            item.supplier_name or '',
            item.producer_name or '',
            item.origin_name_ar or '',
            INSURANCE_LABELS.get(item.insurance_type, item.insurance_type or ''),
            'نعم' if item.requires_fridge else 'لا',
            'نعم' if item.is_fast_moving else 'لا',
            'نعم' if is_chronic else 'لا',
            item.last_synced.strftime('%Y-%m-%d') if item.last_synced else '',
        ])

    # Column widths
    for col in ws.columns:
        max_len = max((len(str(c.value or '')) for c in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    response = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = 'attachment; filename="catalog_export.xlsx"'
    return response
