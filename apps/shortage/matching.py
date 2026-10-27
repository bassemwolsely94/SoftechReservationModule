"""
apps/shortage/matching.py  — v3

Intelligent item-name matcher with:
  • Arabic normalization (diacritics, alef variants, taa marbuta)
  • Arabic → English phonetic transliteration (char-level + prefix search)
  • English → Arabic fragment hinting
  • Drug component extraction (strength, dosage form, quantity)
  • rapidfuzz (ratio + partial_ratio + token_sort_ratio + jaro_winkler)
  • Tolerant DB pre-filter:
      – English input: also searches tok[1:] to catch 1-char prefix typos
      – Arabic  input: searches AR→EN prefix (first 3-4 chars) + original Arabic
      – Fallback full-scan when < 15 candidates pass the prefilter
"""
from __future__ import annotations
import re
from typing import NamedTuple

# ── rapidfuzz (fast) with difflib fallback ────────────────────────────────────
try:
    from rapidfuzz import fuzz as _fuzz
    from rapidfuzz.distance import JaroWinkler as _JaroWinkler
    _USE_RAPIDFUZZ = True
except ImportError:
    import difflib as _difflib
    _USE_RAPIDFUZZ = False


# ── Arabic → English phonetic map (char-by-char) ────────────────────────────
_AR_TO_EN: dict[str, str] = {
    'ا': 'a',  'أ': 'a',  'إ': 'a',  'آ': 'a',
    'ب': 'b',  'ت': 't',  'ث': 'th',
    'ج': 'g',  'ح': 'h',  'خ': 'kh',
    'د': 'd',  'ذ': 'z',  'ر': 'r',  'ز': 'z',
    'س': 's',  'ش': 'sh', 'ص': 's',  'ض': 'd',
    'ط': 't',  'ظ': 'z',  'ع': 'a',  'غ': 'gh',
    'ف': 'f',  'ق': 'k',  'ك': 'k',
    'ل': 'l',  'م': 'm',  'ن': 'n',
    'ه': 'h',  'ة': 'a',  'و': 'o',  'ي': 'i',
    'ى': 'a',  'ء': '',   'ئ': 'y',  'ؤ': 'w',
}

# ── Variant transliterations (loanword phonetics) ───────────────────────────
#
# Arabic lacks several sounds and substitutes the nearest letter:
#   'v' → ف (fa, normally 'f')       نيفيلوب → nevilob
#   'p' → ب (ba, normally 'b')       بنسلين  → penicillin
#   'c' → ك (kaf, normally 'k')      كلوبكس  → clopex
#   'e' → ي (ya, normally 'i')       نيفيلوب → nevilob
#   'u' → و (waw, normally 'o')      كلوكوز  → glucose
#
# Three maps generated from combinations that cover the most common cases.

# Alt-1 — v/p/e/u  (فيتامين→vitamin, نيفيلوب→nevilob, بيبسي→pepsi)
_AR_TO_EN_ALT1: dict[str, str] = {
    **_AR_TO_EN,
    'ف': 'v',
    'ب': 'p',
    'ي': 'e',
    'و': 'u',
}

# Alt-2 — c/p  keeps و→o  (كلوبكس→clopcs ≈ CLOPEX, كابيتان→capitan)
# Critical for drugs starting with C spelled via ك in Arabic.
_AR_TO_EN_ALT2: dict[str, str] = {
    **_AR_TO_EN,
    'ك': 'c',   # k → c
    'ق': 'c',   # q → c  (occasionally used for English 'c' sound)
    'ب': 'p',   # b → p
}

# Alt-3 — v only (ف→v, all others standard)
# Bridges Alt-1 and primary: نيفيلوب → nivilob (1 edit from NEVILOB)
# Alt-1 gives "nevelup" (ي→e, و→u, ب→p) which is further from NEVILOB.
# Alt-3 keeps ي→i and ب→b but applies ف→v giving nivilob ≈ nevilob.
_AR_TO_EN_ALT3: dict[str, str] = {
    **_AR_TO_EN,
    'ف': 'v',   # f → v  (the only phonetic loanword change)
}

# Backward-compat alias
_AR_TO_EN_ALT = _AR_TO_EN_ALT1

# ── Common English pharma fragments → Arabic equivalents ─────────────────────
_EN_FRAG_TO_AR: list[tuple[str, str]] = [
    ('amox',  'اموكس'),  ('ceph',  'سيف'),
    ('azith', 'ازيث'),   ('metro', 'ميترو'),
    ('para',  'باراس'),  ('ibup',  'ايبو'),
    ('omep',  'اوميب'),  ('ator',  'اتور'),
    ('simva', 'سيمفا'),  ('lisi',  'ليزو'),
    ('ramip', 'راميب'),  ('doxo',  'دوكسو'),
    ('cipro', 'سيبرو'),  ('augm',  'اوجم'),
    ('clari', 'كلاري'),  ('eryt',  'اريث'),
    ('bism',  'بيزم'),   ('lanso', 'لانسو'),
    ('panto', 'بانتو'),  ('esom',  'ايسوم'),
    ('rani',  'رانيت'),  ('clav',  'كلاف'),
    ('xarel', 'زاريل'),  ('rivar', 'ريفار'),
    ('nebiv', 'نيبيف'),  ('nifed', 'نيفيد'),
    ('bisop', 'بيسوب'),  ('carve', 'كارف'),
    ('metop', 'ميتوب'),  ('atenol','اتينول'),
    ('telmis','تيلمي'),  ('valsar','فالسار'),
    ('losart','لوسار'),  ('olmesa','اولمي'),
    ('lanta', 'لانتا'),  ('galvus','جالفس'),
    ('januv', 'جانوف'),  ('victoz','فيكتوز'),
    ('forxig','فوركس'),  ('jardian','جاردي'),
]

