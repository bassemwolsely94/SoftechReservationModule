"""
apps/catalog/wildcard.py — ONE search behaviour for every item search box in the system.

Owner decision (2026-10-05), SOFTECH-style:
  • `*` and `%` are BOTH wildcards ("any characters"), everywhere:
        vol*ren*50*tab*  =  vol%ren%50%tab  →  VOLTAREN 50MG 20TAB
  • a search always means "contains" (implicit wildcard at both ends), case-insensitive;
  • the parts must appear IN THE ORDER typed; a SPACE is literal (not a wildcard);
  • ranking (item pickers, design 2026-11-16 §5.2) — the name STARTS with it, then a part
    starts a WORD, then CONTAINS (the literal text — «1% cream» → items that really say
    "1% CREAM" — before the wildcard pattern), then the same words in ANY order («50 voltaren»
    → VOLTAREN 50MG); whole typed numbers lead each tier, then name A→Z; a hit only in the
    scientific name ranks below the same hit in the name. Module filters (`wq`,
    `filter_and_rank`) keep literal → pattern → any order;
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


def starts_pattern(q: str, fold: bool = True) -> str:
    """`pattern` without the leading % — the name STARTS with the typed text / pattern."""
    p = parse(q, fold)
    return '%'.join(_esc(s.upper()) for s in p['segments']) + '%' if p['segments'] else '%'


def re_esc(s: str) -> str:
    """A PostgreSQL-ARE-safe escape of typed text: a backslash before every non-alphanumeric
    ASCII character (in an ARE a backslash + a non-alphanumeric is always that character)."""
    return ''.join('\\' + c if ord(c) < 128 and not c.isalnum() else c for c in s)


WORD_START = '(^|[^A-Z0-9ء-ي])'          # on the FOLDED (upper-case) name


def word_regex(q: str, fold: bool = True) -> str:
    """The first typed part starting a WORD of the name, the other parts after it in order."""
    segs = [s.upper() for s in parse(q, fold)['segments']]
    return WORD_START + '.*'.join(re_esc(s) for s in segs) if segs else ''


def number_regex(n: str) -> str:
    """`n` as a WHOLE number: 5 hits 5MG and 5MG/5MG, not 2.5MG, 50MG or 15MG (a decimal is one
    number, both ways: neither 2 nor 5 is whole inside 2.5)."""
    return r'(^|[^0-9.])' + re_esc(n) + r'($|[^0-9.]|\.($|[^0-9]))'


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


NAME_TIERS = ('starts', 'word', 'contains', 'contains')     # rank % 4; rank 8 = any_order
NAME_WINDOW = 60                      # design §5.2: a fixed candidate window before the trim
NAME_CAP = 300                        # most name candidates ranked per query (speed; see below)


def _rank_name_ids(q: str, base, *, window: int = NAME_WINDOW, starts_only: bool = False) -> list:
    """[(item_id, tier)] for the NAME tiers in ONE query, SOFTECH-ordered:
    0 starts · 1 word (a part starts a word) · 2 contains the literal text · 3 contains the
    pattern · 4–7 the same four found only in name_scientific (one step below, same tier
    names) · 8 any_order. Inside a rank: literal text first (only differs when a wildcard was
    typed), then whole typed numbers (D2 — digits still MATCH anywhere, only the boost needs a
    whole number), then name A→Z. starts_only (D7, 2-letter queries): name starts-with only."""
    p = parse(q, fold=True)
    if not p['segments']:
        return []
    fields = ITEM_FIELDS
    sp, wr = starts_pattern(q), word_regex(q)
    lp, pp = literal_pattern(q), pattern(q)
    num = Value(0, output_field=IntegerField())
    for n in dict.fromkeys(_NUM.findall(p['raw'])):
        num = num + Case(When(name__fregex=number_regex(n), then=Value(1)), default=Value(0),
                         output_field=IntegerField())
    if starts_only:                   # every row is rank 0: whole numbers, then name
        rows = (base.filter(name__fulike=sp).annotate(_num=num).order_by('-_num', 'name', 'id')
                .values_list('id', flat=True)[:window])
        return [(i, 'starts') for i in rows]
    whens = []
    for k, f in enumerate(fields):
        whens += [When(Q(**{f'{f}__fulike': sp}), then=Value(4 * k)),
                  When(Q(**{f'{f}__fregex': wr}), then=Value(4 * k + 1)),
                  When(Q(**{f'{f}__fulike': lp}), then=Value(4 * k + 2)),
                  When(Q(**{f'{f}__fulike': pp}), then=Value(4 * k + 3))]
    rank = Case(*whens, default=Value(8), output_field=IntegerField())
    lit = (Case(When(_any(fields, 'fulike', lp), then=Value(1)), default=Value(0),
                output_field=IntegerField()) if p['wild'] else Value(0, output_field=IntegerField()))
    # Speed (budget 40 ms). The CASE above re-folds the name per arm, so it only runs on a
    # bounded candidate set — never on every match of a broad query («tab», «cream» match
    # thousands):
    #   · every `starts` hit, uncapped (a range scan on the folded prefix b-tree, catalog 0045);
    #   · the first NAME_CAP in-order pattern hits the trigram index returns (unordered, so
    #     the scan stops early);
    #   · any_order is the LAST rank, so its query runs only when the pattern tiers left the
    #     window short (then capped at the window, and only for 2+ words).
    # Exact whenever the pattern matches ≤ NAME_CAP items and any-order ≤ window; past that,
    # the lower tiers rank a sample — still in tier order, whole numbers first, then by name.
    cands = (base.filter(_any(fields, 'fulike', sp)).order_by().values('id')
             .union(base.filter(ordered_q(q, *fields, fold=True)).order_by().values('id')[:NAME_CAP]))
    rows = list(base.filter(id__in=cands).annotate(_rank=rank, _lit=lit, _num=num)
                .order_by('_rank', '-_lit', '-_num', 'name', 'id').values_list('id', '_rank')[:window])
    if len(rows) < window and len(p['terms']) >= 2:
        have = [i for i, _ in rows]
        more = (base.filter(any_order_q(q, *fields, fold=True)).exclude(id__in=have).order_by()
                .values('id')[:window])
        rows += list(base.filter(id__in=more).annotate(_num=num).order_by('-_num', 'name', 'id')
                     .values_list('id', Value(8, output_field=IntegerField()))[:window - len(rows)])
    return [(i, NAME_TIERS[r % 4] if r < 8 else 'any_order') for i, r in rows]


def item_search(q: str, *, limit: int = 20, active_only: bool = True, code_prefix: bool = True) -> list:
    """[(item_id, tier)] best first. tier: 'code' (exact code / barcode) · 'learned' (people
    confirmed this spelling) · 'starts' · 'word' · 'contains' · 'any_order' (the name tiers,
    `_rank_name_ids`) · 'sound' (Arabic by sound) · 'approx' (typo fallback, only when nothing
    else matched) · 'code_part' (digits inside a code — last, only when the rest left room,
    never on the POS path)."""
    from apps.catalog.models import Item, ItemBarcode
    from apps.shortage.matching import _trigram_indexes
    p = parse(q)
    # nothing to search: no letter or digit at all («**», «-», «()»)
    if not p['segments'] or not re.search(r'[^\W_]', p['raw']):
        return []
    # D7: one letter is no search (names need 3 characters, 2 = "starts with"); one digit
    # still goes on to the exact code lookup below
    compact = re.sub(r'[\s*%]', '', fold_query(p['raw']))
    if len(compact) < 2 and not compact.isdigit():
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
        # exact `=` (codes / barcodes are digits, nothing to case-fold) so the b-tree
        # indexes are used; __iexact wraps the column in UPPER() and forces a seq scan
        # ONE statement: each half of the UNION uses its own b-tree
        add(base.filter(Q(softech_id=raw) | Q(barcode=raw)).order_by().values_list('id', flat=True)
            .union(ItemBarcode.objects.filter(barcode=raw, item__in=base).order_by()
                   .values_list('item_id', flat=True)), 'code')
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
    # D7: names need 3 characters — two are "starts with" only; one digit is a code alone
    if len(compact) >= 2:
        # the index forcing matters here: for the capped candidate sub-select (LIMIT) the
        # planner prefers a seq scan that re-folds every name it passes (≈30 ms on «cream»)
        # over the trigram bitmap (≈3 ms) — it doesn't know how dear the fold expression is
        with _trigram_indexes():
            for i, tier in _rank_name_ids(raw, base, window=max(NAME_WINDOW, limit),
                                          starts_only=len(compact) < 3):
                add((i,), tier)
    add(sound, 'sound')
    # no catalog text hit (a remembered item alone doesn't count) → typo-tolerant fallback
    if not raw.isdigit() and not any(t not in ('code', 'learned') for _, t in out):
        try:
            add(_approx_ids(WILD.sub(' ', raw), limit, base), 'approx')
        except Exception:
            pass
    # a code FRAGMENT (inside the code / barcode) — last, and only when the tiers above left
    # room: `contains` on a code can't use the b-tree, so it is a scan we skip when we can.
    # Never on the POS path (code_prefix=False keeps codes exact-only).
    if code_prefix and not p['wild'] and raw.isdigit() and len(raw) >= 2 and len(out) < limit:
        add(base.filter(Q(softech_id__contains=raw) | Q(barcode__contains=raw))
            .order_by('softech_id').values_list('id', flat=True)[:limit], 'code_part')
        if len(out) < limit:
            add(ItemBarcode.objects.filter(barcode__contains=raw, item__in=base)
                .order_by('barcode').values_list('item_id', flat=True)[:limit], 'code_part')
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
