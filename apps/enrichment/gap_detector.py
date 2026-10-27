"""
apps/enrichment/gap_detector.py

CatalogCompletenessScore engine.
Scans items, computes per-item completeness, returns aggregate stats.
"""
from __future__ import annotations

from apps.catalog.models import Item
from .models import ItemEnrichment, ENRICHABLE_FIELDS


def compute_item_score(item: Item) -> float:
    """
    Recompute and persist completeness score for one item.
    Creates ItemEnrichment record if not yet present.
    Returns the score (0-100).
    """
    enrichment, _ = ItemEnrichment.objects.get_or_create(item=item)
    enrichment.compute_score()
    enrichment.save(update_fields=['completeness_score'])
    return enrichment.completeness_score


def recompute_all_scores(chunk_size: int = 500) -> dict:
    """
    Recompute completeness scores for all active items.
    Creates missing ItemEnrichment rows.
    Returns a summary dict.
    """
    qs = Item.objects.filter(is_active=True)
    scores: list[float] = []

    for item in qs.iterator(chunk_size=chunk_size):
        scores.append(compute_item_score(item))

    total = len(scores)
    avg   = sum(scores) / total if total else 0.0
    return {
        'total': total,
        'average_score': round(avg, 1),
        'complete_80pct_plus': sum(1 for s in scores if s >= 80),
        'partial_20_to_80':    sum(1 for s in scores if 20 <= s < 80),
        'empty_under_20':      sum(1 for s in scores if s < 20),
    }


def get_completeness_report() -> dict:
    """
    Aggregate completeness stats from the DB (fast — no per-item iteration).
    """
    from django.db.models import Avg, Count, Q
    from apps.enrichment.models import EnrichmentSuggestion

    stats = ItemEnrichment.objects.aggregate(
        avg_score     = Avg('completeness_score'),
        total_enriched= Count('id'),
        complete      = Count('id', filter=Q(completeness_score__gte=80)),
        partial       = Count('id', filter=Q(completeness_score__gte=20, completeness_score__lt=80)),
        empty         = Count('id', filter=Q(completeness_score__lt=20)),
        published     = Count('id', filter=Q(is_published=True)),
    )

    total_items  = Item.objects.filter(is_active=True).count()
    not_enriched = total_items - (stats['total_enriched'] or 0)

    sug_counts = (
        EnrichmentSuggestion.objects
        .values('status')
        .annotate(c=Count('id'))
    )
    sug_map = {row['status']: row['c'] for row in sug_counts}

    # Top 10 items with most pending suggestions (most work needed)
    from apps.enrichment.models import EnrichmentSuggestion as ES
    top_pending = (
        ES.objects
        .filter(status='pending')
        .values('item__id', 'item__name', 'item__softech_id')
        .annotate(pending_count=Count('id'))
        .order_by('-pending_count')[:10]
    )

    return {
        'total_items':         total_items,
        'total_enriched':      stats['total_enriched'] or 0,
        'not_enriched':        not_enriched,
        'avg_score':           round(stats['avg_score'] or 0, 1),
        'complete':            stats['complete'] or 0,
        'partial':             stats['partial'] or 0,
        'empty':               stats['empty'] or 0,
        'published':           stats['published'] or 0,
        'suggestions_pending': sug_map.get('pending', 0),
        'suggestions_approved':sug_map.get('approved', 0),
        'suggestions_rejected':sug_map.get('rejected', 0),
        'suggestions_edited':  sug_map.get('edited', 0),
        'top_pending_items': [
            {
                'item_id':    r['item__id'],
                'item_name':  r['item__name'],
                'item_code':  r['item__softech_id'],
                'pending':    r['pending_count'],
            }
            for r in top_pending
        ],
    }
