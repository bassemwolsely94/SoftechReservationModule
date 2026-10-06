"""
apps/supply/branch_requests.py — «طلبات واتساب»: branch requests pasted from WhatsApp groups.

The Meta Cloud API cannot read WhatsApp GROUPS, so staff paste the chat (or upload a
photo). This module turns that text into reviewable item lines. Deterministic: no LLM
decides an item or a quantity; every line is confirmed by a person.

  split_messages(text)  → [{sender, time, text}]   (Desktop copy, Android/iOS export, plain)
  extract(text)         → [fragment dicts]         (one per item / note, qty parsed)
  resolve(fragment)     → item, score, flags, variant candidates
  build_lines(request, text) / add_ocr_lines(request, rows) → BranchRequestLine rows
  confirm(request, user) → shortage.ShortageList for the branch (+ teaches the matcher)
  pseudo_isr(request)    → the confirmed lines in the ISR-fulfilment engine's shape

QUANTITY RULE (owner, 2026-10-04 — "the most frequent approach, may have irregularities"):
a number is a QUANTITY only with a unit word or a count marker next to it —
علبة/علب/عبوة/box/عدد/شريط/×, «1box», «علبتين». A bare number at the end is the STRENGTH
("Aricept 10" = Aricept 10mg, qty 1). Irregular cases are flagged, never silently trusted:
  qty_maybe_strength — the qty number is also a strength of that product ("كارفيد 25 علبة")
  qty_large          — more than 10 packs
VARIANTS: when several versions of the same product fit (strengths, pack sizes, flavours)
nothing is auto-picked — the numbers written narrow them, else the reviewer chooses a
version or «كل الأنواع». Each option carries branch stock + network sales so an obsolete
duplicate code (no sales, no stock) is told apart from a real other size.
"""
from __future__ import annotations

import re

from apps.shortage.matching import (_normalize, find_best_matches, head_mismatch,
                                    learn_alias, looks_non_drug, score_match)

# ── text normalisation ──────────────────────────────────────────────────────────
_AR_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')
_INVISIBLE = dict.fromkeys(map(ord, '‎‏‪‫‬‭‮﻿'), None)


def _clean(text: str) -> str:
    t = str(text or '').translate(_INVISIBLE).translate(_AR_DIGITS)
    return t.replace(' ', ' ').replace(' ', ' ').replace('\r', '')


# ── 1. messages ─────────────────────────────────────────────────────────────────
_T = r'\d{1,2}:\d{2}(?::\d{2})?(?:\s?[APap]\.?[Mm]\.?|\s?[صم])?'
_D = r'\d{1,4}[/.\-]\d{1,2}[/.\-]\d{1,4}'
_HEADERS = [
    re.compile(rf'^\[(?P<time>{_T}),\s*(?P<date>{_D})\]\s*(?P<rest>.*)$'),        # Desktop copy
    re.compile(rf'^\[(?P<date>{_D}),?\s+(?P<time>{_T})\]\s*(?P<rest>.*)$'),        # iOS export
    re.compile(rf'^(?P<date>{_D}),?\s+(?P<time>{_T})\s+[-–]\s+(?P<rest>.*)$'),     # Android export
]
_SYSTEM = ('end-to-end encrypted', 'تم تشفير', '<media omitted>', 'image omitted', 'تم حذف هذه الرسالة',
           'this message was deleted', 'created group', 'added', 'joined using')


def _split_sender(rest: str):
    """'Branch: Nozha #2 ElAdib …: THIOTACID …' → (sender, text). Sender names may hold
    ': ' themselves, so take the LAST ': ' in the first 90 chars."""
    head = rest[:90]
    i = head.rfind(': ')
    if i <= 0:
        return '', rest
    return rest[:i].strip(), rest[i + 2:]


def split_messages(text: str) -> list[dict]:
    """Chat paste → messages. Lines without a header continue the previous message; a paste
    with no headers at all is split on blank lines (one block = one message)."""
    lines = _clean(text).split('\n')
    msgs, cur, any_header = [], None, False
    for ln in lines:
        m = next((r.match(ln.strip()) for r in _HEADERS if r.match(ln.strip())), None)
        if m:
            any_header = True
            sender, body = _split_sender(m.group('rest'))
            cur = {'sender': sender, 'time': f'{m.group("date")} {m.group("time")}'.strip(), 'lines': [body]}
            msgs.append(cur)
        elif cur is not None:
            cur['lines'].append(ln)
        else:
            cur = {'sender': '', 'time': '', 'lines': [ln]}
            msgs.append(cur)
    if not any_header:                                  # plain paste → blank-line blocks
        msgs, block = [], []
        for ln in lines + ['']:
            if ln.strip():
                block.append(ln)
            elif block:
                msgs.append({'sender': '', 'time': '', 'lines': block})
                block = []
    out = []
    for m in msgs:
        body = '\n'.join(l for l in m['lines']).strip()
        if not body or any(s in body.lower() for s in _SYSTEM) and len(body) < 120:
            continue
        out.append({'sender': m['sender'][:120], 'time': m['time'][:40], 'text': body})
    return out


