"""
apps/supply/line_matching.py — ONE matching core for «صندوق الإتاحة» (supplier lists) and
«طلبات واتساب» (branch requests). Doc 31 phase A, owner 2026-10-25 («strict» flags).

Before, both used the same catalog matcher (find_best_matches + the learned memory) but
everything around it was separate, so the same text could match differently on the two
screens. Measured on 431 confirmed texts (memory off): the inbox RANKING picks the right
item more often (77.7 % vs 38.6 % — the WhatsApp side refuses to guess between versions),
the WhatsApp FLAGS + version list are safer (16 vs 47 lines that look clean but are wrong);
both together: 77.7 % and only 6 clean-but-wrong.

  match_text(text, source=…)  — one catalog search, read by BOTH engines:
      • the inbox engine (ingest.resolve_line: memory → form/strength tie-break) and its
        review flags (strength / form / head / ambiguous);
      • the WhatsApp engine (branch_requests.resolve: product family, versions narrowed by
        the numbers and words written, branch stock + network sales per version) and its
        flags (choose_variant / pack_not_found / qty / strips / low_score);
      • `engines_disagree` when the two engines pick different items.
    The item pre-filled for review: a supplier line takes the inbox engine's pick; a branch
    request takes the WhatsApp engine's (owner 2026-10-04: versions are never auto-picked
    there). Every flag is a reason a person must look — nothing is confirmed here.
    Cut-offs stay per screen (supplier 0.55, branch 0.70) until the owner picks one value.

  header(line, sender_rule=…) — the WhatsApp message header (timestamp + sender), one
    pattern for every export format (Desktop copy time-first / date-first, Android, iOS).
    The sender split differs on purpose: a branch group's sender name can hold ': ' itself
    («Branch: Nozha #2 …: THIOTACID» → 'last'), a supplier line holds ': ' after the item
    («EGY DRUG: Concor 5 : 20%» → 'first').

Deterministic; no LLM decides anything.
"""
from __future__ import annotations

import re

# ── text folding (shared) ────────────────────────────────────────────────────────
_AR_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')
_INVISIBLE = dict.fromkeys(map(ord, '‎‏‪‫‬‭‮﻿'), None)


def fold(text: str) -> str:
    """Arabic-Indic digits → 0-9, ٪ → %, invisible direction marks and odd spaces removed."""
    t = str(text or '').translate(_INVISIBLE).translate(_AR_DIGITS)
    return t.replace(' ', ' ').replace(' ', ' ').replace('\r', '').replace('٪', '%')


# ── WhatsApp message header (shared) ─────────────────────────────────────────────
WA_TIME = r'\d{1,2}:\d{2}(?::\d{2})?\s*(?:[AaPp]\.?\s?[Mm]\.?|ص|م)?'
WA_DATE = r'\d{1,4}[/.\-]\d{1,2}[/.\-]\d{1,4}'
# «[20/09/2026, 10:15] Name: …» · «20/09/2026, 10:15 - Name: …» (Android) · «[20/9/2026 10:17 ص] …»
# · «9/20/26, 10:15 PM - Name: …» · Desktop copy time-first «[12:44 pm, 07/10/2026] Name: …»
WA_TS = (r'^\s*\[?\s*(?:(?P<d1>' + WA_DATE + r'),?\s+(?P<t1>' + WA_TIME + r')|(?P<t2>' + WA_TIME
         + r'),?\s+(?P<d2>' + WA_DATE + r'))\s*\]?\s*(?:[-–—]\s*)?')
_HEADER = re.compile(WA_TS + r'(?P<rest>.*)$')


def header(line: str, *, sender_rule: str = 'first'):
    """A WhatsApp header line → {'sender', 'date', 'time', 'body'}; None when the line has no
    timestamp. sender = '' for a system line (timestamp, no «Name:»)."""
    m = _HEADER.match(fold(line))
    if not m:
        return None
    rest = m.group('rest')
    sender, body = '', rest
    head = rest[:90]
    if sender_rule == 'last':
        i = head.rfind(': ')
        if i > 0:
            sender, body = rest[:i].strip(), rest[i + 2:].strip()
    else:
        sm = re.match(r'(?P<sender>[^:\n]{1,60}):\s*', rest)
        if sm:
            sender, body = sm.group('sender').strip(), rest[sm.end():]
    return {'sender': sender, 'date': (m.group('d1') or m.group('d2') or '').strip(),
            'time': (m.group('t1') or m.group('t2') or '').strip(), 'body': body}


