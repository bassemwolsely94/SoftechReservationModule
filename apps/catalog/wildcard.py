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

Fast: item patterns become  FOLD(name) LIKE '%VOL%REN%50%TAB%'  (FOLD_SQL below), answered
from the trigram / prefix indexes on that folded expression (catalog migrations 0044 / 0045);
the modules' `ulike` filters run UPPER(col) LIKE … on the older trigram indexes.

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


# ── the FOLDED name form (item search): Arabic letter variants, tashkeel, case, space runs ─
# ONE constant builds the SQL the lookups run. The indexes on it (catalog migration 0047, which
# rebuilt those of 0044 / 0045) hold a FROZEN copy of this expression — PostgreSQL only uses
# an expression index when
# the query's expression is the same, so a change here needs a new migration that rebuilds
# those indexes (test_wildcard_search.FoldSqlFrozenTests fails until it exists).
# translate() DELETES the characters of its `from` list that have no partner in `to`: the
# tashkeel / tatweel (_TASHKEEL_CHARS) go that way. Arabic-Indic digits are NOT folded in the
# stored name — the real catalog has none (checked 2026-11-16); fold_query folds them in the
# query only.
FOLD_FROM = 'أإآٱةىؤئ'
FOLD_TO = 'ااااهيوي'
# Only the marks the catalog holds (checked 2026-11-16): tatweel U+0640 and the harakat
# U+064B–U+0652. translate() scans its whole from-list for every character of every name, so
# the earlier ~55-mark list (Quranic marks, superscript alef …) slowed every folded LIKE
# ('%1%cream' through item_search on the real catalog: ≈92 ms with it, ≈57 ms without).
_TASHKEEL_CHARS = ''.join(map(chr, [0x0640, *range(0x064B, 0x0653)]))
# Marks are deleted BEFORE the space runs collapse (as fold_query does): a word made of marks
# alone between two spaces must leave one space, not two.
FOLD_SQL = ("regexp_replace(translate(upper(coalesce({col},'')), "
            "'" + FOLD_FROM + _TASHKEEL_CHARS + "', '" + FOLD_TO + r"'), '\s+', ' ', 'g')")

_DIGITS = {ord(c): str(i) for i, c in enumerate('٠١٢٣٤٥٦٧٨٩')}
_DIGITS.update({ord(c): str(i) for i, c in enumerate('۰۱۲۳۴۵۶۷۸۹')})
_TASHKEEL = re.compile('[' + _TASHKEEL_CHARS + ']')
_FOLD_MAP = str.maketrans(FOLD_FROM, FOLD_TO)


def fold_query(q: str) -> str:
    """The query in the folded form FOLD_SQL gives a stored name: tashkeel / tatweel removed,
    أإآٱ→ا ة→ه ى→ي ؤ→و ئ→ي, upper case, space runs collapsed. On the query side only: Arabic-Indic
    digits → 0-9 (stored names hold none — see FOLD_SQL) and the ends stripped. Wildcards kept.
    (Python's \\s and PostgreSQL's \\s may differ on rare spaces such as NBSP.)"""
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


LETTERS = 'A-Zء-ي'                       # the letter class of the FOLDED (upper-case) name
WORD_START = f'(^|[^{LETTERS}0-9])'     # on the FOLDED (upper-case) name


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


def crosses_to_many(model, field: str) -> bool:
    """True when the search path `field` walks a to-many relation (reverse FK / M2M), e.g.
    transfers' `items__item__name` — one parent then joins to many rows."""
    for part in field.split('__'):
        try:
            f = model._meta.get_field(part)
        except Exception:                     # a lookup / transform, or not a model field
            return False
        if f.many_to_many or f.one_to_many:
            return True
        if not f.is_relation or f.related_model is None:
            return False
        model = f.related_model
    return False


