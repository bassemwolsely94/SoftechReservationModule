"""
apps/pic_analytics/queries/ordering.py — the whitelisted `ordering` parameter of the paged PIC
Analytics lists (DRF style: `field` ascending, `-field` descending). The server sorts ALL records
before paging, never just the visible page. Empty values (None / '') always come last, whichever
the direction; ties keep the list's default order (the sort is stable).
"""
import re


def parse_ordering(raw, allowed):
    """'-net' -> ('net', True). Empty -> (None, False) (= the list's default order).
    A field that is not in `allowed` is refused (ValueError -> HTTP 400), never silently used."""
    raw = (raw or '').strip()
    if not raw:
        return None, False
    desc = raw.startswith('-')
    key = raw.lstrip('-')
    if key not in allowed:
        raise ValueError('ترتيب غير مدعوم: ' + key)
    return key, desc


def _empty(v):
    return v is None or v == '' or v == ()


# Arabic letters in the order (and equivalence groups) of the browser collator Intl.Collator('ar'), read off
# a real run of it: one group = letters that compare equal. Hamza/waw/ya carriers join the alef group;
# alef-maqsura = ya; ta-marbuta = ta. Alef-madda and alef-wasla behave as alef followed by a tiny extra
# weight (below every letter): 'آمال' < 'احمد' < 'ب', while plain 'ا' < 'آ'.
_GROUPS = 'ءأؤإئا ب پ ةت ث ج چ ح خ د ذ ر ز س ش ص ض ط ظ ع غ ف ڤ ق ك ک گ ػ ؼ ل م ن ه ھ ہ و ىيی ؽ ؾ ؿ'.split()
_RANK = {ch: n for n, g in enumerate(_GROUPS, 1) for ch in g}
_EXPAND = {'آ': [(2, 1), (2, 0.5)], 'ٱ': [(2, 1), (2, 0.7)]}
_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')
_MARKS = re.compile('[ؐ-ًؚ-ٰٟۖ-ۭـ]')      # tashkeel, small marks, tatweel
_CHUNK = re.compile(r'(\d+)')


def _char_key(c):
    if c in _RANK:
        return (2, _RANK[c])            # Arabic letters in collator order
    if c.isalpha():
        return (3, ord(c))              # Latin and the rest come after Arabic (as in the collator)
    return (0, ord(c))                  # space / punctuation come first


def text_key(s):
    """Sort key for text that orders like the browser's Intl.Collator('ar', {numeric: true, sensitivity: 'base'})
    used by the sortable tables (checked in apps/tests/test_pic_ordering.py against a list taken from it):
    diacritics and tatweel are ignored, Latin is case-insensitive, Arabic letters follow the collator's
    equivalence groups (أ/إ/ا equal, ى/ي equal, ...), digit runs compare as numbers (Arabic-Indic digits
    included, so 'فرع 2' < 'فرع 10') and come before letters."""
    s = _MARKS.sub('', s.casefold().translate(_DIGITS))
    key = []
    for chunk in _CHUNK.split(s):
        if chunk.isdigit():
            key.append((1, int(chunk)))
        else:
            for c in chunk:
                key.extend(_EXPAND.get(c) or [_char_key(c)])
    return tuple(key)


def _norm(v):
    return text_key(v) if isinstance(v, str) else v


def sort_items(items, value, desc=False):
    """Stable sort of `items` by value(item); empty values last in both directions."""
    items = list(items)
    full = [(i, _norm(value(i))) for i in items]
    keep = sorted((p for p in full if not _empty(p[1])), key=lambda p: p[1], reverse=desc)
    return [p[0] for p in keep] + [p[0] for p in full if _empty(p[1])]
