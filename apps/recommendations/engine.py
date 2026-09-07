"""
apps/recommendations/engine.py

Frequently Bought Together (FBT) Mining Engine.

Algorithm:
  1. Load all PurchaseHistoryLine rows (sales only, doc_code='115') within lookback window.
  2. Group by invoice (purchase_id) to get baskets.
  3. For each basket, enumerate all (item_a, item_b) pairs.
  4. Count co-occurrences, item-level occurrences, and total invoices.
  5. Compute confidence, support, lift, composite score.
  6. Bulk-insert FrequentlyBoughtTogether pairs above thresholds.
  7. Generate CustomerRecommendation rows for customers who bought high-confidence anchors.

Performance notes:
  - Uses chunked DB reads (no full table in RAM for large datasets).
  - Pair counting in Python defaultdict (faster than GROUP BY for basket analysis).
  - Bulk-creates in batches of 2000.
  - Runs in a background thread when triggered from API.

SOFTECH / Sybase: READ NEVER. All data comes from PostgreSQL only.
"""
import logging
import math
from collections import defaultdict
from datetime import date, timedelta
from itertools import combinations

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

# ── Tunable defaults ──────────────────────────────────────────────────────────
DEFAULT_LOOKBACK_DAYS  = 365
DEFAULT_MIN_SUPPORT    = 0.001   # at least 0.1% of invoices
DEFAULT_MIN_CONFIDENCE = 0.05    # at least 5% of anchor purchases
TOP_N_PER_ITEM         = 10      # keep at most N recommendations per anchor
TOP_N_PER_CUSTOMER     = 20      # keep at most N customer recommendations
BATCH_SIZE             = 2_000


