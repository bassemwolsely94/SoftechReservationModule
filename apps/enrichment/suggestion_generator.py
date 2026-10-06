"""
apps/enrichment/suggestion_generator.py

Generates EnrichmentSuggestion rows from existing SOFTECH data.

Strategy:
  - Phase 1: Rule-based extraction from already-synced SOFTECH fields
  - Phase 2: Cross-reference with apps.chronic (ATC codes, concentrations)
  - Phase 3 hook: _call_ai_extractor() — wire up an LLM API here when ready
  - Never queries SOFTECH (Sybase) directly — uses local PostgreSQL only
"""
from __future__ import annotations
import re
from typing import Optional

from apps.catalog.models import Item
from .models import (
    ItemEnrichment, EnrichmentSuggestion, EnrichmentBatch,
    ENRICHABLE_FIELDS, FIELD_LABELS_AR,
)

# ── Confidence tiers ──────────────────────────────────────────────────────────
CONF_HIGH   = 0.92   # Direct 1-to-1 SOFTECH field mapping
CONF_MEDIUM = 0.72   # Inferred from related SOFTECH fields
CONF_LOW    = 0.45   # Heuristic / pattern extraction

# ── Patterns ──────────────────────────────────────────────────────────────────
_STRENGTH_RE = re.compile(r'(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml|iu|unit|%)', re.IGNORECASE)
_VOLUME_RE   = re.compile(r'(\d+(?:\.\d+)?)\s*(ml|l|fl\.?oz)', re.IGNORECASE)


def _extract_strength(name: str) -> str:
    m = _STRENGTH_RE.search(name or '')
    if m:
        return f'{m.group(1)}{m.group(2).lower()}'
    return ''


def _extract_volume(name: str) -> str:
    m = _VOLUME_RE.search(name or '')
    if m:
        return f'{m.group(1)}{m.group(2).lower()}'
    return ''


def _extract_brand(name: str) -> str:
    """First word of product name is usually the brand."""
    words = (name or '').split()
    return words[0] if len(words) >= 1 else ''


def _call_ai_extractor(item: Item) -> dict[str, str]:
    """
    Two-stage AI enrichment:
      1. Scrape OpenFDA for English label data (free public API)
      2. Call Gemini 1.5 Flash with all available context

    Falls back to {} gracefully if GEMINI_API_KEY is not configured
    or any network call fails.
    """
    try:
        from .ai_extractor import enrich_item_with_ai
        return enrich_item_with_ai(item)
    except Exception as exc:
        import logging
        logging.getLogger('elrezeiky').warning(
            'AI extractor failed for item %s: %s', item.pk, exc
        )
        return {}


# ── Main entry point ──────────────────────────────────────────────────────────

