"""
apps/images/normalizer.py

Product Name Normalization Engine.

Takes a raw ERP item (name, active_ingredients, shape, etc.) and produces:
  - canonical_name       cleaned, lowercased, no noise
  - search_query_en      best English search string for image lookup
  - search_query_ar      Arabic query
  - brand                extracted brand token
  - strength             extracted dose (500mg, 10ml, etc.)
  - dosage_form          tablet / syrup / cream / etc.
  - pack_size            30 tabs / 100ml / etc.
  - parse_confidence     0-1

Design goals:
  • Zero external API calls — pure heuristics + dictionaries
  • Deterministic — same input → same output always
  • Fast — called for every item in batch
  • Arabic-aware — handles Arabic names, numbers, units
"""
from __future__ import annotations
import re
import unicodedata
from typing import Optional

from apps.catalog.models import Item


# ── Pharma dictionaries ────────────────────────────────────────────────────────

DOSAGE_FORMS: dict[str, str] = {
    # English → canonical
    'tablet': 'tablet', 'tablets': 'tablet', 'tab': 'tablet', 'tabs': 'tablet',
    'caplet': 'tablet', 'caplets': 'tablet',
    'capsule': 'capsule', 'capsules': 'capsule', 'cap': 'capsule', 'caps': 'capsule',
    'syrup': 'syrup', 'syr': 'syrup', 'elixir': 'syrup',
    'suspension': 'suspension', 'susp': 'suspension',
    'solution': 'solution', 'sol': 'solution',
    'injection': 'injection', 'inj': 'injection', 'vial': 'injection',
    'ampoule': 'injection', 'amp': 'injection',
    'cream': 'cream', 'crm': 'cream',
    'ointment': 'ointment', 'oint': 'ointment',
    'gel': 'gel',
    'drops': 'drops', 'drop': 'drops',
    'spray': 'spray',
    'patch': 'patch',
    'suppository': 'suppository', 'supp': 'suppository',
    'powder': 'powder', 'sachet': 'sachet',
    'lotion': 'lotion',
    'shampoo': 'shampoo',
    'inhaler': 'inhaler', 'inhale': 'inhaler',
    'nasal': 'nasal spray',
    'eye drops': 'eye drops', 'ear drops': 'ear drops',
    'infusion': 'infusion',
    'enema': 'enema',
    'pessary': 'pessary',
    # Arabic → canonical
    'أقراص': 'tablet', 'قرص': 'tablet', 'حبوب': 'tablet',
    'كبسول': 'capsule', 'كبسولات': 'capsule',
    'شراب': 'syrup',
    'معلق': 'suspension', 'معلّق': 'suspension',
    'محلول': 'solution',
    'حقن': 'injection', 'حقنة': 'injection',
    'كريم': 'cream',
    'مرهم': 'ointment',
    'جل': 'gel',
    'قطرة': 'drops', 'قطرات': 'drops',
    'بخاخ': 'spray',
    'لصقة': 'patch',
    'تحميل': 'suppository',
    'مسحوق': 'powder',
    'لوشن': 'lotion',
    'شامبو': 'shampoo',
    'تنفس': 'inhaler',
    'أنفي': 'nasal spray',
}

# Arabic dosage form keywords for form detection
ARABIC_FORMS = set(DOSAGE_FORMS.keys()) - {
    k for k in DOSAGE_FORMS if not any('؀' <= c <= 'ۿ' for c in k)
}

NOISE_WORDS = {
    # English noise
    'film', 'coated', 'fc', 'sr', 'er', 'mr', 'xr', 'xl', 'cr', 'la',
    'modified', 'release', 'extended', 'sustained', 'immediate', 'slow',
    'long', 'acting', 'retard',
    'sugar', 'free', 'gluten', 'halal',
    'box', 'pack', 'packet', 'set', 'kit',
    'each', 'per',
    'new', 'original', 'formula', 'extra', 'plus', 'forte', 'max', 'ultra',
    'mini', 'junior', 'adult', 'pediatric', 'infant',
    'import', 'imported', 'local',
    'generic',
    # Units noise (kept in strength, removed from canonical)
    'piece', 'pieces', 'pcs', 'pc', 'unit', 'units',
}

UNIT_ALIASES = {
    'mg': 'mg', 'milligram': 'mg', 'milligrams': 'mg',
    'mcg': 'mcg', 'microgram': 'mcg', 'μg': 'mcg',
    'g': 'g', 'gm': 'g', 'gram': 'g', 'grams': 'g',
    'ml': 'ml', 'milliliter': 'ml', 'mls': 'ml', 'cc': 'ml',
    'l': 'l', 'liter': 'l',
    'iu': 'iu', 'unit': 'iu', 'units': 'iu',
    '%': '%', 'percent': '%',
    'meq': 'meq', 'mmol': 'mmol',
}

# ── Regexes ────────────────────────────────────────────────────────────────────

_STRENGTH_RE  = re.compile(
    r'(\d+(?:\.\d+)?)\s*'
    r'(mg|mcg|g|gm|ml|l|iu|unit|units|%|meq|mmol|μg)\b',
    re.IGNORECASE,
)
_PACK_RE      = re.compile(
    r'(\d+)\s*'
    r'(tab(?:let)?s?|cap(?:sule)?s?|ml|sachet|vial|amp(?:oule)?|patch|supp|piece|pcs?)\b',
    re.IGNORECASE,
)
_ARABIC_NUM   = re.compile(r'[٠-٩]+')
_NOISE_RE     = re.compile(r'\b(' + '|'.join(re.escape(w) for w in NOISE_WORDS) + r')\b', re.I)
_WHITESPACE   = re.compile(r'\s+')
_PUNCTUATION  = re.compile(r'[^\w\s\-\+/،]')


