"""
apps/shortage/phonetic.py — Arabic ↔ Latin SOUND matching for the catalog matcher.

Egyptian pharmacy Arabic writes brand names by SOUND: سيريلاك = CERELAC, ريباريل = REPARIL,
انتروجيرمينا = ENTEROGERMINA, اوكسميت = OXYMET. Short vowels aren't written and several
Latin letters share one Arabic letter. So both sides are reduced to a CONSONANT SKELETON
over sound classes, and skeletons are compared:

    B  b p ب        F  f v ph ف       K  k c(hard) q ck ch(chloro) ق ك خ
    S  s c(soft) ص س   Z  z ز ذ ظ      J  g j ج غ        T  t th ت ط ث
    D  d د ض         X  sh ش           KS x  (= كس)      L M N R H W Y
    vowels a e i o u (and y between consonants), ا و ي ى ء ع ة, a silent h → dropped

    سيريلاك → SRLK ← CERELAC     سبلفكت → SBLFKT ← SUPLFECT     اوكسميت → KSMT ← OXYMET

The catalog side is computed once per process (≈38k active items, refreshed every
INDEX_TTL seconds) and searched with rapidfuzz in C — a few milliseconds per lookup.
Arabic dosage-form words (نقط, جيل, ق, ش, فيال …) are NOT name tokens: they become a form
hint; filler words (كوته, اخر, صغير …) are dropped.
Deterministic — no model decides anything.
"""
from __future__ import annotations

import re
import threading
import time

INDEX_TTL = 30 * 60

# ── Latin → skeleton ────────────────────────────────────────────────────────────
_EN_DIGRAPHS = [('ph', 'f'), ('sch', 'x'), ('sh', 'x'), ('ch', 'k'), ('ck', 'k'), ('qu', 'k'),
                ('th', 't'), ('gh', ''), ('kh', 'k'), ('x', 'ks'), ('wh', 'w')]
_EN_CLASS = {'b': 'B', 'p': 'B', 'f': 'F', 'v': 'F', 'k': 'K', 'q': 'K', 'g': 'J', 'j': 'J',
             's': 'S', 'z': 'Z', 't': 'T', 'd': 'D', 'l': 'L', 'm': 'M', 'n': 'N', 'r': 'R',
             'h': 'H', 'w': 'W', 'x': 'X'}


def skeleton_en(word: str) -> str:
    w = re.sub(r'[^a-z]', '', (word or '').lower())
    if not w:
        return ''
    w = re.sub(r'c(?=[eiy])', 's', w)          # soft c: cerelac, cetal, cyst
    w = w.replace('c', 'k')
    for a, b in _EN_DIGRAPHS:
        w = w.replace(a, b)
    out = []
    adjacent = False                                # previous kept letter directly before (no vowel)
    for i, ch in enumerate(w):
        if ch in 'aeiou':
            adjacent = False
            continue
        if ch == 'y':                               # consonant only before a vowel at the start
            if i == 0 and len(w) > 1 and w[1] in 'aeiou':
                out.append('Y')
                adjacent = True
            else:
                adjacent = False
            continue
        if ch == 'h' and (i == len(w) - 1 or (i > 0 and w[i - 1] not in 'aeiou')):
            continue                                # silent h: rhinex, -h, after a consonant
        if ch == 'w' and i > 0:                     # "two", "elbow": w inside a word is a vowel
            adjacent = False
            continue
        c = _EN_CLASS.get(ch)
        if c and not (adjacent and out and out[-1] == c):   # collapse only true doubles: ll, tt
            out.append(c)
        adjacent = bool(c)
    return ''.join(out)


# Vowel-aware key: Arabic DOES write long vowels (ا و ي), which tells short skeletons apart
# («بيبيلاك» BIBILAK = BEBELAC, not PALC). Vowels → classes A (a) / I (e i y) / U (o u w).
_V_EN = {'a': 'A', 'e': 'I', 'i': 'I', 'y': 'I', 'o': 'U', 'u': 'U', 'w': 'U'}
_V_AR = {'ا': 'A', 'أ': 'A', 'إ': 'A', 'آ': 'A', 'ى': 'A', 'ي': 'I', 'و': 'U'}