# ── Dosage-form synonyms ──────────────────────────────────────────────────────
_FORM_SYNONYMS: dict[str, list[str]] = {
    'tablet':      ['قرص', 'اقراص', 'tab', 'tabs', 'tablet', 'tablets', 'تابلت'],
    'capsule':     ['كبسولة', 'كبسول', 'cap', 'caps', 'capsule', 'capsules'],
    'syrup':       ['شراب', 'syrup', 'syr', 'susp', 'suspension', 'معلق', 'محلول'],
    'ampoule':     ['امبول', 'امبولة', 'amp', 'ampoule', 'injection', 'inj', 'حقن'],
    'cream':       ['كريم', 'cream', 'oint', 'ointment', 'مرهم', 'جل', 'gel'],
    'drops':       ['قطرة', 'قطرات', 'drops', 'drop', 'نقط'],
    'patch':       ['لاصق', 'patch', 'patches'],
    'inhaler':     ['بخاخ', 'inhaler', 'spray', 'مستنشق'],
    'suppository': ['تحميلة', 'supp', 'suppository'],
    'sachet':      ['ساشيه', 'sachet', 'powder', 'pdr'],
}

_FORM_LOOKUP: dict[str, str] = {}
for _canonical, _syns in _FORM_SYNONYMS.items():
    for _s in _syns:
        _FORM_LOOKUP[_s.lower()] = _canonical


# ── Text normalization ────────────────────────────────────────────────────────

_IS_ARABIC_RE = re.compile(r'[؀-ۿ]')


def _is_arabic(text: str) -> bool:
    return bool(_IS_ARABIC_RE.search(text))


def _normalize(text: str) -> str:
    """Lowercase, strip diacritics, normalize alef/taa/ya variants."""
    if not text:
        return ''
    # Remove tashkeel (diacritics U+064B–U+065F + U+0670)
    text = re.sub(r'[ً-ٰٟ]', '', text)
    # Normalize alef variants → ا
    text = re.sub(r'[أإآٱ]', 'ا', text)
    # taa marbuta → ه
    text = re.sub(r'ة', 'ه', text)
    # alef maqsura → ي
    text = re.sub(r'ى', 'ي', text)
    text = text.lower()
    # Arabic-Indic / Persian digits → ASCII ("اوميز ١٠" == "اوميز 10")
    text = text.translate(_DIGITS)
    # Remove punctuation except digits and Arabic/Latin letters
    text = re.sub(r'[^\w\s]', ' ', text)
    return ' '.join(text.split())


_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


def _ar_to_en_phonetic(text: str, alt: bool = False) -> str:
    """
    Transliterate Arabic characters to English phonetic equivalent.
    Non-Arabic characters pass through unchanged.

    alt=True uses loanword variant-1 mapping (ف→v, ب→p, ي→e, و→u).
    """
    mapping = _AR_TO_EN_ALT1 if alt else _AR_TO_EN
    result = []
    for ch in text:
        result.append(mapping.get(ch, ch))
    return ''.join(result)


def _transliterate(text: str, mapping: dict) -> str:
    """Apply an arbitrary AR→EN mapping char-by-char."""
    return ''.join(mapping.get(ch, ch) for ch in text)


_VOWELS = frozenset('aeiou')


def _vowel_swap_variant(s: str) -> str | None:
    """
    Handle Arabic consonant-cluster helping vowels.

    Arabic cannot start a word with a consonant cluster (e.g. "GL", "GR"),
    so a short vowel is inserted between them.  When Arabic speakers spell
    a loanword like GLIPTUS they write "جيلبتس" (Gi-l-…) because the ي
    (short 'i') bridges the GL cluster.  Standard phonetic maps produce
    "gilpts" — the helping vowel is at position 1, but in the English word
    the vowel 'i' sits at position 2 (gl-i-pts).

    This function detects the pattern consonant + vowel + consonant at the
    START of the transliterated string and returns a variant with the vowel
    moved one position to the right:
        "gilpts"  →  "glipts"   (prefix "gli" → finds GLIPTUS)
        "gilbts"  →  "glibts"   (prefix "gli" → also finds GLIPTUS)

    Returns None if the pattern does not apply.
    """
    if (len(s) >= 4
            and s[0] not in _VOWELS   # consonant
            and s[1] in _VOWELS       # helping vowel
            and s[2] not in _VOWELS   # consonant
            and s[2] != ' '):         # not a word boundary
        return s[0] + s[2] + s[1] + s[3:]
    return None


def _all_ar_phonetics(text: str) -> list[str]:
    """
    Return all transliteration variants of an Arabic string, deduplicated.

    Four base maps:
      primary  — standard (ك→k, ب→b, ف→f, و→o, ي→i)
      alt1     — v/p/e/u  (ف→v, ب→p, ي→e, و→u)   e.g. فيتامين→vitamin
      alt2     — c/p      (ك→c, ق→c, ب→p)          e.g. كلوبكس→clopcs
      alt3     — v only   (ف→v)                     e.g. نيفيلوب→nivilob (1 edit from NEVILOB)

    Plus vowel-swap variants (see _vowel_swap_variant) that handle Arabic
    consonant-cluster vowel insertion:
      "gilpts" → "glipts"   e.g. جيلبتس → GLIPTUS
    """
    base_variants = [
        _transliterate(text, _AR_TO_EN),
        _transliterate(text, _AR_TO_EN_ALT1),
        _transliterate(text, _AR_TO_EN_ALT2),
        _transliterate(text, _AR_TO_EN_ALT3),
    ]
    seen: list[str] = []
    for s in base_variants:
        if s not in seen:
            seen.append(s)
    # Add vowel-swap variants (one per base variant that qualifies)
    for s in list(seen):
        sv = _vowel_swap_variant(s)
        if sv and sv not in seen:
            seen.append(sv)
    return seen


def _en_to_ar_fragments(text: str) -> str:
    """Replace common English pharma fragment with Arabic phonetic hint."""
    text_lower = text.lower()
    for en_frag, ar_frag in _EN_FRAG_TO_AR:
        text_lower = text_lower.replace(en_frag, ar_frag)
    return text_lower


# ── Component extraction ──────────────────────────────────────────────────────

_STRENGTH_RE = re.compile(
    r'(\d+(?:[.,]\d+)?)\s*'
    r'(mg|ml|mcg|iu|g\b|gm|gms|mg/ml|mg/5ml|%|ملج|مج|مل|وحده|unit)',
    re.IGNORECASE,
)
_QTY_RE = re.compile(
    r'\b(\d+)\s*(قرص|كبسول|علبة|pack|tab|cap|pcs|pc|عبوه)?\s*$',
    re.IGNORECASE,
)


