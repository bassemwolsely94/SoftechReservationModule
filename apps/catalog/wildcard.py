"""
apps/catalog/wildcard.py — ONE search behaviour for every item search box in the system.

Owner decision (2026-10-05), SOFTECH-style:
  • `*` and `%` are BOTH wildcards ("any characters"), everywhere:
        vol*ren*50*tab*  =  vol%ren%50%tab  →  VOLTAREN 50MG 20TAB
  • a search always means "contains" (implicit wildcard at both ends), case-insensitive;
  • the parts must appear IN THE ORDER typed; a SPACE is literal (not a wildcard);
  • ranking — results whose name LITERALLY contains exactly what was typed come first
    («1% cream» → the items that really say "1% CREAM" on top), then the wildcard pattern
    in order, then the same words in ANY order (2nd tier: «50 voltaren» → VOLTAREN 50MG);
  • nothing found → the smart matcher's fallback (typos, Arabic by sound, learned memory),
    tagged «تقريبي»; Arabic queries always include sound matches («بالنطق»).

Fast: patterns become  UPPER(name) LIKE '%VOL%REN%50%TAB%'  which PostgreSQL answers from
the trigram indexes (catalog migration 0041).

Use:
    wq(q, 'name', 'name_scientific')        → a Q for any filter box (pattern or any-order)
    filter_and_rank(qs, q, fields)          → filtered + ranked queryset (main lists)
    WildcardSearchFilter                    → drop-in DRF SearchFilter replacement
    item_search(q, limit=…)                 → tiered item ids for pickers / Ctrl+K
"""
from __future__ import annotations

import re

from django.db.models import Case, Field, IntegerField, Lookup, Q, Value, When
from rest_framework.filters import SearchFilter

WILD = re.compile(r'[*%]')


# ── a LIKE lookup that keeps OUR wildcards (Django's icontains escapes % and _) ──────
class _UpperLike(Lookup):
    """field__ulike=PATTERN → UPPER(field::text) LIKE PATTERN ESCAPE '\\'. PATTERN is
    already upper-cased with % wildcards and \\-escaped literal % / _ — built by `pattern`."""
    lookup_name = 'ulike'
    prepare_rhs = False          # the pattern is text even on a number / date column

    def as_sql(self, compiler, connection):
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        if connection.vendor == 'postgresql':
            return f"UPPER({lhs}::text) LIKE {rhs} ESCAPE '\\'", lhs_params + rhs_params
        return f"UPPER({lhs}) LIKE {rhs} ESCAPE '\\'", lhs_params + rhs_params


# every field type: PostgreSQL casts the column to text (numbers, codes, phones alike)
Field.register_lookup(_UpperLike)


def _esc(s: str) -> str:
    return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def parse(q: str) -> dict:
    """{'raw', 'segments' (text between wildcards, in order), 'terms' (every word),
    'wild' (a wildcard was typed)}."""
    raw = re.sub(r'\s+', ' ', (q or '').strip())
    segments = [s for s in WILD.split(raw) if s.strip()]
    terms = [t for t in re.split(r'[\s*%]+', raw) if t]
    return {'raw': raw, 'segments': segments, 'terms': terms, 'wild': bool(WILD.search(raw))}


def pattern(q: str) -> str:
    """'vol*ren*50*tab*' → '%VOL%REN%50%TAB%' (ordered, contains, literal spaces)."""
    p = parse(q)
    return '%' + '%'.join(_esc(s.upper()) for s in p['segments']) + '%' if p['segments'] else '%'


def literal_pattern(q: str) -> str:
    """Exactly what was typed, % and * taken LITERALLY — the 'exact text first' tier."""
    return '%' + _esc(parse(q)['raw'].upper()) + '%'


def _any(fields, lookup, value) -> Q:
    out = Q()
    for f in fields:
        out |= Q(**{f'{f}__{lookup}': value})
    return out


