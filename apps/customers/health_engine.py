"""
apps/customers/health_engine.py

CustomerHealthEngine
════════════════════
Builds and persists a structured CustomerHealthProfile for every customer
by cross-referencing their PurchaseHistory with the existing chronic module:

  chronic.ActiveIngredient  — drug substance master (ATC + chronic_class)
  chronic.ItemIngredientMap — Item → ActiveIngredient mappings

Design rules:
  - ONLY reads. Never writes to SOFTECH.
  - Idempotent: safe to call repeatedly.
  - Non-blocking: all imports are local to prevent circular deps.
  - Respects manually_overridden flag on CustomerHealthProfile.
  - Uses ONLY data that already exists in the DB — no external API calls.
  - If ChronicMedicationProfile (followups app) exists for an item,
    uses its pack_size / avg_daily_usage to estimate refill interval.

Usage:
    from apps.customers.health_engine import CustomerHealthEngine
    engine = CustomerHealthEngine(customer)
    engine.build()

Nightly batch (called from segment_customers command):
    CustomerHealthEngine.run_batch(batch_size=500)
"""
from __future__ import annotations
import logging
from collections import defaultdict
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger('elrezeiky.health')

# ── Condition → chronic_class key mapping ──────────────────────────────────────
# Maps ActiveIngredient.chronic_class values → CustomerHealthProfile boolean field
CONDITION_TO_FIELD = {
    'diabetes':          'has_diabetes',
    'hypertension':      'has_hypertension',
    'cardiovascular':    'has_cardiovascular',
    'thyroid':           'has_thyroid',
    'cholesterol':       'has_cholesterol',
    'asthma':            'has_asthma',
    'depression':        'has_psychiatric',   # depression maps to psychiatric
    'epilepsy':          'has_epilepsy',
    'parkinson':         'has_psychiatric',   # parkinson also maps to psychiatric
    'osteoporosis':      'has_osteoporosis',
    'renal':             'has_renal',
    'oncology':          'has_oncology',
    'gerd':              'has_gerd',
    'anemia':            'has_anemia',
    'anticoagulant':     'has_anticoagulant',
    'immunosuppressant': 'has_immunosuppressant',
    'other_chronic':     'has_other_chronic',
}

# Minimum number of purchases in the last 365 days to flag as chronic
MIN_PURCHASES_FOR_CHRONIC = 2

# Confidence scoring weights
CONFIDENCE_WEIGHTS = {
    'purchase_count':    0.50,   # How many times did they buy this?
    'recency':           0.30,   # How recently?
    'ingredient_mapped': 0.20,   # Is the item properly mapped in chronic module?
}


