"""
apps/images/pipeline.py

Main Image Acquisition Pipeline Orchestrator.

Entry points:
  create_job(item, ...)          — create / reactivate a search job
  run_job(job)                   — execute one job (called by worker thread)
  approve_candidate(candidate)   — promote to ProductMedia
  build_item_queryset(filters)   — build filtered Item QS for batch launch

Supports:
  force_rerun=True   — re-search even if the item already has an approved image
  auto_clean=True    — attempt watermark removal before saving candidates
"""
from __future__ import annotations
import logging
import time
from typing import Optional

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.catalog.models import Item
from .models import ImageCandidate, ImageSearchJob, ProductNormalization

logger = logging.getLogger('elrezeiky')

AUTO_APPROVE_THRESHOLD = 0.78
REVIEW_THRESHOLD       = 0.40
STOP_AFTER_CANDIDATES  = 12
MAX_DOWNLOAD_PER_JOB   = 15


# ── Job creation ───────────────────────────────────────────────────────────────

def create_job(
    item: Item,
    priority: int = 2,
    triggered_by=None,
    auto_approve_threshold: float = AUTO_APPROVE_THRESHOLD,
    force_rerun: bool = False,
) -> ImageSearchJob:
    """
    Create (or reactivate) a job for an item.
    force_rerun=True  → creates a new job even if a done/skipped one exists.
    """
    if not force_rerun:
        existing = ImageSearchJob.objects.filter(
            item=item, status__in=('pending', 'running')
        ).first()
        if existing:
            return existing

    return ImageSearchJob.objects.create(
        item                   = item,
        priority               = priority,
        triggered_by           = triggered_by,
        auto_approve_threshold = auto_approve_threshold,
    )


# ── Item queryset builder (for batch launch with advanced filters) ─────────────

def build_item_queryset(filters: dict) -> QuerySet:
    """
    Build a filtered Item queryset for batch job creation.

    Accepted filter keys:
      scope          'no_image' | 'all_active' | 'low_score' | 'top_qty' | 'top_value'
      category_id    int
      producer_name  str  (partial match)
      abc_class      'A' | 'B' | 'C'
      limit          int  (max items)
    """
    from apps.catalog.models import Item
    from apps.product_experience.models import ProductMedia

    qs = Item.objects.filter(is_active=True, is_stockable=True)

    # ── Category filter ────────────────────────────────────────────────────────
    cat_id = filters.get('category_id')
    if cat_id:
        qs = qs.filter(category_id=cat_id)

    # ── Producer / manufacturer filter ────────────────────────────────────────
    producer = (filters.get('producer_name') or '').strip()
    if producer:
        qs = qs.filter(producer_name__icontains=producer)

    # ── ABC class filter (from latest demand run) ─────────────────────────────
    abc = (filters.get('abc_class') or '').strip().upper()
    if abc in ('A', 'B', 'C'):
        qs = _filter_by_abc(qs, abc)

    # ── Scope ─────────────────────────────────────────────────────────────────
    scope = filters.get('scope', 'no_image')

    if scope == 'no_image':
        items_with_image = (
            ProductMedia.objects
            .filter(media_type='image', approved=True)
            .values_list('item_id', flat=True)
        )
        qs = qs.exclude(id__in=items_with_image)

    elif scope == 'low_score':
        from apps.enrichment.models import ItemEnrichment
        low_ids = (
            ItemEnrichment.objects
            .filter(completeness_score__lt=40, image_url='')
            .values_list('item_id', flat=True)
        )
        qs = qs.filter(id__in=low_ids)

    elif scope == 'top_qty':
        qs = _order_by_top_sold(qs, by='qty')

    elif scope == 'top_value':
        qs = _order_by_top_sold(qs, by='value')

    # ── Limit ─────────────────────────────────────────────────────────────────
    limit = int(filters.get('limit', 100))
    return qs[:limit]