def vkey_en(word: str) -> str:
    w = re.sub(r'[^a-z]', '', (word or '').lower())
    w = re.sub(r'c(?=[eiy])', 's', w).replace('c', 'k')
    for a, b in _EN_DIGRAPHS:
        w = w.replace(a, b)
    out = []
    for ch in w:
        c = _V_EN.get(ch) or _EN_CLASS.get(ch)
        if c and (not out or out[-1] != c):
            out.append(c)
    return ''.join(out)


def vkey_ar(word: str) -> str:
    w = re.sub(r'[^؀-ۿ]', '', word or '')
    out = []
    for i, ch in enumerate(w):
        if ch == 'ه' and i == len(w) - 1:
            continue
        c = _V_AR.get(ch) or _AR_CLASS.get(ch)
        if c and (not out or out[-1] != c):
            out.append(c)
    return ''.join(out)


# ── Arabic → skeleton ───────────────────────────────────────────────────────────
_AR_CLASS = {'ب': 'B', 'پ': 'B', 'ف': 'F', 'ڤ': 'F', 'ق': 'K', 'ك': 'K', 'ک': 'K', 'خ': 'K',
             'س': 'S', 'ص': 'S', 'ز': 'Z', 'ذ': 'Z', 'ظ': 'Z', 'ج': 'J', 'غ': 'J', 'گ': 'J',
             'ت': 'T', 'ط': 'T', 'ث': 'T', 'د': 'D', 'ض': 'D', 'ش': 'X', 'ل': 'L', 'م': 'M',
             'ن': 'N', 'ر': 'R', 'ه': 'H', 'ح': 'H'}
_AR_VOWELISH = set('اأإآىءئؤعةوي')


def skeleton_ar(word: str) -> str:
    w = re.sub(r'[^؀-ۿ]', '', word or '')
    if not w:
        return ''
    out = []
    adjacent = False
    for i, ch in enumerate(w):
        if ch in _AR_VOWELISH:
            # ي starting the word before a consonant = a consonant (Y); else a vowel
            if i == 0 and ch == 'ي' and len(w) > 1 and w[1] not in _AR_VOWELISH:
                out.append('Y')
                adjacent = True
                continue
            adjacent = False
            continue
        if ch == 'ه' and i == len(w) - 1:          # final ه = a vowel ending
            continue
        c = _AR_CLASS.get(ch)
        if c and not (adjacent and out and out[-1] == c):   # Arabic has no written doubles
            out.append(c)
        adjacent = bool(c)
    return ''.join(out)