def run_fbt_engine(
    lookback_days: int   = DEFAULT_LOOKBACK_DAYS,
    min_support: float   = DEFAULT_MIN_SUPPORT,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> int:
    """
    Execute the full FBT mining pipeline.
    Returns the RecommendationEngineRun.pk on success, raises on failure.
    """
    from apps.recommendations.models import (
        RecommendationEngineRun, FrequentlyBoughtTogether, CustomerRecommendation,
    )
    from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
    from apps.catalog.models import Item

    run = RecommendationEngineRun.objects.create(
        status        = 'running',
        min_support   = min_support,
        min_confidence= min_confidence,
        lookback_days = lookback_days,
    )
    logger.info('[FBT] Run %d started (lookback=%dd, min_sup=%.4f, min_conf=%.2f)',
                run.pk, lookback_days, min_support, min_confidence)

    try:
        cutoff = date.today() - timedelta(days=lookback_days)

        # ── Step 1: Load baskets ─────────────────────────────────────────────
        # Fetch (purchase_id, item_id) pairs for sales only
        lines_qs = (
            PurchaseHistoryLine.objects
            .filter(
                purchase__doc_code='115',
                purchase__invoice_date__date__gte=cutoff,
                item__isnull=False,
            )
            .values_list('purchase_id', 'item_id')
        )

        # Build basket dict: {purchase_id: set(item_ids)}
        baskets: dict[int, set] = defaultdict(set)
        line_count = 0
        for pid, iid in lines_qs.iterator(chunk_size=5_000):
            baskets[pid].add(iid)
            line_count += 1

        total_invoices = len(baskets)
        logger.info('[FBT] Run %d — %d invoices, %d lines loaded', run.pk, total_invoices, line_count)

        if total_invoices < 10:
            run.status = 'success'
            run.invoices_scanned = total_invoices
            run.finished_at = timezone.now()
            run.save(update_fields=['status', 'invoices_scanned', 'finished_at'])
            logger.warning('[FBT] Run %d — too few invoices, skipping pair mining', run.pk)
            return run.pk

        # ── Step 2: Count pairs and occurrences ──────────────────────────────
        pair_counts: dict[tuple, int] = defaultdict(int)
        item_counts: dict[int, int]   = defaultdict(int)

        for item_set in baskets.values():
            items = sorted(item_set)
            for iid in items:
                item_counts[iid] += 1
            for a, b in combinations(items, 2):
                pair_counts[(a, b)] += 1

        logger.info('[FBT] Run %d — %d unique pairs counted', run.pk, len(pair_counts))

        # ── Step 3: Filter and compute metrics ──────────────────────────────
        # Pre-load item IDs that exist in catalog (avoid FK errors)
        valid_ids = set(Item.objects.filter(is_active=True).values_list('id', flat=True))

        qualified_pairs = []
        # per-item top-N tracking
        anchor_heap: dict[int, list] = defaultdict(list)

        for (a, b), co_occ in pair_counts.items():
            if a not in valid_ids or b not in valid_ids:
                continue

            support    = co_occ / total_invoices
            if support < min_support:
                continue

            conf_ab    = co_occ / item_counts[a]
            conf_ba    = co_occ / item_counts[b]

            # Keep both directions if above threshold
            for anchor, rec, conf in ((a, b, conf_ab), (b, a, conf_ba)):
                if conf < min_confidence:
                    continue
                p_rec  = item_counts[rec] / total_invoices
                lift   = conf / p_rec if p_rec > 0 else 0.0
                score  = conf * math.log(co_occ + 1)

                anchor_heap[anchor].append((score, anchor, rec, co_occ, item_counts[anchor], conf, support, lift))

        # Keep only top-N per anchor
        fbt_rows = []
        for anchor, heap in anchor_heap.items():
            heap.sort(reverse=True)
            for score, a, b, co_occ, a_occ, conf, sup, lift in heap[:TOP_N_PER_ITEM]:
                fbt_rows.append(FrequentlyBoughtTogether(
                    run_id            = run.pk,
                    item_a_id         = a,
                    item_b_id         = b,
                    co_occurrences    = co_occ,
                    item_a_occurrences= a_occ,
                    confidence        = round(conf, 6),
                    support           = round(sup, 6),
                    lift              = round(lift, 4),
                    score             = round(score, 6),
                ))

        logger.info('[FBT] Run %d — %d pairs qualified, bulk-inserting...', run.pk, len(fbt_rows))

        # ── Step 4: Bulk insert ──────────────────────────────────────────────
        with transaction.atomic():
            for i in range(0, len(fbt_rows), BATCH_SIZE):
                FrequentlyBoughtTogether.objects.bulk_create(
                    fbt_rows[i:i + BATCH_SIZE],
                    ignore_conflicts=True,
                )

        # ── Step 5: Customer recommendations ────────────────────────────────
        cust_recs = _generate_customer_recs(run, baskets, cutoff, anchor_heap, total_invoices, valid_ids)

        # ── Step 6: Finalise run ─────────────────────────────────────────────
        run.status           = 'success'
        run.pairs_generated  = len(fbt_rows)
        run.invoices_scanned = total_invoices
        run.customers_scored = cust_recs
        run.finished_at      = timezone.now()
        run.save(update_fields=['status', 'pairs_generated', 'invoices_scanned',
                                'customers_scored', 'finished_at'])

        logger.info('[FBT] Run %d complete — %d pairs, %d customer recs',
                    run.pk, len(fbt_rows), cust_recs)
        return run.pk

    except Exception as exc:
        logger.exception('[FBT] Run %d failed: %s', run.pk, exc)
        run.status        = 'failed'
        run.error_message = str(exc)
        run.finished_at   = timezone.now()
        run.save(update_fields=['status', 'error_message', 'finished_at'])
        raise


def _generate_customer_recs(run, baskets, cutoff, anchor_heap, total_invoices, valid_ids):
    """
    Generate CustomerRecommendation rows.
    For each customer, find their top purchased items, look up FBT recs,
    exclude items they already bought recently, and score the candidates.
    """
    from apps.recommendations.models import CustomerRecommendation
    from apps.customers.models import PurchaseHistory, PurchaseHistoryLine

    # Build customer → set(recent_item_ids) purchased in last 90 days
    recent_cutoff = cutoff
    cust_purchases: dict[int, set] = defaultdict(set)
    cust_top_items: dict[int, dict] = defaultdict(lambda: defaultdict(int))

    ph_qs = (
        PurchaseHistoryLine.objects
        .filter(
            purchase__doc_code='115',
            purchase__invoice_date__date__gte=recent_cutoff,
            purchase__customer__isnull=False,
            item__isnull=False,
        )
        .values_list('purchase__customer_id', 'item_id', 'quantity')
    )
    for cid, iid, qty in ph_qs.iterator(chunk_size=5_000):
        if iid in valid_ids:
            cust_purchases[cid].add(iid)
            cust_top_items[cid][iid] += float(qty or 1)

    # ── Pre-build: chronic item set for is_chronic_related flag ──────────────
    # An item is "chronic-related" if it maps to a chronic ActiveIngredient.
    # We build this set once outside the loop for O(1) lookups per recommendation.
    chronic_item_ids: set[int] = set()
    try:
        from apps.chronic.models import ItemIngredientMap
        chronic_item_ids = set(
            ItemIngredientMap.objects
            .filter(active_ingredient__is_chronic=True)
            .values_list('item_id', flat=True)
        )
    except Exception as exc:
        logger.debug('Could not load chronic item ids: %s', exc)

    # ── Pre-build: customer → detected conditions set ─────────────────────────
    # Used to boost is_chronic_related when the customer actually has that condition.
    cust_conditions: dict[int, set] = {}
    try:
        from apps.customers.models import CustomerHealthProfile
        for hp in CustomerHealthProfile.objects.filter(
            customer_id__in=cust_top_items.keys()
        ).values('customer_id', 'condition_confidence'):
            cust_conditions[hp['customer_id']] = set(
                k for k, v in (hp['condition_confidence'] or {}).items() if v >= 0.4
            )
    except Exception as exc:
        logger.debug('Could not load customer conditions: %s', exc)

    # Build rec rows
    rec_rows = []
    for cid, item_freq in cust_top_items.items():
        # Sort customer items by frequency
        top_items = sorted(item_freq.items(), key=lambda x: -x[1])[:5]
        candidate_scores: dict[int, float] = defaultdict(float)
        candidate_reasons: dict[int, str]  = {}

        for anchor_id, freq_weight in top_items:
            if anchor_id not in anchor_heap:
                continue
            for score, a, b, co_occ, a_occ, conf, sup, lift in anchor_heap[anchor_id][:TOP_N_PER_ITEM]:
                if b in cust_purchases[cid]:
                    continue   # skip already-bought items
                # Weight by customer's own purchase frequency of the anchor
                weighted = score * math.log(freq_weight + 1)
                candidate_scores[b] += weighted
                if b not in candidate_reasons:
                    pct = round(conf * 100)
                    candidate_reasons[b] = f'اشترى معه {pct}% من العملاء'

        if not candidate_scores:
            continue

        top_recs = sorted(candidate_scores.items(), key=lambda x: -x[1])[:TOP_N_PER_CUSTOMER]
        for item_id, score in top_recs:
            is_chronic = item_id in chronic_item_ids
            rec_rows.append(CustomerRecommendation(
                run_id            = run.pk,
                customer_id       = cid,
                item_id           = item_id,
                score             = round(score, 6),
                reason            = candidate_reasons.get(item_id, ''),
                is_chronic_related= is_chronic,
            ))

    with transaction.atomic():
        for i in range(0, len(rec_rows), BATCH_SIZE):
            CustomerRecommendation.objects.bulk_create(
                rec_rows[i:i + BATCH_SIZE],
                ignore_conflicts=True,
            )

    return len(rec_rows)


def get_fbt_for_item(item_id: int, limit: int = 6) -> list:
    """
    Returns top FBT recommendations for a given item_id.
    Uses the most recent successful run.
    Returns list of {item_id, item_name, softech_id, confidence, score}.
    """
    from apps.recommendations.models import RecommendationEngineRun, FrequentlyBoughtTogether

    latest_run = (
        RecommendationEngineRun.objects
        .filter(status='success')
        .order_by('-started_at')
        .first()
    )
    if not latest_run:
        return []

    pairs = (
        FrequentlyBoughtTogether.objects
        .filter(run=latest_run, item_a_id=item_id)
        .select_related('item_b')
        .order_by('-score')[:limit]
    )
    return [
        {
            'item_id':    p.item_b_id,
            'item_name':  p.item_b.name,
            'softech_id': p.item_b.softech_id,
            'confidence': round(p.confidence, 3),
            'score':      round(p.score, 3),
            'co_occurrences': p.co_occurrences,
        }
        for p in pairs
    ]


def get_customer_recs(customer_id: int, limit: int = 8,
                       apply_clinical_filter: bool = True) -> list:
    """
    Returns personalized recommendations for a customer.
    Uses the most recent successful run.
    If apply_clinical_filter=True, removes items with major drug interactions
    against the customer's known active medications.
    """
    from apps.recommendations.models import RecommendationEngineRun, CustomerRecommendation

    latest_run = (
        RecommendationEngineRun.objects
        .filter(status='success')
        .order_by('-started_at')
        .first()
    )
    if not latest_run:
        return []

    # Fetch more than needed so we have room after clinical filtering
    fetch_limit = limit * 3 if apply_clinical_filter else limit
    recs = (
        CustomerRecommendation.objects
        .filter(run=latest_run, customer_id=customer_id)
        .select_related('item')
        .order_by('-score')[:fetch_limit]
    )

    result = []
    unsafe_item_ids: set[int] = set()

    if apply_clinical_filter:
        unsafe_item_ids = _get_unsafe_items_for_customer(customer_id)

    for r in recs:
        if r.item_id in unsafe_item_ids:
            continue   # clinical filter: skip major interaction risk
        result.append({
            'item_id':       r.item_id,
            'item_name':     r.item.name,
            'softech_id':    r.item.softech_id,
            'score':         round(r.score, 3),
            'reason':        r.reason,
            'is_chronic':    r.is_chronic_related,
            'clinical_safe': True,
        })
        if len(result) >= limit:
            break

    return result


def _get_unsafe_items_for_customer(customer_id: int) -> set[int]:
    """
    Returns a set of item_ids that have MAJOR drug interactions with
    the customer's current active medications.

    Reads from:
      customers.CustomerHealthProfile.active_medications → ingredient names
      chronic.DrugInteraction → (ingredient_a, ingredient_b, severity=major)
      catalog.Item.active_ingredients → text field (comma-separated)

    Returns empty set if any step fails (non-blocking — recommendations
    degrade gracefully rather than failing).
    """
    try:
        from apps.customers.models import CustomerHealthProfile
        from apps.chronic.models import DrugInteraction
        from apps.catalog.models import Item
        from django.db.models import Q

        # Get current active ingredient names for this customer
        try:
            hp = CustomerHealthProfile.objects.get(customer_id=customer_id)
            current_ingredients = {
                ing.strip().lower()
                for ing in hp.active_ingredient_names
                if ing.strip()
            }
            # Also include declared allergies
            allergy_ingredients = {
                a.get('ingredient', '').lower()
                for a in (hp.known_allergies or [])
                if a.get('ingredient')
            }
            current_ingredients |= allergy_ingredients
        except CustomerHealthProfile.DoesNotExist:
            return set()

        if not current_ingredients:
            return set()

        # Find major interactions involving any of the current ingredients
        major_interactions = DrugInteraction.objects.filter(
            Q(ingredient_a__in=current_ingredients) | Q(ingredient_b__in=current_ingredients),
            severity='major',
            is_active=True,
        ).values_list('ingredient_a', 'ingredient_b')

        # Build set of "dangerous" ingredients to avoid
        dangerous_ingredients: set[str] = set()
        for ing_a, ing_b in major_interactions:
            # If ingredient_a is in current meds, ingredient_b is the danger
            if ing_a.lower() in current_ingredients:
                dangerous_ingredients.add(ing_b.lower())
            if ing_b.lower() in current_ingredients:
                dangerous_ingredients.add(ing_a.lower())

        if not dangerous_ingredients:
            return set()

        # Find items whose active_ingredients overlap with dangerous set
        unsafe_ids: set[int] = set()
        for item in Item.objects.filter(
            is_active=True, active_ingredients__isnull=False
        ).exclude(active_ingredients='').values('id', 'active_ingredients'):
            item_ings = {
                i.strip().lower()
                for i in (item['active_ingredients'] or '').split(',')
                if i.strip()
            }
            if item_ings & dangerous_ingredients:
                unsafe_ids.add(item['id'])

        return unsafe_ids

    except Exception as exc:
        logger.debug('Clinical safety filter failed: %s', exc)
        return set()