class DrugComponents(NamedTuple):
    name_clean: str
    strength:   str | None
    form:       str | None
    quantity:   float | None


def extract_components(raw: str) -> DrugComponents:
    """Parse strength, dosage form, and quantity from a raw drug name string."""
    text = raw.strip()

    strength = None
    m = _STRENGTH_RE.search(text)
    if m:
        strength = m.group(0).strip()
        text = (text[:m.start()] + ' ' + text[m.end():]).strip()

    form  = None
    words = text.split()
    kept  = []
    for w in words:
        canonical = _FORM_LOOKUP.get(w.lower())
        if canonical and form is None:
            form = canonical
        else:
            kept.append(w)

    quantity = None
    m2 = _QTY_RE.search(' '.join(kept))
    if m2:
        try:
            quantity  = float(m2.group(1))
            kept_str  = ' '.join(kept)[:m2.start()].strip()
            kept      = kept_str.split()
        except ValueError:
            pass

    name_clean = ' '.join(kept).strip() or raw.strip()
    return DrugComponents(name_clean=name_clean, strength=strength,
                          form=form, quantity=quantity)


# ── Similarity scoring ────────────────────────────────────────────────────────

def _sim(a: str, b: str) -> float:
    """
    Return similarity [0..1] between two normalized strings.
    Uses rapidfuzz (ratio + partial_ratio + token_sort_ratio + JaroWinkler).
    JaroWinkler is great for English brand-name typos (short same-language).
    Do NOT use for Arabic→English cross-language comparisons — use _sim_edit.
    """
    if not a or not b:
        return 0.0
    if _USE_RAPIDFUZZ:
        scores = [
            _fuzz.ratio(a, b) / 100.0,
            _fuzz.partial_ratio(a, b) / 100.0,
            _fuzz.token_sort_ratio(a, b) / 100.0,
            _fuzz.token_set_ratio(a, b) / 100.0,
        ]
        if len(a) <= 20 or len(b) <= 20:
            scores.append(_JaroWinkler.similarity(a, b))
        return max(scores)
    import difflib
    return max(
        difflib.SequenceMatcher(None, a, b).ratio(),
        len(set(a.split()) & set(b.split())) /
        max(len(set(a.split())), len(set(b.split())), 1),
    )


def _sim_edit(a: str, b: str) -> float:
    """
    Edit-distance similarity WITHOUT JaroWinkler.

    Used for Arabic→English cross-language comparisons where JaroWinkler's
    prefix bias causes false positives:
      "nevelup" vs "nevxal"  → JW 82%  (wrong, prefix match)
      "nifilob" vs "nevilob" → ratio 71% (correct, edit-distance)

    partial_ratio finds the best substring alignment, which is critical for
    comparing a short transliterated name against a full item name.
    """
    if not a or not b:
        return 0.0
    if _USE_RAPIDFUZZ:
        return max(
            _fuzz.ratio(a, b) / 100.0,
            _fuzz.partial_ratio(a, b) / 100.0,
            _fuzz.token_sort_ratio(a, b) / 100.0,
        )
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio()


def _sim_lev_token(query: str, text: str) -> float:
    """
    Token-level Levenshtein similarity for Arabic→English cross-language scoring.

    Compares `query` (a single transliterated Arabic word) against each
    whitespace-separated token in `text`, returns the max normalized
    Levenshtein similarity.

    Why NOT partial_ratio here:
      partial_ratio("nevelup", "never die 40ml") = 72.73%
        — it finds the 4-char "neve" substring window, spuriously high.
      Lev.normalized_similarity("nivilob", "nevilob") = 85.71%
        — correct, 1-character difference (i→e at position 1 via alt3 map).

    Why NOT simple ratio here:
      ratio("clopcs", "clopex")   = 66.7%  (correct, 2 subs in 6 chars)
      ratio("clopcs", "clopacirc")= 66.7%  (same! — LCS coincidence)
      Lev("clopcs", "clopex")     = 66.7%  (same)
      Lev("clopcs", "clopacirc")  = 55.6%  (correctly lower — 4 edits in 9 chars)
    """
    if not query or not text:
        return 0.0

    # ── Word-by-word matching ─────────────────────────────────────────────────
    # Compare each meaningful word in `query` against each meaningful word in
    # `text`.  This handles multi-word Arabic inputs correctly:
    #   raw_name  = "جيلبتس بلس 50/1000 & 50/850"
    #   phonetic  = "glipts pls 50 1000 50 850"
    #   query-tok = ["glipts", "pls"]          ← digits skipped
    #   text-tok  = ["gliptus", "tab"]         ← digits skipped
    #   Lev("glipts", "gliptus") = 71.4%  ← wins over AMINO (≈10%)
    #
    # Pure-digit tokens are skipped here because their contribution is captured
    # by the strength/form bonus in score_match().
    #
    # Minimum text-token length (80 % of query-token length) prevents very
    # short abbreviation tokens (e.g. "CLOS" 4 chars) from scoring spuriously
    # high against a 6-char query ("clopcs"):
    #   Lev("clopcs","clos") = 66.7%  ← false positive without the filter

    q_words = [w for w in query.split() if w and len(w) >= 3 and not w.isdigit()]
    t_all   = text.split() or [text]

    if not q_words:
        return 0.0

    best = 0.0
    try:
        from rapidfuzz.distance import Levenshtein as _Lev
        _lev_sim = _Lev.normalized_similarity
    except (ImportError, AttributeError):
        _lev_sim = None

    for qw in q_words:
        min_tlen = max(3, round(len(qw) * 0.8))
        t_cands  = [t for t in t_all if len(t) >= min_tlen and not t.isdigit()]
        if not t_cands:                             # nothing long enough → relax
            t_cands = [t for t in t_all if not t.isdigit() and len(t) >= 3]
        if not t_cands:
            t_cands = t_all                         # last resort: all tokens

        for tw in t_cands:
            if _lev_sim is not None:
                s = _lev_sim(qw, tw)
            elif _USE_RAPIDFUZZ:
                s = _fuzz.ratio(qw, tw) / 100.0
            else:
                import difflib
                s = difflib.SequenceMatcher(None, qw, tw).ratio()
            if s > best:
                best = s

    return best