# ── one matching core ────────────────────────────────────────────────────────────
SUPPLIER, BRANCH = 'supplier', 'branch'
SAFE_FLAGS = {'urgent', 'learned_group', 'learned_fuzzy'}   # = branch_request_views.SAFE_FLAGS
# Arabic labels for the screens (owner: «strict» — every flag is a reason to look)
FLAG_LABELS = {
    'choose_variant': 'اختر النسخة', 'strength_mismatch': 'التركيز مختلف', 'ambiguous': 'منتج آخر قريب',
    'no_match': 'لا يوجد تطابق', 'form_mismatch': 'الشكل مختلف', 'pack_not_found': 'حجم العبوة غير موجود',
    'engines_disagree': 'المحركان مختلفان', 'head_mismatch': 'اسم الدواء مختلف', 'low_score': 'تطابق ضعيف',
    'word_mismatch': 'النوع مختلف', 'strips': 'شرائط', 'qty_large': 'كمية كبيرة',
    'qty_maybe_strength': 'الرقم قد يكون تركيزاً', 'learned_fuzzy': 'من الذاكرة (قريب)',
    'learned_group': 'من الذاكرة · عدة أصناف', 'urgent': 'مستعجل', 'ocr': 'من صورة',
}
SEARCH_TOP_N, SEARCH_MIN = 8, 0.30


def _frag(text):
    return {'text': text, 'raw': text, 'qty': 1.0, 'unit': 'pack', 'qty_source': 'default', 'all_variants': False}


def match_text(text: str, *, source: str, vendor_code: str = '', branch=None, frag=None,
               threshold: float | None = None) -> dict:
    """{'item', 'score', 'learned', 'flags', 'candidates', 'kind', 'extra_ids',
        'suggested_item_id', 'runner_up_name', 'runner_up_score', 'engines'}"""
    from apps.shortage.matching import find_best_matches
    from . import branch_requests as BR
    from . import ingest as ING
    frag = frag or _frag(text)
    th = threshold if threshold is not None else (ING.AUTO_MATCH_IMPORT if source == SUPPLIER else BR.AUTO_SCORE)
    matches = find_best_matches(frag['text'], top_n=SEARCH_TOP_N, min_score=SEARCH_MIN, vendor_code=vendor_code)
    inbox = ING.resolve_line(frag['text'], vendor_code=vendor_code, threshold=ING.AUTO_MATCH_IMPORT,
                             matches=[m for m in matches if m['score'] >= ING.AUTO_MATCH_IMPORT])
    wa = BR.resolve(frag, branch, matches=matches[:6])
    wa_item = wa.get('item')
    learned = bool(inbox.learned) or 'learned_fuzzy' in (wa.get('flags') or []) or 'learned_group' in (wa.get('flags') or [])

    if source == SUPPLIER:
        item, score = inbox.item, inbox.score
    else:
        item, score = wa_item, wa.get('score')

    flags = list(wa.get('flags') or [])
    if source == SUPPLIER:
        # the supplier screen's own cut-off stands (owner decision pending) — the WhatsApp
        # engine's 0.70 «low_score» is not applied to it
        flags = [f for f in flags if f != 'low_score']
        if item is None and 'no_match' not in flags:
            flags.append('no_match')
    if item is not None and not learned and not inbox.picked:
        flags += ING.review_flags(frag['text'], item.name, runner_up_name=inbox.runner_up_name,
                                  score=inbox.score, runner_up_score=inbox.runner_up_score)
    if item is not None and not learned and score is not None and score < th:
        flags.append('low_score')
    if not learned and inbox.item is not None and wa_item is not None and inbox.item.id != wa_item.id:
        flags.append('engines_disagree')
    if learned:                                   # a person confirmed this spelling before
        flags = [f for f in flags if f in SAFE_FLAGS or f.startswith('qty_') or f == 'strips']
    flags = list(dict.fromkeys(flags))
    return {
        'item': item, 'score': score, 'learned': learned, 'flags': flags,
        'candidates': wa.get('candidates') or [], 'kind': wa.get('kind', 'item'),
        'extra_ids': wa.get('extra_ids') or [], 'suggested_item_id': getattr(item, 'id', None),
        'runner_up_name': inbox.runner_up_name, 'runner_up_score': inbox.runner_up_score,
        'engines': {'inbox': getattr(inbox.item, 'id', None), 'whatsapp': getattr(wa_item, 'id', None)},
    }


def needs_review(flags) -> bool:
    return bool(set(flags or []) - SAFE_FLAGS)
