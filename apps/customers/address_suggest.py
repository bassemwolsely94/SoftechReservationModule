"""
customers/address_suggest.py — autocomplete for the POS new-customer address fields.

Suggests ONLY values already stored (CustomerLocation + the order-level delivery snapshot), most used
first, matched with the shared wildcard rules and Arabic-insensitive folding (أ/إ/آ→ا, ى→ي, ة→ه).
Pure PG read; never SOFTECH. Variants of the same place (الإسكندرية / الاسكندريه) merge into one
suggestion shown with its most common spelling.
"""
import re
from collections import Counter

from django.db.models import Count

from apps.catalog.wildcard import text_matches
from apps.delivery.models import CustomerLocation, DeliveryOrder

FIELDS = ('area', 'district', 'landmark')
_ORDER_COL = {f: f'delivery_{f}' for f in FIELDS}

_AR_FOLD = str.maketrans({'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا', 'ى': 'ي', 'ة': 'ه', 'ـ': ''})
_DIACRITICS = re.compile('[ً-ٰٟ]')


def _norm(s):
    s = _DIACRITICS.sub('', str(s or '')).translate(_AR_FOLD)
    return ' '.join(s.split()).lower()


def _fold_q(q):
    """Fold a query but keep wildcard characters intact."""
    return _norm(q)


def _tally(field, area_filter):
    """[(display_value, area_value, uses)] from both sources."""
    rows = []
    sources = ((CustomerLocation, field, 'area'),
               (DeliveryOrder, _ORDER_COL[field], _ORDER_COL['area']))
    for model, col, area_col in sources:
        qs = model.objects.exclude(**{col: ''})
        cols = [col] + ([area_col] if area_filter and field != 'area' else [])
        for r in qs.values(*cols).annotate(n=Count('id')):
            rows.append((r[col], r[area_col] if len(cols) > 1 else '', r['n']))
    return rows


def address_suggest(field, q, *, area='', limit=10):
    if field not in FIELDS:
        raise ValueError(f'field must be one of {FIELDS}')
    area_q = _fold_q(area) if field != 'area' else ''
    query = _fold_q(q)
    total, spellings = Counter(), {}
    for value, row_area, n in _tally(field, bool(area_q)):
        value = (value or '').strip()
        key = _norm(value)
        if not key:
            continue
        if area_q and not text_matches(_norm(row_area), area_q):
            continue
        if query and not text_matches(key, query):
            continue
        total[key] += n
        spellings.setdefault(key, Counter())[value] += n
    ranked = sorted(total, key=lambda k: (-total[k], k))
    return [spellings[k].most_common(1)[0][0] for k in ranked[:max(1, limit)]]
