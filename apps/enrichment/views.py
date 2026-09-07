"""
apps/enrichment/views.py

AI Catalog Enrichment Platform — API views.
"""
import threading
from django.utils import timezone
from django.db.models import Count, Prefetch, Q
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.catalog.models import Item
from .models import (
    ItemEnrichment, EnrichmentSuggestion, EnrichmentBatch,
    EnrichmentApprovalLog, ENRICHABLE_FIELDS, FIELD_LABELS_AR,
)
from .serializers import (
    ItemEnrichmentSerializer, EnrichmentQueueItemSerializer,
    EnrichmentSuggestionSerializer, EnrichmentBatchSerializer,
)
from .gap_detector import get_completeness_report


# ── Item Enrichment ViewSet ───────────────────────────────────────────────────

class ItemEnrichmentViewSet(viewsets.ModelViewSet):
    """
    GET  /api/enrichment/enrichments/          → item queue (sorted by score)
    GET  /api/enrichment/enrichments/{id}/     → full enrichment record
    PATCH /api/enrichment/enrichments/{id}/    → manual field update
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = ItemEnrichmentSerializer
    http_method_names  = ['get', 'patch', 'head', 'options']

    def get_queryset(self):
        # ── Auto-initialise missing ItemEnrichment records ────────────────────
        # On first use the table is empty; create stub rows for all active
        # items so the queue is never blank.  Runs in the list action only,
        # capped at 2 000 items per request to stay fast.
        if self.action == 'list':
            _ensure_enrichment_stubs(limit=2_000)

        qs = (
            ItemEnrichment.objects
            .select_related('item__category')
        )
        p = self.request.query_params

        # ── Text search (param: search) ───────────────────────────────────────
        search = p.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(item__name__icontains=search) |
                Q(item__softech_id__icontains=search) |
                Q(item__barcode__icontains=search)
            )

        # ── Score range (params: score_min / score_max) ───────────────────────
        score_min = p.get('score_min')
        if score_min:
            try:
                qs = qs.filter(completeness_score__gte=float(score_min))
            except ValueError:
                pass

        score_max = p.get('score_max')
        if score_max:
            try:
                qs = qs.filter(completeness_score__lte=float(score_max))
            except ValueError:
                pass

        # ── Published filter ─────────────────────────────────────────────────
        is_published = p.get('is_published')
        if is_published is not None:
            qs = qs.filter(is_published=is_published.lower() in ('true', '1'))

        # ── Category filter ───────────────────────────────────────────────────
        category = p.get('category')
        if category:
            try:
                qs = qs.filter(item__category_id=int(category))
            except (ValueError, TypeError):
                qs = qs.filter(item__category__name__icontains=category)

        # ── Has pending suggestions (param: has_pending = true/1) ─────────────
        has_pending = p.get('has_pending', '').lower()
        if has_pending in ('1', 'true'):
            qs = qs.filter(suggestions__status='pending').distinct()

        # ── Ordering ─────────────────────────────────────────────────────────
        ordering = p.get('ordering', 'completeness_score')
        allowed = {
            'completeness_score':  'completeness_score',
            '-completeness_score': '-completeness_score',
            'item__name':          'item__name',
            '-last_enriched_at':   '-last_enriched_at',
        }
        qs = qs.order_by(allowed.get(ordering, 'completeness_score'))

        # ── Annotate pending count for list view ──────────────────────────────
        if self.action == 'list':
            qs = qs.annotate(
                pending_count_ann=Count(
                    'suggestions',
                    filter=Q(suggestions__status='pending'),
                )
            )
        return qs

    def get_serializer_class(self):
        if self.action == 'list':
            return EnrichmentQueueItemSerializer
        return ItemEnrichmentSerializer

    def partial_update(self, request, *args, **kwargs):
        response = super().partial_update(request, *args, **kwargs)
        instance = self.get_object()
        instance.compute_score()
        instance.last_enriched_at = timezone.now()
        instance.enriched_by = request.user
        instance.save(update_fields=['completeness_score', 'last_enriched_at', 'enriched_by'])
        return response


# ── Enrichment Suggestion ViewSet ─────────────────────────────────────────────

class EnrichmentSuggestionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET  /api/enrichment/suggestions/              → list (filter by item, status)
    GET  /api/enrichment/suggestions/{id}/         → detail
    POST /api/enrichment/suggestions/{id}/approve/ → approve (optionally edit value)
    POST /api/enrichment/suggestions/{id}/reject/  → reject with note
    POST /api/enrichment/suggestions/bulk-approve/ → bulk approve for item
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = EnrichmentSuggestionSerializer

    def get_queryset(self):
        qs = EnrichmentSuggestion.objects.select_related('item', 'reviewed_by')
        p  = self.request.query_params

        item_id = p.get('item')
        if item_id:
            qs = qs.filter(item_id=item_id)

        status_f = p.get('status', 'pending')
        if status_f and status_f != 'all':
            qs = qs.filter(status=status_f)

        field = p.get('field')
        if field:
            qs = qs.filter(field_name=field)

        batch = p.get('batch')
        if batch:
            qs = qs.filter(batch_id=batch)

        return qs.order_by('-confidence', 'field_name')

    # ── approve ────────────────────────────────────────────────────────────────
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """
        POST { value: '...' }   — approve as-is, or edit value first
        """
        suggestion = self.get_object()
        if suggestion.status not in ('pending', 'rejected'):
            return Response(
                {'detail': 'هذا الاقتراح تمت مراجعته مسبقاً'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        value  = (request.data.get('value') or suggestion.suggested_value).strip()
        edited = value != suggestion.suggested_value.strip()

        suggestion.status         = 'edited' if edited else 'approved'
        suggestion.approved_value = value
        suggestion.reviewed_by    = request.user
        suggestion.reviewed_at    = timezone.now()
        suggestion.save(update_fields=[
            'status', 'approved_value', 'reviewed_by', 'reviewed_at',
        ])

        # Apply to enrichment record (fill empty fields only)
        enrichment, _ = ItemEnrichment.objects.get_or_create(item=suggestion.item)
        old_val = getattr(enrichment, suggestion.field_name, '')
        setattr(enrichment, suggestion.field_name, value)
        enrichment.compute_score()
        enrichment.last_enriched_at = timezone.now()
        enrichment.enriched_by      = request.user
        enrichment.save()

        # Audit log
        EnrichmentApprovalLog.objects.create(
            item                 = suggestion.item,
            field_name           = suggestion.field_name,
            source               = suggestion.source,
            confidence_at_review = suggestion.confidence,
            outcome              = 'edited' if edited else 'approved',
            accepted_value       = value,
            reviewer             = request.user,
        )

        return Response(EnrichmentSuggestionSerializer(suggestion).data)

    # ── reject ─────────────────────────────────────────────────────────────────
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """POST { notes: '...' }"""
        suggestion = self.get_object()
        suggestion.status      = 'rejected'
        suggestion.notes       = request.data.get('notes', '')
        suggestion.reviewed_by = request.user
        suggestion.reviewed_at = timezone.now()
        suggestion.save(update_fields=['status', 'notes', 'reviewed_by', 'reviewed_at'])

        EnrichmentApprovalLog.objects.create(
            item                 = suggestion.item,
            field_name           = suggestion.field_name,
            source               = suggestion.source,
            confidence_at_review = suggestion.confidence,
            outcome              = 'rejected',
            accepted_value       = '',
            reviewer             = request.user,
        )
        return Response(EnrichmentSuggestionSerializer(suggestion).data)

    # ── bulk-approve ───────────────────────────────────────────────────────────
    @action(detail=False, methods=['post'], url_path='bulk-approve')
    def bulk_approve(self, request):
        """
        POST { item_id: X, min_confidence: 0.8 }
        Approve all pending suggestions for the item above the threshold.
        """
        item_id  = request.data.get('item_id')
        min_conf = float(request.data.get('min_confidence', 0.80))

        if not item_id:
            return Response({'detail': 'item_id مطلوب'}, status=status.HTTP_400_BAD_REQUEST)

        pending = list(EnrichmentSuggestion.objects.filter(
            item_id=item_id,
            status='pending',
            confidence__gte=min_conf,
        ).select_related('item'))

        if not pending:
            return Response({'approved': 0})

        # Fetch enrichment ONCE — a new object per get_or_create would lose prior setattr changes
        enrichment, _ = ItemEnrichment.objects.get_or_create(item=pending[0].item)
        changed  = False
        approved = 0

        for sug in pending:
            value = sug.suggested_value
            sug.status         = 'approved'
            sug.approved_value = value
            sug.reviewed_by    = request.user
            sug.reviewed_at    = timezone.now()
            sug.save(update_fields=['status', 'approved_value', 'reviewed_by', 'reviewed_at'])

            if not getattr(enrichment, sug.field_name, ''):
                setattr(enrichment, sug.field_name, value)
                changed = True

            EnrichmentApprovalLog.objects.create(
                item=sug.item, field_name=sug.field_name, source=sug.source,
                confidence_at_review=sug.confidence, outcome='approved',
                accepted_value=value, reviewer=request.user,
            )
            approved += 1

        if changed:
            enrichment.compute_score()
            enrichment.last_enriched_at = timezone.now()
            enrichment.enriched_by      = request.user
            enrichment.save()

        return Response({'approved': approved})


# ── Enrichment Batch ViewSet ──────────────────────────────────────────────────

class EnrichmentBatchViewSet(viewsets.ModelViewSet):
    """
    POST /api/enrichment/batches/        → create + trigger batch in background
    GET  /api/enrichment/batches/        → list batches (audit trail)
    GET  /api/enrichment/batches/{id}/   → batch detail + progress
    POST /api/enrichment/batches/{id}/cancel/ → cancel
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = EnrichmentBatchSerializer

    def get_queryset(self):
        return EnrichmentBatch.objects.all().order_by('-created_at')

    def perform_create(self, serializer):
        batch = serializer.save(created_by=self.request.user)
        _start_batch_thread(batch.pk)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        batch = self.get_object()
        if batch.status not in ('pending', 'running'):
            return Response(
                {'detail': 'لا يمكن إلغاء دفعة في هذه الحالة'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        batch.status = 'cancelled'
        batch.save(update_fields=['status'])
        return Response({'detail': 'تم الإلغاء'})


def _start_batch_thread(batch_pk: int) -> None:
    """Fire-and-forget background thread for batch processing."""
    def _run():
        from apps.enrichment.suggestion_generator import bulk_generate_suggestions
        try:
            b = EnrichmentBatch.objects.get(pk=batch_pk, status='pending')
            bulk_generate_suggestions(b)
        except EnrichmentBatch.DoesNotExist:
            pass
        except Exception as exc:
            EnrichmentBatch.objects.filter(pk=batch_pk).update(
                status='failed', error_log=str(exc)[:2000],
            )

    t = threading.Thread(target=_run, daemon=True)
    t.start()


# ── Standalone API views ──────────────────────────────────────────────────────

def _ensure_enrichment_stubs(limit: int = 2_000) -> None:
    """
    Create ItemEnrichment stub rows for any active Item that doesn't have one.
    Safe to call on every list request — bulk_create with ignore_conflicts
    makes it a no-op once all items are initialised.
    """
    existing_ids = set(
        ItemEnrichment.objects.values_list('item_id', flat=True)
    )
    missing_items = (
        Item.objects
        .filter(is_active=True)
        .exclude(id__in=existing_ids)
        .values_list('id', flat=True)[:limit]
    )
    if missing_items:
        ItemEnrichment.objects.bulk_create(
            [ItemEnrichment(item_id=pk) for pk in missing_items],
            ignore_conflicts=True,
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def completeness_report(request):
    """GET /api/enrichment/report/ — aggregate completeness stats."""
    return Response(get_completeness_report())


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def item_enrichment_detail(request, item_pk):
    """
    GET /api/enrichment/items/{item_pk}/
    Returns full enrichment record + pending suggestions + item SOFTECH data.
    Creates ItemEnrichment if missing.
    """
    try:
        item = Item.objects.select_related('category').get(pk=item_pk)
    except Item.DoesNotExist:
        return Response({'detail': 'الصنف غير موجود'}, status=status.HTTP_404_NOT_FOUND)

    enrichment, _ = ItemEnrichment.objects.get_or_create(item=item)

    suggestions = (
        EnrichmentSuggestion.objects
        .filter(item=item, status='pending')
        .order_by('-confidence')
    )

    return Response({
        'enrichment':  ItemEnrichmentSerializer(enrichment).data,
        'suggestions': EnrichmentSuggestionSerializer(suggestions, many=True).data,
        'softech': {
            'id':               item.id,
            'softech_id':       item.softech_id,
            'name':             item.name,
            'name_scientific':  item.name_scientific,
            'category':         item.category.name_ar if item.category else '',
            'pack_price':       float(item.pack_price),
            'producer_name':    item.producer_name,
            'origin_name_ar':   item.origin_name_ar,
            'effect_name_ar':   item.effect_name_ar,
            'effect_name2_ar':  item.effect_name2_ar,
            'shape_name_ar':    item.shape_name_ar,
            'family_name_ar':   item.family_name_ar,
            'active_ingredients': item.active_ingredients,
            'pack_qty':         item.pack_qty,
            'unit_name':        item.unit_name,
            'requires_fridge':  item.requires_fridge,
        },
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_for_item(request, item_pk):
    """
    POST /api/enrichment/items/{item_pk}/generate/
    { overwrite: false }

    Full pipeline:
      1. Rule-based extraction from SOFTECH PostgreSQL fields
      2. OpenFDA web scraping
      3. Gemini AI extraction

    Runs synchronously (fast enough for single items).
    For bulk processing use the batch endpoint instead.
    """
    from .suggestion_generator import generate_suggestions_for_item

    try:
        item = Item.objects.select_related('category').get(pk=item_pk)
    except Item.DoesNotExist:
        return Response({'detail': 'الصنف غير موجود'}, status=status.HTTP_404_NOT_FOUND)

    overwrite  = str(request.data.get('overwrite', 'false')).lower() in ('true', '1')
    candidates = generate_suggestions_for_item(item, batch=None, overwrite_pending=overwrite)

    created = 0
    if candidates:
        objs = [EnrichmentSuggestion(**c) for c in candidates]
        result = EnrichmentSuggestion.objects.bulk_create(objs, ignore_conflicts=True)
        created = len(result)

    return Response({
        'generated': len(candidates),
        'created':   created,
        'fields':    [c['field_name'] for c in candidates],
        'sources':   list({c['source'] for c in candidates}),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def recompute_scores(request):
    """
    POST /api/enrichment/recompute-scores/
    Triggers a full completeness score recomputation in background.
    """
    def _run():
        from apps.enrichment.gap_detector import recompute_all_scores
        recompute_all_scores()

    threading.Thread(target=_run, daemon=True).start()
    return Response({'detail': 'جارٍ إعادة الحساب في الخلفية'})