def ordered_q(q: str, *fields) -> Q:
    return _any(fields, 'ulike', pattern(q))


def any_order_q(q: str, *fields) -> Q:
    """Every word somewhere in the same field set, any order («50 voltaren tab»)."""
    terms = parse(q)['terms']
    if len(terms) < 2:
        return Q(pk__in=[])
    out = Q()
    for t in terms:
        out &= _any(fields, 'ulike', '%' + _esc(t.upper()) + '%')
    return out


def wq(q: str, *fields) -> Q:
    """The filter for ANY search box: the wildcard pattern in order, OR all words in any
    order. With no wildcard and one word it is exactly the old `icontains`."""
    if not parse(q)['segments']:
        return Q()
    return ordered_q(q, *fields) | any_order_q(q, *fields)


def rank_case(q: str, fields) -> Case:
    """0 = literal text, 1 = wildcard in order, 2 = any order."""
    return Case(When(_any(fields, 'ulike', literal_pattern(q)), then=Value(0)),
                When(ordered_q(q, *fields), then=Value(1)),
                default=Value(2), output_field=IntegerField())


def filter_and_rank(qs, q: str, fields, *, extra_q: Q | None = None):
    """Filter a queryset with the shared rules and order it literal → ordered → any-order
    (then the queryset's own ordering)."""
    if not parse(q)['segments']:
        return qs
    cond = wq(q, *fields)
    if extra_q is not None:
        cond |= extra_q
    order = list(qs.query.order_by) or list(qs.model._meta.ordering or [])
    return qs.filter(cond).annotate(_wild_rank=rank_case(q, fields)).order_by('_wild_rank', *order)


class WildcardSearchFilter(SearchFilter):
    """DRF SearchFilter with the system's search rules (wildcards, order, ranking). DRF's
    field prefixes (^ = @ $) are ignored — every field is a 'contains' field."""

    def filter_queryset(self, request, queryset, view):
        fields = [f.lstrip('^=@$') for f in (self.get_search_fields(view, request) or [])]
        q = request.query_params.get(self.search_param, '')
        if not fields or not parse(q)['segments']:
            return queryset
        return filter_and_rank(queryset, q, fields).distinct()


# ── item pickers / Ctrl+K: the full tiered search ──────────────────────────────
ITEM_FIELDS = ('name', 'name_scientific')


def item_search(q: str, *, limit: int = 20, active_only: bool = True, code_prefix: bool = True) -> list:
    """[(item_id, tier)] best first. tier: 'code' (exact code / barcode) · 'learned'
    (people confirmed this spelling) · 'literal' · 'ordered' · 'any_order' · 'sound'
    (Arabic by sound) · 'approx' (typo fallback, only when nothing else matched)."""
    from apps.catalog.models import Item, ItemBarcode
    from apps.shortage.matching import _trigram_indexes
    p = parse(q)
    if not p['segments']:
        return []
    base = Item.objects.filter(is_active=True) if active_only else Item.objects.all()
    out, seen = [], set()

    def add(ids, tier):
        for i in ids:
            if i not in seen:
                seen.add(i)
                out.append((i, tier))

    raw = p['raw']
    if not p['wild']:
        add(base.filter(Q(softech_id__iexact=raw) | Q(barcode__iexact=raw)).values_list('id', flat=True), 'code')
        add(ItemBarcode.objects.filter(barcode__iexact=raw, item__in=base).values_list('item_id', flat=True), 'code')
        if code_prefix and raw.isdigit() and len(raw) >= 4:   # a partial code / barcode → its prefix
            add(base.filter(Q(softech_id__startswith=raw) | Q(barcode__startswith=raw)).order_by('softech_id')
                .values_list('id', flat=True)[:limit], 'code')
        try:
            from apps.shortage.learning import learned_item_ids
            add(learned_item_ids(raw), 'learned')
        except Exception:
            pass
    arabic = bool(re.search(r'[؀-ۿ]', raw))
    sound = []
    if arabic:
        try:
            from apps.shortage.phonetic import search_ids
            sound = search_ids(WILD.sub(' ', raw), limit=limit)
        except Exception:
            sound = []
    with _trigram_indexes():
        add(base.filter(_any(ITEM_FIELDS, 'ulike', literal_pattern(raw))).order_by()
            .values_list('id', flat=True)[:limit], 'literal')
        if len(out) < limit:
            add(base.filter(ordered_q(raw, *ITEM_FIELDS)).order_by()
                .values_list('id', flat=True)[:limit * 2], 'ordered')
        if len(out) < limit:
            add(base.filter(any_order_q(raw, *ITEM_FIELDS)).order_by()
                .values_list('id', flat=True)[:limit * 2], 'any_order')
    add(sound, 'sound')
    # no catalog text hit (a remembered item alone doesn't count) → typo-tolerant fallback
    if not raw.isdigit() and not any(t not in ('code', 'learned') for _, t in out):
        try:
            add(_approx_ids(WILD.sub(' ', raw), limit, base), 'approx')
        except Exception:
            pass
    return out[:limit]


