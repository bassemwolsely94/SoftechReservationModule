"""
catalog/search_index.py — normalization for the product-intelligence universal
search overlay.

`normalize_search_text` folds Arabic orthographic variance (tashkeel, alef/ya/ta
forms, tatweel) and lowercases Latin so a trigram (pg_trgm) match on `Item.search_name`
is robust to how a cashier types. `build_search_name` assembles the per-item
haystack from the already-synced SOFTECH fields (code + barcode + names). It is
deterministic and side-effect free — the same inputs always give the same string
(rules 2/10). Aliases live in their own table and are joined at query time, so they
are intentionally NOT folded in here.
"""
import re

# Arabic diacritics (tashkeel) + tatweel(ـ) → removed entirely.
_TASHKEEL = re.compile(r'[ؗ-ًؚ-ْـ]')
_WS = re.compile(r'\s+')

# Orthographic folds: collapse interchangeable Arabic letter forms.
_FOLD = str.maketrans({
    'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا',   # alef variants → bare alef
    'ة': 'ه',                                   # teh marbuta → heh
    'ى': 'ي',                                   # alef maksura → yeh
    'ؤ': 'و', 'ئ': 'ي',                         # hamza carriers → base
})


def normalize_search_text(value) -> str:
    """Fold Arabic variance + lowercase Latin + collapse whitespace. None-safe."""
    if not value:
        return ''
    s = str(value)
    s = _TASHKEEL.sub('', s)
    s = s.translate(_FOLD)
    s = s.lower()
    s = _WS.sub(' ', s).strip()
    return s


def build_search_name(*, softech_id='', name='', name_scientific='', barcode='', extra='') -> str:
    """
    Assemble the normalized search haystack for one item. Parts are normalized
    individually then space-joined; duplicate/empty parts are dropped so the field
    stays compact. `extra` lets callers fold in extra tokens (e.g. a family name)
    without changing the signature elsewhere.
    """
    parts = [softech_id, barcode, name, name_scientific, extra]
    seen, out = set(), []
    for p in parts:
        n = normalize_search_text(p)
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return ' '.join(out)


def search_name_for(item) -> str:
    """Build the haystack from an Item instance (or any object with the fields)."""
    return build_search_name(
        softech_id=getattr(item, 'softech_id', '') or '',
        name=getattr(item, 'name', '') or '',
        name_scientific=getattr(item, 'name_scientific', '') or '',
        barcode=getattr(item, 'barcode', '') or '',
    )
