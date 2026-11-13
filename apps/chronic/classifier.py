"""
apps.chronic.classifier
========================
Utilities for classifying catalog items as chronic medications.

NOTE: stktransm.phcode = customer personcode (e.g. 04HD1006 = branch-HD-serial).
      It is NOT a pharmaceutical/ATC code. Items are classified directly per-item
      by linking them to an ActiveIngredient via ItemIngredientMap.

Main entry points
-----------------
preload_from_chronic_medication()   — auto-create ActiveIngredient + ItemIngredientMap
                                      records for every catalog.ChronicMedication entry
                                      that is not yet linked to an ingredient.
                                      Safe to re-run (idempotent).

get_item_classification_stats()     — returns a dict of item_id → stats from
                                      PurchaseHistoryLine for a set of item IDs.
"""

from django.db.models import Count, Sum, Max, Q

from apps.catalog.models import Item
from .models import (
    ActiveIngredient,
    IngredientTag,
    ItemIngredientMap,
    MedicationTag,
)


# ─────────────────────────────────────────────────────────────────────────────
# Customer type detection
# walkin / home_delivery / b2b / unclassified, from the channel GROUP (channel
# registry, apps/forecasting/channels.py) of the customer's most recent sale
# (PurchaseHistory.sales_channel = stktransm.ptclassifcode). Customer.softech_ptclassifcode
# is blank for almost every customer, so it is not used.
# ─────────────────────────────────────────────────────────────────────────────

_GROUP_TO_CUSTOMER_TYPE = {
    'cash': 'walkin',
    'delivery': 'home_delivery',
    'contract': 'b2b', 'employee': 'b2b', 'insurance': 'b2b',
    'compensation': 'b2b', 'donation': 'b2b', 'card': 'b2b',
}


def customer_type(customer, latest_channel: str | None) -> str:
    """Returns 'walkin', 'home_delivery', 'b2b' or 'unclassified'.

    `latest_channel` = sales_channel of the customer's most recent sale (None = no sale).
    Any other group (permanent, vip, settlement, other, unknown code) or no sale →
    'unclassified'. `customer` is kept for callers / future rules; it is not read."""
    from apps.forecasting.channels import channel
    if not (latest_channel or '').strip():
        return 'unclassified'
    return _GROUP_TO_CUSTOMER_TYPE.get(channel(latest_channel).group, 'unclassified')


# ─────────────────────────────────────────────────────────────────────────────
# ATC / keyword helpers for auto-naming ingredients
# ─────────────────────────────────────────────────────────────────────────────

CHRONIC_CLASS_KEYWORDS = {
    'ضغط':           'hypertension',
    'سكر':           'diabetes',
    'كوليسترول':     'cholesterol',
    'الغدة':         'thyroid',
    'قلب':           'cardiovascular',
    'ربو':           'asthma',
    'تخثر':          'anticoagulant',
    'الصرع':         'epilepsy',
    'باركنسون':      'parkinson',
    'اكتئاب':        'depression',
    'مناعة':         'immunosuppressant',
    'هشاشة':         'osteoporosis',
    'diabet':        'diabetes',
    'hypertens':     'hypertension',
    'cardiovasc':    'cardiovascular',
    'cholesterol':   'cholesterol',
    'thyroid':       'thyroid',
    'asthma':        'asthma',
    'anticoagul':    'anticoagulant',
    'epilep':        'epilepsy',
    'parkinson':     'parkinson',
    'depress':       'depression',
    'immunosuppress':'immunosuppressant',
    'osteoporos':    'osteoporosis',
}


def chronic_class_from_keywords(text: str) -> str:
    """Best-effort chronic_class from category name / label text."""
    if not text:
        return ''
    t = text.lower()
    for kw, cls in CHRONIC_CLASS_KEYWORDS.items():
        if kw in t:
            return cls
    return ''


# ─────────────────────────────────────────────────────────────────────────────
# Pre-load from catalog.ChronicMedication
# ─────────────────────────────────────────────────────────────────────────────

def preload_from_chronic_medication(created_by=None) -> dict:
    """
    For every catalog.ChronicMedication entry whose item is NOT yet linked
    to any ActiveIngredient, create a matching ActiveIngredient and
    ItemIngredientMap so the Chronic Classifier module sees them immediately.

    Groups items by category_label so items in the same category share
    one ActiveIngredient (avoids duplicates).

    Returns:
        {
          'ingredients_created': int,
          'maps_created':        int,
          'already_mapped':      int,
        }
    """
    from apps.catalog.models import ChronicMedication

    # Items already classified in the new system
    already_mapped_ids = set(
        ItemIngredientMap.objects.values_list('item_id', flat=True)
    )

    # ChronicMedication records not yet in the new system
    new_entries = (
        ChronicMedication.objects
        .filter(is_active=True)
        .exclude(item_id__in=already_mapped_ids)
        .select_related('item__category')
    )

    # Group by category_label → one ActiveIngredient per distinct label
    label_to_ingredient = {}
    ingredients_created = 0
    maps_created        = 0
    already_mapped      = already_mapped_ids & set(
        ChronicMedication.objects.filter(is_active=True).values_list('item_id', flat=True)
    )

    for cm in new_entries:
        label = (cm.category_label or 'دواء مزمن').strip()

        # Get or create an ActiveIngredient for this label
        if label not in label_to_ingredient:
            # Try to find an existing ingredient with this name first
            ing = ActiveIngredient.objects.filter(
                Q(name__iexact=label) | Q(name_ar__iexact=label)
            ).first()

            if not ing:
                chronic_class = chronic_class_from_keywords(label)
                ing = ActiveIngredient.objects.create(
                    name=label,
                    name_ar=label,
                    is_chronic=True,
                    chronic_class=chronic_class,
                    notes='أُنشئ تلقائياً من بيانات catalog.ChronicMedication',
                    created_by=created_by,
                )
                ingredients_created += 1

            label_to_ingredient[label] = ing

        ingredient = label_to_ingredient[label]

        # Create ItemIngredientMap
        _, was_created = ItemIngredientMap.objects.get_or_create(
            item=cm.item,
            active_ingredient=ingredient,
            defaults={
                'is_primary':  True,
                'mapped_by':   created_by,
            },
        )
        if was_created:
            maps_created += 1

    return {
        'ingredients_created': ingredients_created,
        'maps_created':        maps_created,
        'already_mapped':      len(already_mapped),
    }