def score_match(raw_name: str, item_name: str, item_scientific: str = '') -> float:
    """
    Return similarity [0..1] between raw_name and an Item.

    Signals:
      1.  Normalized direct similarity (Arabic↔Arabic or English↔English)
      2.  AR→EN phonetic similarity  (Arabic input vs English item)
      3.  EN→AR fragment similarity  (English fragments vs Arabic item)
      4.  Scientific name similarity (×0.25 weight)
      5.  Strength match bonus (+0.10)
      6.  Form match bonus    (+0.05)
    """
    raw_norm  = _normalize(raw_name)
    name_norm = _normalize(item_name)
    sci_norm  = _normalize(item_scientific or '')

    # ── Signal 1: direct normalized similarity ────────────────────────────────
    base_score = _sim(raw_norm, name_norm)

    # ── Signal 2: Arabic → English phonetic (primary + alt loanword variant) ──
    # Handles: Arabic user input vs English DB names.
    # Two variants because Arabic lacks v/p/e natively:
    #   primary: ف→f, ب→b, ي→i, و→o  (standard)
    #   alt:     ف→v, ب→p, ي→e, و→u  (loanword — نيفيلوب→nevilob)
    # All phonetic variants of the raw name (primary, v/p/e/u, c/p)
    arabic_input  = _is_arabic(raw_name)
    raw_phonetics = (
        _all_ar_phonetics(raw_norm) if arabic_input
        else [raw_norm]
    )

    # ── Build name_en: English phonetic form of the item name ─────────────────
    # Purpose: compare Arabic-transliterated query against English item name.
    #
    # Problem: many items have an Arabic translation appended, e.g.
    #   "DIGLIFLOZ PLUS 5MG / 1000MG 30TAB (3STRIPSX10) ديجليفلوز بلس"
    # _transliterate converts "بلس" → "bls", which then matches the query's
    # "بلس" → "bls" phonetic with Lev = 1.0 (false positive — both are "plus").
    #
    # Fix: for English-dominant items (more Latin chars than Arabic chars),
    # strip the Arabic suffix before building name_en.  For Arabic-dominant
    # items (fully Arabic names) keep full transliteration so phonetic search
    # can find them.
    _ar_count  = sum(1 for c in item_name if '؀' <= c <= 'ۿ')
    _lat_count = sum(1 for c in item_name if c.isascii() and c.isalpha())
    if _lat_count >= _ar_count:
        # English-dominant: strip Arabic suffix before phonetic comparison
        _name_stripped = re.sub(r'[؀-ۿ]+', ' ', name_norm)
        name_en = ' '.join(_name_stripped.split())
    else:
        # Arabic-dominant: transliterate entire name to English phonetics
        name_en = _transliterate(name_norm, _AR_TO_EN)

    # ── Choose similarity function ────────────────────────────────────────────
    # For Arabic→English cross-language we use _sim_lev_token:
    #   • Token-level: compares the transliterated word against each NAME TOKEN,
    #     so "nevelup" vs "never die" → best token = "never" → Lev 57.1%
    #   • Levenshtein (with subs): differentiates equal-LCS strings:
    #     "clopcs" vs "clopex"   (6 chars, 2 subs) → 66.7%  ← winner
    #     "clopcs" vs "clopacirc"(6 vs 9, 4 edits) → 55.6%  ← correctly lower
    #   • Alt-3 map (ف→v) gives "nivilob" from "نيفيلوب", which is 1 edit from
    #     "nevilob" → Lev 85.7%, vs NEVER DIE's "nevelup"→"never" Lev 57.1%.
    # For English→English (same-language brand typos) we keep _sim (JW helps).

    if arabic_input:
        en_score    = max(_sim_lev_token(rp, name_en) for rp in raw_phonetics)
        name_clean_norm = _normalize(extract_components(item_name).name_clean)
        cross_score = max(_sim_lev_token(rp, name_clean_norm) for rp in raw_phonetics)
    else:
        en_score    = max(_sim(rp, name_en) for rp in raw_phonetics)
        cross_score = 0.0

    # ── Signal 3: English → Arabic fragment ───────────────────────────────────
    raw_ar_frag = _normalize(_en_to_ar_fragments(raw_name))
    frag_score  = _sim(raw_ar_frag, name_norm)

    # ── Signal 4: Scientific name ─────────────────────────────────────────────
    sci_score = 0.0
    if sci_norm:
        sci_direct = _sim(raw_norm, sci_norm)
        sci_en     = (max(_sim_edit(rp, sci_norm) for rp in raw_phonetics)
                      if arabic_input else 0.0)
        sci_score  = max(sci_direct, sci_en) * 0.25

    # ── Component bonuses ─────────────────────────────────────────────────────
    raw_comp   = extract_components(raw_name)
    name_comp  = extract_components(item_name)

    strength_bonus = 0.0
    if raw_comp.strength and name_comp.strength:
        raw_str  = _normalize(raw_comp.strength)
        name_str = _normalize(name_comp.strength)
        if raw_str == name_str:
            strength_bonus = 0.15          # exact match  (e.g. 5mg == 5mg)
        elif raw_str[:3] == name_str[:3]:
            strength_bonus = 0.05          # same prefix  (e.g. 5mg ~ 5/12.5mg)

    form_bonus = 0.0
    if raw_comp.form and name_comp.form:
        if raw_comp.form == name_comp.form:
            form_bonus = 0.05

    combined = (
        max(base_score, en_score, cross_score, frag_score) * 0.70
        + sci_score
        + strength_bonus
        + form_bonus
    )
    return round(min(combined, 1.0), 4)


# ── DB candidate pre-filter ───────────────────────────────────────────────────

# 3-char phonetic prefixes that are too generic for Arabic input prefiltering.
# These mostly correspond to dosage-form words or extremely common substrings
# that match thousands of unrelated items and push real candidates past the cap.
# Examples: "gel" → 1651 items in the DB (all GEL formulations, cosmetics, etc.)
_PREFILTER_SKIP_3: frozenset[str] = frozenset([
    'gel', 'tab', 'cap', 'syr', 'sol', 'sus', 'inj', 'amp',
    'cre', 'oin', 'lot', 'pow', 'pdr', 'lin', 'eff', 'pat',
    'inh', 'sup', 'sac', 'pil', 'nos', 'ear', 'eye',
])