def _filter_by_abc(qs: QuerySet, abc: str) -> QuerySet:
    """Filter items by ABC class from the latest demand run."""
    try:
        from apps.purchasing.models import DemandCalculationRun, ItemDemandAggregated
        run = DemandCalculationRun.objects.filter(status='success').order_by('-calc_date').first()
        if not run:
            return qs
        item_ids = (
            ItemDemandAggregated.objects
            .filter(run=run, abc_class=abc)
            .values_list('item_id', flat=True)
        )
        return qs.filter(id__in=item_ids)
    except Exception as exc:
        logger.debug('ABC filter failed: %s', exc)
        return qs


def _order_by_top_sold(qs: QuerySet, by: str = 'qty') -> QuerySet:
    """
    Annotate and order items by monthly_avg (qty) or monthly_avg × pack_price (value).
    Uses ItemDemandAggregated from the latest successful demand run.
    """
    try:
        from apps.purchasing.models import DemandCalculationRun, ItemDemandAggregated
        run = DemandCalculationRun.objects.filter(status='success').order_by('-calc_date').first()
        if not run:
            return qs

        agg_qs = ItemDemandAggregated.objects.filter(run=run)
        if by == 'value':
            # Annotate approximate monthly revenue: monthly_avg × pack_price
            from django.db.models import ExpressionWrapper, F, FloatField
            agg_qs = agg_qs.annotate(
                monthly_value=ExpressionWrapper(
                    F('total_monthly_avg') * F('pack_price'),
                    output_field=FloatField(),
                )
            ).order_by('-monthly_value')
        else:
            agg_qs = agg_qs.order_by('-total_monthly_avg')

        ordered_ids = list(agg_qs.values_list('item_id', flat=True))
        # Preserve order using CASE WHEN in PostgreSQL
        from django.db.models import Case, IntegerField, Value, When
        preserved = Case(
            *[When(id=pk, then=Value(i)) for i, pk in enumerate(ordered_ids[:500])],
            output_field=IntegerField(),
            default=Value(9999),
        )
        return qs.filter(id__in=ordered_ids).annotate(_ord=preserved).order_by('_ord')
    except Exception as exc:
        logger.debug('Top-sold ordering failed: %s', exc)
        return qs


# ── Job runner ─────────────────────────────────────────────────────────────────

