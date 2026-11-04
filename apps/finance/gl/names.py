"""Arabic name normalisation used to match finance's group / account spellings."""
import re

_DIACRITICS = re.compile('[ً-ٰٟ]')  # tanween, fatha, damma, kasra, shadda, sukun...
_TRANS = str.maketrans({
    'ة': 'ه', 'ى': 'ي', 'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ـ': None,
})


def normalize_ar(s) -> str:
    """strip, collapse whitespace, ة→ه, ى→ي, أ/إ/آ→ا, drop tatweel (and diacritics)."""
    s = _DIACRITICS.sub('', str(s or '')).translate(_TRANS)
    return re.sub(r'\s+', ' ', s).strip()
