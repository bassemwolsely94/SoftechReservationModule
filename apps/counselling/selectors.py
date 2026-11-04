"""
Read helpers for approved counselling content — the stable API other apps use (Project 5's label
printer, the WhatsApp card, the drug assistant). They return the latest APPROVED snapshot only, and
None whenever the content switch is off, the item has no sheet, or the sheet is retired.
"""
from django.conf import settings

from .models import CounsellingContentItem, WITH_FOOD_LABELS


def content_enabled() -> bool:
    return bool(getattr(settings, 'COUNSELLING_CONTENT_ENABLED', False))


def sheet_for(item):
    """The sheet linked to `item` (any status), or None."""
    link = (CounsellingContentItem.objects.select_related('content', 'content__approved_version')
            .filter(item_id=getattr(item, 'pk', item)).first())
    return link.content if link else None


def approved_content(item) -> dict | None:
    if not content_enabled():
        return None
    c = sheet_for(item)
    if c is None or c.status == 'retired' or c.approved_version is None:
        return None
    v = c.approved_version
    return {**v.data, 'version': v.version, 'approved_at': v.approved_at.isoformat(), 'content_id': c.pk}


def approved_usage_text(item) -> str | None:
    data = approved_content(item)
    if not data:
        return None
    parts = [data.get('dose_ar', ''), data.get('frequency_ar', ''),
             WITH_FOOD_LABELS.get(data.get('with_food', ''), ''), data.get('how_to_use_ar', '')]
    text = ' — '.join(p.strip() for p in parts if p and p.strip())
    return text or None
