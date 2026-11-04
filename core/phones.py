"""
core/phones.py — the ONE phone-matching rule for every module (2026-11-04).

The Egyptian number rule itself lives in apps/pbx/cdr.py (phone_key / national_number /
digits_only — tested in test_pbx_numbers); this module re-exports it and adds the two things
every customer lookup needs:

  • phone_q(raw, fields)  — a DB prefilter (`<field>__endswith` the key's last 8 digits, OR'd),
                            or None when the number is too short to identify anyone (< 7 digits).
                            None means "not found": never run the lookup on nothing — an empty
                            `endswith('')` matches EVERY customer.
  • same_phone(a, b)      — exact equality of the national keys ('+20 100-000-0010' ==
                            '01000000010'; Cairo '24842067' == '0224842067').

A lookup prefilters with phone_q and confirms each candidate with same_phone before it attaches
or returns anything — matching() / first_match() do both.
"""
from django.db.models import Q

from apps.pbx.cdr import digits_only, national_number, phone_key  # noqa: F401  (re-exported)

PREFILTER_DIGITS = 8          # Cairo landlines are stored with or without their 02 → last 8
MAX_CANDIDATES = 200          # prefilter rows confirmed per field (a real number has a handful)
DEFAULT_FIELDS = ('phone', 'phone_alt')


def phone_q(raw, fields=DEFAULT_FIELDS):
    """Q prefilter for `raw` on `fields` (OR), or None when `raw` has no usable number."""
    key = phone_key(raw)
    if not key:
        return None
    tail = key[-PREFILTER_DIGITS:]
    q = Q()
    for f in fields:
        q |= Q(**{f'{f}__endswith': tail})
    return q


def same_phone(a, b) -> bool:
    """True when both are the same usable number; '' / short codes never match anything."""
    ka = phone_key(a)
    return bool(ka) and ka == phone_key(b)


def _value(obj, path):
    for part in path.split('__'):
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return obj


def matching(qs, raw, fields=DEFAULT_FIELDS, limit=None):
    """Rows of `qs` (its own order kept) whose any of `fields` is exactly `raw`'s number."""
    q = phone_q(raw, fields)
    if q is None:
        return []
    if not qs.ordered:
        qs = qs.order_by('pk')
    out = []
    for obj in qs.filter(q)[:MAX_CANDIDATES]:
        if any(same_phone(_value(obj, f), raw) for f in fields):
            out.append(obj)
            if limit and len(out) >= limit:
                break
    return out


def first_match(qs, raw, fields=DEFAULT_FIELDS):
    """First row matching `raw`, trying `fields` in priority order (phone before phone_alt)."""
    for f in fields:
        found = matching(qs, raw, (f,), limit=1)
        if found:
            return found[0]
    return None
