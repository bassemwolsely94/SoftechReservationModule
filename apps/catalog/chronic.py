"""
apps/catalog/chronic.py

Chronic medication detection helpers.
The ChronicMedication model lives in apps/catalog/models.py.

Detection strategy
------------------
SOFTECH's items table has no phcode / ATC-code column.
We detect chronic medications by matching keywords in the Arabic and English
therapeutic-category names (itemsclassif) that are already synced into
catalog.Category.name_ar / catalog.Category.name.

Public API:
  - CHRONIC_CATEGORY_KEYWORDS  dict of Arabic keyword → Arabic category label
  - is_chronic_item(item)      bool — is this Item chronic?
  - get_chronic_category(item)  str  — Arabic label or ''
  - tag_chronic_items()          int  — bulk-tag catalog; returns count created
  - create_chronic_follow_up_task(demand_record, item, due_hours)
"""


# ── Keyword → human-readable chronic-disease label ───────────────────────────
# Keys are substrings checked case-insensitively against the category's
# Arabic name (name_ar) or English name (name).  First match wins.
CHRONIC_CATEGORY_KEYWORDS: dict[str, str] = {
    # Arabic keywords
    'ضغط':            'ضغط الدم',
    'سكر':            'أدوية السكر',
    'كوليسترول':      'خافضات الكوليسترول',
    'الغدة الدرقية':  'الغدة الدرقية',
    'تخثر':           'مضادات التخثر والجلطة',
    'قلب':            'أمراض القلب والأوعية الدموية',
    'ربو':            'الربو وأمراض الرئة المزمنة',
    'الصرع':          'الصرع',
    'باركنسون':       'مرض باركنسون',
    'اكتئاب':         'الاكتئاب والقلق',
    'مناعة':          'مثبطات المناعة',
    'هشاشة':          'هشاشة العظام',
    # English keywords (SOFTECH often stores names in English too)
    'hypertens':      'ضغط الدم',
    'diabet':         'أدوية السكر',
    'cholesterol':    'خافضات الكوليسترول',
    'thyroid':        'الغدة الدرقية',
    'anticoagul':     'مضادات التخثر والجلطة',
    'cardiovasc':     'أمراض القلب والأوعية الدموية',
    'asthma':         'الربو وأمراض الرئة المزمنة',
    'epilep':         'الصرع',
    'parkinson':      'مرض باركنسون',
    'depress':        'الاكتئاب والقلق',
    'immunosuppress': 'مثبطات المناعة',
    'osteoporos':     'هشاشة العظام',
}


def _category_label_for(name_ar: str, name_en: str) -> str:
    """
    Return the chronic disease label if either name contains a known keyword.
    Returns '' if no match.
    """
    ar = (name_ar or '').lower()
    en = (name_en or '').lower()
    for keyword, label in CHRONIC_CATEGORY_KEYWORDS.items():
        kw = keyword.lower()
        if kw in ar or kw in en:
            return label
    return ''


def is_chronic_item(item) -> bool:
    """
    Return True if item belongs to a chronic medication category.
    Checks category name first; falls back to item scientific name keywords.
    """
    cat = getattr(item, 'category', None)
    if cat:
        if _category_label_for(
            getattr(cat, 'name_ar', ''),
            getattr(cat, 'name', ''),
        ):
            return True
    # Fallback: scan scientific name for well-known chronic-drug stems
    sci = (getattr(item, 'name_scientific', '') or '').lower()
    name = (getattr(item, 'name', '') or '').lower()
    STEM_FALLBACKS = ('metformin', 'insulin', 'atorvastatin', 'amlodipine',
                      'losartan', 'lisinopril', 'levothyroxine', 'warfarin',
                      'aspirin', 'clopidogrel', 'metoprolol', 'bisoprolol',
                      'salbutamol', 'fluticasone', 'montelukast')
    return any(s in sci or s in name for s in STEM_FALLBACKS)


def get_chronic_category(item) -> str:
    """Return Arabic category label, or '' if not chronic."""
    cat = getattr(item, 'category', None)
    if cat:
        label = _category_label_for(
            getattr(cat, 'name_ar', ''),
            getattr(cat, 'name', ''),
        )
        if label:
            return label
    # Fallback labels for stem matches
    sci = (getattr(item, 'name_scientific', '') or '').lower()
    name = (getattr(item, 'name', '') or '').lower()
    STEM_LABELS = {
        'metformin': 'أدوية السكر', 'insulin': 'أدوية السكر',
        'atorvastatin': 'خافضات الكوليسترول',
        'amlodipine': 'ضغط الدم', 'losartan': 'ضغط الدم',
        'lisinopril': 'ضغط الدم', 'metoprolol': 'ضغط الدم',
        'bisoprolol': 'ضغط الدم',
        'levothyroxine': 'الغدة الدرقية',
        'warfarin': 'مضادات التخثر والجلطة',
        'clopidogrel': 'مضادات التخثر والجلطة',
        'aspirin': 'أمراض القلب والأوعية الدموية',
        'salbutamol': 'الربو وأمراض الرئة المزمنة',
        'fluticasone': 'الربو وأمراض الرئة المزمنة',
        'montelukast': 'الربو وأمراض الرئة المزمنة',
    }
    for stem, label in STEM_LABELS.items():
        if stem in sci or stem in name:
            return label
    return ''


def tag_chronic_items() -> int:
    """
    Scan the Item catalog and upsert ChronicMedication rows.
    Safe to call repeatedly — existing records are not overwritten.
    Returns the count of newly created records.
    """
    from apps.catalog.models import Item, ChronicMedication
    created = 0
    qs = (
        Item.objects
        .filter(is_active=True)
        .select_related('category')
        .only('id', 'name', 'name_scientific', 'category__name', 'category__name_ar')
    )
    for item in qs.iterator(chunk_size=500):
        if is_chronic_item(item):
            category = get_chronic_category(item)
            _, was_created = ChronicMedication.objects.get_or_create(
                item=item,
                defaults={'category_label': category},
            )
            if was_created:
                created += 1
    return created


def create_chronic_follow_up_task(demand_record, item, due_hours: int = 72):
    """
    Create a FollowUpTask on a DemandRecord for a chronic medication.
    Idempotent — won't duplicate pending tasks for the same demand.

    Returns (task, created_bool).
    """
    from django.utils import timezone
    from datetime import timedelta
    from apps.demand.models import FollowUpTask

    due_date = timezone.now() + timedelta(hours=due_hours)
    task, created = FollowUpTask.objects.get_or_create(
        demand=demand_record,
        task_type='call',
        status='pending',
        defaults={
            'due_date': due_date,
            'assigned_to': demand_record.assigned_to,
            'note': (
                f'متابعة دواء مزمن: {item.name}'
                ' — يرجى التأكد من توافر الدواء وإبلاغ العميل بموعد الاستلام'
            ),
        },
    )
    return task, created