# ── Arabic words that are NOT part of a product name ────────────────────────────
AR_FORMS = {   # → a Latin form word to look for in the item name (a ranking hint)
    'نقط': 'drop', 'نقطه': 'drop', 'قطره': 'drop', 'قطرة': 'drop', 'نقطة': 'drop',
    'جيل': 'gel', 'جل': 'gel', 'كريم': 'cream', 'مرهم': 'oint', 'دهان': 'oint',
    'ش': 'syrup', 'شراب': 'syrup', 'سيرب': 'syrup', 'ق': 'tab', 'اقراص': 'tab', 'قرص': 'tab', 'أقراص': 'tab',
    'كبسول': 'cap', 'كبسوله': 'cap', 'كبسولات': 'cap', 'فيال': 'vial', 'امبول': 'amp',
    'أمبول': 'amp', 'حقن': 'amp', 'حقنه': 'amp', 'لبوس': 'supp', 'اكياس': 'sachet', 'أكياس': 'sachet',
    'كيس': 'sachet', 'فوار': 'eff', 'بخاخ': 'spray', 'سبراي': 'spray', 'دش': 'douche',
    'غسول': 'wash', 'شامبو': 'shampoo', 'لوشن': 'lotion', 'بودره': 'powder', 'بودرة': 'powder',
    'مسحوق': 'powder', 'معلق': 'susp', 'محلول': 'sol', 'لبن': 'milk', 'حليب': 'milk',
    'جرام': 'gm', 'جم': 'gm', 'مل': 'ml', 'مجم': 'mg', 'ملجم': 'mg',
}
# Arabic DESCRIPTOR words → the English words catalog names use (a ranking hint, not a
# name): «سيريلاك فواكه» = CERELAC …FRUITS, «بيتادين مطهر» = BETADINE …ANTISEPTIC.
AR_WORDS = {
    'فواكه': ('fruit',), 'فاكهه': ('fruit',), 'تفاح': ('apple',), 'موز': ('banana',),
    'برتقال': ('orange',), 'عسل': ('honey',), 'ليمون': ('lemon',), 'فراوله': ('strawberr',),
    'قمح': ('wheat',), 'ارز': ('rice',), 'رز': ('rice',), 'خضار': ('vegetable',), 'شوفان': ('oat',),
    'تمر': ('date',), 'لبن': ('milk',), 'نعناع': ('mint',), 'كرز': ('cherry',), 'فانيليا': ('vanilla',),
    'شيكولاته': ('chocolate', 'choco'), 'شوكولاته': ('chocolate', 'choco'),
    'اطفال': ('inf', 'pediatric', 'paed', 'child', 'kid', 'baby', 'junior'),
    'طفل': ('inf', 'child', 'kid', 'baby'), 'رضع': ('infant', 'baby'), 'كبار': ('adult',),
    'وومان': ('woman', 'women'), 'ستات': ('woman', 'women'), 'نساء': ('women', 'woman'),
    'مان': ('man', 'men'), 'رجال': ('man', 'men'), 'حامل': ('pregna', 'prenatal'),
    'مطهر': ('antiseptic',), 'صغير': ('small', 'mini'), 'كبير': ('big', 'large', 'jumbo'),
    'ممتد': ('sr', 'xr', 'retard', 'cr'), 'فوار': ('eff',), 'بدون': ('free', 'without'),
    'سكر': ('sugar',), 'ليلي': ('night',), 'نهاري': ('day',), 'بلس': ('plus',), 'اكسترا': ('extra',),
    'فورت': ('forte',), 'ماكس': ('max',), 'جولد': ('gold',), 'بيبي': ('baby',), 'جونيور': ('junior',),
    'برو': ('pro',), 'ادفانس': ('advance', 'adv'), 'كومبليت': ('complete',), 'سبراي': ('spray',),
}
AR_FILLER = {'كوته', 'كوتة', 'اخر', 'آخر', 'متاح', 'مطلوب', 'عدد', 'علبه', 'علبة', 'علب', 'شريط',
             'سعر', 'بسعر', 'خصم', 'بونص', 'جديد', 'قديم', 'نكهه', 'نكهة', 'كل', 'الانواع', 'انواع',
             'و', 'من', 'او', 'أو', 'مع', 'عرض', 'اورجينال', 'اوريجينال', 'محلي', 'مستورد', 'ابيض',
             'احمر', 'ازرق', 'للبرد', 'والكحه', 'للكحه', 'للبرد', 'جرعه', 'جرعة'}


def query_tokens(text: str):
    """(name skeletons in order, form hints) for an Arabic (or mixed) line."""
    p = parse_query(text)
    return p['skels'], p['forms']


def parse_query(text: str) -> dict:
    """An Arabic (or mixed) line → {'skels', 'vkeys' (name words, in order), 'forms'
    (dosage-form hints), 'words' (English descriptor hints)}."""
    t = re.sub(r'[ً-ٰٟ]', '', str(text or ''))
    t = re.sub(r'[أإآٱ]', 'ا', t).replace('ة', 'ه').replace('ى', 'ي')
    skels, vkeys, forms, words = [], [], set(), set()
    for tok in re.findall(r'[؀-ۿ]+|[A-Za-z]+', t):
        if re.match(r'[A-Za-z]', tok):
            if tok.lower() in _LATIN_FORM:
                forms.add(tok.lower())
                continue
            sk, vk = skeleton_en(tok), vkey_en(tok)
        else:
            if tok in AR_FORMS:
                forms.add(AR_FORMS[tok])
                continue
            if tok in AR_WORDS:
                words.update(AR_WORDS[tok])
                if tok not in ('مان', 'وومان', 'بلس', 'اكسترا', 'فورت', 'ماكس', 'جولد', 'بيبي',
                               'جونيور', 'برو', 'ادفانس', 'كومبليت'):
                    continue                     # a pure descriptor; brand-like words stay too
            if tok in AR_FILLER:
                continue
            sk, vk = skeleton_ar(tok), vkey_ar(tok)
        if sk:                                   # 1-letter skeletons kept for joins (وان تو ثري)
            skels.append(sk)
            vkeys.append(vk)
    return {'skels': skels, 'vkeys': vkeys, 'forms': forms, 'words': words}