# ── 2. quantity + fragments ─────────────────────────────────────────────────────
_UNITS = {
    'pack': ['علبة', 'علبه', 'علب', 'عبوة', 'عبوه', 'عبوات', 'box', 'boxes', 'bx', 'pack', 'packs',
             'pcs', 'pc', 'قطعة', 'قطعه', 'قطع', 'خرطوشة', 'خرطوشه', 'خراطيش', 'زجاجة', 'زجاجه',
             'ازازة', 'ازازه', 'كرتونة', 'كرتونه'],
    'strip': ['شريط', 'شرايط', 'شرائط', 'strip', 'strips'],
}
_DUALS = {'علبتين': ('pack', 2), 'عبوتين': ('pack', 2), 'شريطين': ('strip', 2), 'ازازتين': ('pack', 2)}
_UNIT_OF = {w: u for u, ws in _UNITS.items() for w in ws}
_UNIT_ALT = '|'.join(sorted(map(re.escape, _UNIT_OF), key=len, reverse=True))
_COUNT_UNIT = re.compile(rf'(?<![\w.])(\d+)\s*({_UNIT_ALT})(?![\w])', re.IGNORECASE)
_ADAD = re.compile(rf'(?<![\w])عدد\s*(\d+)(?:\s*({_UNIT_ALT}))?(?![\w])', re.IGNORECASE)
_TIMES = re.compile(r'(?:(?<=\s)|^)(?:[xX×]\s*(\d+)|(\d+)\s*[xX×])(?=\s|$)')
_UNIT_ALONE = re.compile(rf'(?<![\w])({_UNIT_ALT})(?![\w])', re.IGNORECASE)
_ALL_TYPES = re.compile(r'(كل|جميع)\s+(ال)?(انواع|أنواع|الوان|ألوان|اصناف|أصناف|نكهات)|all\s+(types|kinds|flavou?rs)',
                        re.IGNORECASE)
_FILLERS = ['عميل', 'العميل', 'للعميل', 'محتاج', 'محتاجه', 'محتاجة', 'محتاجين', 'مطلوب', 'مطلوبه',
            'مطلوبة', 'ضروري', 'ضرورى', 'مستعجل', 'مستعجله', 'عاجل', 'لتعاقد', 'تعاقد', 'برجاء', 'رجاء',
            'عايز', 'عايزه', 'عاوز', 'ابعتوا', 'ابعت', 'لو سمحت', 'من فضلك', 'يا ريت', 'please', 'urgent']
_FILLER_RE = re.compile(r'(?<![\w])(' + '|'.join(map(re.escape, _FILLERS)) + r')(?![\w])', re.IGNORECASE)
_URGENT_RE = re.compile(r'مستعجل|ضرور|عاجل|urgent', re.IGNORECASE)
_PHONE_RE = re.compile(r'^\+?\d[\d\s\-]{7,}$')
_REF_RE = re.compile(r'^\d{3}[A-Za-z]{1,3}\d{3,}$')            # e.g. 130HD16417
_SPLIT_RE = re.compile(r'\s*[،,؛;]\s*|\s+\+\s+|\s+و\s+')