_NUM = re.compile(r'\d+(?:\.\d+)?')
APPROX_MIN = 0.6                      # below this a sound-alike is noise, not a typo


def _approx_ids(text: str, limit: int, base) -> list:
    """Typos («voltren 50», «agmentin 1g», «panadool»): items whose brand SOUNDS like the
    first word (consonant skeleton, apps/shortage/phonetic — ms-fast), re-ranked by how
    close the whole name is and whether the typed numbers are in it. Falls back to the
    shared matcher. Deterministic — this only proposes, a person picks."""
    from rapidfuzz import fuzz
    from apps.shortage import phonetic
    cands = phonetic.candidates(text, limit=60, cutoff=0.75)
    if cands:
        names = dict(base.filter(id__in=[i for i, _ in cands]).values_list('id', 'name'))
        nums = _NUM.findall(text)
        # «50MG» and «50 mg» are the same words to the comparisons below
        split = lambda t: re.sub(r'(\d)([A-Z])', r'\1 \2', re.sub(r'([A-Z])(\d)', r'\1 \2', t.upper()))
        up = split(text)
        # the other typed words («extra», «1g», «tab») — each found (spelling-tolerant) in
        # the name counts, so PANADOL EXTRA beats PANADOL for «panadool extra»
        qwords = re.findall(r'[A-Z0-9.]+', up)
        head = qwords[0] if qwords else ''
        words = [w for w in qwords[1:] if len(w) >= 2 and not _NUM.fullmatch(w)]   # numbers: `agree`

        def score(c):
            iid, snd = c
            name = split(names.get(iid) or '')
            have = set(_NUM.findall(name))
            agree = sum(1 for n in nums if n in have) / len(nums) if nums else 0
            toks = re.findall(r'[A-Z0-9.]+', name)
            wagree = (sum(1 for w in words if any(fuzz.ratio(w, t) >= 80 for t in toks)) / len(words)
                      if words else 0)
            # the brand as SPELLED (CATAFLM ≈ CATAFLAM, not ANTIFLAM that only sounds alike)
            spelled = fuzz.ratio(head, toks[0]) / 100 if head and toks else 0
            return (0.35 * snd + 0.15 * spelled + 0.2 * fuzz.token_set_ratio(up, name) / 100
                    + 0.2 * wagree + 0.1 * agree)
        scored = sorted(((score(c), c[0]) for c in cands if c[0] in names), reverse=True)
        ranked = [i for sc, i in scored if sc >= APPROX_MIN]
        if ranked:
            return ranked[:limit]
        if scored:                    # sound-alikes exist but none is close → no guess
            return []
    from apps.shortage.matching import find_best_matches
    return [m['item_id'] for m in find_best_matches(text, top_n=limit, min_score=0.6)]