# ── catalog side: an in-process index of item-name skeletons ────────────────────
_LATIN_FORM = {'tab', 'tabs', 'tablet', 'tablets', 'cap', 'caps', 'capsule', 'capsules', 'mg', 'ml',
               'gm', 'g', 'mcg', 'ug', 'iu', 'syrup', 'syr', 'susp', 'suspension', 'drops', 'drop',
               'cream', 'gel', 'oint', 'ointment', 'amp', 'amps', 'vial', 'vials', 'inj', 'sachet',
               'sachets', 'eff', 'spray', 'supp', 'lotion', 'shampoo', 'powder', 'big', 'size', 'new',
               'old', 'small', 'xx', 'xxx', 'strips', 'stripsx', 'strip', 'box', 'pack', 'offer', 'local',
               'imported', 'and', 'with', 'for', 'the', 'of', 'oral', 'sol', 'solution', 'adult', 'infant'}

_lock = threading.Lock()
_index = {'built': 0.0, 'ids': [], 'first': [], 'joined': [], 'joined3': [], 'tokens': {}, 'vtokens': {},
          'sci': [], 'vfirst': []}


def _item_tokens(name: str, sci: str = ''):
    """[(consonant skeleton, vowel key)] for the first 4 name words (forms / units skipped)."""
    toks = []
    for w in re.findall(r'[A-Za-z]+', name or ''):
        lw = w.lower()
        if lw in _LATIN_FORM:
            continue
        sk = skeleton_en(w)
        if sk:
            toks.append((sk, vkey_en(w)))
        if len(toks) == 4:
            break
    return toks


def _build():
    from apps.catalog.models import Item
    ids, first, joined, joined3, tokens, vtokens, sci, vfirst = [], [], [], [], {}, {}, [], []
    for iid, name, sname in Item.objects.filter(is_active=True).values_list('id', 'name', 'name_scientific').iterator():
        toks = _item_tokens(name)
        if not toks:
            continue
        sks = [t[0] for t in toks]
        ids.append(iid)
        vfirst.append(toks[0][1])
        first.append(sks[0])
        joined.append(''.join(sks[:2]))
        joined3.append(''.join(sks[:3]))
        tokens[iid] = sks
        vtokens[iid] = [t[1] for t in toks]
        s = _item_tokens(sname or '')
        sci.append(s[0][0] if s else '')
    _index.update(built=time.time(), ids=ids, first=first, joined=joined, joined3=joined3,
                  tokens=tokens, vtokens=vtokens, sci=sci, vfirst=vfirst)


def index():
    if time.time() - _index['built'] > INDEX_TTL or not _index['ids']:
        with _lock:
            if time.time() - _index['built'] > INDEX_TTL or not _index['ids']:
                _build()
    return _index


def reset_index(*_a, **_k):
    _index['built'] = 0.0


def _connect_signals():
    """A catalog item saved / deleted through the ORM refreshes the sound index on the next
    lookup (bulk SOFTECH syncs are covered by INDEX_TTL)."""
    from django.db.models.signals import post_delete, post_save
    from apps.catalog.models import Item
    post_save.connect(reset_index, sender=Item, dispatch_uid='phonetic_reset_save')
    post_delete.connect(reset_index, sender=Item, dispatch_uid='phonetic_reset_delete')