def _to_many_rank(qs, q: str, fields) -> Case:
    """rank_case for a search reaching to-many fields: each tier is a `pk IN (subquery)` so the
    parent is not joined to its lines — one row per parent, with its BEST tier."""
    base = qs.model._base_manager.all()

    def pks(cond):
        return base.filter(cond).values('pk')
    return Case(When(pk__in=pks(_any(fields, 'ulike', literal_pattern(q, False))), then=Value(0)),
                When(pk__in=pks(ordered_q(q, *fields, fold=False)), then=Value(1)),
                default=Value(2), output_field=IntegerField())


def filter_and_rank(qs, q: str, fields, *, extra_q: Q | None = None):
    """Filter a queryset with the shared rules and order it literal → ordered → any-order
    (then the queryset's own ordering).

    When a search field crosses a to-many relation the match and the rank run as `pk IN
    (subquery)`, so a parent whose lines match at different tiers comes back ONCE with its best
    tier (a join would give one row per matching line and inflate GROUP BY counts). Single-valued
    fields keep the plain filter + CASE, unchanged."""
    if not parse(q)['segments']:
        return qs
    order = list(qs.query.order_by) or list(qs.model._meta.ordering or [])
    if any(crosses_to_many(qs.model, f) for f in fields):
        cond = Q(pk__in=qs.model._base_manager.filter(wq(q, *fields)).values('pk'))
        if extra_q is not None:
            cond |= extra_q
        return qs.filter(cond).annotate(_wild_rank=_to_many_rank(qs, q, fields)).order_by('_wild_rank', *order)
    cond = wq(q, *fields)
    if extra_q is not None:
        cond |= extra_q
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