def parse_qty(fragment: str) -> dict:
    """One fragment → {text, qty, unit, qty_source, all_variants}. `text` is what is left
    for matching (qty phrase, «كل الانواع» and filler words removed; strength kept)."""
    t = _clean(fragment).strip()
    all_v = bool(_ALL_TYPES.search(t))
    t = _ALL_TYPES.sub(' ', t)
    qty, unit, src = None, 'pack', 'default'

    for w, (u, n) in _DUALS.items():
        if re.search(rf'(?<![\w]){w}(?![\w])', t):
            qty, unit, src = n, u, 'unit'
            t = re.sub(rf'(?<![\w]){w}(?![\w])', ' ', t)
            break
    if qty is None:
        m = _ADAD.search(t)
        if m:
            qty, src = int(m.group(1)), 'count'
            unit = _UNIT_OF.get((m.group(2) or '').lower(), 'pack')
            t = t[:m.start()] + ' ' + t[m.end():]
    if qty is None:
        m = _COUNT_UNIT.search(t)
        if m:
            qty, unit, src = int(m.group(1)), _UNIT_OF[m.group(2).lower()], 'unit'
            before, after = t[:m.start()].strip(), t[m.end():].strip()
            # Arabic writes "4 علب اوميز" (count, unit, then the item) — when the qty phrase
            # sits mid-text, the item is what FOLLOWS it; at the end, what precedes it.
            t = after if (before and after and re.search(r'[A-Za-z؀-ۿ]{3,}', after)) else f'{before} {after}'
    if qty is None:
        m = _TIMES.search(t)
        if m:
            qty, src = int(m.group(1) or m.group(2)), 'count'
            t = t[:m.start()] + ' ' + t[m.end():]
    if qty is None:
        m = _UNIT_ALONE.search(t)
        if m:
            qty, unit, src = 1, _UNIT_OF[m.group(1).lower()], 'unit'
            t = t[:m.start()] + ' ' + t[m.end():]

    t = _FILLER_RE.sub(' ', t)
    t = re.sub(r'\s+', ' ', t).strip(' -–:.')
    return {'text': t, 'qty': qty if qty is not None else 1, 'unit': unit,
            'qty_source': src if qty is not None else 'default', 'all_variants': all_v}


# Arabic function words that never appear in a drug name — a fragment carrying them is a
# remark ("لكم طرفنا تبع الكرباء", "مستعجل علي ادويته من يوم الخميس"), not an item.
_AR_FUNCTION = {'لكم', 'طرفنا', 'تبع', 'بتاع', 'بتاعت', 'من', 'علي', 'على', 'يوم', 'في', 'عند', 'اللي',
                'الي', 'عشان', 'علشان', 'بكره', 'بكرة', 'النهارده', 'امبارح', 'لسه', 'هيعدي', 'هيجي',
                'ادويته', 'ادويتها', 'علاجه', 'علاجها', 'الخميس', 'الجمعة', 'السبت', 'الاحد', 'الاثنين',
                'الثلاثاء', 'الاربعاء', 'انهارده', 'معاه', 'معاها', 'كلم', 'اتصل', 'هو', 'هي', 'ده', 'دي'}
# Common given names (Latin + Arabic) — "Nevine ibrahim" / "Ahmed Sabry" are the customer,
# not an item (else NEVINE → "NEVIN HAIR REMOVER").
_GIVEN_NAMES = set('''ahmed ahmad mohamed mohammed muhammad mahmoud mostafa moustafa mustafa omar
amr ali hassan hussein hossam khaled karim kareem tarek tamer sherif shady sameh samir sami
youssef yousef ibrahim ismail islam mina mena george gerges girgis michael mikhail peter
bishoy beshoy fady fadi ramy rami remon romany magdy medhat emad essam ayman hany hani
waleed walid wael osama ashraf adel atef nabil nader hesham hisham ehab ihab haitham yasser
sayed said abdelrahman abdallah abdullah abdo ayah aya nada noha nora noura nourhan nevine
nevin nivin heba hala hanan hend hoda mona mai may mariam maryam marwa mervat amira amany
eman iman esraa asmaa salma sara sarah samar shaimaa shereen sherine rania randa reem rehab
dina dalia doaa fatma fatima ghada laila layla lamia magda manal nermeen nermin nesma nihal
radwa rasha safaa samia soad sohair yasmin yasmine zeinab zainab marina mariana christine
مريم محمد احمد أحمد محمود مصطفى عمر علي حسن حسين خالد كريم طارق تامر شريف يوسف ابراهيم
إبراهيم اسماعيل مينا جورج بيتر مايكل نيفين نيفين هبة منى سارة ساره ريم دينا فاطمة زينب'''.split())


def _note_kind(t: str):
    s = t.strip()
    if _PHONE_RE.match(s):
        return 'phone'
    if _REF_RE.match(s.replace(' ', '')):
        return 'ref'
    return None


def _is_remark(text: str) -> bool:
    """Arabic-only words with a function word or a long sentence → a remark, not a drug."""
    words = re.findall(r'[؀-ۿ]+', text)
    if not words or re.search(r'[A-Za-z]', text):
        return False
    return bool(_AR_FUNCTION & set(words)) or len(words) >= 5


def _is_person_name(text: str, after_phone: bool) -> bool:
    """1–3 letter-only words starting with a known given name (or any such short line right
    after a phone number) → the customer's name."""
    words = re.findall(r'[A-Za-z؀-ۿ]+', text)
    if not words or len(words) > 3 or re.search(r'\d', text):
        return False
    if words[0].lower() in _GIVEN_NAMES:
        return True
    # right after a phone: a short line is the customer's name — unless it starts with a
    # word the catalog knows ("Physiomer Strong Jet" after a phone is still an item)
    return after_phone and len(words) >= 2 and not _catalog_word(words[0])