def search_ids(query: str, *, limit: int = 8) -> list:
    """For SEARCH boxes: catalog items an Arabic query SOUNDS like («سيريلاك» → CERELAC …),
    via the shared matcher (learned memory included). [] for a Latin query or no evidence."""
    if not re.search(r'[؀-ۿ]', query or '') or len((query or '').strip()) < 3:
        return []
    from .matching import find_best_matches
    return [m['item_id'] for m in find_best_matches(query, top_n=limit, min_score=0.75)]


# ── retrieval + scoring ─────────────────────────────────────────────────────────
def _sim(a: str, b: str) -> float:
    from rapidfuzz.distance import Levenshtein
    if not a or not b:
        return 0.0
    return Levenshtein.normalized_similarity(a, b)


def candidates(text: str, *, limit: int = 60, cutoff: float = 0.72) -> list:
    """[(item_id, sound score 0..1)] for the line's first name word(s) — by skeleton
    similarity against every catalog item's brand (and scientific) skeleton. ms-fast."""
    from rapidfuzz import process
    from rapidfuzz.distance import Levenshtein
    p = parse_query(text)
    skels, vkeys = p['skels'], p['vkeys']
    if not skels:
        return []
    ix = index()
    q1 = skels[0]
    q12 = ''.join(skels[:2])
    q123 = ''.join(skels[:3])
    hits = {}
    pools = [(q1, ix['first']), (q12, ix['joined']), (q1, ix['sci'])]
    if len(q1) <= 2 and len(skels) > 1:          # a 1–2 letter first word is too short alone
        pools = [(q12, ix['joined']), (q123, ix['joined3'])]
    if len(q1) <= 3 and vkeys and len(vkeys[0]) >= 3:
        pools.append((vkeys[0], ix['vfirst']))   # «هيرو» HR is ambiguous; HIRU = HERO is not
    # each lookup method keeps its own best `limit` — the union is scored by the caller, so
    # many short "STL" products can't crowd out ACETYLCYSTEINE found via the joined words
    for q, pool in pools:
        if len(q) < 2:
            continue
        for _choice, score, idx in process.extract(q, pool, scorer=Levenshtein.normalized_similarity,
                                                   limit=limit, score_cutoff=cutoff):
            iid = ix['ids'][idx]
            if score > hits.get(iid, 0):
                hits[iid] = score
    return sorted(hits.items(), key=lambda x: -x[1])


def sound_score(text: str, item_id: int) -> float:
    """How well the line's name words SOUND like the item's name words (0..1): the first
    query word against the item's first two words, plus coverage of the other words."""
    p = parse_query(text)
    skels, vkeys = p['skels'], p['vkeys']
    ix = index()
    toks = ix['tokens'].get(item_id) or []
    vtoks = ix['vtokens'].get(item_id) or []
    if not skels or not toks:
        return 0.0

    def both(qs, qv, ts, tv):
        # consonants carry most of the signal; the long vowels Arabic writes break ties
        # between short skeletons (BIBILAK = BEBELAC ≠ PALC)
        return 0.7 * _sim(qs, ts) + 0.3 * _sim(qv, tv)

    best = 0.0
    # k = how many query words form the name: «استيل سيساتين» is ONE word (ACETYLCYSTEINE),
    # «وان تو ثري» is three words matching three
    for k in (1, 2, 3):
        if k > len(skels):
            break
        qs, qv = ''.join(skels[:k]), ''.join(vkeys[:k])
        head = max(both(qs, qv, ''.join(toks[:j]), ''.join(vtoks[:j])) for j in (1, 2, 3) if j <= len(toks))
        rest = [(s, v) for s, v in zip(skels[k:], vkeys[k:]) if len(s) >= 2]
        if rest:
            cover = sum(max(both(s, v, t, tv) for t, tv in zip(toks, vtoks)) for s, v in rest) / len(rest)
            best = max(best, 0.8 * head + 0.2 * cover)
        else:
            best = max(best, head)
    return round(best, 4)


def word_hints(text: str) -> set:
    return parse_query(text)['words']


def form_hints(text: str) -> set:
    return query_tokens(text)[1]