def _build_prefilter_q(raw_name: str):
    """
    Build a Q object that casts a wide enough net to catch candidates
    even with 1-character substitutions or Arabic→English phonetic input.

    Strategy:
      English tokens (len ≥ 5):
        • full token          → handles exact match
        • token[1:]           → handles 1-char substitution at START (zarelto → arelto → XARELTO)
        • token[-4:]          → handles 1-char substitution at START via suffix anchor
        • token[:-1]          → handles 1-char substitution at END

      Arabic tokens:
        • AR→EN first 3 chars → broad phonetic prefix (nif → NIFEDIPINE)
                                 skipped if it maps to a generic form word (see _PREFILTER_SKIP_3)
        • AR→EN first 4 chars → narrower prefix for longer names
        • Original Arabic     → catches any Arabic DB entries
    """
    from django.db.models import Q

    comp   = extract_components(raw_name)
    clean  = _normalize(comp.name_clean)
    tokens = clean.split()[:4]

    arabic_input = _is_arabic(raw_name)
    q = Q()

    for tok in tokens:
        if len(tok) < 2:
            continue

        # Skip pure-numeric tokens (e.g. "50", "1000" from "50/1000mg" inputs).
        # They match thousands of items (any 50mg drug), flooding the cap and
        # pushing the real drug out.  Strength/qty are handled by score_match().
        if tok.isdigit():
            continue

        if arabic_input:
            # ── Arabic input ──────────────────────────────────────────────────
            # Multiple transliteration variants cover first-character differences,
            # so NO skip-first-char search is needed (causes false positives on
            # very short 3-char prefixes matching unrelated product names).
            for tok_en in _all_ar_phonetics(tok):

                # 3-char prefix — broad net; skip generic form-word prefixes
                # (e.g. "gel" from "gelpts" would match 1600+ GEL formulations,
                # flooding the candidate cap before the real drug appears).
                if len(tok_en) >= 3:
                    p3 = tok_en[:3]
                    if p3 not in _PREFILTER_SKIP_3:
                        q |= Q(name__icontains=p3) | Q(name_scientific__icontains=p3)

                # 4-char prefix — better precision; always included (more specific)
                if len(tok_en) >= 5:
                    p4 = tok_en[:4]
                    q |= Q(name__icontains=p4) | Q(name_scientific__icontains=p4)

            # Original Arabic token (catches any Arabic names stored in DB)
            q |= Q(name__icontains=tok)

        else:
            # ── English input ─────────────────────────────────────────────────
            # Full token (standard)
            q |= Q(name__icontains=tok) | Q(name_scientific__icontains=tok)

            if len(tok) >= 5:
                # Skip first char: "zarelto" → "arelto" → matches "XARELTO"
                q |= Q(name__icontains=tok[1:]) | Q(name_scientific__icontains=tok[1:])

                # Last 4 chars: suffix anchor for prefix substitutions
                q |= Q(name__icontains=tok[-4:]) | Q(name_scientific__icontains=tok[-4:])

                # Skip last char: handles trailing typos
                q |= Q(name__icontains=tok[:-1]) | Q(name_scientific__icontains=tok[:-1])

    return q


def _arabic_name_q(raw_name: str):
    """Items whose name contains an Arabic word of the line (≥3 letters, not a filler /
    dosage-form word) — catalog names like «CETAL 120MG 5SUPP سيتال»."""
    from django.db.models import Q
    from . import phonetic
    q = Q()
    for tok in re.findall(r'[؀-ۿ]{3,}', _normalize(raw_name)):
        if tok in phonetic.AR_FILLER or tok in phonetic.AR_FORMS or tok in phonetic.AR_WORDS:
            continue
        q |= Q(name__icontains=tok)
    return q


def _arabic_name_tokens(raw_name: str) -> list:
    from . import phonetic
    return [t for t in re.findall(r'[؀-ۿ]{2,}', _normalize(raw_name))
            if t not in phonetic.AR_FILLER and t not in phonetic.AR_FORMS and t not in phonetic.AR_WORDS]


def _arabic_word_score(q_tokens: list, item) -> float:
    """Arabic line vs an item's ARABIC name words, WHOLE words (no substring credit):
    0.92 for an exact first word, scaled by similarity; 0 below 0.8 (no evidence)."""
    if not q_tokens:
        return 0.0
    it = re.findall(r'[؀-ۿ]{2,}', _normalize(item.name or ''))
    if not it:
        return 0.0
    head = max(_ratio(q_tokens[0], t) for t in it)
    if head < 0.8:
        return 0.0
    rest = q_tokens[1:]
    cover = (sum(max(_ratio(q, t) for t in it) for q in rest) / len(rest)) if rest else 1.0
    return round(0.62 + 0.30 * (0.8 * head + 0.2 * cover if rest else head), 4)


def _sound_score(raw_name: str, item) -> float:
    """Arabic line → Latin item by SOUND (apps/shortage/phonetic.sound_score) on the
    matcher's 0..1 scale: a perfect sound match of the name = 0.92. Below 0.75 sound
    similarity there is no evidence (0)."""
    from . import phonetic
    snd = phonetic.sound_score(raw_name, item.id)
    return round(0.62 + 0.30 * snd, 4) if snd >= 0.75 else 0.0