def _catalog_word(word: str) -> bool:
    from apps.catalog.models import Item
    w = word.strip()
    if len(w) < 4:
        return False
    return Item.objects.filter(is_active=True, name__istartswith=w).exists()


def extract(text: str) -> list[dict]:
    """A message body → fragments. A line that only says «كل الانواع» or only carries a
    quantity («عدد 3 خراطيش») applies to the previous item in the same message."""
    frags = []
    last_item = None
    after_phone = False
    for raw_line in _clean(text).split('\n'):
        line = raw_line.strip()
        if not line:
            continue
        nk = _note_kind(line)
        if nk:
            frags.append({'raw': line, 'kind': 'note', 'note': nk})
            after_phone = nk == 'phone'
            continue
        line = re.sub(r'^و\s+', '', line)                # "و كارفيد 25 علبة" continues a list
        if _is_person_name(line, after_phone):
            frags.append({'raw': line, 'kind': 'note', 'note': 'name'})
            after_phone = False                         # only the line right after a phone
            continue
        after_phone = False
        parts = [p for p in _SPLIT_RE.split(line) if p and p.strip()] or [line]
        for part in parts:
            p = parse_qty(part)
            if p['qty_source'] == 'default' and not p['all_variants'] and _is_remark(p['text']):
                frags.append({'raw': part.strip(), 'kind': 'note', 'note': 'remark'})
                continue
            if not p['text'] or not re.search(r'[A-Za-z؀-ۿ]{2,}', p['text']):
                # quantity-only / «كل الانواع»-only line → modifies the previous item
                if last_item is not None and (p['qty_source'] != 'default' or p['all_variants']):
                    if p['qty_source'] != 'default':
                        last_item.update(qty=p['qty'], unit=p['unit'], qty_source=p['qty_source'])
                    last_item['all_variants'] = last_item['all_variants'] or p['all_variants']
                    last_item['raw'] += ' / ' + part.strip()
                else:
                    frags.append({'raw': part.strip(), 'kind': 'note', 'note': 'remark'})
                continue
            f = {'raw': part.strip(), 'kind': 'item', **p}
            frags.append(f)
            last_item = f
    return frags


# ── 3. matching + variants ──────────────────────────────────────────────────────
AUTO_SCORE = 0.70           # below → the line needs a look even if unflagged
NOTE_SCORE = 0.62           # a short alpha-only fragment matching worse than this is a note
QTY_LARGE = 10


def _nums(text: str) -> set:
    t = re.sub(r'(?<=\d),(?=\d{3}(?!\d))', '', str(text or ''))
    return {float(x) for x in re.findall(r'\d+(?:\.\d+)?', t)}


_STRENGTH_NUM = re.compile(r'(\d+(?:\.\d+)?)\s*(?:mg|mcg|ug|µg|iu|ml|gm|g\b|%|/)', re.IGNORECASE)


def _strength_nums(name: str) -> set:
    """Numbers that are a STRENGTH in a catalog name (followed by mg/mcg/ug/iu/ml/%), plus
    the first number after the brand — so '(4STRIPSX25)' does not make 'EUTHYROX 100UG'
    look like a 25."""
    t = str(name or '')
    out = {float(m.group(1)) for m in _STRENGTH_NUM.finditer(t)}
    first = re.search(r'\d+(?:\.\d+)?', t)
    if first:
        out.add(float(first.group(0)))
    return out


_PACK_NUM = re.compile(r'(\d+)\s*(?:tabs?|tablets?|caps?|capsules?|amps?|ampoules?|sachets?|supp|'
                       r'suppositor\w*|lozenges?|loz[e]?|vials?|pcs|pieces?|قرص|اقراص|أقراص|كبسول\w*|'
                       r'امبول\w*|أمبول\w*|لبوس|كيس|اكياس|أكياس)\b', re.IGNORECASE)


def written_pack(text: str) -> set:
    """Pack-size numbers written in a request — "Aricept 5mg 60tab" → {60}."""
    return {float(m.group(1)) for m in _PACK_NUM.finditer(_clean(text))}


def _pack_counts(name: str) -> set:
    """Unit counts in a catalog name — "ARICEPT 5MG 14TAB (2STRIPSX7)" → {14}."""
    return {float(m.group(1)) for m in _PACK_NUM.finditer(str(name or ''))}


