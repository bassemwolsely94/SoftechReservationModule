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


# ── the FOLDED name form (item search): Arabic letter variants, case and space runs ───────
# ONE constant builds both the SQL the lookups run and the expression the trigram indexes
# are created on (catalog migration 0044) — PostgreSQL only uses an expression index when
# the query's expression is the same, so never edit one without the other.
FOLD_FROM = 'أإآٱةىؤئ'
FOLD_TO = 'ااااهيوي'
FOLD_SQL = (r"translate(upper(regexp_replace(coalesce({col},''), '\s+', ' ', 'g')), "
            "'" + FOLD_FROM + "', '" + FOLD_TO + "')")

_DIGITS = {ord(c): str(i) for i, c in enumerate('٠١٢٣٤٥٦٧٨٩')}
_DIGITS.update({ord(c): str(i) for i, c in enumerate('۰۱۲۳۴۵۶۷۸۹')})
_TASHKEEL = re.compile('[\u0640\u064B-\u065F\u0670\u06D6-\u06ED]')     # tatweel + harakat
_FOLD_MAP = str.maketrans(FOLD_FROM, FOLD_TO)


def fold_query(q: str) -> str:
    """The query in the same folded form as FOLD_SQL: Arabic digits → 0-9, tashkeel / tatweel
    removed, أإآٱ→ا ة→ه ى→ي ؤ→و ئ→ي, upper case, space runs collapsed, stripped. Wildcards kept."""
    t = (q or '').translate(_DIGITS)
    t = _TASHKEEL.sub('', t).translate(_FOLD_MAP).upper()
    return re.sub(r'\s+', ' ', t).strip()


class _FoldedLookup(Lookup):
    prepare_rhs = False

    def _lhs(self, compiler, connection):
        lhs, params = self.process_lhs(compiler, connection)
        if connection.vendor == 'postgresql':
            return FOLD_SQL.format(col=lhs), params
        return f"UPPER({lhs})", params            # no folding off PostgreSQL (dev / SQLite only)


class _FoldedLike(_FoldedLookup):
    """field__fulike=PATTERN → FOLD(field) LIKE PATTERN ESCAPE '\\' (PATTERN built by
    `pattern(..., fold=True)`; same expression as the trigram index → index scan)."""
    lookup_name = 'fulike'

    def as_sql(self, compiler, connection):
        lhs, lhs_params = self._lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        return f"{lhs} LIKE {rhs} ESCAPE '\\'", lhs_params + rhs_params


class _FoldedRegex(_FoldedLookup):
    """field__fregex=REGEX → FOLD(field) ~ REGEX (PostgreSQL)."""
    lookup_name = 'fregex'

    def as_sql(self, compiler, connection):
        lhs, lhs_params = self._lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        return f"{lhs} ~ {rhs}", lhs_params + rhs_params


Field.register_lookup(_FoldedLike)
Field.register_lookup(_FoldedRegex)


def _esc(s: str) -> str:
    return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def parse(q: str, fold: bool = False) -> dict:
    """{'raw', 'segments' (text between wildcards, in order), 'terms' (every word),
    'wild' (a wildcard was typed)}. fold=True runs `fold_query` first (item name search);
    the default leaves the text as typed for the modules still on `ulike`."""
    raw = re.sub(r'\s+', ' ', (fold_query(q) if fold else (q or '')).strip())
    segments = [s for s in WILD.split(raw) if s.strip()]
    terms = [t for t in re.split(r'[\s*%]+', raw) if t]
    return {'raw': raw, 'segments': segments, 'terms': terms, 'wild': bool(WILD.search(raw))}


def pattern(q: str, fold: bool = True) -> str:
    """'vol*ren*50*tab*' → '%VOL%REN%50%TAB%' (ordered, contains, literal spaces). Folded
    (Arabic forms / digits) by default — pair it with `fulike`; fold=False pairs with `ulike`."""
    p = parse(q, fold)
    return '%' + '%'.join(_esc(s.upper()) for s in p['segments']) + '%' if p['segments'] else '%'


def text_matches(text, q: str) -> bool:
    """Plain-text check with the same rules as the screens' wildcardMatch (utils/wildcard.js):
    the parts in the order typed, OR every word in any order; case-insensitive. Used where a
    server export must apply exactly the filter the grid applied."""
    p = parse(q)
    if not p['segments']:
        return True
    hay = str(text or '').lower()
    at = 0
    for s in p['segments']:
        i = hay.find(s.lower(), at)
        if i < 0:
            break
        at = i + len(s)
    else:
        return True
    return all(t.lower() in hay for t in p['terms'])


