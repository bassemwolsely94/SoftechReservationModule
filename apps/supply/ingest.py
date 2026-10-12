"""
apps/supply/ingest.py — the shared ingestion pipeline.

Turns raw ingest lines (typed / bulk-pasted / OCR'd / voice) into normalized,
catalog-resolved candidates, INDEPENDENTLY of which model will store them. Both
``apps.shortage`` (branch-PULL shortage lists) and the coming supplier-PUSH
availability inbox call this instead of each duplicating the same parse → match →
learn logic.

This is a THIN wrapper over the authoritative matcher + alias flywheel in
``apps.shortage.matching``. It performs NO fuzzy scoring, normalization, or alias
storage of its own — it orchestrates the existing functions:

  • parse_quantity_from_text  — "amox 500 10" → ("amox 500", 10.0)
  • dedup_key                 — (drug, strength) dedup key
  • find_best_matches         — confidence-scored catalog match (+ ItemAlias corpus)
  • learn_alias               — reinforce a confirmed raw-name → Item mapping

Behaviour here is byte-for-byte identical to the logic previously inlined in
``apps.shortage.views`` (add_item / _import_lines); it was extracted verbatim so a
second consumer can reuse it without a parallel implementation.
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.shortage.matching import (
    find_best_matches,
    parse_quantity_from_text,
    dedup_key,
    learn_alias,
)

# Auto-match confidence thresholds — the operator ALWAYS still confirms; these only
# decide whether a suggestion is pre-filled. Kept as the historical shortage values.
AUTO_MATCH_IMPORT = 0.55   # bulk / voice import (_import_lines)
AUTO_MATCH_SINGLE = 0.70   # single add-item


@dataclass
class ParsedLine:
    """A raw ingest entry after quantity split + dedup keying.

    ``override_id`` / ``override_sid`` carry an explicit user-picked catalog item
    (by PG pk or SOFTECH itemcode) supplied inline with the entry — when present the
    resolver skips fuzzy matching and treats the line as a confirmed pick.
    """
    raw:          str
    raw_name:     str
    qty:          float
    override_id:  object       # int | None
    override_sid: str
    dedup_key:    str


@dataclass
class ResolvedLine:
    """The catalog resolution of a ParsedLine.

    ``picked`` is True only when the user pre-selected the item (override) — that is
    a high-quality confirmation worth teaching the alias corpus. A fuzzy auto-match
    is NOT ``picked`` (it still needs human confirmation)."""
    item:    object            # catalog.Item | None
    item_id: object            # int | None
    score:   object            # float | None
    picked:  bool
    learned: bool = False      # resolved from a human-confirmed alias (ItemAlias)
    runner_up_name:  str = ''  # second-best candidate — for the ambiguity guard
    runner_up_score: object = None


def parse_entry(entry) -> ParsedLine | None:
    """Normalize one ingest entry into a ParsedLine, or None to skip.

    ``entry`` is either a plain string ("name [qty]") or a dict
    ``{raw, item_id?, item_softech_id?}`` (a dict carries an explicit user pick).
    Returns None for a blank raw name (caller skips it), matching the previous
    ``if not raw: continue`` behaviour.
    """
    if isinstance(entry, dict):
        raw          = str(entry.get('raw', '')).strip()
        override_id  = entry.get('item_id')
        override_sid = str(entry.get('item_softech_id') or '').strip()
    else:
        raw, override_id, override_sid = str(entry).strip(), None, ''

    if not raw:
        return None

    raw_name, qty = parse_quantity_from_text(raw)
    return ParsedLine(
        raw=raw,
        raw_name=raw_name,
        qty=qty,
        override_id=override_id,
        override_sid=override_sid,
        dedup_key=dedup_key(raw_name),
    )


def resolve_line(raw_name: str, *, override_id=None, override_sid: str = '',
                 threshold: float = AUTO_MATCH_IMPORT, vendor_code: str = '') -> ResolvedLine:
    """Resolve a raw name to a catalog Item.

    1. An explicit user pick (PG pk, else SOFTECH itemcode) wins → score 1.0, picked.
    2. Otherwise the top fuzzy match at/above ``threshold`` (learned corpus first);
       the operator still confirms it, so it is NOT ``picked``.
    ``vendor_code`` (a SOFTECH supplier personcode) scopes the alias corpus so a
    supplier's private spelling resolves first — passed straight to the matcher; blank
    (the default, used by shortage's branch-PULL path) means global aliases only.
    Never raises — an unresolvable line returns item=None.
    """
    from apps.catalog.models import Item

    item_obj = None
    score = None
    picked = False

    # 1. Explicit user pick — by PG pk, else by SOFTECH itemcode.
    if override_id or override_sid:
        try:
            item_obj = (Item.objects.get(pk=override_id) if override_id
                        else Item.objects.get(softech_id=override_sid))
            score, picked = 1.0, True
        except (Item.DoesNotExist, ValueError, TypeError):
            item_obj = None

    # 2. Fuzzy auto-match (top-1 at threshold) — user still confirms. top_n=2 only adds the
    #    runner-up for the ambiguity guard; the top-1 is identical to a top_n=1 call.
    learned = False
    runner_name, runner_score = '', None
    if item_obj is None:
        matches = find_best_matches(raw_name, top_n=8, min_score=threshold, vendor_code=vendor_code)
        matches = _prefer_written(raw_name, matches)
        if matches:
            best = matches[0]
            try:
                item_obj = Item.objects.get(pk=best['item_id'])
                score = best['score']
                # an exact OR close-spelling memory: a person already confirmed this
                # (numbers identical), so the review flags are not re-raised
                learned = bool(best.get('learned') or best.get('learned_fuzzy'))
            except Item.DoesNotExist:
                pass
            if len(matches) > 1:
                runner_name, runner_score = matches[1]['item_name'], matches[1]['score']

    return ResolvedLine(
        item=item_obj,
        item_id=getattr(item_obj, 'id', None),
        score=score,
        picked=picked,
        learned=learned,
        runner_up_name=runner_name,
        runner_up_score=runner_score,
    )


# ── Written form / strength as a tie-break ─────────────────────────────────────────
# Close candidates (within FORM_TIE_MARGIN of the top score) are re-ordered so the one whose
# dosage form and strength agree with what the supplier wrote comes first: «Depovita amp» →
# DEPOVIT-B12 AMP (not the lozenges), «لانتوس كارتلج» → LANTUS PENFILL (not SoloStar pens),
# «Telfast syr» → the suspension. Deterministic; a remembered (learned) match is never moved.
FORM_TIE_MARGIN = 0.10

# Catalog / distributor form words the shared synonym table lacks (pens vs cartridges,
# lozenges, syringes, sachets …). Catalog names glue them to numbers: «20TAB», «5PENFILL».
_EXTRA_FORMS = {
    'lozenge': 'lozenge', 'lozenges': 'lozenge', 'loz': 'lozenge', 'loze': 'lozenge', 'استحلاب': 'lozenge',
    'pen': 'pen', 'pens': 'pen', 'flexpen': 'pen', 'solostar': 'pen', 'kwikpen': 'pen', 'flextouch': 'pen',
    'قلم': 'pen', 'اقلام': 'pen', 'أقلام': 'pen',
    'penfill': 'cartridge', 'cartridge': 'cartridge', 'cartridges': 'cartridge', 'cartidige': 'cartridge',
    'كارتلج': 'cartridge', 'كارتريدج': 'cartridge', 'خراطيش': 'cartridge', 'خرطوشة': 'cartridge',
    'خرطوشه': 'cartridge',
    'vial': 'ampoule', 'vials': 'ampoule', 'amps': 'ampoule', 'ampoules': 'ampoule', 'syringe': 'ampoule',
    'syringes': 'ampoule', 'فيال': 'ampoule',
    'sach': 'sachet', 'sachets': 'sachet', 'sac': 'sachet', 'sticks': 'sachet', 'اكياس': 'sachet', 'أكياس': 'sachet',
    'emulgel': 'cream', 'lotion': 'cream', 'divitab': 'tablet', 'chewable': 'tablet',
    'shampoo': 'shampoo', 'شامبو': 'shampoo', 'soap': 'soap', 'صابون': 'soap', 'صابونه': 'soap',
    'mouthwash': 'mouthwash', 'film': 'film', 'فيلم': 'film',
}


def forms_of(text: str) -> list:
    """Every dosage form named in a supplier text or a catalog name, in order
    («MELACRYST 3MG 20FILM ORAL FILM TAB» → film, tablet)."""
    import re
    from apps.shortage.matching import _FORM_LOOKUP
    out = []
    for tok in re.findall(r'[A-Za-z؀-ۿ]+', str(text or '')):
        t = tok.lower()
        f = _EXTRA_FORMS.get(t) or _FORM_LOOKUP.get(t)
        if f and f not in out:
            out.append(f)
    return out


def form_of(text: str):
    """The first dosage form named in a text (None if none)."""
    f = forms_of(text)
    return f[0] if f else None


def _words(text: str) -> set:
    """Latin name words (no numbers / forms) — guards the tie-break to the same product."""
    import re
    from apps.shortage.matching import _FORM_LOOKUP
    return {w for w in re.findall(r'[a-z]{3,}', str(text or '').lower())
            if w not in _EXTRA_FORMS and w not in _FORM_LOOKUP}


def _prefer_written(raw_name: str, matches: list) -> list:
    """Re-order close candidates by agreement with the written form + strength."""
    if len(matches) < 2 or matches[0].get('learned') or matches[0].get('learned_fuzzy'):
        return matches
    want_form, want_nums = form_of(raw_name), _name_numbers(raw_name)
    if not want_form and not want_nums:
        return matches
    top = matches[0]['score']
    words = _words(raw_name)
    top_overlap = len(words & _words(matches[0]['item_name']))

    def agree(m):
        return (int(bool(want_nums) and want_nums <= _name_numbers(m['item_name'])) * 2
                + int(bool(want_form) and want_form in forms_of(m['item_name'])))

    # only candidates naming the written words as well as the top one does (never jump
    # from «Limitless power max» to «Limitless woman max» because the form fits)
    close = [m for m in matches if m['score'] >= top - FORM_TIE_MARGIN
             and (m is matches[0] or len(words & _words(m['item_name'])) >= top_overlap)]
    rest = [m for m in matches if m not in close]
    best = max(close, key=lambda m: (agree(m), m['score']))
    if best is matches[0]:
        return matches
    return [dict(best, written_preferred=True)] + [m for m in close if m is not best] + rest


# ── Match-safety guard (§5: never silently trust a dangerous false match) ──────────

_AMBIGUITY_MARGIN = 0.05


def _name_numbers(text: str) -> set:
    """Numeric values in a product name ('25,000IU' → 25000; '0.25MG' → 0.25)."""
    import re
    t = re.sub(r'(?<=\d),(?=\d{3}(?!\d))', '', str(text or ''))
    return {float(x) for x in re.findall(r'\d+(?:\.\d+)?', t)}


def _head_word(name: str) -> str:
    import re
    words = re.findall(r'[A-Za-z]{3,}', str(name or '').upper())
    return words[0] if words else ''


def review_flags(read_text: str, item_name: str, *, runner_up_name: str = '',
                 score=None, runner_up_score=None) -> list:
    """Deterministic reasons a fuzzy match must NOT be trusted without a human, even at a
    high similarity score (the fuzzy score does not penalise these):

      strength_mismatch — a number the supplier wrote is absent from the item name
                          ("Recormon 4000" vs "RECORMON 5000", "Concor Plus 5/12.5" vs 10/12.5)
      form_mismatch     — both name a dosage form and they differ (tablet vs I.V. vial)
      head_mismatch     — the match latched onto a different leading drug word
                          (shared apps.shortage.matching.head_mismatch)
      ambiguous         — a DIFFERENT product scores within 0.05 of the winner
    Human-confirmed aliases and explicit picks are never re-flagged (callers skip them)."""
    from apps.shortage.matching import extract_components, head_mismatch

    flags = []
    raw_nums, item_nums = _name_numbers(read_text), _name_numbers(item_name)
    if raw_nums and item_nums and not raw_nums <= item_nums:
        flags.append('strength_mismatch')
    rf = extract_components(read_text).form or form_of(read_text)
    itf = {extract_components(item_name).form} | set(forms_of(item_name))
    itf.discard(None)
    if rf and itf and rf not in itf:
        flags.append('form_mismatch')
    if head_mismatch(read_text, item_name):
        flags.append('head_mismatch')
    if (runner_up_name and score is not None and runner_up_score is not None
            and runner_up_score >= score - _AMBIGUITY_MARGIN
            and _head_word(runner_up_name) != _head_word(item_name)):
        flags.append('ambiguous')
    return flags


def teach_alias(raw_name: str, item, *, source: str = 'manual', vendor_code: str = ''):
    """Reinforce a confirmed raw-name → Item mapping in the shared ItemAlias corpus.

    Thin pass-through to ``matching.learn_alias`` so every ingest consumer teaches the
    same flywheel. Returns the ItemAlias (or None). The caller keeps its own try/except
    so each module preserves its existing failure logging."""
    return learn_alias(raw_name, item, source=source, vendor_code=vendor_code)