def pack_hint(match_text: str, item_name: str):
    """When the written pack size isn't in the catalog: how many of the chosen packs make
    it up — "60tab" with a 14TAB pack → {'written': 60, 'per_pack': 14, 'packs': 5}.
    A suggestion shown to the reviewer; the quantity is never changed automatically."""
    import math
    w, p = written_pack(match_text), _pack_counts(item_name)
    if len(w) != 1 or len(p) != 1:
        return None
    wn, pn = next(iter(w)), next(iter(p))
    if pn <= 0 or wn == pn:
        return None
    return {'written': int(wn), 'per_pack': int(pn), 'packs': int(math.ceil(wn / pn))}


def _brand_tokens(name: str) -> list:
    """The product-family key of a catalog name: its first word — plus the second when the
    first is short/generic ('ONE ALPHA', 'HIGH FORTE'), so 'STREPSILS (COOL)' and
    'STREPSILS (ORIGINAL)' are one family while 'ONE ALPHA' isn't every 'ONE …'."""
    toks = []
    for tok in _normalize(name).replace('-', ' ').split():
        if re.search(r'\d', tok):
            break
        if re.fullmatch(r'[a-z]{2,}', tok):
            toks.append(tok)
        if len(toks) == 2:
            break
    if toks and len(toks[0]) >= 5:
        return toks[:1]
    return toks


def _family(top_name: str, limit=40):
    """Every active catalog item of the same product family as the top match."""
    from apps.catalog.models import Item
    toks = _brand_tokens(top_name)
    if not toks or len(toks[0]) < 3:
        return []
    rx = r'^\s*' + r'[\s\-]+'.join(re.escape(t) for t in toks) + r'(\s|$|[^a-z])'
    return list(Item.objects.filter(is_active=True, name__iregex=rx)
                .only('id', 'softech_id', 'name', 'pack_price', 'unit_price', 'cost_price')[:limit])


def _stock_and_rate(item_ids, branch):
    """({item_id: branch stock}, {item_id: network monthly sales}) from our synced copies."""
    from django.db.models import Sum
    from apps.catalog.models import ItemStock
    stock, rate = {}, {}
    if branch is not None:
        for r in (ItemStock.objects.filter(item_id__in=item_ids, branch=branch)
                  .values('item_id').annotate(q=Sum('quantity_on_hand'))):
            stock[r['item_id']] = float(r['q'] or 0)
    try:
        from apps.purchasing.models import ItemDemandMetrics
        from apps.purchasing.rate_writer import _latest_run
        run = _latest_run()
        for r in (ItemDemandMetrics.objects.filter(run=run, item_id__in=item_ids)
                  .values('item_id').annotate(a=Sum('monthly_avg'))):
            rate[r['item_id']] = round(float(r['a'] or 0), 2)
    except Exception:                       # no engine run yet → rates unknown, not fatal
        pass
    return stock, rate


def _cand(item, score, stock, rate):
    return {'id': item.id, 'code': item.softech_id, 'name': item.name,
            'score': round(float(score), 3) if score is not None else None,
            'pack_price': float(item.pack_price or 0),
            'branch_stock': stock.get(item.id), 'network_rate': rate.get(item.id, 0.0)}