def generate_suggestions_for_item(
    item: Item,
    batch: Optional[EnrichmentBatch] = None,
    overwrite_pending: bool = False,
) -> list[dict]:
    """
    Generate suggestion dicts for one item using SOFTECH data + rules.
    Returns list of dicts (not yet persisted to DB).

    overwrite_pending=False  → skip fields that already have a pending/approved suggestion
    overwrite_pending=True   → generate for ALL fields regardless
    """
    enrichment, _ = ItemEnrichment.objects.get_or_create(item=item)

    # Collect suggestions by field_name → keep highest-confidence one
    seen: dict[str, dict] = {}

    def add(field: str, value: str, source: str, confidence: float):
        if not value or not value.strip():
            return
        value = value.strip()
        if field not in seen or confidence > seen[field]['confidence']:
            seen[field] = {
                'item':            item,
                'enrichment':      enrichment,
                'batch':           batch,
                'field_name':      field,
                'suggested_value': value,
                'current_value':   getattr(enrichment, field, '') or '',
                'source':          source,
                'confidence':      confidence,
                'status':          'pending',
            }

    # ── Brand name ────────────────────────────────────────────────────────────
    brand = _extract_brand(item.name)
    if brand and len(brand) >= 2:
        add('brand_name', brand, 'rule_engine', CONF_MEDIUM)

    # ── Bilingual name ────────────────────────────────────────────────────────
    # SOFTECH has no dedicated Arabic item name — build hint from effect + shape
    if item.effect_name_ar and item.shape_name_ar:
        add('name_ar', f'{brand or item.name} — {item.effect_name_ar} ({item.shape_name_ar})',
            'rule_engine', CONF_LOW)
    elif item.effect_name_ar:
        add('name_ar', f'{brand or item.name} — {item.effect_name_ar}', 'rule_engine', CONF_LOW)

    # ── Manufacturer ──────────────────────────────────────────────────────────
    if item.producer_name:
        add('manufacturer_en', item.producer_name, 'softech', CONF_HIGH)
        add('manufacturer_ar', item.producer_name, 'softech', CONF_MEDIUM)

    # ── Country of origin ─────────────────────────────────────────────────────
    if item.origin_name_ar:
        add('country_ar', item.origin_name_ar, 'softech', CONF_HIGH)
    if item.origin_name:
        add('country_en', item.origin_name,    'softech', CONF_HIGH)

    # ── Dosage form ───────────────────────────────────────────────────────────
    if item.shape_name_ar:
        add('dosage_form_ar', item.shape_name_ar, 'softech', CONF_HIGH)
    if item.shape_name:
        add('dosage_form_en', item.shape_name,    'softech', CONF_HIGH)

    # ── Strength ──────────────────────────────────────────────────────────────
    strength = _extract_strength(item.name)
    if strength:
        add('strength', strength, 'rule_engine', CONF_MEDIUM)

    # ── Volume ────────────────────────────────────────────────────────────────
    volume = _extract_volume(item.name)
    if volume:
        add('volume', volume, 'rule_engine', CONF_MEDIUM)

    # ── Pack size ─────────────────────────────────────────────────────────────
    if item.pack_qty and item.pack_qty > 0:
        unit = item.unit_name or 'وحدة'
        add('pack_size_label', f'{item.pack_qty} {unit}', 'softech', CONF_HIGH)

    # ── Therapeutic indication ────────────────────────────────────────────────
    ind_ar = ' — '.join(filter(None, [item.effect_name_ar, item.effect_name2_ar]))
    if ind_ar:
        add('indication_ar', ind_ar, 'softech', CONF_HIGH)

    ind_en = ' / '.join(filter(None, [item.effect_name, item.effect_name2]))
    if ind_en:
        add('indication_en', ind_en, 'softech', CONF_HIGH)

    # ── Storage ───────────────────────────────────────────────────────────────
    if item.requires_fridge:
        add('storage_condition', 'يحفظ في الثلاجة (2-8°م)', 'softech', CONF_HIGH)
    else:
        add('storage_condition', 'يحفظ بعيداً عن الحرارة والرطوبة (أقل من 30°م)',
            'rule_engine', CONF_LOW)

    # ── Rx/OTC (from medicine_type_name) ──────────────────────────────────────
    if item.medicine_type_name:
        mt = item.medicine_type_name.lower()
        if any(k in mt for k in ('otc', 'consumer', 'بدون وصفة', 'general')):
            add('rx_otc', 'otc', 'softech', CONF_HIGH)
        elif any(k in mt for k in ('rx', 'prescription', 'وصفة', 'ethical')):
            add('rx_otc', 'rx', 'softech', CONF_HIGH)

    # ── Medical keywords ──────────────────────────────────────────────────────
    kw_ar = list(dict.fromkeys(filter(None, [
        item.effect_name_ar, item.effect_name2_ar,
        item.family_name_ar,
        *(item.active_ingredients.split(',') if item.active_ingredients else []),
    ])))
    kw_ar = [k.strip() for k in kw_ar if k.strip()]
    if kw_ar:
        add('medical_keywords_ar', ', '.join(kw_ar), 'softech', CONF_MEDIUM)

    kw_en = list(dict.fromkeys(filter(None, [
        item.effect_name, item.effect_name2, item.family_name,
    ])))
    kw_en = [k.strip() for k in kw_en if k.strip()]
    if kw_en:
        add('medical_keywords_en', ', '.join(kw_en), 'softech', CONF_MEDIUM)

    # ── SEO description (auto-generated from available fields) ────────────────
    seo_parts = [p for p in [item.name, strength, item.effect_name_ar, item.shape_name_ar] if p]
    if seo_parts:
        add('seo_desc_ar', ' '.join(seo_parts), 'rule_engine', CONF_LOW)

    # ── Cross-reference chronic module for ATC codes + concentrations ─────────
    try:
        from apps.chronic.models import ItemIngredientMap
        for m in (
            ItemIngredientMap.objects
            .filter(item=item)
            .select_related('active_ingredient')
            .order_by('-is_primary')
        ):
            ai = m.active_ingredient
            if ai.atc_code:
                add('atc_code', ai.atc_code, 'chronic_module', CONF_HIGH)
            if m.concentration and m.is_primary:
                add('strength', m.concentration, 'chronic_module', CONF_HIGH)
    except Exception:
        pass

    # ── AI extractor hook (no-op until API is wired up) ───────────────────────
    for field, value in _call_ai_extractor(item).items():
        if field in FIELD_LABELS_AR:
            add(field, value, 'ai_extract', 0.80)

    # ── Filter out fields already covered by pending/approved suggestions ─────
    if not overwrite_pending:
        existing = set(
            EnrichmentSuggestion.objects
            .filter(item=item, status__in=('pending', 'approved'))
            .values_list('field_name', flat=True)
        )
        seen = {k: v for k, v in seen.items() if k not in existing}

    # ── Also skip fields already populated in the enrichment record ───────────
    seen = {
        k: v for k, v in seen.items()
        if not (v['current_value'] and v['current_value'].strip())
    }

    return list(seen.values())


