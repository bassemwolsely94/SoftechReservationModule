"""
apps/shortage/learning.py — the system-wide "gets better every time" memory for catalog
matching. Every screen that matches free text to catalog items goes through
apps/shortage/matching.find_best_matches (shortage lists · supplier availability inbox ·
WhatsApp branch requests · supplier invoice OCR · POS prescription OCR · vision OCR), so
learning here improves all of them at once.

Three kinds of memory, all deterministic (no model decides; people's confirmations do):

  1. ItemAlias          spelling → item. Every confirmation adds / reinforces (use_count).
  2. ItemAliasRejection spelling ✗ item. A person REPLACED the machine's suggestion: that
                        item is pushed down for the spelling next time, and an alias that
                        pointed there loses strength. Confirming it later forgives one.
  3. ItemAliasGroup     spelling → several items ("بيبيلاك 1....2....3" → BEBELAC 1/2/3).

PROGRESSIVE + SPELLING-TOLERANT: a memory also answers CLOSE spellings — a typo, a missing
letter, extra dots/spaces, Arabic-Indic digits — when
  • the text is ≥ FUZZY_MIN similar (rapidfuzz ratio / token-sort on the normalized key), AND
  • the NUMBERS are identical ("aricept 5" never borrows "aricept 10"), AND
  • no other memory for a different item is about as close (then nothing is guessed).
A close-spelling memory comes back as a strong suggestion (score 0.90–0.98, `learned_fuzzy`),
never as the 1.0 "seen exactly this before" certainty of an exact memory.
"""
from __future__ import annotations

import re

FUZZY_MIN = 0.86          # minimum similarity for a close-spelling memory to apply
FUZZY_TIE = 0.02          # a rival memory for another item this close → don't guess
TRGM_FLOOR = 0.3          # DB trigram prefilter


def key(text: str) -> str:
    """The memory key: the matcher's normalization (Arabic letter forms, case,
    punctuation, Arabic-Indic digits folded)."""
    from .matching import _normalize
    return _normalize(text)


def _numbers(k: str) -> list:
    return sorted(re.findall(r'\d+(?:\.\d+)?', k))


def _similarity(a: str, b: str) -> float:
    try:
        from rapidfuzz import fuzz
        return max(fuzz.ratio(a, b), fuzz.token_sort_ratio(a, b)) / 100.0
    except ImportError:                                   # pragma: no cover
        import difflib
        return difflib.SequenceMatcher(None, a, b).ratio()


def _scopes(vendor_code: str) -> list:
    return [vendor_code, ''] if vendor_code else ['']


def _close_rows(model, k: str, vendor_code: str = '', *, limit: int = 30) -> list:
    """(row, similarity) for memories whose key is a CLOSE spelling of k: same numbers,
    similarity ≥ FUZZY_MIN, best first. Exact keys are included (similarity 1.0)."""
    from django.contrib.postgres.search import TrigramSimilarity
    qs = model.objects.filter(vendor_code__in=_scopes(vendor_code))
    try:
        rows = list(qs.annotate(_sim=TrigramSimilarity('normalized', k))
                    .filter(_sim__gte=TRGM_FLOOR).order_by('-_sim')[:limit])
    except Exception:                                      # no pg_trgm → small-table scan
        rows = list(qs[:2000])
    nums = _numbers(k)
    out = []
    for r in rows:
        if _numbers(r.normalized) != nums:
            continue
        sim = 1.0 if r.normalized == k else _similarity(k, r.normalized)
        if sim >= FUZZY_MIN:
            out.append((r, sim))
    out.sort(key=lambda x: (x[1], x[0].vendor_code != '', getattr(x[0], 'use_count', 0)), reverse=True)
    return out


def _fuzzy_score(sim: float) -> float:
    return round(min(0.98, 0.90 + 0.08 * max(0.0, (sim - FUZZY_MIN) / (1 - FUZZY_MIN))), 4)


# ── 2. rejections ───────────────────────────────────────────────────────────────
def rejections(raw_name: str, *, vendor_code: str = '') -> dict:
    """{item_id: rejection count} for this spelling and close spellings."""
    from apps.catalog.models import ItemAliasRejection
    k = key(raw_name)
    if not k:
        return {}
    out = {}
    for r, _sim in _close_rows(ItemAliasRejection, k, vendor_code):
        out[r.item_id] = out.get(r.item_id, 0) + r.count
    return out