def run_job(job: ImageSearchJob) -> None:
    """Execute one job end-to-end in a background thread."""
    from django.db import connection as _db
    from .normalizer  import normalize_item
    from .searcher    import search_all_sources
    from .downloader  import download_image, strip_exif_and_normalise, make_content_file
    from .scorer      import score_image, compute_phash, are_duplicates

    job.status     = 'running'
    job.started_at = timezone.now()
    job.save(update_fields=['status', 'started_at'])

    try:
        item = job.item

        # ── Normalise ─────────────────────────────────────────────────────────
        norm_data = normalize_item(item)
        norm, _   = ProductNormalization.objects.update_or_create(
            item=item, defaults=norm_data,
        )

        # ── Skip check ────────────────────────────────────────────────────────
        from apps.product_experience.models import ProductMedia
        has_image = ProductMedia.objects.filter(item=item, media_type='image', approved=True).exists()
        if has_image and job.attempt_count == 0 and job.priority < 3:
            job.status      = 'skipped'
            job.finished_at = timezone.now()
            job.save(update_fields=['status', 'finished_at'])
            return

        # ── Load learned source weights before releasing DB connection ────────
        learned_weights: dict[str, float] = {}
        if norm.brand:
            from .models import ImageApprovalInsight
            for ins in ImageApprovalInsight.objects.filter(brand__iexact=norm.brand):
                learned_weights[ins.source_type] = ins.weight

        # ── Collect seen URLs + pHashes from previous attempts ────────────────
        seen_urls    = set(ImageCandidate.objects.filter(item=item).values_list('source_url', flat=True))
        phashes_seen = list(ImageCandidate.objects.filter(item=item).exclude(phash='').values_list('phash', flat=True))

        # ── CLOSE DB BEFORE LONG-RUNNING NETWORK I/O ─────────────────────────
        # Releases the PostgreSQL connection back to the pool while we do HTTP.
        # Django will reopen automatically on the next DB call.
        _db.close()

        # ── Search (no DB held during this) ───────────────────────────────────
        barcode     = item.barcode or ''
        raw_results = search_all_sources(
            brand           = norm.brand,
            strength        = norm.strength,
            dosage_form     = norm.dosage_form,
            search_query_en = norm.search_query_en,
            search_query_ar = norm.search_query_ar,
            barcode         = barcode,
            item_name       = item.name,
            stop_after      = STOP_AFTER_CANDIDATES,
            learned_weights = learned_weights,
        )

        job.candidates_found = len(raw_results)
        job.save(update_fields=['candidates_found'])

        if not raw_results:
            job.status     = 'failed'
            job.last_error = 'No image URLs found in any source'
            job.finished_at = timezone.now()
            job.save(update_fields=['status', 'last_error', 'finished_at'])
            return

        # ── Deduplicate URLs (using sets fetched before network I/O) ─────────
        new_results = [r for r in raw_results if r['source_url'] not in seen_urls]

        # ── Download + score + save ───────────────────────────────────────────
        downloaded     = 0
        best_score     = 0.0
        best_candidate: Optional[ImageCandidate] = None

        for result in new_results[:MAX_DOWNLOAD_PER_JOB]:
            url = result['source_url']
            dl  = download_image(url)
            if not dl:
                continue

            raw_bytes, ext  = dl
            clean_bytes     = strip_exif_and_normalise(raw_bytes, ext) or raw_bytes

            # Score with watermark detection + auto-clean
            scores = score_image(
                image_bytes  = clean_bytes,
                source_type  = result['source_type'],
                brand        = norm.brand,
                strength     = norm.strength,
                dosage_form  = norm.dosage_form,
                metadata     = result.get('scraper_metadata', {}),
                auto_clean   = True,
            )

            if scores['total_score'] < REVIEW_THRESHOLD:
                continue

            # Use the cleaned bytes if watermark was removed
            final_bytes = scores['cleaned_bytes'] if scores['was_cleaned'] else clean_bytes

            # pHash dedup
            phash = compute_phash(final_bytes)
            if phash and any(are_duplicates(phash, ph) for ph in phashes_seen):
                continue
            if phash:
                phashes_seen.append(phash)

            # Save candidate
            cf = make_content_file(final_bytes, item.softech_id, f'_{downloaded}')
            with transaction.atomic():
                candidate = ImageCandidate(
                    job              = job,
                    item             = item,
                    source_url       = url,
                    source_type      = result['source_type'],
                    source_page_url  = result.get('source_page_url', ''),
                    query_used       = result.get('query_used', ''),
                    width            = scores['width'],
                    height           = scores['height'],
                    file_size_bytes  = len(final_bytes),
                    format           = scores['format'],
                    phash            = phash,
                    quality_score    = scores['quality_score'],
                    confidence_score = scores['confidence_score'],
                    total_score      = scores['total_score'],
                    score_breakdown  = {
                        **scores['breakdown'],
                        'watermark_score': scores['watermark_score'],
                        'was_cleaned':     scores['was_cleaned'],
                    },
                    scraper_metadata = result.get('scraper_metadata', {}),
                    status           = 'scored',
                )
                candidate.local_file.save(cf.name, cf, save=False)
                candidate.save()

            downloaded += 1
            if scores['total_score'] > best_score:
                best_score     = scores['total_score']
                best_candidate = candidate

        job.candidates_scored = downloaded
        job.best_score        = best_score
        job.save(update_fields=['candidates_scored', 'best_score'])

        # ── Auto-approve ──────────────────────────────────────────────────────
        if best_candidate and best_score >= job.auto_approve_threshold:
            _auto_approve(best_candidate)
            # Surface remaining good candidates for optional human review
            ImageCandidate.objects.filter(
                job=job, status='scored',
                total_score__gte=REVIEW_THRESHOLD,
            ).exclude(pk=best_candidate.pk).update(status='pending_review')
            job.status = 'done'
        elif best_candidate:
            # Mark ALL candidates above threshold as pending_review
            ImageCandidate.objects.filter(
                job=job, status='scored',
                total_score__gte=REVIEW_THRESHOLD,
            ).update(status='pending_review')
            job.status = 'done'
        elif downloaded == 0:
            job.status     = 'failed'
            job.last_error = 'All candidates below quality/watermark threshold'
        else:
            job.status = 'done'

    except Exception as exc:
        logger.exception('ImageJob#%d failed: %s', job.pk, exc)
        job.status     = 'failed'
        job.last_error = str(exc)[:1000]
    finally:
        job.finished_at   = timezone.now()
        job.attempt_count += 1
        job.save(update_fields=[
            'status', 'last_error', 'finished_at', 'attempt_count',
            'candidates_found', 'candidates_scored', 'best_score',
        ])


