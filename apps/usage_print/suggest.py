"""
apps/usage_print/suggest.py — one suggested instruction per invoice line. Deterministic only.

Order (first hit wins; the source is shown to the user next to the text):
  1. patient_last — this patient's last confirmed instruction for this item (named customers only)
  2. item_common  — the instruction most often confirmed for this item (ties → most recent)
  3. curated      — pharmacist-APPROVED per-item content owned by Project 4 (drug assistant), read
                    through `apps.counselling.selectors.approved_usage_text(item)` when it exists.
                    enrichment.ItemEnrichment is never used: its clinical fields are AI-filled.
  4. none         — empty; the user builds it from the preset chips.
Never an LLM. A suggestion is only a starting text — the line still needs a human ✓.
"""
from django.db.models import Count, Max

from .models import UsageSheetLine as L


def _curated(item):
    try:
        from apps.counselling.selectors import approved_usage_text
    except ImportError:
        return None
    try:
        return (approved_usage_text(item) or '').strip() or None
    except Exception:
        return None


def suggest_for(item, customer=None, exclude_sheet=None):
    """(text, source) for one item."""
    if item is None:
        return '', L.SRC_NONE
    confirmed = L.objects.filter(item=item, status=L.STATUS_CONFIRMED).exclude(text='')
    if exclude_sheet is not None:
        confirmed = confirmed.exclude(sheet=exclude_sheet)
    if customer is not None:
        last = confirmed.filter(sheet__customer=customer).order_by('-confirmed_at', '-id').first()
        if last:
            return last.text, L.SRC_PATIENT
    common = (confirmed.values('text').annotate(n=Count('id'), last=Max('confirmed_at'))
              .order_by('-n', '-last').first())
    if common:
        return common['text'], L.SRC_COMMON
    text = _curated(item)
    if text:
        return text, L.SRC_CURATED
    return '', L.SRC_NONE
