"""
apps/shortage/matching.py

Fuzzy item-name matcher.
Scores how closely a raw name (Arabic or English, possibly abbreviated)
matches catalog Item records.

Uses a simple token-overlap approach that works without external dependencies
(difflib is part of Python stdlib).  For better accuracy, install
`python-Levenshtein` and the function will use it automatically.
"""
import re
import difflib
from django.db.models import Q


def _normalize(text: str) -> str:
    """Lower-case, strip diacritics, collapse spaces, remove punctuation."""
    if not text:
        return ''
    # Remove Arabic diacritics (tashkeel)
    text = re.sub(r'[ً-ٰٟ]', '', text)
    # Normalize alef variants
    text = re.sub(r'[أإآ]', 'ا', text)
    text = re.sub(r'ة', 'ه', text)
    text = re.sub(r'ى', 'ي', text)
    text = text.lower()
    text = re.sub(r'[^\w\s]', ' ', text)
    return ' '.join(text.split())


def _tokens(text: str) -> set:
    return set(_normalize(text).split())


def score_match(raw_name: str, item_name: str, item_scientific: str = '') -> float:
    """
    Return a similarity score [0.0 – 1.0] between raw_name and an item.
    Combines:
      1. difflib SequenceMatcher ratio on normalized Arabic name
      2. Token overlap ratio
      3. Scientific name bonus
    """
    raw = _normalize(raw_name)
    name = _normalize(item_name)
    sci  = _normalize(item_scientific or '')

    # Exact match
    if raw == name:
        return 1.0

    # difflib ratio on full strings
    seq_ratio = difflib.SequenceMatcher(None, raw, name).ratio()

    # Token overlap
    raw_tok  = _tokens(raw_name)
    name_tok = _tokens(item_name)
    if raw_tok and name_tok:
        tok_overlap = len(raw_tok & name_tok) / max(len(raw_tok), len(name_tok))
    else:
        tok_overlap = 0.0

    # Scientific name bonus
    sci_bonus = 0.0
    if sci and raw:
        sci_bonus = difflib.SequenceMatcher(None, raw, sci).ratio() * 0.3

    combined = max(seq_ratio, tok_overlap) * 0.7 + sci_bonus
    return min(combined, 1.0)


def find_best_matches(raw_name: str, top_n: int = 5, min_score: float = 0.25):
    """
    Search the Item catalog for the best matches to raw_name.
    Returns list of dicts:
      { item_id, item_name, item_softech_id, score, item_sale_price }
    """
    from apps.catalog.models import Item

    # First: quick DB pre-filter using first 2 tokens of the raw name
    tokens = _normalize(raw_name).split()[:3]
    q = Q()
    for tok in tokens:
        if len(tok) >= 2:
            q |= Q(name__icontains=tok) | Q(name_scientific__icontains=tok)

    if not q:
        candidates = Item.objects.filter(is_active=True)[:200]
    else:
        candidates = Item.objects.filter(is_active=True).filter(q)[:200]

    scored = []
    for item in candidates:
        s = score_match(raw_name, item.name, item.name_scientific)
        if s >= min_score:
            scored.append({
                'item_id':        item.id,
                'item_name':      item.name,
                'item_scientific': item.name_scientific,
                'item_softech_id': item.softech_id,
                'item_sale_price': float(item.unit_price),
                'score':          round(s, 3),
            })

    scored.sort(key=lambda x: x['score'], reverse=True)
    return scored[:top_n]