def record_rejection(raw_name: str, item, *, vendor_code: str = '', source: str = '') -> None:
    """A person replaced the machine's suggestion `item` for `raw_name`. Pushes it down for
    this spelling next time and weakens (eventually removes) an alias that pointed to it."""
    from django.db.models import F
    from apps.catalog.models import ItemAlias, ItemAliasRejection
    k = key(raw_name)
    item_id = getattr(item, 'pk', item)
    if not k or not item_id:
        return
    obj, created = ItemAliasRejection.objects.get_or_create(
        normalized=k, vendor_code=vendor_code or '', item_id=item_id,
        defaults={'sample_raw': (raw_name or '')[:300], 'source': source[:20]})
    if not created:
        ItemAliasRejection.objects.filter(pk=obj.pk).update(count=F('count') + 1)
    for a in ItemAlias.objects.filter(normalized=k, vendor_code__in=_scopes(vendor_code), item_id=item_id):
        if a.use_count <= 1:
            a.delete()
        else:
            a.use_count -= 1
            a.save(update_fields=['use_count', 'updated_at'])


def _forgive(k: str, vendor_code: str, item_id) -> None:
    from apps.catalog.models import ItemAliasRejection
    for r in ItemAliasRejection.objects.filter(normalized=k, vendor_code=vendor_code or '', item_id=item_id):
        if r.count <= 1:
            r.delete()
        else:
            r.count -= 1
            r.save(update_fields=['count', 'updated_at'])


# ── 1. single aliases ───────────────────────────────────────────────────────────
def learn_alias(raw_name: str, item, *, source: str = 'manual', vendor_code: str = ''):
    """Record / reinforce a confirmed spelling → item (idempotent per item; repeats raise
    use_count). Forgives one earlier rejection of the same pair."""
    from apps.catalog.models import ItemAlias
    k = key(raw_name)
    if not k or item is None:
        return None
    item_id = getattr(item, 'pk', item)
    alias, created = ItemAlias.objects.get_or_create(
        normalized=k, vendor_code=vendor_code or '', item_id=item_id,
        defaults={'source': source[:20], 'sample_raw': (raw_name or '')[:300]})
    if not created:
        alias.use_count += 1
        alias.sample_raw = (raw_name or '')[:300]
        alias.save(update_fields=['use_count', 'sample_raw', 'updated_at'])
    _forgive(k, vendor_code, item_id)
    return alias


def _alias_dict(alias, raw_name: str, score: float, *, fuzzy: bool, sim: float = 1.0) -> dict:
    from .matching import extract_components
    item = alias.item
    comp = extract_components(raw_name)
    return {'item_id': item.id, 'item_name': item.name,
            'item_scientific': getattr(item, 'name_scientific', '') or '',
            'item_softech_id': item.softech_id,
            'item_sale_price': float(item.pack_price or item.unit_price or 0),
            'score': score, 'strength': comp.strength, 'form': comp.form,
            'learned': not fuzzy, 'learned_fuzzy': fuzzy, 'similarity': round(sim, 3),
            'learned_from': alias.sample_raw, 'use_count': alias.use_count}


def lookup_alias(raw_name: str, *, vendor_code: str = '') -> dict | None:
    """The remembered item for this spelling. Exact memory first (score 1.0, `learned`):
    supplier-scoped beats global, then strength = use_count − rejections. Otherwise a CLOSE
    spelling memory (score 0.90–0.98, `learned_fuzzy`) when unambiguous. None if nothing."""
    from apps.catalog.models import ItemAlias
    k = key(raw_name)
    if not k:
        return None
    rej = rejections(raw_name, vendor_code=vendor_code)
    rows = [(a, s) for a, s in _close_rows(ItemAlias, k, vendor_code)
            if getattr(a.item, 'is_active', True)]
    if not rows:
        return None

    def strength(a):
        return a.use_count - rej.get(a.item_id, 0)

    exact = [a for a, s in rows if s == 1.0 and strength(a) > 0]
    if exact:
        exact.sort(key=lambda a: (a.vendor_code != '', strength(a)), reverse=True)
        return _alias_dict(exact[0], raw_name, 1.0, fuzzy=False)
    close = [(a, s) for a, s in rows if strength(a) > 0]
    if not close:
        return None
    best, sim = close[0]
    if any(a.item_id != best.item_id and sim - s <= FUZZY_TIE for a, s in close[1:]):
        return None                                        # two different items equally close
    return _alias_dict(best, raw_name, _fuzzy_score(sim), fuzzy=True, sim=sim)