def item_search(q: str, *, limit: int = 20, active_only: bool = True, code_prefix: bool = True,
                base=None) -> list:
    """[(item_id, tier)] best first. tier: 'code' (exact code / barcode) · 'code_prefix' (4+
    digits that START a code / barcode — right after 'code', never on the POS path; a scan must
    never take it as exact) · 'learned' (people confirmed this spelling) · 'starts' · 'word' ·
    'contains' · 'any_order' (the name tiers, `_rank_name_ids`) · 'synonym' (Appendix A table,
    whole word / unit) · 'sound' (Arabic by sound) · 'approx' (typo fallback, only when nothing
    else matched) · 'code_part' (digits inside a code — last, only when the rest left room,
    never on the POS path).

    `base`: an Item queryset every tier searches inside (default: the whole catalog) — the item
    list passes its other filters here so `limit` cuts AFTER them, not before. `active_only`
    still applies on top of it."""
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
    narrowed = base is not None
    base = (base if narrowed else Item.objects.all()).order_by()
    if active_only:
        base = base.filter(is_active=True)
    out, seen = [], set()

    def within(ids):
        # the learned memory and the sound index return ids from the whole catalog: keep the
        # ones inside a caller's `base` (the default base keeps them as before)
        ids = list(ids)
        if not narrowed or not ids:
            return ids
        keep = set(base.filter(id__in=ids).values_list('id', flat=True))
        return [i for i in ids if i in keep]

    in_base = {}                     # item id → inside `base`, asked once per id per search

    def keep(ids):
        ask = [i for i in ids if i not in in_base]
        if ask:
            have = set(base.filter(id__in=ask).values_list('id', flat=True))
            in_base.update((i, i in have) for i in ask)
        return {i for i in ids if in_base[i]}

    def sound_within():
        # the in-memory sound index keeps its best candidates per lookup: with a narrowed
        # `base` it must pick them from base's items only, or a filtered item ranked below the
        # whole catalog's cut is lost. Asked lazily (phonetic.candidates' callable `within`):
        # one query for the index's hits only, never base's whole id list (with «متوفر» that
        # list cost 0.4–0.7 s, 2026-11-17); None (unfiltered) = the index's own path, no query
        return keep if narrowed else None

    def add(ids, tier):
        for i in ids:
            if i not in seen:
                seen.add(i)
                out.append((i, tier))

    # Arabic-Indic digits → 0-9 first: the code / prefix / code_part lookups compare `raw`
    # itself (unfolded), so «٣٦٩٠» must become 3690 to hit code 3690
    raw = p['raw'].translate(_DIGITS)
    if not p['wild']:
        # exact `=` / `IN` so the b-tree indexes are used; __iexact wraps the column in UPPER()
        # and forces a seq scan. Codes are digits, but a few barcodes carry letters (one real
        # one is lower case): the typed text, its upper or its lower case. ONE statement: each
        # half of the UNION uses its own b-tree
        exact = list(dict.fromkeys((raw, raw.upper(), raw.lower())))
        add(base.filter(Q(softech_id__in=exact) | Q(barcode__in=exact)).order_by()
            .values_list('id', flat=True)
            .union(ItemBarcode.objects.filter(barcode__in=exact, item__in=base).order_by()
                   .values_list('item_id', flat=True)), 'code')
        if code_prefix and raw.isdigit() and len(raw) >= 4:   # a partial code / barcode → its prefix
            add(base.filter(Q(softech_id__startswith=raw) | Q(barcode__startswith=raw)).order_by('softech_id')
                .values_list('id', flat=True)[:limit], 'code_prefix')
        try:
            from apps.shortage.learning import learned_item_ids
            add(within(learned_item_ids(raw)), 'learned')
        except Exception:
            pass
    # D7: names need 3 characters — two are "starts with" only; one digit is a code alone
    if len(compact) >= 2:
        # the index forcing matters here: for the capped candidate sub-select (LIMIT) the
        # planner prefers a seq scan that re-folds every name it passes (≈30 ms on «cream»)
        # over the trigram bitmap (≈3 ms) — it doesn't know how dear the fold expression is
        with _trigram_indexes():
            for i, tier in _rank_name_ids(raw, base, window=max(NAME_WINDOW, limit),
                                          starts_only=len(compact) < 3):
                add((i,), tier)
    # Appendix A synonyms (syp → SYRUP, جم → G/GM): only when the name tiers left the window
    # short (the window, not `limit`: synonym rows fill the same candidate window the name
    # tiers use), and — D7 — never for a 2-character query («mg»,
    # «ml», «جم» are "starts with" only)
    if len(compact) >= 3 and len(out) < max(NAME_WINDOW, limit):
        try:
            from apps.catalog.search_synonyms import expand_terms
            exp = expand_terms(parse(raw, fold=True)['terms'])
        except Exception:
            exp = None
        if exp is not None:
            with _trigram_indexes():
                add(_synonym_ids(exp, base, [i for i, _ in out], max(NAME_WINDOW, limit) - len(out)),
                    'synonym')
    # Arabic by sound — only when the tiers above left room: what it adds goes after them, so
    # past `limit` it would be cut anyway. The in-memory sound index (phonetic.quick_ids), not
    # the full shared matcher: its learned memory is the `learned` tier above.
    if len(out) < limit and re.search(r'[؀-ۿ]', raw):
        try:
            from apps.shortage.phonetic import quick_ids
            add(within(quick_ids(WILD.sub(' ', raw), limit=limit, within=sound_within())), 'sound')
        except Exception:
            pass
    # the active ingredient (diclofenac → CATAFLAM): after every brand/name hit, only while the
    # window has room, never a number. An ingredient hit is a real match — approx stays off.
    if not raw.isdigit() and len(compact) >= 3 and len(out) < NAME_WINDOW:
        try:
            add(_ingredient_ids(raw, base, [i for i, _ in out], NAME_WINDOW - len(out)),
                'ingredient')
        except Exception:
            pass
    # no catalog text hit (a remembered item alone doesn't count) → typo-tolerant fallback
    if not raw.isdigit() and not any(t not in ('code', 'code_prefix', 'learned') for _, t in out):
        try:
            # within(): its matcher fallback searches the whole catalog
            add(within(_approx_ids(WILD.sub(' ', raw), limit, base, within=sound_within())), 'approx')
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


ATC_CODE = re.compile(r'^[A-Z]\d{2}([A-Z]{1,2}(\d{2})?)?$')