def resolve(frag: dict, branch=None) -> dict:
    """Fragment → {item, score, flags, candidates, kind}. Never auto-picks between versions
    of the same product; flags anything a person must look at."""
    from apps.catalog.models import Item
    from apps.shortage.learning import lookup_alias_group
    text = frag['text']
    # A remembered ONE-TO-MANY spelling (learned when a person picked several items for it)
    group = None if frag.get('all_variants') else lookup_alias_group(text)
    if group:
        items = {i.id: i for i in Item.objects.filter(id__in=group['item_ids'])}
        ids = [i for i in group['item_ids'] if i in items]
        stock, rate = _stock_and_rate(ids, branch)
        cands = [{**_cand(items[i], group['score'], stock, rate), 'variant': True, 'learned_group': True}
                 for i in ids]
        flags = ['learned_group']
        if frag.get('unit') == 'strip':
            flags.append('strips')
        return {'item': items[ids[0]], 'extra_ids': ids[1:], 'score': group['score'],
                'flags': flags, 'candidates': cands, 'kind': 'item'}
    matches = find_best_matches(text, top_n=6, min_score=0.30)
    # The quantity rule has exceptions: in "كارفيد 25 علبة" the 25 may be the strength.
    # Also match WITH the number; keep whichever reads better (the qty_maybe_strength flag
    # below then tells the reviewer).
    if frag.get('qty_source') in ('unit', 'count') and str(int(frag['qty'])) not in text:
        alt = find_best_matches(f'{text} {int(frag["qty"])}', top_n=6, min_score=0.30)
        if alt and (not matches or alt[0]['score'] >= matches[0]['score']):
            matches = alt                                # equal reads → the number is information
    if not matches:
        return {'item': None, 'score': None, 'flags': ['no_match'], 'candidates': [],
                'kind': 'note' if looks_non_drug(frag['raw']) else 'item'}
    top = matches[0]
    # exact OR close-spelling memory (a person confirmed this spelling, numbers identical)
    learned = bool(top.get('learned') or top.get('learned_fuzzy'))
    flags = ['learned_fuzzy'] if top.get('learned_fuzzy') else []

    # family = all versions of the top match's product; narrow by the numbers + words written
    fam = {i.id: i for i in _family(top['item_name'])}
    fam_ids = list(fam)
    pool_ids = set(fam_ids)            # the versions that fit what was written
    choice = None
    if learned:
        choice = top['item_id']
    elif fam:
        # numbers written: a PACK size ("60tab") narrows the versions but never rules them out
        # (the catalog may only carry 14TAB / 100TAB) — the strength numbers do.
        pack_n = written_pack(text)
        written = _nums(text) - pack_n
        pool = [i for i in fam.values() if not written or written <= _nums(i.name)]
        by_strength = [i for i in pool if written and written <= _strength_nums(i.name)]
        pool = by_strength or pool
        if pack_n and pool:
            same_pack = [i for i in pool if pack_n <= _pack_counts(i.name)]
            if same_pack:
                pool = same_pack
            else:
                flags.append('pack_not_found')            # e.g. "60tab" — adjust the qty
        words = [w for w in re.findall(r'[a-z]{4,}', _normalize(text))
                 if w not in _brand_tokens(top['item_name'])]
        if words:
            narrowed = [i for i in pool if all(w[:4] in _normalize(i.name) for w in words)]
            pool = narrowed or pool
        pool_ids = {i.id for i in pool}
        exact = [i for i in fam.values()
                 if re.sub(r'\s+', ' ', _normalize(i.name)) == re.sub(r'\s+', ' ', _normalize(text))]
        if exact:
            choice = exact[0].id
        elif len(pool) == 1:
            choice = pool[0].id
        elif len(pool) > 1:
            flags.append('choose_variant')
            fam_ids = [i.id for i in pool] + [i for i in fam_ids if i not in {p.id for p in pool}]
        else:
            flags.append('strength_mismatch')          # nothing in the family has those numbers
    else:
        choice = top['item_id']

    # alternatives outside the family (other products that also scored) stay visible
    others = [m for m in matches if m['item_id'] not in fam]
    all_ids = list(dict.fromkeys(fam_ids + [m['item_id'] for m in others]))[:30]
    items = {i.id: i for i in Item.objects.filter(id__in=all_ids)}
    stock, rate = _stock_and_rate(all_ids, branch)
    scores = {m['item_id']: m['score'] for m in matches}
    cands = []
    for iid in all_ids:
        it = items.get(iid)
        if it is None:
            continue
        sc = scores.get(iid)
        if sc is None:
            sc = score_match(text, it.name, getattr(it, 'name_scientific', '') or '')
        c = _cand(it, sc, stock, rate)
        c['variant'] = iid in pool_ids                   # «كل الأنواع» expands to these
        cands.append(c)

    item = items.get(choice) if choice else None
    score = (1.0 if learned else scores.get(choice) or
             (score_match(text, item.name) if item else None)) if item else None
    if item is not None and not learned:
        if head_mismatch(text, item.name):
            flags.append('head_mismatch')
        if score is not None and score < AUTO_SCORE:
            flags.append('low_score')
    if frag.get('all_variants'):
        # «كل الأنواع»: the line stands for the whole family — anchor it on the top version
        # (expand_items() adds the rest when the list is created)
        flags = [f for f in flags if f != 'choose_variant']
        if choice is None and fam:
            choice = fam_ids[0]
            item = items.get(choice)
            score = scores.get(choice) or (score_match(text, item.name) if item else None)
    # irregular quantity
    if frag.get('qty_source') in ('unit', 'count'):
        q = float(frag.get('qty') or 0)
        if q > QTY_LARGE:
            flags.append('qty_large')
        # «عدد 3» / «×3» is an explicit count; only a unit word next to a number is ambiguous
        if frag.get('qty_source') == 'unit' and any(q in _strength_nums(i.name) for i in fam.values()):
            flags.append('qty_maybe_strength')
    if frag.get('unit') == 'strip':
        flags.append('strips')
    kind = 'item'
    if not learned and (score or top['score']) < NOTE_SCORE and frag.get('qty_source') == 'default' \
            and not _nums(text) and (looks_non_drug(frag['raw']) or len(text.split()) <= 3):
        kind = 'note'                                    # a name / place / remark, not a drug
    return {'item': item, 'score': score, 'flags': flags, 'candidates': cands, 'kind': kind}