def _arabic_adjust(item, q_nums: list, q_forms: set, q_words: set) -> float:
    """Agreement of the Arabic line's OTHER information with the item, added to its score:
      numbers — the FIRST number written is usually the strength: +0.06 when it is the
                item's first number, +0.03 when it appears elsewhere in the name, −0.05
                when it doesn't appear at all (small: Arabic lines often end with a count);
      form    — +0.03 when a dosage-form word (نقط → drop, جيل → gel …) is in the name;
      words   — +0.04 per translated descriptor found (فواكه → fruit, اطفال → inf/pediatric,
                مطهر → antiseptic, وومان → woman …), at most +0.08."""
    name_l = (item.name or '').lower()
    adj = 0.0
    if q_nums:
        item_nums = re.findall(r'\d+(?:\.\d+)?', name_l)
        # the item's strength = its first number WITH a unit ("3FRUITS … 125GM" → 125)
        unit_num = re.search(r'(\d+(?:\.\d+)?)\s*(?:mg|mcg|ug|µg|gm|g\b|ml|iu|%|m\.?i\.?u|billion)', name_l)
        lead = unit_num.group(1) if unit_num else (item_nums[0] if item_nums else None)
        # a stage / variant number standing alone — «NAN (1)», «HERO BABY 1 …» — counts as
        # fully as a strength («نان 1» = NAN (1), not NANO … 1 L)
        # (not a COUNT: "OMEZ 40 MG 10 CAP" — the 10 is the capsule count, not a variant)
        standalone = re.findall(
            r'(?:^|[\s(])(\d+(?:\.\d+)?)(?=\)|$|\s+(?!(?:tab|cap|sach|amp|vial|supp|loz|piece|pcs|strip|'
            r'mg|ml|gm|g\b|mcg|iu|ug|caps|tablet|capsule)))', name_l)
        if (lead is not None and float(q_nums[0]) == float(lead)) or \
                any(float(q_nums[0]) == float(n) for n in standalone[:2]):
            adj += 0.06
        elif q_nums[0] in item_nums or any(float(q_nums[0]) == float(n) for n in item_nums):
            adj += 0.03
        else:
            adj -= 0.05
        # further numbers ("50/500" → the 500 tells 50/500 from 50/850)
        others = [n for n in q_nums[1:4] if n != q_nums[0]]
        if others:
            adj += 0.02 * sum(1 for n in others if any(float(n) == float(m) for m in item_nums))
    if q_forms and any(f in name_l for f in q_forms):
        adj += 0.03
    if q_words:
        adj += min(0.08, 0.04 * sum(1 for w in q_words if w in name_l))
    return adj


class _trigram_indexes:
    """Run the candidate prefilter on the trigram indexes (catalog mig 0041).

    PostgreSQL badly over-estimates how many items match short '%BIB%' patterns (~17k of
    51k), so it picks a sequential scan and evaluates the ~25–50 LIKE terms on every row:
    1.1–1.5 s per lookup. Forced onto the indexes the same query returns the IDENTICAL
    rows in ~0.02 s (measured 2026-10-04). enable_seqscan is switched off only for these
    statements (SET LOCAL inside a savepoint) and restored right after."""

    def __enter__(self):
        from django.db import connection, transaction
        self._atomic = None
        if connection.vendor != 'postgresql':
            return self
        self._atomic = transaction.atomic()
        self._atomic.__enter__()
        with connection.cursor() as cur:
            cur.execute('SET LOCAL enable_seqscan = off')
        return self

    def __exit__(self, *exc):
        from django.db import connection
        if self._atomic is None:
            return False
        try:
            with connection.cursor() as cur:
                cur.execute('SET LOCAL enable_seqscan = on')   # an outer transaction continues normally
        except Exception:
            pass
        return self._atomic.__exit__(*exc)


def _anchor_q(raw_name: str):
    """Q for the read DRUG WORD(S) — letter-only tokens of ≥4 chars from the cleaned name
    (no digits, not a dosage-form/pack word). Latin reads only; None when there is none."""
    from django.db.models import Q
    if _is_arabic(raw_name):
        return None
    clean = _normalize(extract_components(raw_name).name_clean)
    toks = [t for t in clean.split()
            if len(t) >= 4 and t.isalpha() and t[:3] not in _PREFILTER_SKIP_3
            and not _FORM_LOOKUP.get(t)][:2]
    if not toks:
        return None
    q = Q()
    for t in toks:
        q |= Q(name__icontains=t)
    return q


# ── Public API ────────────────────────────────────────────────────────────────

_FALLBACK_LIMIT = 800   # when prefilter returns too few, scan this many items
# Arabic → Latin sound matching (apps/shortage/phonetic). A switch only so the
# eval_matching benchmark can measure the engine without it (--baseline).
SOUND_MATCHING = True