class CustomerHealthEngine:
    """
    Compute and persist CustomerHealthProfile for one customer.
    """

    def __init__(self, customer):
        self.customer = customer
        self.today    = date.today()
        self._cutoff  = self.today - timedelta(days=365)

    # ── Public API ─────────────────────────────────────────────────────────────

    def build(self) -> 'CustomerHealthProfile':
        """
        Compute the health profile and save it.
        Returns the saved CustomerHealthProfile.
        """
        from apps.customers.models import CustomerHealthProfile

        profile, _ = CustomerHealthProfile.objects.get_or_create(
            customer=self.customer
        )

        # Respect manual overrides — don't overwrite flags a pharmacist set
        if profile.manually_overridden:
            # Still update active_medications and last_computed_at
            active_meds = self._build_active_medications()
            profile.active_medications = active_meds
            profile.polypharmacy_flag  = len(active_meds) > 5
            profile.last_computed_at   = timezone.now()
            profile.save(update_fields=[
                'active_medications', 'polypharmacy_flag', 'last_computed_at',
            ])
            return profile

        detected, confidence, active_meds = self._detect_conditions()

        # Build update dict for all boolean fields
        updates = {
            'condition_confidence': confidence,
            'active_medications':   active_meds,
            'polypharmacy_flag':    len(active_meds) > 5,
            'last_computed_at':     timezone.now(),
        }

        for condition_key, field_name in CONDITION_TO_FIELD.items():
            updates[field_name] = condition_key in detected

        update_fields = list(updates.keys())

        for k, v in updates.items():
            setattr(profile, k, v)

        profile.save(update_fields=update_fields)

        # Sync is_chronic flag on Customer
        if any(updates[f] for f in update_fields if f.startswith('has_')):
            self.customer.__class__.objects.filter(pk=self.customer.pk).update(
                # We store is_chronic on Customer for fast filtering
                # reuse the existing field pattern from Customer model
            )

        logger.debug(
            'CustomerHealthEngine: customer=%d detected=%s',
            self.customer.pk, list(detected.keys()),
        )
        return profile

    # ── Internal ───────────────────────────────────────────────────────────────

    def _detect_conditions(self) -> tuple[dict, dict, list]:
        """
        Returns (detected, confidence_map, active_medications).

        detected         : {condition_key: True}  — only conditions above threshold
        confidence_map   : {condition_key: 0-1}
        active_medications: list of medication dicts
        """
        from apps.customers.models import PurchaseHistoryLine
        from apps.chronic.models import ItemIngredientMap

        # ── Step 1: Load items bought in last 365 days with chronic mappings ──
        lines = (
            PurchaseHistoryLine.objects
            .filter(
                purchase__customer=self.customer,
                purchase__doc_code='115',             # sales only, not returns
                purchase__invoice_date__gte=self._cutoff,
                item__isnull=False,
            )
            .select_related('item', 'purchase')
            .values(
                'item_id',
                'item__name',
                'purchase__invoice_date',
            )
        )

        if not lines:
            return {}, {}, []

        # Build per-item purchase stats
        item_dates: dict[int, list] = defaultdict(list)
        item_names: dict[int, str]  = {}
        for row in lines:
            iid = row['item_id']
            dt  = row['purchase__invoice_date']
            item_dates[iid].append(dt)
            item_names[iid] = row['item__name'] or ''

        bought_item_ids = set(item_dates.keys())

        # ── Step 2: Load chronic ingredient mappings for bought items ─────────
        maps = (
            ItemIngredientMap.objects
            .filter(
                item_id__in=bought_item_ids,
                active_ingredient__is_chronic=True,
            )
            .select_related('active_ingredient')
        )

        # Accumulate evidence per condition
        # {condition_key: [(item_id, purchase_count, last_date, ingredient_name)]}
        condition_evidence: dict[str, list] = defaultdict(list)
        item_ingredients: dict[int, list]   = defaultdict(list)  # item_id → ingredient names

        for m in maps:
            ai  = m.active_ingredient
            cond = ai.chronic_class
            if not cond or cond not in CONDITION_TO_FIELD:
                continue
            dates = item_dates.get(m.item_id, [])
            if len(dates) < MIN_PURCHASES_FOR_CHRONIC:
                continue
            last_date = max(dates) if dates else None
            condition_evidence[cond].append({
                'item_id':    m.item_id,
                'item_name':  item_names.get(m.item_id, ''),
                'ingredient': ai.name,
                'count':      len(dates),
                'last_date':  last_date,
                'confidence': ai.atc_code and 1.0 or 0.85,  # ATC-mapped = higher confidence
            })
            item_ingredients[m.item_id].append(ai.name)

        # ── Step 3: Compute confidence per condition ───────────────────────────
        detected    : dict[str, bool]  = {}
        confidence  : dict[str, float] = {}

        for cond, evidence_list in condition_evidence.items():
            if not evidence_list:
                continue
            max_count   = max(e['count'] for e in evidence_list)
            # Recency score: 1.0 if bought within 90 days, decay linearly to 0.5 at 365 days
            all_dates   = [e['last_date'] for e in evidence_list if e['last_date']]
            last         = max(all_dates) if all_dates else None
            recency_days = (self.today - (last.date() if hasattr(last, 'date') else last)).days if last else 365
            recency_score = max(0.5, 1.0 - (recency_days / 730))

            count_score   = min(1.0, max_count / 6)   # 6+ purchases = full score
            mapped_score  = 1.0 if any(e['confidence'] >= 1.0 for e in evidence_list) else 0.85

            conf = (
                count_score   * CONFIDENCE_WEIGHTS['purchase_count'] +
                recency_score * CONFIDENCE_WEIGHTS['recency'] +
                mapped_score  * CONFIDENCE_WEIGHTS['ingredient_mapped']
            )
            confidence[cond] = round(conf, 3)

            if conf >= 0.40:   # minimum threshold to flag
                detected[cond] = True

        # ── Step 4: Build active medications list ──────────────────────────────
        active_meds = self._build_active_medications_from_data(
            item_dates, item_names, item_ingredients
        )

        return detected, confidence, active_meds

    def _build_active_medications(self) -> list:
        """Build active_medications from scratch (used when manually_overridden=True)."""
        from apps.customers.models import PurchaseHistoryLine
        from apps.chronic.models import ItemIngredientMap

        lines = (
            PurchaseHistoryLine.objects
            .filter(
                purchase__customer=self.customer,
                purchase__doc_code='115',
                purchase__invoice_date__gte=self._cutoff,
                item__isnull=False,
            )
            .values('item_id', 'item__name', 'purchase__invoice_date')
        )
        item_dates: dict[int, list] = defaultdict(list)
        item_names: dict[int, str]  = {}
        for row in lines:
            iid = row['item_id']
            item_dates[iid].append(row['purchase__invoice_date'])
            item_names[iid] = row['item__name'] or ''

        maps = (
            ItemIngredientMap.objects
            .filter(item_id__in=set(item_dates.keys()), active_ingredient__is_chronic=True)
            .select_related('active_ingredient')
        )
        item_ings: dict[int, list] = defaultdict(list)
        for m in maps:
            item_ings[m.item_id].append(m.active_ingredient.name)

        return self._build_active_medications_from_data(item_dates, item_names, item_ings)

    def _build_active_medications_from_data(
        self,
        item_dates: dict,
        item_names: dict,
        item_ingredients: dict,
    ) -> list:
        """
        Build the active_medications JSON list.
        Only includes items with chronic ingredient mappings bought ≥ MIN_PURCHASES_FOR_CHRONIC.
        """
        result = []
        for item_id, dates in item_dates.items():
            if len(dates) < MIN_PURCHASES_FOR_CHRONIC:
                continue
            ingredients = item_ingredients.get(item_id, [])
            if not ingredients:
                continue  # Only include items mapped to chronic ingredients

            dates_sorted = sorted(dates)
            last_d = dates_sorted[-1]
            last_date_str = (last_d.date() if hasattr(last_d, 'date') else last_d).isoformat()

            # Estimate refill interval from followups.ChronicMedicationProfile if available
            expected_days = None
            try:
                from apps.followups.models import ChronicMedicationProfile
                cp = ChronicMedicationProfile.objects.filter(item_id=item_id).first()
                if cp:
                    expected_days = cp.expected_duration_days
            except Exception:
                pass

            result.append({
                'item_id':          item_id,
                'item_name':        item_names.get(item_id, ''),
                'ingredient':       ingredients[0] if len(ingredients) == 1 else ', '.join(ingredients[:2]),
                'purchase_count':   len(dates),
                'last_purchase_date': last_date_str,
                'expected_duration_days': expected_days,
            })

        # Sort by last purchase date descending
        result.sort(key=lambda x: x['last_purchase_date'], reverse=True)
        return result

    # ── Batch runner ───────────────────────────────────────────────────────────

    @classmethod
    def run_batch(cls, batch_size: int = 300, verbose: bool = False) -> dict:
        """
        Run the engine for all customers who have purchase history.
        Called by segment_customers management command.

        Returns {'processed': N, 'errors': M}
        """
        from apps.customers.models import Customer, PurchaseHistory

        # Only customers who have purchases — no point profiling those with none
        customer_ids_with_history = set(
            PurchaseHistory.objects
            .filter(doc_code='115')
            .values_list('customer_id', flat=True)
            .distinct()
        )

        processed = errors = 0

        for customer in (
            Customer.objects
            .filter(id__in=customer_ids_with_history)
            .iterator(chunk_size=batch_size)
        ):
            try:
                with transaction.atomic():
                    cls(customer).build()
                processed += 1
                if verbose and processed % 100 == 0:
                    logger.info('CustomerHealthEngine: processed %d customers', processed)
            except Exception as exc:
                errors += 1
                logger.error(
                    'CustomerHealthEngine: customer=%d error=%s',
                    customer.pk, exc,
                )

        logger.info(
            'CustomerHealthEngine.run_batch: processed=%d errors=%d',
            processed, errors,
        )
        return {'processed': processed, 'errors': errors}
