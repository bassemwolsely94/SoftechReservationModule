"""
apps/catalog/chronic.py

Chronic medication detection helpers.
The ChronicMedication model lives in apps/catalog/models.py.

Public API:
  - CHRONIC_PHCODE_PREFIXES   dict of prefix → Arabic category label
  - is_chronic_item(item)     bool — is this Item chronic?
  - get_chronic_category(item) str  — Arabic label or ''
  - tag_chronic_items()        int  — bulk-tag catalog; returns count created
  - create_chronic_follow_up_task(demand_record, item, due_hours)
"""


# ── ATC / PHCODE chronic prefix table ────────────────────────────────────────
CHRONIC_PHCODE_PREFIXES = {
    'C':    'أمراض القلب والأوعية الدموية',
    'C03':  'مدرات البول',
    'C07':  'ضغط الدم — حاصرات بيتا',
    'C08':  'ضغط الدم — مثبطات القنوات الكالسيوم',
    'C09':  'ضغط الدم — ACE / ARB',
    'C10':  'خافضات الكوليسترول',
    'A10':  'أدوية السكر',
    'H03':  'الغدة الدرقية',
    'B01':  'مضادات التخثر والجلطة',
    'N03':  'الصرع',
    'N04':  'مرض باركنسون',
    'N06':  'الاكتئاب والقلق',
    'R03':  'الربو وأمراض الرئة المزمنة',
    'L04':  'مثبطات المناعة',
    'M05':  'هشاشة العظام',
    'A02':  'أمراض الجهاز الهضمي المزمنة',
    'J05':  'مضادات الفيروسات المزمنة',
}

# Longer prefixes must be checked before shorter ones — build sorted list once.
_SORTED_PREFIXES = sorted(CHRONIC_PHCODE_PREFIXES.keys(), key=len, reverse=True)


def is_chronic_item(item) -> bool:
    """Return True if item's phcode matches a chronic prefix."""
    phcode = (getattr(item, 'phcode', '') or '').strip().upper()
    if phcode:
        return any(phcode.startswith(p.upper()) for p in _SORTED_PREFIXES)
    # Fallback: medicine_type == 'CH' in some SOFTECH configurations
    return (getattr(item, 'medicine_type', '') or '').strip().upper() == 'CH'


def get_chronic_category(item) -> str:
    """Return Arabic category label, or '' if not chronic."""
    phcode = (getattr(item, 'phcode', '') or '').strip().upper()
    for prefix in _SORTED_PREFIXES:
        if phcode.startswith(prefix.upper()):
            return CHRONIC_PHCODE_PREFIXES[prefix]
    return ''


def tag_chronic_items() -> int:
    """
    Scan the Item catalog and upsert ChronicMedication rows.
    Safe to call repeatedly — existing records are not overwritten.
    Returns the count of newly created records.
    """
    from apps.catalog.models import Item, ChronicMedication
    created = 0
    qs = Item.objects.filter(is_active=True).only('id', 'phcode', 'medicine_type', 'name')
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
