"""
apps/images/views.py

Image Acquisition API — full endpoint set.

Jobs
  GET  /api/images/jobs/               list + filter
  POST /api/images/jobs/               create + trigger
  GET  /api/images/jobs/{id}/          detail + top candidates
  POST /api/images/jobs/{id}/cancel/   cancel
  POST /api/images/jobs/bulk/          bulk create (advanced filters)
  POST /api/images/jobs/revise-all/    re-run for items with existing images

Candidates
  GET  /api/images/candidates/                  list (filter item/status/score)
  POST /api/images/candidates/{id}/review/      approve | reject
  POST /api/images/candidates/{id}/redownload/  re-fetch + re-score

Product Gallery
  GET  /api/images/products/search/                       searchable item list with image status
  GET  /api/images/products/{item_pk}/gallery/            all approved images
  GET  /api/images/products/{item_pk}/candidates/         all candidates for item
  POST /api/images/products/{item_pk}/set-primary/{id}/   set primary image
  PATCH /api/images/products/{item_pk}/reorder/           reorder images
  DELETE /api/images/products/{item_pk}/images/{id}/      delete image
  POST /api/images/products/{item_pk}/upload/             upload image file

Stats
  GET  /api/images/report/        aggregate stats
  GET  /api/images/review-queue/  items awaiting human review
  GET  /api/images/filter-meta/   category/producer lists for UI dropdowns
"""
import threading
from concurrent.futures import ThreadPoolExecutor

from django.db.models import Count, Exists, OuterRef, Q, Subquery
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Item
from .models import ImageCandidate, ImageSearchJob
from .serializers import (
    ImageCandidateSerializer, ImageSearchJobSerializer,
    JobCreateSerializer, CandidateReviewSerializer,
)


# ── Jobs ──────────────────────────────────────────────────────────────────────

class JobListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = ImageSearchJob.objects.select_related('item', 'triggered_by').order_by('-created_at')
        p  = request.query_params

        if p.get('status'):
            qs = qs.filter(status=p['status'])
        if p.get('item'):
            qs = qs.filter(item_id=p['item'])
        if p.get('priority'):
            qs = qs.filter(priority=p['priority'])

        page_size = min(int(p.get('page_size', 25)), 100)
        return Response(ImageSearchJobSerializer(qs[:page_size], many=True, context={'request': request}).data)

    def post(self, request):
        ser = JobCreateSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            item = Item.objects.get(pk=ser.validated_data['item_id'])
        except Item.DoesNotExist:
            return Response({'detail': 'الصنف غير موجود'}, status=status.HTTP_404_NOT_FOUND)

        from .pipeline import create_job
        job = create_job(
            item                   = item,
            priority               = ser.validated_data['priority'],
            triggered_by           = request.user,
            auto_approve_threshold = ser.validated_data['auto_approve_threshold'],
            force_rerun            = ser.validated_data.get('force_rerun', False),
        )
        if job.status == 'pending':
            _start_job_thread(job.pk)

        return Response(
            ImageSearchJobSerializer(job, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


class JobDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            job = ImageSearchJob.objects.select_related('item', 'triggered_by').get(pk=pk)
        except ImageSearchJob.DoesNotExist:
            return Response({'detail': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
        return Response(ImageSearchJobSerializer(job, context={'request': request}).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_job(request, pk):
    try:
        job = ImageSearchJob.objects.get(pk=pk)
    except ImageSearchJob.DoesNotExist:
        return Response({'detail': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
    if job.status not in ('pending', 'running'):
        return Response({'detail': 'لا يمكن إلغاء هذه المهمة'}, status=status.HTTP_400_BAD_REQUEST)
    job.status      = 'cancelled'
    job.finished_at = timezone.now()
    job.save(update_fields=['status', 'finished_at'])
    return Response({'detail': 'تم الإلغاء'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_create_jobs(request):
    """
    POST {
      scope: 'no_image' | 'all_active' | 'low_score' | 'top_qty' | 'top_value',
      category_id:   int (optional),
      producer_name: str (optional),
      abc_class:     'A'|'B'|'C' (optional),
      limit:         int (default 100, max 500),
      priority:      1-4,
      auto_approve_threshold: float,
      force_rerun:   bool,
    }
    """
    from .pipeline import build_item_queryset, create_job

    data      = request.data
    limit     = min(int(data.get('limit', 100)), 500)
    priority  = int(data.get('priority', 2))
    threshold = float(data.get('auto_approve_threshold', 0.78))
    force     = bool(data.get('force_rerun', False))

    filters = {
        'scope':         data.get('scope', 'no_image'),
        'category_id':   data.get('category_id'),
        'producer_name': data.get('producer_name', ''),
        'abc_class':     data.get('abc_class', ''),
        'limit':         limit,
    }

    items   = build_item_queryset(filters)
    created = skipped = 0

    for item in items:
        job = create_job(
            item=item, priority=priority, triggered_by=request.user,
            auto_approve_threshold=threshold, force_rerun=force,
        )
        if job.status == 'pending':
            _start_job_thread(job.pk)
            created += 1
        else:
            skipped += 1

    return Response({'created': created, 'skipped': skipped, 'total_matched': created + skipped})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def revise_all(request):
    """
    POST { limit: 200, priority: 3, min_score: 0.0 }
    Re-run image search for ALL items (including those with existing images).
    Used when you want to review/replace existing images.
    Optionally filter to only items where best_score < min_score.
    """
    from .pipeline import build_item_queryset, create_job

    limit     = min(int(request.data.get('limit', 200)), 500)
    priority  = int(request.data.get('priority', 3))   # default HIGH
    threshold = float(request.data.get('auto_approve_threshold', 0.82))
    min_score = float(request.data.get('min_score', 0.0))

    # All active items — no image filter
    filters  = {'scope': 'all_active', 'limit': limit}
    if request.data.get('category_id'):
        filters['category_id'] = request.data['category_id']
    if request.data.get('producer_name'):
        filters['producer_name'] = request.data['producer_name']
    if request.data.get('abc_class'):
        filters['abc_class'] = request.data['abc_class']

    items   = build_item_queryset(filters)
    created = 0

    for item in items:
        # If min_score filter: skip items whose latest job already has a good score
        if min_score > 0:
            last_job = ImageSearchJob.objects.filter(item=item, status='done').order_by('-created_at').first()
            if last_job and last_job.best_score >= min_score:
                continue

        job = create_job(
            item=item, priority=priority, triggered_by=request.user,
            auto_approve_threshold=threshold, force_rerun=True,
        )
        if job.status == 'pending':
            _start_job_thread(job.pk)
            created += 1

    return Response({'created': created, 'message': f'تم إنشاء {created} مهمة مراجعة'})


# ── Candidates ────────────────────────────────────────────────────────────────

class CandidateListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = ImageCandidate.objects.select_related('item', 'reviewed_by').order_by('-total_score')
        p  = request.query_params

        if p.get('item'):
            qs = qs.filter(item_id=p['item'])

        status_f = p.get('status', 'pending_review')
        if status_f and status_f != 'all':
            qs = qs.filter(status=status_f)

        if p.get('min_score'):
            qs = qs.filter(total_score__gte=float(p['min_score']))

        if p.get('max_watermark'):
            # Filter to candidates with watermark_score below threshold
            # watermark_score is stored in score_breakdown JSON
            # Use Python filter as fallback (small result sets)
            max_wm   = float(p['max_watermark'])
            page_size = min(int(p.get('page_size', 50)), 200)
            results  = []
            for c in qs[:page_size * 3]:
                wm = c.score_breakdown.get('watermark_score', 0)
                if wm <= max_wm:
                    results.append(c)
                    if len(results) >= page_size:
                        break
            return Response(ImageCandidateSerializer(results, many=True, context={'request': request}).data)

        page_size = min(int(p.get('page_size', 30)), 100)
        return Response(ImageCandidateSerializer(qs[:page_size], many=True, context={'request': request}).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def review_candidate(request, pk):
    """POST { action: 'approve'|'reject', note: '...', set_primary: true }"""
    try:
        candidate = ImageCandidate.objects.select_related('item').get(pk=pk)
    except ImageCandidate.DoesNotExist:
        return Response({'detail': 'Not found'}, status=status.HTTP_404_NOT_FOUND)

    ser = CandidateReviewSerializer(data=request.data)
    if not ser.is_valid():
        return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

    if ser.validated_data['action'] == 'approve':
        from .pipeline import approve_candidate
        approve_candidate(candidate, user=request.user,
                          set_as_primary=ser.validated_data['set_primary'])
        return Response({'status': 'approved'})

    candidate.status      = 'rejected'
    candidate.reviewed_by = request.user
    candidate.reviewed_at = timezone.now()
    candidate.review_note = ser.validated_data['note']
    candidate.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_note'])
    # Record rejection for learning
    try:
        from .pipeline import _record_approval_insight
        _record_approval_insight(candidate, approved=False)
    except Exception:
        pass
    return Response({'status': 'rejected'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def redownload_candidate(request, pk):
    try:
        candidate = ImageCandidate.objects.select_related('item').get(pk=pk)
    except ImageCandidate.DoesNotExist:
        return Response({'detail': 'Not found'}, status=status.HTTP_404_NOT_FOUND)

    def _run():
        from .downloader import download_image, strip_exif_and_normalise, make_content_file
        from .scorer     import score_image, compute_phash
        from .models     import ProductNormalization

        norm = ProductNormalization.objects.filter(item=candidate.item).first()
        dl   = download_image(candidate.source_url)
        if not dl:
            return
        raw, ext    = dl
        clean       = strip_exif_and_normalise(raw, ext) or raw
        scores      = score_image(
            clean, candidate.source_type,
            brand       = norm.brand       if norm else '',
            strength    = norm.strength    if norm else '',
            dosage_form = norm.dosage_form if norm else '',
            auto_clean  = True,
        )
        final = scores['cleaned_bytes'] if scores['was_cleaned'] else clean
        phash = compute_phash(final)
        cf    = make_content_file(final, candidate.item.softech_id, f'_r{candidate.pk}')
        candidate.local_file.save(cf.name, cf, save=False)
        candidate.phash            = phash
        candidate.quality_score    = scores['quality_score']
        candidate.confidence_score = scores['confidence_score']
        candidate.total_score      = scores['total_score']
        candidate.score_breakdown  = {**scores['breakdown'], 'watermark_score': scores['watermark_score']}
        candidate.width            = scores['width']
        candidate.height           = scores['height']
        candidate.status           = 'scored'
        candidate.save()

    threading.Thread(target=_run, daemon=True).start()
    return Response({'detail': 'إعادة التنزيل جارية'})


# ── Stats ─────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def images_report(request):
    from apps.product_experience.models import ProductMedia

    total          = Item.objects.filter(is_active=True).count()
    with_image     = ProductMedia.objects.filter(media_type='image', approved=True).values('item').distinct().count()
    pending_review = ImageCandidate.objects.filter(status='pending_review').count()
    auto_approved  = ImageCandidate.objects.filter(status='auto_approved').count()
    was_cleaned    = ImageCandidate.objects.filter(status__in=('approved','auto_approved')).count()
    jobs_running   = ImageSearchJob.objects.filter(status='running').count()
    jobs_pending   = ImageSearchJob.objects.filter(status='pending').count()
    jobs_failed    = ImageSearchJob.objects.filter(status='failed').count()
    coverage_pct   = round(with_image / total * 100, 1) if total else 0

    return Response({
        'total_items':      total,
        'items_with_image': with_image,
        'coverage_pct':     coverage_pct,
        'pending_review':   pending_review,
        'auto_approved':    auto_approved,
        'jobs_running':     jobs_running,
        'jobs_pending':     jobs_pending,
        'jobs_failed':      jobs_failed,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def review_queue(request):
    qs        = (ImageCandidate.objects
                 .filter(status='pending_review')
                 .select_related('item')
                 .order_by('-total_score'))
    page_size = min(int(request.query_params.get('page_size', 30)), 100)
    return Response(ImageCandidateSerializer(qs[:page_size], many=True, context={'request': request}).data)


# ── Product image search (filterable item list with image status) ──────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def product_image_search(request):
    """
    GET /api/images/products/search/
    Searchable, filterable item list with image status for the gallery manager.

    Params:
      q             text search (name, softech_id)
      has_image     'yes' | 'no' | 'pending' | ''  (default = '')
      category_id   int
      producer_name str (partial)
      page          int (default 1)
      page_size     int (default 30, max 100)
    """
    from apps.catalog.models import Item
    from apps.product_experience.models import ProductMedia

    p = request.query_params
    qs = Item.objects.filter(is_active=True, is_stockable=True).select_related('category')

    # ── text search ───────────────────────────────────────────────────────────
    q = (p.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(softech_id__icontains=q))

    # ── category filter ───────────────────────────────────────────────────────
    cat_id = p.get('category_id')
    if cat_id:
        qs = qs.filter(category_id=cat_id)

    # ── producer filter ───────────────────────────────────────────────────────
    producer = (p.get('producer_name') or '').strip()
    if producer:
        qs = qs.filter(producer_name__icontains=producer)

    # ── image-status filter ───────────────────────────────────────────────────
    has_image_filter = p.get('has_image', '')

    approved_media = ProductMedia.objects.filter(
        item=OuterRef('pk'), media_type='image', approved=True
    )
    pending_cands = ImageCandidate.objects.filter(
        item=OuterRef('pk'), status='pending_review'
    )

    qs = qs.annotate(
        has_approved=Exists(approved_media),
        has_pending=Exists(pending_cands),
        approved_count=Subquery(
            ProductMedia.objects.filter(item=OuterRef('pk'), media_type='image', approved=True)
            .values('item').annotate(c=Count('id')).values('c')[:1]
        ),
        pending_count=Subquery(
            ImageCandidate.objects.filter(item=OuterRef('pk'), status='pending_review')
            .values('item').annotate(c=Count('id')).values('c')[:1]
        ),
    )

    if has_image_filter == 'yes':
        qs = qs.filter(has_approved=True)
    elif has_image_filter == 'no':
        qs = qs.filter(has_approved=False)
    elif has_image_filter == 'pending':
        qs = qs.filter(has_pending=True)

    # ── pagination ────────────────────────────────────────────────────────────
    page_size = min(int(p.get('page_size', 30)), 100)
    page      = max(int(p.get('page', 1)), 1)
    offset    = (page - 1) * page_size
    total     = qs.count()

    items_page = qs.order_by('name')[offset: offset + page_size]

    # ── fetch primary thumbnails in one query ─────────────────────────────────
    item_ids = [i.pk for i in items_page]
    primary_map = {}
    for m in ProductMedia.objects.filter(
        item_id__in=item_ids, media_type='image', is_primary=True
    ).select_related():
        primary_map[m.item_id] = m

    results = []
    for item in items_page:
        pm = primary_map.get(item.pk)
        thumb = ''
        if pm and pm.file:
            try:
                thumb = request.build_absolute_uri(pm.file.url)
            except Exception:
                pass
        results.append({
            'id':              item.pk,
            'softech_id':      item.softech_id,
            'name':            item.name,
            'producer_name':   item.producer_name or '',
            'category_name':   item.category.name_ar if item.category else '',
            'has_image':       item.has_approved,
            'approved_count':  item.approved_count or 0,
            'pending_count':   item.pending_count or 0,
            'primary_thumb':   thumb,
        })

    return Response({
        'total':     total,
        'page':      page,
        'page_size': page_size,
        'pages':     max(1, -(-total // page_size)),   # ceiling division
        'results':   results,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def item_candidates(request, item_pk):
    """
    GET /api/images/products/{item_pk}/candidates/
    All ImageCandidates for an item (any status), ordered by score desc.
    Params:
      status  filter by candidate status (optional)
    """
    from apps.catalog.models import Item
    try:
        Item.objects.get(pk=item_pk)
    except Item.DoesNotExist:
        return Response({'detail': 'الصنف غير موجود'}, status=status.HTTP_404_NOT_FOUND)

    qs = (ImageCandidate.objects
          .filter(item_id=item_pk)
          .select_related('reviewed_by')
          .order_by('-total_score'))

    st = request.query_params.get('status')
    if st and st != 'all':
        qs = qs.filter(status=st)

    page_size = min(int(request.query_params.get('page_size', 50)), 200)
    return Response(ImageCandidateSerializer(qs[:page_size], many=True, context={'request': request}).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_product_image(request, item_pk):
    """
    POST /api/images/products/{item_pk}/upload/
    Upload an image file directly and make it an approved ProductMedia.
    Multipart form-data: file, set_primary (bool, default true)
    """
    from apps.catalog.models import Item
    from apps.product_experience.models import ProductMedia
    from django.core.files.uploadedfile import InMemoryUploadedFile

    try:
        item = Item.objects.get(pk=item_pk)
    except Item.DoesNotExist:
        return Response({'detail': 'الصنف غير موجود'}, status=status.HTTP_404_NOT_FOUND)

    f = request.FILES.get('file')
    if not f:
        return Response({'detail': 'لم يتم رفع ملف'}, status=status.HTTP_400_BAD_REQUEST)

    # Basic mime check
    allowed = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
    if f.content_type not in allowed:
        return Response({'detail': 'نوع الملف غير مدعوم'}, status=status.HTTP_400_BAD_REQUEST)

    set_primary = str(request.data.get('set_primary', 'true')).lower() != 'false'

    if set_primary:
        ProductMedia.objects.filter(item=item, media_type='image', is_primary=True).update(is_primary=False)

    media = ProductMedia(
        item       = item,
        media_type = 'image',
        alt_text   = item.name or '',
        order      = 0 if set_primary else 99,
        is_primary = set_primary,
        source     = 'manual',
        approved   = True,
        uploaded_by= request.user,
    )
    ext = f.name.rsplit('.', 1)[-1].lower() if '.' in f.name else 'jpg'
    fname = f'manual_{item.softech_id}_{timezone.now().strftime("%Y%m%d%H%M%S")}.{ext}'
    media.file.save(fname, f, save=True)

    # Sync enrichment URL
    try:
        from apps.enrichment.models import ItemEnrichment
        enr, _ = ItemEnrichment.objects.get_or_create(item=item)
        if set_primary or not enr.image_url:
            enr.image_url = request.build_absolute_uri(media.file.url)
            enr.save(update_fields=['image_url'])
    except Exception:
        pass

    return Response({
        'detail':   'تم رفع الصورة بنجاح',
        'media_id': media.pk,
        'url':      request.build_absolute_uri(media.file.url),
    }, status=status.HTTP_201_CREATED)


# ── Product gallery management ─────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def product_gallery(request, item_pk):
    """
    GET /api/images/products/{item_pk}/gallery/
    Returns all ProductMedia images for an item, ordered by sort order.
    """
    from apps.catalog.models import Item
    from apps.product_experience.models import ProductMedia

    try:
        item = Item.objects.get(pk=item_pk)
    except Item.DoesNotExist:
        return Response({'detail': 'الصنف غير موجود'}, status=status.HTTP_404_NOT_FOUND)

    media = ProductMedia.objects.filter(item=item, media_type='image').order_by('order', '-is_primary', '-created_at')
    data = []
    for m in media:
        data.append({
            'id':         m.pk,
            'url':        request.build_absolute_uri(m.file.url) if m.file else '',
            'thumb_url':  request.build_absolute_uri(m.thumbnail.url) if m.thumbnail else (
                          request.build_absolute_uri(m.file.url) if m.file else ''),
            'is_primary': m.is_primary,
            'order':      m.order,
            'source':     m.source,
            'approved':   m.approved,
            'alt_text':   m.alt_text,
            'created_at': m.created_at.isoformat(),
        })
    return Response({'item_id': item_pk, 'item_name': item.name, 'images': data})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def set_primary_image(request, item_pk, media_pk):
    """
    POST /api/images/products/{item_pk}/set-primary/{media_pk}/
    Sets one image as primary and demotes others.
    """
    from apps.product_experience.models import ProductMedia
    from apps.enrichment.models import ItemEnrichment

    try:
        media = ProductMedia.objects.get(pk=media_pk, item_id=item_pk, media_type='image')
    except ProductMedia.DoesNotExist:
        return Response({'detail': 'الصورة غير موجودة'}, status=status.HTTP_404_NOT_FOUND)

    ProductMedia.objects.filter(item_id=item_pk, media_type='image').update(is_primary=False)
    media.is_primary = True
    media.approved   = True
    media.order      = 0
    media.save(update_fields=['is_primary', 'approved', 'order'])

    # Sync to enrichment
    try:
        enrichment, _ = ItemEnrichment.objects.get_or_create(item_id=item_pk)
        enrichment.image_url = request.build_absolute_uri(media.file.url) if media.file else ''
        enrichment.save(update_fields=['image_url'])
    except Exception:
        pass

    return Response({'detail': 'تم تعيين الصورة الافتراضية', 'media_id': media.pk})


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def reorder_images(request, item_pk):
    """
    PATCH /api/images/products/{item_pk}/reorder/
    Body: { order: [media_id, media_id, ...] }  (first = primary)
    """
    from apps.product_experience.models import ProductMedia

    order_list = request.data.get('order', [])
    if not order_list:
        return Response({'detail': 'order مطلوب'}, status=status.HTTP_400_BAD_REQUEST)

    media_qs = ProductMedia.objects.filter(item_id=item_pk, media_type='image')
    for idx, mid in enumerate(order_list):
        media_qs.filter(pk=mid).update(order=idx, is_primary=(idx == 0))

    return Response({'detail': 'تم إعادة الترتيب'})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_image(request, item_pk, media_pk):
    """DELETE /api/images/products/{item_pk}/images/{media_pk}/"""
    from apps.product_experience.models import ProductMedia

    try:
        media = ProductMedia.objects.get(pk=media_pk, item_id=item_pk, media_type='image')
    except ProductMedia.DoesNotExist:
        return Response({'detail': 'الصورة غير موجودة'}, status=status.HTTP_404_NOT_FOUND)

    was_primary = media.is_primary
    media.delete()

    # If deleted primary, promote the next one
    if was_primary:
        next_media = ProductMedia.objects.filter(item_id=item_pk, media_type='image').order_by('order').first()
        if next_media:
            next_media.is_primary = True
            next_media.save(update_fields=['is_primary'])

    return Response({'detail': 'تم حذف الصورة'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def learning_insights(request):
    """
    GET /api/images/insights/
    Returns top approved sources per brand — shows what the system has learned.
    """
    from .models import ImageApprovalInsight
    from django.db.models import Sum

    top = (
        ImageApprovalInsight.objects
        .filter(considered__gte=3)
        .order_by('-approved')[:50]
    )
    data = [{
        'brand':             i.brand,
        'source_type':       i.source_type,
        'approved':          i.approved,
        'considered':        i.considered,
        'approval_rate':     round(i.approval_rate * 100, 1),
        'weight':            i.weight,
        'avg_quality_score': round(i.avg_quality_score * 100, 1),
    } for i in top]

    # Summary stats
    total_insights = ImageApprovalInsight.objects.count()
    total_approved = ImageApprovalInsight.objects.aggregate(s=Sum('approved'))['s'] or 0

    return Response({
        'top_sources': data,
        'total_brands_learned': total_insights,
        'total_approved_tracked': total_approved,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def filter_meta(request):
    """Return distinct category and producer lists for UI filter dropdowns."""
    from apps.catalog.models import Category

    categories = list(
        Category.objects.filter(item__is_active=True).distinct()
        .values('id', 'name_ar', 'name').order_by('name_ar')
    )
    producers = list(
        Item.objects.filter(is_active=True, is_stockable=True)
        .exclude(producer_name='')
        .values_list('producer_name', flat=True)
        .distinct().order_by('producer_name')[:200]
    )

    # ABC class counts from latest demand run
    abc_counts = {}
    try:
        from apps.purchasing.models import DemandCalculationRun, ItemDemandAggregated
        run = DemandCalculationRun.objects.filter(status='success').order_by('-calc_date').first()
        if run:
            for row in (ItemDemandAggregated.objects.filter(run=run)
                        .values('abc_class').annotate(count=Count('id'))):
                abc_counts[row['abc_class']] = row['count']
    except Exception:
        pass

    return Response({
        'categories': categories,
        'producers':  producers,
        'abc_counts': abc_counts,
    })


# ── Bounded thread pool ────────────────────────────────────────────────────────
# Max 6 concurrent pipeline workers.  Each holds exactly one DB connection
# during the DB phase; the connection is closed before HTTP I/O.
# This caps peak DB connections at: 6 (workers) + Django request threads.
_PIPELINE_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix='img-pipeline')


def _start_job_thread(job_pk: int) -> None:
    """Submit a job to the bounded pool instead of spawning unlimited threads."""
    def _run():
        from django.db import close_old_connections, connection as _db
        close_old_connections()           # discard stale connections from prior runs
        try:
            from .models   import ImageSearchJob
            from .pipeline import run_job
            try:
                job = ImageSearchJob.objects.get(pk=job_pk, status='pending')
                run_job(job)
            except ImageSearchJob.DoesNotExist:
                pass
            except Exception as exc:
                ImageSearchJob.objects.filter(pk=job_pk).update(
                    status='failed', last_error=str(exc)[:1000],
                    finished_at=timezone.now(),
                )
        finally:
            _db.close()                   # CRITICAL: return connection to pool

    _PIPELINE_POOL.submit(_run)