def find_best_matches(raw_name: str, top_n: int = 3,
                      min_score: float = 0.20, vendor_code: str = '',
                      use_memory: bool = True) -> list[dict]:
    """
    Search the Item catalog for the best matches to raw_name.

    Returns up to top_n dicts:
      {item_id, item_name, item_scientific, item_softech_id,
       item_sale_price, score, strength, form, learned}

    Strategy:
      0. LEARNED corpus first — if a human has confirmed this exact (normalized)
         name before (optionally for this vendor), return it pinned at the top
         with score 1.0. This is the flywheel: repeats resolve instantly.
      1. Prefilter via DB icontains (tolerant of 1-char substitutions + Arabic)
      2. If < 15 candidates pass, do a broader fallback scan (up to _FALLBACK_LIMIT)
    """
    from apps.catalog.models import Item

    # use_memory=False: the matcher alone (no learned aliases / rejections) — used by the
    # eval_matching benchmark so accuracy measures the engine, not what it memorised.
    learned = lookup_alias(raw_name, vendor_code=vendor_code) if use_memory else None

    # Arabic lines: the Latin catalog is reached by SOUND (below, ms-fast); the DB prefilter
    # only needs items whose names CONTAIN the Arabic words (~13% carry an Arabic name). The
    # old transliterated-prefix net (dozens of 3-letter LIKEs → 1200 candidates scored
    # letter-by-letter) is what the sound index replaces — measured faster AND more accurate.
    if SOUND_MATCHING and _is_arabic(raw_name):
        q = _arabic_name_q(raw_name)
    else:
        q = _build_prefilter_q(raw_name)

    # Anchor candidates first: items containing the drug word itself. Pack tokens like
    # "30tab" / "3stripsx10" match thousands of items, and the capped prefilter used to
    # drop the real product before scoring (PREVAGLIP 5MG 30TAB: 2291 prefilter hits,
    # PREVAGLIP not in the first 1200 → BIOPREX won, 2026-10-04).
    anchor_q = _anchor_q(raw_name)
    # Only the columns scoring needs (Item has ~100 columns; fetching 1200 full rows per
    # lookup was most of the query time).
    cols = ('id', 'softech_id', 'name', 'name_scientific', 'pack_price', 'unit_price')
    # .order_by(): Item's default ORDER BY name made PostgreSQL walk all ~51k rows in name
    # order testing every '%…%' pattern (≈1.1 s); unordered, it answers from the trigram
    # indexes (catalog mig 0041). Candidates are re-ranked by score below anyway.
    base = Item.objects.filter(is_active=True).only(*cols).order_by()
    with _trigram_indexes():
        candidates = list(base.filter(anchor_q)[:400]) if anchor_q else []
        if q:
            seen = {c.id for c in candidates}
            candidates += [c for c in base.filter(q).exclude(id__in=seen)[:max(0, 1200 - len(candidates))]]

    # Fallback: if prefilter is too sparse, widen the net
    if len(candidates) < 15:
        # Broaden: take first 3 chars of raw name as prefix across all active items
        broad_tok = _normalize(raw_name)[:3]
        if broad_tok:
            from django.db.models import Q as _Q
            extra = list(
                base
                .filter(
                    _Q(name__icontains=broad_tok) |
                    _Q(name_scientific__icontains=broad_tok)
                )
                .exclude(id__in=[c.id for c in candidates])
                [:_FALLBACK_LIMIT]
            )
            candidates.extend(extra)

        # Last resort: top items by activity if still nothing
        if len(candidates) < 5:
            extra2 = list(
                base
                .exclude(id__in=[c.id for c in candidates])
                [:_FALLBACK_LIMIT]
            )
            candidates.extend(extra2)

    # ARABIC → LATIN BY SOUND (apps/shortage/phonetic): سيريلاك = CERELAC. The catalog is
    # mostly English, so for an Arabic line the strongest evidence is how the name SOUNDS.
    # Sound candidates (ms-fast, in-process skeleton index) join the pool, and every
    # candidate gets a sound score + number / dosage-form agreement.
    arabic = _is_arabic(raw_name) and SOUND_MATCHING
    sound = {}
    q_nums, q_forms, q_words = [], set(), set()
    if arabic:
        from . import phonetic
        try:
            sound = dict(phonetic.candidates(raw_name, limit=60))
            have = {c.id for c in candidates}
            missing = [i for i in sound if i not in have]
            if missing:
                candidates += list(base.filter(id__in=missing))
            q_nums = re.findall(r'\d+(?:\.\d+)?', _normalize(raw_name))
            pq = phonetic.parse_query(raw_name)
            q_forms, q_words = pq['forms'], pq['words']
        except Exception:                                 # never let the hint break matching
            sound = {}

    raw_comp = extract_components(raw_name)

    # Drug-name agreement. Pack descriptors ("5MG 30TAB (3STRIPSX10)") are shared by
    # hundreds of products, so token-overlap + strength bonus can push an UNRELATED
    # product to the 1.0 cap, tied with the real one, and DB order then decided:
    # "PREVAGLIP 5MG 30TAB (3STRIPSX10)" → BIOPREX 5MG 30TAB at 1.00 although
    # PREVAGLIP 5MG 30TAB exists (2026-10-04). A candidate whose name disagrees with
    # the read drug word (head_mismatch — Latin reads only) is penalised, and ties go
    # to the one that agrees.
    HEAD_MISMATCH_PENALTY = 0.15
    # Negative learning: items people REPLACED for this spelling (or a close one) drop
    # 0.2 per rejection, up to 3 (apps/shortage/learning.record_rejection).
    REJECTION_PENALTY = 0.2
    from . import learning
    rejected = learning.rejections(raw_name, vendor_code=vendor_code) if use_memory else {}

    raw_norm_full = _normalize(raw_name)
    scored: list[tuple[float, int, float, dict]] = []
    # A PURE-Arabic line skips the legacy letter-by-letter scorer: its substring scoring
    # rated «نان» 100% against «نانو» (NANO PROTEIN over NAN (1)) and it was the slowest
    # step. Sound (Latin names) + whole-word Arabic (Arabic names) replace it. Mixed lines
    # («Limitless الزايم ماكس») keep it for their Latin words.
    pure_arabic = arabic and not re.search(r'[A-Za-z]', raw_name)
    latin_nums = [] if arabic else re.findall(r'\d+(?:\.\d+)?', _normalize(raw_name))
    q_ar_tokens = _arabic_name_tokens(raw_name) if arabic else []
    for item in candidates:
        if pure_arabic:
            s = 0.0
        else:
            s = score_match(raw_name, item.name, getattr(item, 'name_scientific', '') or '')
        agrees = 1
        if s >= min_score and head_mismatch(raw_name, item.name):
            s, agrees = round(max(0.0, s - HEAD_MISMATCH_PENALTY), 4), 0
        rank_s = None
        if arabic:
            raw_s = max(s, _sound_score(raw_name, item), _arabic_word_score(q_ar_tokens, item)) \
                + _arabic_adjust(item, q_nums, q_forms, q_words)
            rank_s = round(raw_s, 4)                 # uncapped: bonuses must not tie at 1.0
            s = round(min(1.0, max(0.0, raw_s)), 4)
        elif SOUND_MATCHING and latin_nums and s >= min_score:
            # Latin lines: the same strength agreement ("Euthyrox 25mcg" → 25, not 75)
            rank_s = round(s + _arabic_adjust(item, latin_nums, set(), set()), 4)
        if rejected.get(item.id):
            pen = REJECTION_PENALTY * min(rejected[item.id], 3)
            s = round(max(0.0, s - pen), 4)
            rank_s = None if rank_s is None else rank_s - pen
        if s >= min_score:
            # 3rd key: whole-name closeness — breaks ties at the 1.0 cap toward the
            # pack actually written ("…5MG 30TAB" → the 30TAB item, not 10TAB)
            scored.append((s if rank_s is None else rank_s, agrees,
                           _ratio(raw_norm_full, _normalize(item.name)), {
                'item_id':          item.id,
                'item_name':        item.name,
                'item_scientific':  getattr(item, 'name_scientific', '') or '',
                'item_softech_id':  item.softech_id,
                'item_sale_price':  float(item.pack_price or item.unit_price or 0),
                'score':            s,
                'strength':         raw_comp.strength,
                'form':             raw_comp.form,
            }))

    scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    results = [d for _, _, _, d in scored[:top_n]]

    # Pin the learned match at the top, de-duplicating if fuzzy also surfaced it. An
    # EXACT memory always leads. A CLOSE-spelling memory leads too — unless the catalog
    # itself has a near-perfect match for a DIFFERENT product (then the memory is shown
    # second, so a typo-tolerant memory can never hijack a correct exact catalog match).
    if learned:
        rest = [d for d in results if d['item_id'] != learned['item_id']]
        demote = False
        if rest and learned.get('learned_fuzzy') and \
                _ratio(raw_norm_full, _normalize(rest[0]['item_name'])) >= max(0.95, learned.get('similarity', 0)):
            demote = True
        # A CONTRADICTED memory (Latin text; the catalog has a ≥0.9 match for ANOTHER
        # product; the remembered item barely resembles the text) — e.g. «tRENTA» once
        # confirmed as DECLOPHEN while TRENTAL exists (an OCR line misaligned with the pick,
        # invoice session 2026-07-27). Still offered, never pinned first. Arabic memories are
        # exempt: Arabic text never resembles the English name.
        elif rest and not _is_arabic(raw_name) and rest[0]['score'] >= 0.65 \
                and not head_mismatch(raw_name, rest[0]['item_name']) \
                and head_mismatch(raw_name, learned['item_name']) \
                and score_match(raw_name, learned['item_name'], learned.get('item_scientific', '')) < 0.45:
            # the written drug word names the catalog's top item (tRENTA → TRENTAL), not the
            # remembered one (DECLOPHEN), which also fits the text poorly overall
            demote = True
            learned = {**learned, 'contradicted': True}
        results = ([rest[0], learned] + rest[1:]) if demote else ([learned] + rest)
        results = results[:top_n]
    return results