# ── 3. one-to-many groups ───────────────────────────────────────────────────────
def _items_key(ids) -> str:
    return ','.join(str(i) for i in sorted({int(i) for i in ids}))


def learn_alias_group(raw_name: str, items, *, source: str = 'manual', vendor_code: str = ''):
    """Record / reinforce "this spelling = these several items" (order kept)."""
    from apps.catalog.models import ItemAliasGroup
    k = key(raw_name)
    ids = list(dict.fromkeys(int(getattr(i, 'pk', i)) for i in items))
    if not k or len(ids) < 2:
        return None
    g, created = ItemAliasGroup.objects.get_or_create(
        normalized=k, vendor_code=vendor_code or '', items_key=_items_key(ids),
        defaults={'item_ids': ids, 'source': source[:20], 'sample_raw': (raw_name or '')[:300]})
    if not created:
        g.use_count += 1
        g.item_ids, g.sample_raw = ids, (raw_name or '')[:300]
        g.save(update_fields=['use_count', 'item_ids', 'sample_raw', 'updated_at'])
    return g


def unlearn_alias_group(raw_name: str, items, *, vendor_code: str = '') -> None:
    """A person changed a suggested group — weaken (eventually remove) that memory."""
    from apps.catalog.models import ItemAliasGroup
    k = key(raw_name)
    for g in ItemAliasGroup.objects.filter(normalized=k, vendor_code=vendor_code or '',
                                           items_key=_items_key(getattr(i, 'pk', i) for i in items)):
        if g.use_count <= 1:
            g.delete()
        else:
            g.use_count -= 1
            g.save(update_fields=['use_count', 'updated_at'])


def lookup_alias_group(raw_name: str, *, vendor_code: str = '') -> dict | None:
    """The remembered SEVERAL items for this spelling — only when that memory is at least
    as strong as the single-item memory for the same spelling (the latest habit wins after
    repeats). {'item_ids', 'score', 'learned_fuzzy', 'use_count', 'learned_from'} or None."""
    from apps.catalog.models import Item, ItemAliasGroup
    k = key(raw_name)
    if not k:
        return None
    rows = _close_rows(ItemAliasGroup, k, vendor_code)
    if not rows:
        return None
    best, sim = rows[0]
    if any(g.items_key != best.items_key and sim - s <= FUZZY_TIE for g, s in rows[1:]):
        return None
    single = lookup_alias(raw_name, vendor_code=vendor_code)
    if single and single.get('use_count', 0) > best.use_count:
        return None                                        # the single-item habit is stronger
    active = set(Item.objects.filter(id__in=best.item_ids, is_active=True).values_list('id', flat=True))
    ids = [i for i in best.item_ids if i in active]
    if len(ids) < 2:
        return None
    return {'item_ids': ids, 'score': 1.0 if sim == 1.0 else _fuzzy_score(sim),
            'learned_fuzzy': sim < 1.0, 'use_count': best.use_count, 'learned_from': best.sample_raw}


def learned_item_ids(raw_name: str, *, vendor_code: str = '') -> list:
    """For SEARCH boxes (item pickers, Ctrl+K): the item(s) people have confirmed for this
    spelling — exact or close (identical numbers) — so typing «اوميز 10» surfaces OMEZ 10
    although the catalog name is English. Read-only (searches never teach). [] if none."""
    raw = (raw_name or '').strip()
    if len(raw) < 3 or '*' in raw:
        return []
    group = lookup_alias_group(raw, vendor_code=vendor_code)
    if group:
        return list(group['item_ids'])
    single = lookup_alias(raw, vendor_code=vendor_code)
    return [single['item_id']] if single else []


def learn_correction(raw_name: str, *, suggested=None, chosen=(), source: str = 'manual',
                     vendor_code: str = '') -> None:
    """One call for a human decision on a machine suggestion: the chosen item(s) are
    learned (a single alias, or a group when several), and the suggested item is recorded
    as rejected if the person did not keep it."""
    chosen_ids = [int(getattr(c, 'pk', c)) for c in chosen if c]
    sug_id = getattr(suggested, 'pk', suggested)
    if sug_id and int(sug_id) not in chosen_ids:
        record_rejection(raw_name, sug_id, vendor_code=vendor_code, source=source)
    if len(chosen_ids) == 1:
        learn_alias(raw_name, chosen_ids[0], source=source, vendor_code=vendor_code)
    elif len(chosen_ids) > 1:
        learn_alias_group(raw_name, chosen_ids, source=source, vendor_code=vendor_code)