def literal_pattern(q: str, fold: bool = True) -> str:
    """Exactly what was typed, % and * taken LITERALLY — the 'exact text first' tier."""
    return '%' + _esc(parse(q, fold)['raw'].upper()) + '%'


def _any(fields, lookup, value) -> Q:
    out = Q()
    for f in fields:
        out |= Q(**{f'{f}__{lookup}': value})
    return out


def ordered_q(q: str, *fields, fold: bool = False) -> Q:
    return _any(fields, 'fulike' if fold else 'ulike', pattern(q, fold))


def any_order_q(q: str, *fields, fold: bool = False) -> Q:
    """Every word somewhere in the same field set, any order («50 voltaren tab»)."""
    terms = parse(q, fold)['terms']
    if len(terms) < 2:
        return Q(pk__in=[])
    out = Q()
    for t in terms:
        out &= _any(fields, 'fulike' if fold else 'ulike', '%' + _esc(t.upper()) + '%')
    return out


def wq(q: str, *fields) -> Q:
    """The filter for ANY search box: the wildcard pattern in order, OR all words in any
    order. With no wildcard and one word it is exactly the old `icontains`."""
    if not parse(q)['segments']:
        return Q()
    return ordered_q(q, *fields, fold=False) | any_order_q(q, *fields, fold=False)


def rank_case(q: str, fields, fold: bool = False) -> Case:
    """0 = literal text, 1 = wildcard in order, 2 = any order."""
    return Case(When(_any(fields, 'fulike' if fold else 'ulike', literal_pattern(q, fold)), then=Value(0)),
                When(ordered_q(q, *fields, fold=fold), then=Value(1)),
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
    """[(item_id, tier)] best first. tier: 'code' (exact code / barcode) · 'code_part' (digits inside a code, last, never POS) · 'learned'
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
    code_part = []
    if not p['wild']:
        # exact `=` (codes / barcodes are digits, nothing to case-fold) so the b-tree
        # indexes are used; __iexact wraps the column in UPPER() and forces a seq scan
        add(base.filter(Q(softech_id=raw) | Q(barcode=raw)).values_list('id', flat=True), 'code')
        add(ItemBarcode.objects.filter(barcode=raw, item__in=base).values_list('item_id', flat=True), 'code')
        if code_prefix and raw.isdigit() and len(raw) >= 4:   # a partial code / barcode → its prefix
            add(base.filter(Q(softech_id__startswith=raw) | Q(barcode__startswith=raw)).order_by('softech_id')
                .values_list('id', flat=True)[:limit], 'code')
        # a code FRAGMENT (inside the code / barcode): collected now, appended LAST — never
        # on the POS path (code_prefix=False keeps codes exact-only)
        if code_prefix and raw.isdigit() and len(raw) >= 2:
            code_part = list(base.filter(Q(softech_id__contains=raw) | Q(barcode__contains=raw))
                             .order_by('softech_id').values_list('id', flat=True)[:limit])
            code_part += list(ItemBarcode.objects.filter(barcode__contains=raw, item__in=base)
                              .order_by('barcode').values_list('item_id', flat=True)[:limit])
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
        add(base.filter(_any(ITEM_FIELDS, 'fulike', literal_pattern(raw))).order_by()
            .values_list('id', flat=True)[:limit], 'literal')
        if len(out) < limit:
            add(base.filter(ordered_q(raw, *ITEM_FIELDS, fold=True)).order_by()
                .values_list('id', flat=True)[:limit * 2], 'ordered')
        if len(out) < limit:
            add(base.filter(any_order_q(raw, *ITEM_FIELDS, fold=True)).order_by()
                .values_list('id', flat=True)[:limit * 2], 'any_order')
    add(sound, 'sound')
    # no catalog text hit (a remembered item alone doesn't count) → typo-tolerant fallback
    if not raw.isdigit() and not any(t not in ('code', 'learned') for _, t in out):
        try:
            add(_approx_ids(WILD.sub(' ', raw), limit, base), 'approx')
        except Exception:
            pass
    add(code_part, 'code_part')
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
