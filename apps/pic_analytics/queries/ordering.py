"""
apps/pic_analytics/queries/ordering.py — the whitelisted `ordering` parameter of the paged PIC
Analytics lists (DRF style: `field` ascending, `-field` descending). The server sorts ALL records
before paging, never just the visible page. Empty values (None / '') always come last, whichever
the direction; ties keep the list's default order (the sort is stable).
"""


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
    return v is None or v == ''


def _norm(v):
    return v.casefold() if isinstance(v, str) else v


def sort_items(items, value, desc=False):
    """Stable sort of `items` by value(item); empty values last in both directions."""
    items = list(items)
    full = [(i, _norm(value(i))) for i in items]
    keep = sorted((p for p in full if not _empty(p[1])), key=lambda p: p[1], reverse=desc)
    return [p[0] for p in keep] + [p[0] for p in full if _empty(p[1])]