def lookup_alias(raw_name: str, *, vendor_code: str = '') -> dict | None:
    """The remembered item for this spelling — exact (score 1.0, ``learned``) or a close
    spelling (0.90–0.98, ``learned_fuzzy``), net of rejections. See apps/shortage/learning."""
    from . import learning
    return learning.lookup_alias(raw_name, vendor_code=vendor_code)


def learn_alias(raw_name: str, item, *, source: str = 'manual', vendor_code: str = ''):
    """Record/reinforce a confirmed raw-name → Item mapping (repeats raise use_count;
    forgives one earlier rejection). See apps/shortage/learning."""
    from . import learning
    return learning.learn_alias(raw_name, item, source=source, vendor_code=vendor_code)


def dedup_key(raw_name: str) -> str:
    """
    Deduplication key for shortage items.

    Keys on (normalized_drug_name, normalized_strength) so that the same
    drug at DIFFERENT concentrations is treated as DIFFERENT items:
        "نيفيلوب 2.5mg"  →  key: "نيفيلوب||2 5mg"
        "نيفيلوب 5mg"    →  key: "نيفيلوب||5mg"      ← different ✓
        "نيفيلوب 5mg"    →  key: "نيفيلوب||5mg"      ← true duplicate ✗

    If both entries have NO strength, they are considered the same item:
        "نيفيلوب" + "نيفيلوب"  →  same key → duplicate ✗
    """
    comp         = extract_components(raw_name)
    name_part    = _normalize(comp.name_clean)
    strength_part = _normalize(comp.strength or '')
    return f'{name_part}||{strength_part}'


def parse_quantity_from_text(text: str) -> tuple[str, float]:
    """
    Parse 'amoxicillin 500mg 10' → ('amoxicillin 500mg', 10.0)
    Returns (name_part, qty) where qty defaults to 1.0 if not found.
    """
    parts = text.strip().split()
    if len(parts) >= 2:
        try:
            qty = float(parts[-1])
            if 1 <= qty <= 9999:
                return ' '.join(parts[:-1]), qty
        except ValueError:
            pass
    return text.strip(), 1.0


# ── Match-quality guards (flag a forced/spurious match for human review) ────────

_NOTE_KEYWORDS = ('رجاء', 'برجاء', 'الاتصال', 'العميل', 'ملاحظ', 'تبع', 'دكتور',
                  'تليفون', 'موبايل', 'العميد', 'please', 'contact', 'call', 'note')


def looks_non_drug(text: str) -> bool:
    """Heuristic: this OCR'd line is probably NOT a medication — a note, a name, a
    phone number, or a long free-text sentence — so any fuzzy match to it should be
    reviewed rather than trusted (real handwritten lists carry such scribbles)."""
    t = str(text or '').strip()
    if not t:
        return True
    if re.search(r'\d{7,}', t):                 # phone / long id number
        return True
    low = t.lower()
    if any(k in low for k in _NOTE_KEYWORDS):
        return True
    words = [w for w in re.split(r'\s+', t) if len(w) > 1]
    return len(words) >= 6                       # a sentence, not a drug name


def _lead_core(text: str) -> str:
    """First meaningful drug-name token (Arabic transliterated to English), with
    strength/qty stripped — used to check the match latched onto the right word."""
    comp = extract_components(text)
    name = _normalize(comp.name_clean or text)
    if re.search(r'[؀-ۿ]', name):
        name = _ar_to_en_phonetic(name)
    for tok in name.split():
        if len(tok) >= 3 and re.search(r'[a-z]', tok):
            return tok
    return ''


def head_mismatch(read_text: str, item_name: str) -> bool:
    """True when the matched item shares NO token agreeing with the read name's
    leading drug token — i.e. the match latched onto a buried substring
    (Prograf→"…REPROGRAM", Valcyte→"VALSATENS"). Only judged for Latin reads, so
    Arabic transliteration fuzz never causes a false flag."""
    if not re.search(r'[a-zA-Z]', str(read_text or '')):
        return False
    rc = _lead_core(read_text)
    if len(rc) < 4:
        return False
    for tok in _normalize(item_name).split():
        if len(tok) < 3:
            continue
        if tok[:4] == rc[:4] or tok.startswith(rc) or rc.startswith(tok):
            return False
        if _ratio(rc, tok) >= 0.8:
            return False
    return True


def _ratio(a: str, b: str) -> float:
    if _USE_RAPIDFUZZ:
        return _fuzz.ratio(a, b) / 100.0
    return _difflib.SequenceMatcher(None, a, b).ratio()