# ── Arabic helpers ─────────────────────────────────────────────────────────────

def _normalize_arabic(text: str) -> str:
    """Normalise Arabic diacritics and letter variants."""
    text = unicodedata.normalize('NFKC', text)
    # Remove tashkeel (diacritics)
    text = re.sub(r'[ً-ٰٟ]', '', text)
    # Normalise alef variants → ا
    text = re.sub(r'[آأإ]', 'ا', text)
    # Normalise teh marbuta → ه
    text = text.replace('ة', 'ه')
    return text

def _arabic_to_western(text: str) -> str:
    table = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
    return text.translate(table)


# ── Main normalizer ────────────────────────────────────────────────────────────

def normalize_item(item: Item) -> dict:
    """
    Parse an ERP Item into structured normalization fields.
    Returns a dict ready to save into ProductNormalization.
    """
    name = (item.name or '').strip()

    # ── Step 1: convert Arabic numerals, normalise Arabic script ──────────────
    working = _arabic_to_western(name)

    # ── Step 2: extract strength (must come before noise removal) ─────────────
    strengths = _STRENGTH_RE.findall(working)
    strength  = ''
    if strengths:
        num, unit = strengths[0]
        unit      = UNIT_ALIASES.get(unit.lower(), unit.lower())
        strength  = f'{num}{unit}'

    # ── Step 3: extract pack size ─────────────────────────────────────────────
    pack_matches = _PACK_RE.findall(working)
    pack_size    = ''
    if pack_matches:
        qty, form_token = pack_matches[0]
        pack_size       = f'{qty} {form_token.lower()}'

    # ── Step 4: detect dosage form ────────────────────────────────────────────
    dosage_form = _detect_form(working, item)

    # ── Step 5: extract brand ─────────────────────────────────────────────────
    brand = _extract_brand(working, item)

    # ── Step 6: build canonical name ─────────────────────────────────────────
    canonical = _build_canonical(working, brand, strength, dosage_form)

    # ── Step 7: build search queries ─────────────────────────────────────────
    search_en = _build_search_en(brand, strength, dosage_form, item)
    search_ar = _build_search_ar(item, brand, strength)

    # ── Step 8: confidence ────────────────────────────────────────────────────
    confidence = _score_confidence(brand, strength, dosage_form, canonical)

    return {
        'canonical_name':   canonical,
        'normalized_name':  canonical.lower(),
        'search_query_en':  search_en,
        'search_query_ar':  search_ar,
        'brand':            brand,
        'strength':         strength,
        'dosage_form':      dosage_form,
        'pack_size':        pack_size,
        'parse_confidence': confidence,
    }


def _detect_form(name: str, item: Item) -> str:
    """Return canonical dosage form string or ''."""
    lower = name.lower()

    # Direct match from item.shape_name (SOFTECH field — most reliable)
    if item.shape_name:
        form = DOSAGE_FORMS.get(item.shape_name.strip().lower(), '')
        if form:
            return form

    if item.shape_name_ar:
        form = DOSAGE_FORMS.get(_normalize_arabic(item.shape_name_ar).strip(), '')
        if form:
            return form

    # Fallback: scan name
    for token, canonical in DOSAGE_FORMS.items():
        if token in lower:
            return canonical

    return ''


def _extract_brand(name: str, item: Item) -> str:
    """
    Extract brand name.  Heuristic: first meaningful word.
    Skips numeric-only tokens and known form words.
    """
    # First word of the SOFTECH name is almost always the brand
    words = name.split()
    for w in words:
        clean = re.sub(r'[^\w]', '', w).strip()
        if (
            clean
            and not clean.isdigit()
            and len(clean) >= 2
            and clean.lower() not in DOSAGE_FORMS
            and clean.lower() not in NOISE_WORDS
        ):
            return clean.upper()
    return ''


def _build_canonical(name: str, brand: str, strength: str, form: str) -> str:
    """Produce a clean canonical name string."""
    # Remove punctuation noise but keep hyphens, plus signs
    cleaned = _PUNCTUATION.sub(' ', name)
    # Remove noise words
    cleaned = _NOISE_RE.sub(' ', cleaned)
    # Collapse whitespace
    cleaned = _WHITESPACE.sub(' ', cleaned).strip()
    return cleaned


def _build_search_en(brand: str, strength: str, form: str, item: Item) -> str:
    """Build the most effective English image search query."""
    parts = []
    if brand:
        parts.append(brand)
    if strength:
        parts.append(strength)
    if form and form not in ('tablet',):   # too generic alone
        parts.append(form)
    if item.producer_name:
        parts.append(item.producer_name.split()[0])  # first word of manufacturer
    query = ' '.join(parts) if parts else (item.name or '')
    return query.strip()[:200]


def _build_search_ar(item: Item, brand: str, strength: str) -> str:
    """Build Arabic image search query."""
    parts = []
    # Brand first
    if brand:
        parts.append(brand)
    if item.effect_name_ar:
        parts.append(item.effect_name_ar.split()[0])
    if strength:
        parts.append(strength)
    if item.shape_name_ar:
        parts.append(item.shape_name_ar)
    return ' '.join(parts).strip()[:200] or (item.name or '')


def _score_confidence(brand, strength, form, canonical) -> float:
    """Quick heuristic confidence score for how well we parsed this item."""
    score = 0.3   # baseline
    if brand:
        score += 0.3
    if strength:
        score += 0.2
    if form:
        score += 0.1
    if len(canonical) > 5:
        score += 0.1
    return min(score, 1.0)