def strips_per_pack(name: str):
    m = re.search(r'\((\d+)\s*STRIPS?', str(name or ''), re.IGNORECASE)
    return int(m.group(1)) if m else None


def packs(line) -> float:
    """The line's quantity in packs (strips converted when the pack size is in the name)."""
    q = float(line.qty or 0)
    if line.qty_unit == 'strip' and line.item is not None:
        n = strips_per_pack(line.item.name)
        if n:
            return round(q / n, 3)
    return q


# ── 4. persistence ──────────────────────────────────────────────────────────────
def _make_line(req, pos, msg_i, msg, frag, *, from_ocr=False):
    from apps.supply.models import BranchRequestLine as L
    if frag['kind'] == 'note':
        return L(request=req, position=pos, msg_index=msg_i, msg_sender=msg.get('sender', ''),
                 msg_time=msg.get('time', ''), from_ocr=from_ocr, raw_text=frag['raw'][:500],
                 kind=L.KIND_NOTE, flags=[frag.get('note', 'remark')])
    r = resolve(frag, req.branch)
    flags = r['flags'] + (['ocr'] if from_ocr else [])
    ln = L(request=req, position=pos, msg_index=msg_i, msg_sender=msg.get('sender', ''),
           msg_time=msg.get('time', ''), from_ocr=from_ocr, raw_text=frag['raw'][:500],
           match_text=frag['text'][:300], kind=r['kind'], qty=frag['qty'], qty_unit=frag['unit'],
           qty_source=frag['qty_source'], all_variants=frag['all_variants'], item=r['item'],
           score=r['score'], flags=flags, candidates=r['candidates'])
    ln._extra_ids = r.get('extra_ids') or []             # set after bulk_create (M2M needs a pk)
    return ln


def _set_extras(rows):
    for ln in rows:
        if getattr(ln, '_extra_ids', None) and ln.pk:
            ln.extra_items.set(ln._extra_ids)


def build_lines(req, text: str) -> int:
    """Parse + match a paste into the request's lines (appended). Returns lines added."""
    from apps.supply.models import BranchRequestLine as L
    start = L.objects.filter(request=req).count()
    msg_base = (L.objects.filter(request=req).order_by('-msg_index')
                .values_list('msg_index', flat=True).first() or -1) + 1
    rows, pos = [], start
    for mi, msg in enumerate(split_messages(text)):
        urgent = bool(_URGENT_RE.search(msg['text']))
        for frag in extract(msg['text']):
            ln = _make_line(req, pos, msg_base + mi, msg, frag)
            if urgent and ln.kind == L.KIND_ITEM:
                ln.flags = list(ln.flags) + ['urgent']
            rows.append(ln)
            pos += 1
    L.objects.bulk_create(rows)
    _set_extras(rows)
    return len(rows)


def add_ocr_lines(req, readings: list[str], label='صورة') -> int:
    """OCR'd photo rows → lines (always flagged 'ocr': handwriting is never trusted alone)."""
    from apps.supply.models import BranchRequestLine as L
    start = L.objects.filter(request=req).count()
    mi = (L.objects.filter(request=req).order_by('-msg_index')
          .values_list('msg_index', flat=True).first() or -1) + 1
    msg = {'sender': label, 'time': ''}
    rows = []
    for k, frag in enumerate(f for r in readings for f in extract(r)):
        rows.append(_make_line(req, start + k, mi, msg, frag, from_ocr=True))
    L.objects.bulk_create(rows)
    _set_extras(rows)
    return len(rows)


def expand_items(line) -> list:
    """The catalog items a confirmed line stands for: «كل الأنواع» → every version
    (the candidates sharing the picked item's family), else the picked item."""
    from apps.catalog.models import Item
    if line.item is None:
        return []
    if not line.all_variants:
        # one pick, or several picked by hand (item + extra_items), each with the line's qty
        extras = [i for i in line.extra_items.all() if i.id != line.item_id] if line.pk else []
        return [line.item] + extras
    ids = [c['id'] for c in (line.candidates or []) if c.get('variant')]
    if ids:                                              # the versions that fit what was written
        found = {i.id: i for i in Item.objects.filter(id__in=ids, is_active=True)}
        out = [found[i] for i in ids if i in found]
        if line.item.id not in found:
            out.insert(0, line.item)
        return out
    fam = _family(line.item.name)
    return fam or [line.item]