def _ingredient_pairs(q: str, base, room: int, have=()):
    """[(item_id, ActiveIngredient.name)] — items whose mapped active ingredient matches the typed
    text / pattern (the name is a plain column: `ulike` with the unfolded pattern). Primary
    ingredient first, then item name; one row per item."""
    from apps.chronic.models import ItemIngredientMap
    if room <= 0:
        return []
    cond = Q(active_ingredient__name__ulike=pattern(q, fold=False))
    code = fold_query(q).strip().upper()
    if ATC_CODE.match(code):                  # A10 / A10B / A10BA02 → by ATC prefix too
        cond |= Q(active_ingredient__atc_code__istartswith=code)
    rows = (ItemIngredientMap.objects
            .filter(cond, item__in=base)
            .exclude(item_id__in=list(have))
            .order_by('-is_primary', 'item__name', 'item_id', 'active_ingredient__name')
            .values_list('item_id', 'active_ingredient__name')[:room * 3])
    seen, out = set(), []
    for iid, name in rows:
        if iid not in seen:
            seen.add(iid)
            out.append((iid, name))
    return out[:room]


def _ingredient_ids(q: str, base, have, room: int) -> list:
    return [i for i, _ in _ingredient_pairs(q, base, room, have)]


def ingredient_names(q: str, item_ids) -> dict:
    """{item_id: matched ActiveIngredient name} for the picker's «المادة الفعالة» chip."""
    from apps.catalog.models import Item
    pairs = _ingredient_pairs(q, Item.objects.filter(id__in=list(item_ids)), len(item_ids))
    return dict(pairs)


def _synonym_ids(expanded, base, have, room: int) -> list:
    """Items where EVERY term matches: the typed text anywhere in the folded name, OR one of its
    canonical forms as a whole word / a unit glued to a number (`500MG`, `1G`; never inside a
    longer word — «G» is not GRAPE). A term that is its own canonical (g, mg, tab…) matches only
    by the whole-word rule, or «g» would hit every name containing a G. `expanded` is
    `search_synonyms.expand_terms`: [(typed, canonical forms)]."""
    cond = Q()
    for typed, canon in expanded:
        t = Q()
        if typed not in canon:
            t |= Q(name__fulike='%' + _esc(typed) + '%')
        if canon:
            t |= Q(name__fregex=f'(^|[^{LETTERS}])(' + '|'.join(re_esc(c) for c in canon)
                   + f')($|[^{LETTERS}])')
        cond &= t
    if room <= 0:
        return []
    return list(base.filter(cond).exclude(id__in=have).order_by('name', 'id')
                .values_list('id', flat=True)[:room])


_NUM = re.compile(r'\d+(?:\.\d+)?')
APPROX_MIN = 0.6                      # below this a sound-alike is noise, not a typo


def _approx_ids(text: str, limit: int, base, *, within=None) -> list:
    """Typos («voltren 50», «agmentin 1g», «panadool»): items whose brand SOUNDS like the
    first word (consonant skeleton, apps/shortage/phonetic — ms-fast), re-ranked by how
    close the whole name is and whether the typed numbers are in it. Falls back to the
    shared matcher. Deterministic — this only proposes, a person picks. `within`: base's
    item ids when a filter narrows it (phonetic.candidates picks its best from them only)."""
    from rapidfuzz import fuzz
    from apps.shortage import phonetic
    cands = phonetic.candidates(text, limit=60, cutoff=0.75, within=within)
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
            # the word / number terms count only when such words / numbers were typed —
            # otherwise «panadool» alone could never reach APPROX_MIN; dividing by the
            # weights in use keeps the scale 0..1
            sc = 0.35 * snd + 0.15 * spelled + 0.2 * fuzz.token_set_ratio(up, name) / 100
            used = 0.7
            if words:
                sc, used = sc + 0.2 * wagree, used + 0.2
            if nums:
                sc, used = sc + 0.1 * agree, used + 0.1
            return sc / used
        scored = sorted(((score(c), c[0]) for c in cands if c[0] in names), reverse=True)
        ranked = [i for sc, i in scored if sc >= APPROX_MIN]
        if ranked:
            return ranked[:limit]
        if scored:                    # sound-alikes exist but none is close → no guess
            return []
    from apps.shortage.matching import find_best_matches
    return [m['item_id'] for m in find_best_matches(text, top_n=limit, min_score=0.6)]