# ── Batch processor ───────────────────────────────────────────────────────────

def bulk_generate_suggestions(batch: EnrichmentBatch, chunk_size: int = 100) -> None:
    """
    Process all items in a batch, persist suggestions, update batch counters.
    Designed to run in a background thread.
    """
    from django.utils import timezone
    from apps.catalog.models import Item

    batch.status     = 'running'
    batch.started_at = timezone.now()
    batch.save(update_fields=['status', 'started_at'])

    # Build queryset from scope
    qs = (
        Item.objects
        .filter(is_active=True, is_stockable=True)
        .select_related('category')
    )
    scope  = batch.scope_type
    params = batch.scope_params or {}

    if scope == 'category' and params.get('category_id'):
        qs = qs.filter(category_id=params['category_id'])
    elif scope == 'supplier' and params.get('supplier_code'):
        qs = qs.filter(supplier_code=params['supplier_code'])
    elif scope == 'selected' and params.get('item_ids'):
        qs = qs.filter(id__in=params['item_ids'])
    elif scope == 'low_score':
        threshold = float(params.get('threshold', 30.0))
        low_ids = set(
            ItemEnrichment.objects
            .filter(completeness_score__lt=threshold)
            .values_list('item_id', flat=True)
        )
        no_enrichment_ids = set(
            qs.exclude(id__in=ItemEnrichment.objects.values_list('item_id', flat=True))
            .values_list('id', flat=True)
        )
        qs = qs.filter(id__in=low_ids | no_enrichment_ids)

    batch.total_items = qs.count()
    batch.save(update_fields=['total_items'])

    total_suggestions = 0
    auto_published    = 0
    errors            = 0
    items_since_check = 0

    for item in qs.iterator(chunk_size=chunk_size):
        # Check for cancellation every 5 items (DB-friendly cadence)
        items_since_check += 1
        if items_since_check >= 5:
            items_since_check = 0
            batch.refresh_from_db(fields=['status'])
            if batch.status == 'cancelled':
                break

        try:
            candidates = generate_suggestions_for_item(
                item, batch=batch, overwrite_pending=False,
            )
            if candidates:
                obj_list = []
                for c in candidates:
                    if c['confidence'] >= batch.auto_publish_threshold:
                        c['status'] = 'approved'
                        auto_published += 1
                    obj_list.append(EnrichmentSuggestion(**c))

                EnrichmentSuggestion.objects.bulk_create(obj_list, ignore_conflicts=True)
                total_suggestions += len(obj_list)

                # Auto-apply approved suggestions to the enrichment record
                enrichment = obj_list[0].enrichment if obj_list else None
                if enrichment:
                    changed = False
                    for s in obj_list:
                        if s.status == 'approved' and not getattr(enrichment, s.field_name, ''):
                            setattr(enrichment, s.field_name, s.suggested_value)
                            s.approved_value = s.suggested_value
                            changed = True
                    if changed:
                        enrichment.compute_score()
                        enrichment.last_enriched_at = timezone.now()
                        enrichment.save()

        except Exception as exc:
            errors += 1
            batch.error_log = (batch.error_log or '') + f'\nItem #{item.pk}: {exc}'

        batch.processed_items += 1
        if batch.processed_items % 50 == 0:
            batch.save(update_fields=['processed_items', 'error_log'])

    batch.status              = 'success' if errors == 0 else 'failed'
    batch.suggestions_generated = total_suggestions
    batch.auto_published      = auto_published
    batch.error_count         = errors
    batch.finished_at         = timezone.now()
    batch.save()