def confirm(req, user) -> 'object':
    """Create the branch shortage list from the CONFIRMED item lines and teach the matcher
    each human-confirmed spelling. Idempotent: a confirmed request returns its list."""
    from django.db import transaction
    from django.utils import timezone
    from apps.shortage.models import ShortageItem, ShortageList
    from apps.supply.models import BranchRequest, BranchRequestLine as L
    if req.status == BranchRequest.STATUS_CONFIRMED and req.shortage_list_id:
        return req.shortage_list
    lines = list(req.lines.filter(kind=L.KIND_ITEM, confirmed=True).select_related('item')
                 .prefetch_related('extra_items'))
    if not lines:
        raise ValueError('لا توجد أسطر مؤكَّدة — أكِّد الأصناف أولاً.')
    profile = getattr(user, 'staff_profile', None)
    with transaction.atomic():
        req = BranchRequest.objects.select_for_update().get(pk=req.pk)
        if req.status == BranchRequest.STATUS_CONFIRMED and req.shortage_list_id:
            return req.shortage_list
        sl = ShortageList.objects.create(
            branch=req.branch, created_by=profile, source='whatsapp',
            title=f'طلبات واتساب #{req.pk}' + (f' — {req.group_name}' if req.group_name else ''),
            notes=f'من «طلبات واتساب» #{req.pk} ({len(lines)} سطر).')
        seen = set()
        for ln in lines:
            targets = expand_items(ln) or [None]
            for it in targets:
                key = getattr(it, 'id', None) or ln.match_text
                if key in seen:
                    continue
                seen.add(key)
                ShortageItem.objects.create(
                    shortage_list=sl, item=it, raw_name=(ln.match_text or ln.raw_text)[:300],
                    quantity_needed=packs(ln), unit=ln.get_qty_unit_display() if ln.qty_unit != 'pack' else '',
                    notes=(f'{ln.msg_sender} {ln.msg_time}'.strip() + (' · كل الأنواع' if ln.all_variants else ''))[:300],
                    source='whatsapp', match_score=ln.score, is_confirmed=it is not None,
                    is_unmatched=it is None, confirmed_by=profile if it is not None else None,
                    confirmed_at=timezone.now() if it is not None else None)
            # every confirmed line teaches the shared memory: one item → a spelling alias,
            # several hand-picked items → a group memory («كل الأنواع» is a family rule,
            # not a spelling, so it is not memorised)
            if ln.item is not None and ln.match_text and not ln.all_variants:
                try:
                    from apps.shortage import learning
                    picked = [t for t in targets if t is not None]
                    if len(picked) == 1:
                        learning.learn_alias(ln.match_text, picked[0], source='whatsapp')
                    elif len(picked) > 1:
                        learning.learn_alias_group(ln.match_text, picked, source='whatsapp')
                except Exception:
                    pass
        req.status, req.shortage_list = BranchRequest.STATUS_CONFIRMED, sl
        req.confirmed_by, req.confirmed_at = user, timezone.now()
        req.save(update_fields=['status', 'shortage_list', 'confirmed_by', 'confirmed_at'])
    return sl


def pseudo_isr(req, *, confirmed_only=False) -> dict:
    """The request in the ISR-fulfilment engine's shape: one line per catalog item, qty in
    packs, summed when two lines name the same item. Counted: confirmed lines, plus CLEAN
    unconfirmed suggestions (no warning flag, good score) so the analysis can run before the
    review ends — a doubtful suggestion (e.g. «اوميز» → a cream) never enters the numbers."""
    from apps.supply.models import BranchRequestLine as L
    agg = {}
    for ln in (req.lines.filter(kind=L.KIND_ITEM, item__isnull=False).select_related('item')
               .prefetch_related('extra_items')):
        if not ln.confirmed and (confirmed_only or set(ln.flags or []) - {'urgent', 'learned_group', 'learned_fuzzy'}
                                 or (ln.score or 0) < AUTO_SCORE or ln.from_ocr):
            continue                     # transfers (confirmed_only) move only what a person confirmed
        for it in expand_items(ln):
            a = agg.setdefault(it.softech_id, {'code': str(it.softech_id).strip(), 'qty': 0.0,
                                               'cost': float(it.cost_price or 0), 'price': float(it.pack_price or 0),
                                               'nowqty_at_request': 0.0})
            a['qty'] += packs(ln)
    lines = list(agg.values())
    user = getattr(req.created_by, 'username', '') or ''
    return {'isr': f'WA-{req.pk}', 'kind': 'whatsapp', 'branch': req.branch.softech_branch_id,
            'for_branch': req.branch.softech_branch_id,
            'date': req.created_at.strftime('%Y-%m-%d') if req.created_at else '',
            'approved': 0, 'value': round(sum(l['qty'] * l['cost'] for l in lines), 3),
            'user': user, 'lines': lines}