# ── Approval ───────────────────────────────────────────────────────────────────

def approve_candidate(candidate: ImageCandidate, user=None, set_as_primary: bool = True) -> None:
    from apps.product_experience.models import ProductMedia

    item = candidate.item
    if set_as_primary:
        ProductMedia.objects.filter(item=item, is_primary=True).update(is_primary=False)

    media = ProductMedia.objects.create(
        item        = item,
        media_type  = 'image',
        file        = candidate.local_file,
        alt_text    = item.name or '',
        order       = 0,
        is_primary  = set_as_primary,
        source      = 'ai_generated',
        approved    = True,
        uploaded_by = user,
    )
    candidate.status      = 'approved' if user else 'auto_approved'
    candidate.reviewed_by = user
    candidate.reviewed_at = timezone.now()
    candidate.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
    _sync_enrichment_url(item, media)

    # ── Update learning insights ───────────────────────────────────────────────
    _record_approval_insight(candidate, approved=True)

    logger.info('Candidate#%d approved → ProductMedia#%d for %s', candidate.pk, media.pk, item.softech_id)


def _auto_approve(candidate: ImageCandidate) -> None:
    approve_candidate(candidate, user=None, set_as_primary=True)
    candidate.status = 'auto_approved'
    candidate.save(update_fields=['status'])
    # Record "considered but not selected" for other candidates in this job
    for other in ImageCandidate.objects.filter(job=candidate.job).exclude(pk=candidate.pk):
        _record_approval_insight(other, approved=False)


def _record_approval_insight(candidate: ImageCandidate, approved: bool) -> None:
    """
    Update ImageApprovalInsight whenever a candidate is approved or rejected.
    Safe to call in any thread; uses update_or_create with F expressions.
    """
    try:
        from django.db.models import F
        from .models import ImageApprovalInsight
        norm = ProductNormalization.objects.filter(item=candidate.item).first()
        if not norm or not norm.brand:
            return
        obj, _ = ImageApprovalInsight.objects.get_or_create(
            brand=norm.brand.upper(), source_type=candidate.source_type,
        )
        if approved:
            ImageApprovalInsight.objects.filter(pk=obj.pk).update(
                approved=F('approved') + 1, considered=F('considered') + 1,
            )
        else:
            ImageApprovalInsight.objects.filter(pk=obj.pk).update(
                considered=F('considered') + 1,
            )
        # Update rolling avg quality score for this source/brand combo
        if approved and candidate.quality_score > 0:
            new_avg = round(
                (obj.avg_quality_score * max(obj.approved - 1, 0) + candidate.quality_score)
                / max(obj.approved, 1), 4
            )
            ImageApprovalInsight.objects.filter(pk=obj.pk).update(avg_quality_score=new_avg)
    except Exception as exc:
        logger.debug('Could not update approval insight: %s', exc)


def _sync_enrichment_url(item: Item, media) -> None:
    try:
        from apps.enrichment.models import ItemEnrichment
        enrichment, _ = ItemEnrichment.objects.get_or_create(item=item)
        if not enrichment.image_url:
            enrichment.image_url = media.file.url if media.file else ''
            enrichment.save(update_fields=['image_url'])
    except Exception as exc:
        logger.debug('Enrichment URL sync failed for %s: %s', item.pk, exc)
