"""
apps/supply/availability.py — the supplier-PUSH ingestion service.

Turns a supplier's messy availability message (WhatsApp paste, OCR'd screenshot, Excel
row) into AvailabilityLine rows. It REUSES the shared pipeline:
  • item name → catalog match : apps/supply/ingest.resolve_line  (+ learn_alias, vendor-scoped)
  • image → text              : apps/vision.ocr.run_engines / pick_primary
  • supplier name → personcode: apps/invoices/suppliers.resolve_supplier

What is NEW here is only the deterministic extraction of SUPPLIER ECONOMICS from a line
(quantity available / price / FOC / discount / expiry / supplier code) — a shortage line
never carries these. Everything is optional: a bare "Recormon 4000 available" is valid (§4).

Deterministic only (no LLM in the number path, §28). Arabic-Indic digits are folded to
Latin platform-wide (memory: latin-digits module-wide).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from .ingest import resolve_line, review_flags, teach_alias

# ═══════════════════════════════════════════════════════════════════════════════
# Supplier-message parser — an ORDERED, deterministic pipeline (hardened in Phase 7
# against real WhatsApp copies):
#   1. fold digits · strip the WhatsApp timestamp/sender header · drop noise lines
#   2. strip bullets / numbering / emoji · split "A 5، B 3" multi-item lines
#   3. economics by EXPLICIT markers: FOC → price → discount → expiry → code → quantity
#   4. only then a trailing-number fallback, with a safety rule: a single bare number glued
#      to the drug name ("Recormon 4000", "Kreon 25000") is the STRENGTH, never the quantity
#      — a lost strength causes wrong matches; an unknown quantity is valid (§4).
# The branch-shortage parser (parse_quantity_from_text) keeps its own convention.
# ═══════════════════════════════════════════════════════════════════════════════

# Arabic-Indic + Eastern-Arabic (Persian) digits → Latin.
_AR_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')
_NUM = r'\d+(?:[.,]\d+)?'

# "[20/09/2026, 10:15] Name: …" · "20/09/2026, 10:15 - Name: …" · "[20/9/2026 10:17 ص] Name: …"
# · "9/20/26, 10:15 PM - Name: …" · WhatsApp Desktop copy, time first: "[12:44 pm, 07/10/2026] Name: …".
# Group `sender` is the chat participant (supplier hint).
_WA_TIME = r'\d{1,2}:\d{2}(?::\d{2})?\s*(?:[AaPp]\.?\s?[Mm]\.?|ص|م)?'
_WA_DATE = r'\d{1,4}[/.\-]\d{1,2}[/.\-]\d{2,4}'
_WA_TS = (r'^\s*\[?\s*(?:' + _WA_DATE + r',?\s+' + _WA_TIME + r'|' + _WA_TIME + r',?\s+' + _WA_DATE + r')'
          r'\s*\]?\s*(?:[-–—]\s*)?')
_WA_HEADER_RE = re.compile(_WA_TS + r'(?P<sender>[^:\n]{1,60}):\s*')
_WA_SYSTEM_RE = re.compile(_WA_TS + r'[^:]*$')          # timestamp but no "Name:" → system line

_NOISE_RE = re.compile(
    r'<\s*media omitted\s*>|<\s*تم استبعاد الوسائط\s*>|(?:image|video|audio|sticker|document) omitted|'
    r'this message was deleted|you deleted this message|تم حذف هذه الرسالة|حذفت هذه الرسالة|'
    r'end-to-end encrypted|missed (?:voice|video) call|مكالمة (?:صوتية|فيديو) فائتة', re.I)
_GREETING_RE = re.compile(
    r'^(?:السلام عليكم|سلام عليكم|صباح|مساء|أهلا|اهلا|مرحبا|شكرا|شكراً|تمام|حاضر|'
    r'ok\b|okay\b|thanks|thank you|hello|hi\b|dear\b|good (?:morning|evening|afternoon))', re.I)
_BULLET_RE = re.compile(r'^[\s\-–—\*•·▪►➤✓✔☑★☆◆◇■□▫>]+')
_NUMBERING_RE = re.compile(r'^\(?\d{1,3}\s*[\)\-\.]\s*(?=[^\d\s])')
_EMOJI_RE = re.compile('[\U0001F000-\U0001FAFF☀-➿️‍‎‏]')

_FOC_W   = r'(?:foc|free|bonus|بونص|بونس|هدية|هديه|مجانا|مجانًا|مجاني|مجانى)'
_UNIT_W  = (r'(?:boxes|box|bx|pcs|pc|pieces|piece|units|unit|pens|pen|vials|vial|ampoules|amps|amp|'
            r'packs|pack|علب|علبة|علبه|عبوة|عبوه|عبوات|قطعة|قطعه|قطع|امبول|أمبول|فيال|قلم|اقلام|أقلام)')
_QTY_KW  = (r'(?:qty|quantity|الكمية|الكميه|كمية|كميه|عدد|available|avail|in stock|'
            r'متاح|متوفر|متوفره|متوافر|موجود|موجوده)')
_PRICE_KW = r'(?:price|السعر|سعر|بسعر)'
# Egyptian pounds: 'ج.م' (with the dot), جنيه, a lone 'ج', EGP, LE. NOT 'جم' / 'جرام' — those
# are GRAMS in pharma names ('اوجمنتين ١ جم' = Augmentin 1 g), never a price.
_CUR     = r'(?:ج\.\s?م\.?|جنيه|جنية|ج(?![مر؀-ۿ])|egp|l\.?e\.?)'
_DISC_KW = r'(?:خصم|disc(?:ount)?)'
_EXP_KW  = r'(?:exp(?:iry)?\.?|ex\.|صلاحية|صلاحيه|تنتهي|انتهاء)'
_CODE_KW = r'(?:code|كود)'
# Residual label words removed from the name once their numbers were taken.
# Count units only — a FORM word that is also a unit («امبول», amp, vial, pen) stays in the
# name: «Depovita amp» without "amp" matched the lozenges.
_COUNT_UNIT_W = (r'(?:boxes|box|bx|pcs|pc|pieces|piece|units|unit|packs|pack|علب|علبة|علبه|عبوة|عبوه|'
                 r'عبوات|قطعة|قطعه|قطع)')
_STRIP_WORDS_RE = re.compile(
    r'(?<!\w)(?:' + '|'.join([_QTY_KW, _FOC_W, _PRICE_KW, _DISC_KW, _EXP_KW, _COUNT_UNIT_W,
                              r'stock', r'only', r'فقط']) + r')(?!\w)', re.I)
_CUR_RESIDUE_RE = re.compile(r'(?<!\w)(?:جنيه|جنية|egp|l\.?e\.?|ج\.\s?م\.?)(?!\w)', re.I)

# ── Distributor «الوارد» terms (owner 2026-10-07, real lists from EGY DRUG / PO / AKHNATON) ──
# Quota «كوته علبه / اثنين / خمسه / كوته 30» = the most one pharmacy may order.
_QUOTA_WORDS = {'علبه': 1, 'علبة': 1, 'علبع': 1, 'واحده': 1, 'واحدة': 1, 'علبتين': 2,
                'اثنين': 2, 'اتنين': 2, 'اثنيت': 2, 'إثنين': 2, 'اثنان': 2,
                'تلاته': 3, 'ثلاثه': 3, 'ثلاثة': 3, 'تلاتة': 3, 'تلات': 3,
                'اربعه': 4, 'أربعه': 4, 'اربعة': 4, 'أربعة': 4, 'خمسه': 5, 'خمسة': 5,
                'سته': 6, 'ستة': 6, 'عشره': 10, 'عشرة': 10}
_QUOTA_RE = re.compile(
    r'(?P<half>نصف|نص)?\s*(?<![؀-ۿ])كو[تط](?:ه|ة|ا)(?![؀-ۿ])(?:\s*(?:(?P<n>\d+)(?![\d.,/])|(?P<w>'
    + '|'.join(sorted(_QUOTA_WORDS, key=len, reverse=True)) + r')(?![؀-ۿ])))?')
# Bonus «25+1», tiers «18+2 …… 36+4 …… 106+14» — buy N get M free on the ORDER.
_BONUS_RE = re.compile(r'(?<![\w/])(?<!\d\.)(\d+)\s*\+\s*(\d+)(?!\d)(?![./]\d)')
# Promo pack «30t +7free» — extra units INSIDE the pack (not a bonus on the order).
_PROMO_RE = re.compile(r'(?<![\d.])(\d+)\s*(?:t|tab|tabs|caps?|c|ق|ك)?\s*\+\s*(\d+)\s*'
                       r'(?:free|مجان[اىي]?|هدي[هة])', re.I)
# Availability signals written in words (kept, and removed from the product name).
_SIGNAL_PHRASES = [
    ('last_qty', re.compile(r'(?:ا|آ|أ)خر\s+(?:ال)?كمي(?:ه|ة|ات)')),
    ('limited', re.compile(r'(?:ال)?كمي(?:ه|ة|ات)\s+محدود(?:ه|ة)?(?:\s+جد[اً]+)?')),
    ('back_in_stock', re.compile(r'بقا(?:له|لها|لو)\s+فتر(?:ه|ة)\s+(?:م|ما\s*)?(?:كنش|كانش)\s+موجود(?:ه|ة)?'
                                 r'|(?:رجع|عاد)\s+(?:تاني|للتوفر|متوفر)')),
    ('scarce_variant', re.compile(r'(?:ال)?تركيز\s+(?:ده|دا|دي)\s+قليل(?:ه|ة)?|(?:ال)?كمي(?:ه|ة)\s+قليل(?:ه|ة)')),
]
_SIGNAL_EMOJI = {'🔥': 'hot', '🚩': 'flag'}
# «اخر 30 علبه» / «فاضل فقط 100 علبه» — what is left at the supplier.
_LEFT_RE = re.compile(r'(?:(?:ا|آ|أ)خر|فاضل|باقي|متبقي)\s*(?:فقط\s*)?(\d+)\s*' + _UNIT_W + r'?(?![\w.])')
# «بتركيزاته / بأنواعه / كل الانواع» — the whole product family (a person confirms which).
_FAMILY_RE = re.compile(
    r'(?<![\w])(?:ب\s*(?:تركيزات|تراكيز|تركيز|تراكيزات|انواع|أنواع|اشكال|أشكال|احجام|أحجام|نكهات)(?:ه|ها)?'
    r'|(?:كل|جميع)\s+(?:ال)?(?:انواع|أنواع|تركيزات|اصناف|أصناف|نكهات)|all\s+(?:types|kinds|strengths))(?![\w])',
    re.I)


@dataclass
class ParsedAvailability:
    name_part: str
    supplier_qty: float | None = None
    price: float | None = None
    foc_qty: float | None = None
    discount_pct: float | None = None
    expiry: str = ''
    supplier_item_code: str = ''
    extracted: dict = field(default_factory=dict)   # what was pulled + removed (audit)
    noise: bool = False                             # greeting / media / system line
    bonus_buy: float | None = None                  # «25+1» → buy 25 (foc_qty = 1)
    bonus_tiers: list = field(default_factory=list)  # [[18, 2], [36, 4], [106, 14]]
    quota: float | None = None                      # «كوته خمسه» → 5
    promo: str = ''                                 # «30t +7free» → '30+7 free'
    signals: list = field(default_factory=list)     # last_qty / limited / hot / …
    all_variants: bool = False                      # «بتركيزاته» → the whole family

    def terms(self) -> dict:
        """The economics as AvailabilityLine field values."""
        return {'supplier_qty': self.supplier_qty, 'price': self.price, 'foc_qty': self.foc_qty,
                'discount_pct': self.discount_pct, 'expiry': self.expiry,
                'supplier_item_code': self.supplier_item_code, 'bonus_buy': self.bonus_buy,
                'bonus_tiers': self.bonus_tiers, 'quota': self.quota, 'promo': self.promo,
                'signals': self.signals}


TERM_FIELDS = ('supplier_qty', 'price', 'foc_qty', 'discount_pct', 'expiry', 'supplier_item_code',
               'bonus_buy', 'bonus_tiers', 'quota', 'promo', 'signals')


def line_terms(line) -> dict:
    """A saved line's economics — copied onto the sibling lines of a split."""
    return {f: getattr(line, f) for f in TERM_FIELDS}


def _fold_digits(s: str) -> str:
    return (s or '').translate(_AR_DIGITS).replace('٪', '%')


def _to_float(s):
    return float(str(s).replace(',', '.'))


def clean_line(raw: str):
    """Line-level cleanup shared by splitting and parsing. Returns the cleaned product text,
    or None for a line that is not a product (header-only system line, media / deleted
    marker, greeting, section heading)."""
    text = _fold_digits(str(raw or '')).strip()
    if not text:
        return None
    if _WA_SYSTEM_RE.match(text) and not _WA_HEADER_RE.match(text):
        return None
    text = _WA_HEADER_RE.sub('', text, count=1)
    text = _EMOJI_RE.sub(' ', text)
    text = _BULLET_RE.sub('', text)
    text = _NUMBERING_RE.sub('', text).strip()
    if not text or _NOISE_RE.search(text):
        return None
    has_digit = bool(re.search(r'\d', text))
    if not has_digit and (_GREETING_RE.match(text) or text.rstrip().endswith(':')):
        return None
    if not re.search(r'[A-Za-z؀-ۿ]{2,}', text):
        return None
    return text


def _split_multi(line: str) -> list:
    """'Voltaren 50 5، Brufen 400 3' → two lines — only when EVERY part looks like an item."""
    parts = [p.strip() for p in re.split(r'\s*[،;]\s*|\s+\|\s+', line) if p.strip()]
    if len(parts) > 1 and all(re.search(r'[A-Za-z؀-ۿ]{3,}', p) for p in parts):
        return parts
    return [line]


def split_availability_lines(raw_content: str) -> list:
    out = []
    for ln in str(raw_content or '').splitlines():
        cleaned = clean_line(ln)
        if cleaned:
            out.extend(_split_multi(cleaned))
    return out


def detect_sender(raw_content: str) -> str:
    """The most frequent WhatsApp sender in a pasted chat — a supplier hint when the
    operator didn't type one (§2: make the WhatsApp path fast)."""
    from collections import Counter
    senders = Counter()
    for ln in str(raw_content or '').splitlines():
        m = _WA_HEADER_RE.match(_fold_digits(ln))
        if m:
            senders[m.group('sender').strip()] += 1
    return senders.most_common(1)[0][0] if senders else ''


def _norm_expiry(a: str, b: str) -> str:
    """Two date parts (either order) → 'MM/YYYY'."""
    x, y = int(a), int(b)
    if x > 12 and y <= 12:             # YYYY-MM
        year, month = x, y
    else:                              # MM/YYYY or MM/YY
        month, year = x, y
    if year < 100:
        year += 2000
    if not 1 <= month <= 12:
        return f'{a}/{b}'
    return f'{month:02d}/{year}'


def parse_availability_line(raw: str) -> ParsedAvailability:
    """Extract supplier economics from one availability line, deterministically.
    Every field is optional; nothing found = None/blank (a valid availability signal)."""
    signals = [s for e, s in _SIGNAL_EMOJI.items() if e in str(raw or '')]
    text = clean_line(raw)
    if text is None:
        return ParsedAvailability(name_part='', noise=True, extracted={'noise': True})
    extracted: dict = {}
    foc = price = discount = qty = bonus_buy = quota = None
    expiry = code = promo = ''
    tiers: list = []

    def take(pattern, flags=re.I):
        nonlocal text
        m = re.search(pattern, text, flags) if isinstance(pattern, str) else pattern.search(text)
        if m:
            text = (text[:m.start()] + ' ' + text[m.end():]).strip()
        return m

    # 0. Distributor wording: whole family, availability phrases, what is left, quota.
    all_variants = bool(take(_FAMILY_RE))
    for name, rx in _SIGNAL_PHRASES:
        m = take(rx)
        if m:
            signals.append(name)
            extracted.setdefault('signals', []).append(m.group(0))
    m = take(_LEFT_RE)
    if m:
        qty = float(m.group(1))
        signals.append('last_qty')
        extracted['left'] = m.group(0)
    m = take(_QUOTA_RE)
    if m:
        extracted['quota'] = m.group(0).strip()
        if m.group('half'):
            signals.append('half_quota')
        elif m.group('n') or m.group('w'):
            quota = float(m.group('n')) if m.group('n') else float(_QUOTA_WORDS[m.group('w')])
        else:
            signals.append('quota')               # «كوته» with no number: limited per pharmacy
    m = _PROMO_RE.search(text)
    if m:
        promo = f'{m.group(1)}+{m.group(2)} free'
        extracted['promo'] = m.group(0)
        # the pack size stays in the name ("Limitless man 30 tab"), the free units go
        text = (text[:m.start()] + f' {m.group(1)} tab ' + text[m.end():]).strip()

    # 1. Bonus — «25+1» buy 25 get 1; several tiers «18+2 …… 36+4 …… 106+14» are all kept
    #    (the first = the smallest order that earns a bonus). Then «بونص 2» / «+2 foc».
    for m in list(_BONUS_RE.finditer(text)):
        buy, free = float(m.group(1)), float(m.group(2))
        if buy > 0 and 0 < free <= buy:
            tiers.append([buy, free])
    if tiers:
        text = _BONUS_RE.sub(lambda m: ' ' if 0 < float(m.group(2)) <= float(m.group(1)) else m.group(0), text)
        bonus_buy, foc = tiers[0]
        extracted['bonus'] = ' / '.join(f'{int(b) if b == int(b) else b}+{int(f) if f == int(f) else f}'
                                        for b, f in tiers)
    if foc is None:
        m = (take(_FOC_W + r'\s*[:=]?\s*(\d+)')                      # keyword → number
             or take(r'\+\s*(\d+)\s*' + _FOC_W + r'?')                 # +2 (foc)
             or take(r'(?<![\d.])(\d+)\s*' + _FOC_W))                  # number → keyword
        if m:
            foc = float(m.group(1))
            extracted['foc'] = m.group(0)

    # 2. Price — explicit markers only (never confuse strength/qty with a price).
    m = (take(r'@\s*(' + _NUM + r')\s*' + _CUR + r'?(?!\w)')
         or take(_PRICE_KW + r'\s*[:=]?\s*(' + _NUM + r')\s*' + _CUR + r'?(?!\w)')
         or take(r'(?<![\d.])(' + _NUM + r')\s*' + _CUR + r'(?!\w)'))
    if m:
        price = _to_float(m.group(1))
        extracted['price'] = m.group(0)

    # 3. Discount — "خصم 5%", "خصم اضافي 2%", "5% خصم", "15%", "%15".
    m = (take(_DISC_KW + r'\s*(?:اضافي|اضافى|إضافي|إضافى|extra)?\s*[:=]?\s*(' + _NUM + r')\s*%?')
         or take(r'(?<![\d.])(' + _NUM + r')\s*%\s*' + _DISC_KW + r'?')
         or take(r'%\s*(' + _NUM + r')'))
    if m:
        discount = _to_float(m.group(1))
        extracted['discount'] = m.group(0)

    # 4. Expiry — with a keyword any MM/YY(YY) or YYYY-MM; bare only with a 4-digit year.
    m = (take(_EXP_KW + r'\s*[:\-]?\s*(\d{1,4})[/.\-](\d{1,4})(?!\d)')
         or take(r'(?<![\d/.])(\d{1,2})[/.](20\d{2})(?!\d)')
         or take(r'(?<![\d/.])(20\d{2})[/\-](\d{1,2})(?![\d/])'))
    if m:
        expiry = _norm_expiry(m.group(1), m.group(2))
        extracted['expiry'] = m.group(0)

    # 5. Supplier's own item code — "code 12345" / "كود 12345".
    m = take(_CODE_KW + r'\s*[:#]?\s*([A-Za-z0-9\-]{2,20})')
    if m:
        code = m.group(1)
        extracted['code'] = m.group(0)

    # 6. Quantity — explicit markers: "متاح 20" / "qty: 15" / "x3" / "5 boxes" / "3 pens".
    if qty is None:
        m = (take(_QTY_KW + r'\s*[:=]?\s*(\d+)(?!\s*' + _UNIT_W + r')(?![\d.])')
             or take(r'(?<!\w)[x×*]\s*(\d+)(?![\d.])')
             or take(r'(?<![\d.])(\d+)\s*' + _UNIT_W + r'(?!\w)(?=[^A-Za-z؀-ۿ]*$)'))
        if m:
            qty = float(m.group(1))
            extracted['qty'] = m.group(0)

    # 7. Tidy: residual label words, currency, separators; distributor shorthand for forms.
    text = re.sub(r'(?<=\d)-(?=\d)', '/', text)      # «فيموستون 10-2» is a strength, not "qty 2"
    text = _STRIP_WORDS_RE.sub(' ', text)
    text = _CUR_RESIDUE_RE.sub(' ', text)
    text = re.sub(r'[—–\-:•·|،,;=%@\[\]()]+', ' ', text)
    text = _expand_forms(text)
    # list separators left behind by what was taken out («محلول ملح 18+2……36+4» → «محلول ملح»)
    _sep = r'(?:\s*(?:&|\.{2,}|…+)\s*)'
    text = re.sub(_sep + r'{2,}', ' ... ', text)
    text = re.sub(r'^' + _sep + r'+|' + _sep + r'+$', '', text)
    text = re.sub(r'\s+', ' ', text).strip()

    # 8. Trailing-number fallback — only when another number already sits in the name
    #    ("Xgeva 120mg 3", "Concor 5 10"). A single bare number is the strength; a list of
    #    strengths («بليتال 100....50», «كليكسان 20 & 40») is never a quantity.
    if qty is None and not _VARIANT_SPLIT_RE.search(text):
        tokens = text.split()
        if len(tokens) >= 2 and re.fullmatch(r'\d+', tokens[-1]) and \
                any(re.search(r'\d', t) for t in tokens[:-1]):
            qty = float(tokens[-1])
            extracted['qty'] = f'trailing {tokens[-1]}'
            text = ' '.join(tokens[:-1])

    if all_variants:
        extracted['all_variants'] = True
    return ParsedAvailability(
        name_part=text.strip(),
        supplier_qty=qty, price=price, foc_qty=foc, discount_pct=discount,
        expiry=expiry, supplier_item_code=code, extracted=extracted,
        bonus_buy=bonus_buy, bonus_tiers=tiers, quota=quota, promo=promo,
        signals=list(dict.fromkeys(signals)), all_variants=all_variants,
    )


# Distributor shorthand → the words the matcher knows: «Lamictal 50ml t» (= 50 mg tablets —
# "ml t" is how one distributor types it), «Trental 400t», «Plavix t», «تلفاست ش», «100ق».
_FORM_FIXES = [
    (re.compile(r'(\d+(?:\.\d+)?)\s*ml\s*t(?![a-z])', re.I), r'\1 tab'),
    (re.compile(r'(\d)t(?![a-z])', re.I), r'\1 tab'),
    (re.compile(r'(?<=[a-z\d])\s+t(?![a-z\d])', re.I), ' tab'),
    (re.compile(r'(?:(?<=\d)|(?<=\s))ق(?![؀-ۿ])'), ' اقراص'),
    (re.compile(r'(?:(?<=\d)|(?<=\s))ش(?![؀-ۿ])'), ' شراب'),
    (re.compile(r'(?:(?<=\d)|(?<=\s))ك(?![؀-ۿ])'), ' كبسول'),
    (re.compile(r'(\d)([؀-ۿ]{2,})'), r'\1 \2'),            # «4بليون» → «4 بليون»
    (re.compile(r'([؀-ۿ]{2,})(\d)'), r'\1 \2'),            # «ساندوز1جم» → «ساندوز 1 جم»
]


def _expand_forms(text: str) -> str:
    for rx, rep in _FORM_FIXES:
        text = rx.sub(rep, text)
    return text


# ── Variant lines: one distributor line, several products ─────────────────────────────
# «كليكسان 20 & 40 & 60 & 80», «بليتال 100....50», «سيالس ٢و٤», «فولتارين لبوس واقراص وامبول»,
# «بانادول اكيوت..ادفانس...اكسترا», «تارج...كو تارج... كو ديوفان» → one row per product.
_FORM_WORDS = (r'(?:اقراص|أقراص|قرص|امبول|أمبول|جيل|چيل|كريم|مرهم|شراب|نقط|نقط|لبوس|اكياس|أكياس|فوار|'
               r'بخاخ|اسبراي|سبراي|كبسول|فيال|حقن|فيلم|tab|tabs|caps?|syr|amp|gel|cream|oint|drops?|sach|film)')
_VARIANT_SPLIT_RE = re.compile(
    r'\s*(?:&|\.{2,}|…+)\s*'
    r'|(?<=\d)\s*و\s*(?=\d)'
    r'|\s+و\s+'
    r'|\s+و(?=' + _FORM_WORDS + r'(?![\w]))', re.I)
MAX_VARIANTS = 8


def split_variants(name: str) -> list:
    """A distributor line naming several products → one name per product. The first part
    gives the brand; a part starting with a number replaces the first part's strength, a word
    part replaces its last word(s); a part repeating the brand stands alone. A form word on
    the LAST numeric part («نوفونورم 0.5 & 1 & 2 اقراص») applies to every strength."""
    parts = [p.strip(' .') for p in _VARIANT_SPLIT_RE.split(name or '')]
    parts = [p for p in parts if re.search(r'[A-Za-z؀-ۿ\d]', p)]
    if len(parts) <= 1:
        return [parts[0]] if parts else [str(name or '').strip()]
    first = parts[0].split()
    last = parts[-1].split()
    suffix = last[1:] if (re.match(r'\d', last[0]) and len(last) > 1
                          and all(re.fullmatch(_FORM_WORDS, w, re.I) for w in last[1:])) else []
    num_at = max((i for i, w in enumerate(first) if re.match(r'\d', w)), default=None)
    out = []
    for i, p in enumerate(parts):
        w = p.split()
        if i == 0 or w[0].lower() == first[0].lower():
            words = w
        elif re.match(r'\d', w[0]):
            words = (first[:num_at] if num_at is not None else first) + w
        else:
            keep = max(len(first) - len(w), 1) if len(first) > 1 else 0
            words = first[:keep] + w
        if suffix and re.match(r'\d', words[-1]):
            words = words + suffix
        out.append(' '.join(words))
    return list(dict.fromkeys(out))[:MAX_VARIANTS]


def compute_fingerprint(raw_content: str) -> str:
    """Stable hash of normalized content for duplicate-import detection (§32)."""
    norm = re.sub(r'\s+', ' ', _fold_digits(str(raw_content or '')).lower()).strip()
    return hashlib.sha256(norm.encode('utf-8')).hexdigest() if norm else ''


def find_duplicate_batch(fingerprint: str, *, supplier_id=None, within_hours: int = 24):
    """Return a recent AvailabilityBatch with the same fingerprint (same supplier if
    given), or None. We WARN on this, never block — a real repeated announcement is
    legitimate (§32)."""
    from django.utils import timezone
    from datetime import timedelta
    from .models import AvailabilityBatch

    if not fingerprint:
        return None
    since = timezone.now() - timedelta(hours=within_hours)
    qs = AvailabilityBatch.objects.filter(raw_fingerprint=fingerprint, created_at__gte=since)
    if supplier_id:
        qs = qs.filter(supplier_id=supplier_id)
    return qs.order_by('-created_at').first()


# ── Line ingestion (reuses the shared match pipeline) ──────────────────────────

def _split_lines(raw_content: str) -> list[str]:
    """Split a pasted blob into candidate product lines (headers / noise dropped)."""
    return split_availability_lines(raw_content)


# Chat remarks inside a «الوارد» list ("ده كل الوارد", "فتحه شهر جديد", "رجاء كل الي عايز
# ديبوفيت امبول يبعتلي") — kept as the list's notes, never matched as products.
_LIST_REMARK_WORDS = {'وارد', 'الوارد', 'فتحه', 'فتحة', 'شهر', 'جديد', 'كذا', 'رجاء', 'برجاء', 'يبعتلي',
                      'يبعت', 'ابعتلي', 'فعلا', 'بتتسحب', 'عايز', 'عاوز', 'محتاج', 'شركه', 'شركة'}


def _is_list_remark(text: str) -> bool:
    """Judged on the product name LEFT after quota / signals / bonus were read
    («ليفاجول كبسول كوته كميه محدوده جدا» is an item). A function word counts only after the
    first word («دي ديب نقط» is D-Deep drops); a long Arabic line counts only without a
    variant separator («فولتارين لبوس واقراص وامبول وجيل» is four products)."""
    from .branch_requests import _AR_FUNCTION
    if re.search(r'[A-Za-z\d]', text):
        return False
    seq = [w for w in re.findall(r'[؀-ۿ]+', text) if len(w) > 1]
    if not seq:
        return False
    if _LIST_REMARK_WORDS & set(seq) or _AR_FUNCTION & set(seq[1:]):
        return True
    return len(seq) >= 5 and not _VARIANT_SPLIT_RE.search(text)


def read_list(raw_content: str):
    """A pasted supplier list → (entries, remarks). Each entry is {'raw', 'parsed', 'barcode'}.
    A line holding only a stock note («اخر 30 علبه», «كميات محدوده») belongs to the item just
    above it; chat remarks are returned separately (they become the list's notes)."""
    entries, remarks, prev = [], [], None
    for raw in str(raw_content or '').splitlines():
        cleaned = clean_line(raw)
        if cleaned is None:
            continue                        # blank / header-only / media — keeps `prev`
        emoji = [s for e, s in _SIGNAL_EMOJI.items() if e in raw]
        for part in _split_multi(cleaned):
            m = _BARCODE_RE.search(part)
            tok = m.group(1) if m else ''
            p = parse_availability_line(part.replace(tok, ' ') if tok else part)
            p.signals = list(dict.fromkeys(p.signals + emoji))
            if not p.noise and _is_list_remark(p.name_part):
                remarks.append(part)
                prev = None
                continue
            if not re.search(r'[A-Za-z؀-ۿ]{2,}', p.name_part or ''):
                if prev is not None and (p.supplier_qty is not None or p.signals or p.quota is not None):
                    pp = prev['parsed']
                    if p.supplier_qty is not None:
                        pp.supplier_qty = p.supplier_qty
                    if p.quota is not None:
                        pp.quota = p.quota
                    pp.signals = list(dict.fromkeys(pp.signals + p.signals))
                    pp.extracted.setdefault('notes', []).append(part)
                    prev['raw'] = f"{prev['raw']} / {part}"
                elif not p.noise:
                    remarks.append(cleaned)
                continue
            prev = {'raw': part, 'parsed': p, 'barcode': tok}
            entries.append(prev)
    return entries, remarks


FAMILY_CAP = 15          # «بتركيزاته»: at most this many family members are proposed


def _new_line(batch, raw_text, source, terms, **kw):
    from .models import AvailabilityLine
    return AvailabilityLine(batch=batch, raw_text=raw_text[:300], source=source,
                            **{k: v for k, v in terms.items()}, **kw)


def _resolve_into(line, name, vendor_code):
    """Match one product name and record provenance on an (unsaved) line."""
    resolved = resolve_line(name, vendor_code=vendor_code)
    # The machine's ORIGINAL suggestion is preserved here even if an operator later corrects
    # the item — that is what makes match accuracy / correction rate measurable (KPIs).
    # Match-safety guard: a fuzzy match with a strength / form / name conflict, or a close
    # rival product, is held for human review however high its score (§5). Human-confirmed
    # aliases and explicit picks are trusted as-is.
    flags = []
    if resolved.item is not None and not resolved.picked and not resolved.learned:
        flags = review_flags(name, resolved.item.name,
                             runner_up_name=resolved.runner_up_name,
                             score=resolved.score, runner_up_score=resolved.runner_up_score)
    line.match_reason.update({'name_part': name, 'suggested_item_id': resolved.item_id,
                              'suggested_score': resolved.score, 'learned': resolved.learned,
                              'review_flags': flags})
    if resolved.item is not None:
        line.item, line.match_score, line.is_unmatched = resolved.item, resolved.score, False
    else:
        line.is_unmatched = True
    return line


def build_line(batch, raw_text: str, *, source: str = 'bulk', vendor_code: str = '',
               parsed: ParsedAvailability | None = None, barcode: str = ''):
    """Create the AvailabilityLine(s) for one raw supplier line: extract economics, resolve
    the catalog item (auto-match, unconfirmed), and record match provenance. Returns the
    saved line — the HEAD when the line names several products:
      • «كليكسان 20 & 40 & 60 & 80», «بليتال 100....50» → one row per product (text input);
      • «اوتريفين بانواعه» → the matched product + its family (flagged for review);
      • a remembered one-to-many spelling → that group again.
    Every further product is a sibling row (split_from → head) with the same economics, so a
    person confirms / edits the group as one supplier line."""
    from .models import AvailabilityLine

    # A barcode in the line (Excel exports often carry one) identifies the product exactly —
    # taken out first so its digits are never read as a strength / quantity.
    if parsed is None:
        by_barcode, barcode = barcode_item(raw_text)
        parsed = parse_availability_line(raw_text.replace(barcode, ' ') if barcode else raw_text)
    else:
        # a spreadsheet row / a list entry: economics already read
        by_barcode, barcode = barcode_item(barcode) if barcode else (None, '')
    if parsed.noise or not parsed.name_part:
        return None                     # greeting / media / system line — not a product
    terms = parsed.terms()
    vendor = batch.supplier if batch.supplier_id else None
    by_code = vendor_code_item(vendor, parsed.supplier_item_code)
    direct = by_barcode or by_code
    if direct is not None:
        flags = []
        if by_barcode and by_code and by_code.id != by_barcode.id:
            flags.append('vendor_code_conflict')      # the supplier's code says another item
        line = _new_line(batch, raw_text, source, terms, item=direct, match_score=1.0, is_unmatched=False,
                         match_reason={'name_part': parsed.name_part, 'economics': parsed.extracted,
                                       'suggested_item_id': direct.id, 'suggested_score': 1.0,
                                       'learned': False, 'review_flags': flags,
                                       'via': 'barcode' if by_barcode else 'vendor_code',
                                       'barcode': barcode})
        line.save()
        return line

    # What a person's decision is remembered under: the whole written line (a family line
    # keeps its «all kinds» meaning, so plain «اوتريفين» never expands by itself).
    learn = f'{parsed.name_part} كل الانواع' if parsed.all_variants else parsed.name_part
    base_reason = {'economics': parsed.extracted}
    if learn != parsed.name_part:
        base_reason['learn_name'] = learn

    # A remembered ONE-TO-MANY spelling for this supplier ("بيبيلاك 1....2....3" →
    # BEBELAC 1/2/3, learned when a person split this line before) — split it again now,
    # as an unconfirmed suggestion (apps/shortage/learning.lookup_alias_group).
    from apps.shortage.learning import lookup_alias_group
    group = lookup_alias_group(learn, vendor_code=vendor_code)
    if group:
        from apps.catalog.models import Item
        items = {i.id: i for i in Item.objects.filter(id__in=group['item_ids'])}
        ids = [i for i in group['item_ids'] if i in items]
        if ids:
            reason = {**base_reason, 'name_part': parsed.name_part, 'suggested_item_id': ids[0],
                      'suggested_score': group['score'], 'learned': True, 'review_flags': [],
                      'learned_group_ids': ids, 'learned_from': group.get('learned_from', '')}
            line = _new_line(batch, raw_text, source, terms, item=items[ids[0]],
                             match_score=group['score'], is_unmatched=False, match_reason=reason)
            line.save()
            for iid in ids[1:]:
                _new_line(batch, raw_text, source, terms, split_from=line, item=items[iid],
                          match_score=group['score'],
                          match_reason={**reason, 'suggested_item_id': iid, 'split_from_line': line.pk}).save()
            return line

    # Several products on one written line → one row each (typed / pasted text only — an
    # Excel product name like "Johnson & Johnson …" is one product).
    names = split_variants(parsed.name_part) if source != 'file' else [parsed.name_part]
    if len(names) > 1:
        base_reason.update(variant_of=parsed.name_part, learn_name=learn)
    head = _resolve_into(_new_line(batch, raw_text, source, terms, match_reason=dict(base_reason)),
                         names[0], vendor_code)
    head.save()
    for name in names[1:]:
        sib = _new_line(batch, raw_text, source, terms, split_from=head,
                        match_reason={**base_reason, 'split_from_line': head.pk})
        _resolve_into(sib, name, vendor_code).save()

    # «بتركيزاته / بأنواعه» → propose the matched product's whole family for review.
    if parsed.all_variants and len(names) == 1 and head.item_id:
        from .branch_requests import _family
        fam = [i for i in _family(head.item.name, limit=FAMILY_CAP + 1) if i.id != head.item_id][:FAMILY_CAP - 1]
        if fam:
            mr = head.match_reason
            mr['review_flags'] = list(dict.fromkeys((mr.get('review_flags') or []) + ['family']))
            mr['family_ids'] = [head.item_id] + [i.id for i in fam]
            head.save(update_fields=['match_reason'])
            for it in fam:
                _new_line(batch, raw_text, source, terms, split_from=head, item=it,
                          match_score=head.match_score, is_unmatched=False,
                          match_reason={**mr, 'suggested_item_id': it.id, 'split_from_line': head.pk,
                                        'review_flags': ['family']}).save()
    return head


def ingest_batch(batch, raw_content: str, *, source: str = 'bulk', vendor_code: str = '') -> list:
    """Read a pasted/OCR'd list and build the line(s) per product. Returns the created
    head lines; the supplier's chat remarks are appended to the batch notes."""
    entries, remarks = read_list(raw_content)
    out = []
    for e in entries:
        line = build_line(batch, e['raw'], source=source, vendor_code=vendor_code,
                          parsed=e['parsed'], barcode=e['barcode'])
        if line is not None:
            out.append(line)
    if remarks:
        note = ('ملاحظات المورد: ' + ' · '.join(remarks))[:2000]
        batch.notes = f'{batch.notes}\n{note}' if batch.notes else note
        batch.save(update_fields=['notes', 'updated_at'])
    return out


def _learn_name(line) -> str:
    """What the matcher looks up for this line (the parsed product name, without price /
    qty / bonus) — so a learned spelling is found again next time. A line split into several
    products is remembered under the whole written line."""
    mr = line.match_reason or {}
    return mr.get('learn_name') or mr.get('name_part') or line.raw_text


_BARCODE_RE = re.compile(r'(?<![\d.])(\d{8,14})(?![\d.])')


def barcode_item(text: str):
    """(Item, token) when a barcode in the text belongs to exactly ONE catalog item (main
    barcode or any active extra barcode), else (None, ''). A phone number or an order
    number simply finds nothing."""
    from apps.catalog.models import Item, ItemBarcode
    for tok in _BARCODE_RE.findall(_fold_digits(text or '')):
        ids = set(Item.objects.filter(barcode=tok, is_active=True).values_list('id', flat=True))
        ids |= set(ItemBarcode.objects.filter(barcode=tok, is_active=True, item__is_active=True)
                   .values_list('item_id', flat=True))
        if len(ids) == 1:
            return Item.objects.get(pk=ids.pop()), tok
    return None, ''


def vendor_code_item(vendor, code: str):
    """The item this supplier's OWN product code points to — see resolve_vendor_codes."""
    code = (code or '').strip()
    if vendor is None or not code:
        return None
    iid, _src = resolve_vendor_codes(vendor, [code]).get(code, (None, 'unknown'))
    if iid is None:
        return None
    from apps.catalog.models import Item
    return Item.objects.filter(pk=iid).first()


def resolve_vendor_codes(vendor, codes) -> dict:
    """{code: (item_id | None, source)} for one supplier, batched. The ONE rule (live
    matching and the code-coverage report both use it):
      1. confirmed here / in supplier invoices (VendorItemMapping) → 'mapping'
         — confirmed as DIFFERENT items → (None, 'ambiguous'), never guessed
      2. else SOFTECH's itemssuppliers (nightly mirror, works offline) → 'mirror'
         — a code on several SOFTECH items is dropped there → 'unknown'
      3. else (None, 'unknown')"""
    codes = sorted({str(c).strip() for c in (codes or []) if str(c or '').strip()})
    if vendor is None or not codes:
        return {}
    from collections import defaultdict
    from apps.catalog.models import Item
    from apps.catalog.supplier_links import resolve_codes
    from apps.invoices.models import VendorItemMapping
    by_code = defaultdict(set)
    for code, iid in (VendorItemMapping.objects.filter(vendor=vendor, vendor_item_code__in=codes)
                      .values_list('vendor_item_code', 'item_id')):
        by_code[code].add(iid)
    out = {}
    for c in codes:
        ids = by_code.get(c)
        if ids:
            out[c] = (next(iter(ids)), 'mapping') if len(ids) == 1 else (None, 'ambiguous')
    rest = [c for c in codes if c not in out]
    if rest:
        mirror = resolve_codes(vendor.softech_personcode, rest)
        ids = dict(Item.objects.filter(softech_id__in=set(mirror.values())).values_list('softech_id', 'id'))
        for c in rest:
            iid = ids.get(mirror.get(c))
            out[c] = (iid, 'mirror') if iid else (None, 'unknown')
    return out


def learn_vendor_mapping(line, item, *, staff=None) -> dict | None:
    """Remember (supplier, spelling[, supplier code]) → item in VendorItemMapping — the
    same memory supplier invoices use, so a code confirmed here resolves there and back.
    A supplier code already confirmed as ANOTHER item is not overwritten: the conflict is
    returned (and shown on the line) for a person to settle."""
    batch = line.batch
    vendor = batch.supplier if batch.supplier_id else None
    if vendor is None:
        return None
    from apps.invoices.models import VendorItemMapping
    from apps.shortage.matching import _normalize
    norm = _normalize(_learn_name(line))[:300]
    code = (line.supplier_item_code or '').strip()
    conflict = None
    if code:
        other = (VendorItemMapping.objects.filter(vendor=vendor, vendor_item_code=code)
                 .exclude(item=item).select_related('item').first())
        if other:
            conflict = {'item_id': other.item_id, 'item_name': other.item.name, 'code': code}
            code = ''
    if norm:
        m, created = VendorItemMapping.objects.get_or_create(
            vendor=vendor, raw_name_normalized=norm,
            defaults={'item': item, 'vendor_item_code': code, 'use_count': 1, 'created_by': staff})
        if not created:
            m.use_count = m.use_count + 1 if m.item_id == item.id else 1   # a re-pick starts over
            m.item = item
            if code:
                m.vendor_item_code = code
            m.save(update_fields=['item', 'vendor_item_code', 'use_count', 'updated_at'])
    return conflict


def set_line_items(line, item_ids, *, staff=None, vendor_code: str = '') -> list:
    """Match one supplier line to ONE OR SEVERAL catalog items ("بيبيلاك 1....2....3").
    The original line keeps the first item; each further item becomes a sibling line
    (split_from → original) carrying the same raw text and supplier economics, so every
    consumer still sees one item per line. Re-calling with another list updates / adds /
    removes siblings; an empty list un-matches the line. Every line in the group is
    confirmed; the vendor alias is taught only for a one-to-one match. Returns the group."""
    from django.db import transaction
    from apps.catalog.models import Item
    from .models import AvailabilityLine
    from apps.shortage import learning
    ids = list(dict.fromkeys(int(i) for i in item_ids))[:30]
    items = {i.id: i for i in Item.objects.filter(id__in=ids)}
    if len(items) != len(ids):
        raise ValueError('صنف غير موجود.')
    head = line.split_from or line
    name = _learn_name(head)
    mr = head.match_reason or {}
    with transaction.atomic():
        # learning from the decision: a dropped machine suggestion is rejected, a changed
        # remembered group is weakened, a confirmed group is remembered
        sug = mr.get('suggested_item_id')
        if sug and len(ids) > 1 and int(sug) not in ids:   # (one id: confirm_line records it)
            learning.record_rejection(name, sug, vendor_code=vendor_code, source='availability')
        old_group = mr.get('learned_group_ids') or []
        if old_group and set(old_group) != set(ids):
            learning.unlearn_alias_group(name, old_group, vendor_code=vendor_code)
        if len(ids) > 1:
            learning.learn_alias_group(name, ids, source='availability', vendor_code=vendor_code)
        siblings = list(AvailabilityLine.objects.select_for_update().filter(split_from=head).order_by('id'))
        if not ids:
            head.item, head.match_score, head.is_confirmed, head.is_unmatched = None, None, False, True
            head.confirmed_by = head.confirmed_at = None
            head.save(update_fields=['item', 'match_score', 'is_confirmed', 'is_unmatched',
                                     'confirmed_by', 'confirmed_at'])
            AvailabilityLine.objects.filter(pk__in=[s.pk for s in siblings]).delete()
            return [head]
        teach = len(ids) == 1
        group = [confirm_line(head, items[ids[0]], staff=staff, vendor_code=vendor_code, teach=teach)]
        for k, iid in enumerate(ids[1:]):
            sib = siblings[k] if k < len(siblings) else AvailabilityLine(
                batch=head.batch, split_from=head, raw_text=head.raw_text, source=head.source,
                **line_terms(head), notes=head.notes, match_reason={**(head.match_reason or {}), 'split_from_line': head.pk,
                                                'review_flags': []})
            if sib.pk is None:
                sib.save()
            group.append(confirm_line(sib, items[iid], staff=staff, vendor_code=vendor_code, teach=False))
        surplus = [s.pk for s in siblings[len(ids) - 1:]]
        if surplus:
            AvailabilityLine.objects.filter(pk__in=surplus).delete()
    return group


def confirm_line(line, item, *, staff=None, vendor_code: str = '', teach: bool = True):
    """Confirm a line's catalog match and teach the alias corpus (vendor-scoped, so this
    supplier's private spelling resolves instantly next time — §29). teach=False for a
    line split across several items (one spelling must not map to many items)."""
    from django.utils import timezone

    line.item = item
    line.match_score = 1.0
    line.is_confirmed = True
    line.is_unmatched = False
    line.confirmed_by = staff
    line.confirmed_at = timezone.now()
    mr = dict(line.match_reason or {})
    mr.pop('vendor_code_conflict', None)
    if teach:
        try:
            conflict = learn_vendor_mapping(line, item, staff=staff)
            if conflict:
                mr['vendor_code_conflict'] = conflict
        except Exception:
            pass
    line.match_reason = mr
    line.save(update_fields=['item', 'match_score', 'is_confirmed', 'is_unmatched',
                             'confirmed_by', 'confirmed_at', 'match_reason'])
    if teach:
        try:
            from apps.shortage import learning
            # teach the PARSED name (what is looked up next time), not the whole raw line
            # with price / qty — and reject the machine's suggestion if it was replaced
            learning.learn_correction(_learn_name(line), suggested=(line.match_reason or {}).get('suggested_item_id'),
                                      chosen=[item], source='availability', vendor_code=vendor_code or '')
        except Exception:
            pass
    return line


def resolve_batch_supplier(supplier_name: str):
    """Resolve a raw supplier name → VendorProfile via the existing supplier resolver
    (curated top-10 + learned aliases; offline). Returns (VendorProfile|None, resolution
    dict|None). Never raises."""
    if not supplier_name:
        return None, None
    try:
        from apps.invoices.suppliers import resolve_supplier, get_or_create_vendor
        res = resolve_supplier(supplier_name)
        if res:
            vp = get_or_create_vendor(res['personcode'], res['name'], alias=supplier_name)
            return vp, res
    except Exception:
        pass
    return None, None


# ── Review-grid analysis (Phase 6) ─────────────────────────────────────────────

def analyze_rows(batch, line_ids) -> list:
    """The review rows for SOME lines only — after a tick / confirm the screen swaps just
    the changed rows instead of re-analysing the whole list (~2 s for 78 lines)."""
    return analyze_batch(batch, line_ids=line_ids)['lines']


# ── Trust: how far the line's item can be relied on, 0–100 (deterministic) ─────────
# A person confirmed it → 100. Otherwise the match evidence: barcode 97, the supplier's own
# code 95, else the matcher's score; each safety flag costs points (a different strength is
# the most dangerous); past approvals of this same spelling → this item add confidence.
TRUST_PENALTY = {'strength_mismatch': 30, 'head_mismatch': 25, 'form_mismatch': 20,
                 'ambiguous': 10, 'vendor_code_conflict': 40, 'family': 15}


def trust_score(ln, approvals: int = 0, carried: bool = False) -> int:
    if not ln.item_id:
        return 0
    if ln.is_confirmed:
        return 100
    mr = ln.match_reason or {}
    via = mr.get('via')
    base = 97 if via == 'barcode' else 95 if via == 'vendor_code' else (ln.match_score or 0) * 100
    base -= sum(TRUST_PENALTY.get(f, 0) for f in (mr.get('review_flags') or []))
    base += min(10, 3 * approvals)
    if carried and via not in ('barcode', 'vendor_code'):
        base += 5                         # SOFTECH lists this item under this supplier
    return int(max(0, min(99, round(base))))


def approvals_for(lines, *, vendor_code: str = '', vendor=None) -> dict:
    """{line_id: n} — how many times people already confirmed THIS spelling as THIS item
    (shared memory: ItemAlias, vendor-scoped + global; and this supplier's
    VendorItemMapping). The larger of the two — both are taught by the same confirm."""
    from collections import defaultdict
    from apps.catalog.models import ItemAlias
    from apps.shortage.learning import key
    keyed = {ln.id: key(_learn_name(ln)) for ln in lines if ln.item_id}
    if not keyed:
        return {}
    alias = defaultdict(int)
    for a in ItemAlias.objects.filter(normalized__in=set(keyed.values()),
                                      vendor_code__in=[vendor_code or '', '']
                                      ).values('normalized', 'item_id', 'use_count'):
        alias[(a['normalized'], a['item_id'])] += a['use_count']
    vim = {}
    if vendor is not None:
        from apps.invoices.models import VendorItemMapping
        vim = {(m['raw_name_normalized'], m['item_id']): m['use_count'] for m in
               VendorItemMapping.objects.filter(vendor=vendor, raw_name_normalized__in=set(keyed.values()))
               .values('raw_name_normalized', 'item_id', 'use_count')}
    out = {}
    for ln in lines:
        if ln.id in keyed:
            k = (keyed[ln.id], ln.item_id)
            out[ln.id] = max(alias.get(k, 0), vim.get(k, 0))
    return out


def scope_info(batch, branch_ids=None) -> dict:
    """The branches an analysis is for: [] = every branch (company total, the default)."""
    from apps.branches.models import Branch
    ids = [int(b) for b in (branch_ids if branch_ids is not None else (batch.branch_scope or []))]
    names = dict(Branch.objects.filter(pk__in=ids).values_list('id', 'name'))
    ids = [b for b in ids if b in names]
    return {'branch_ids': ids, 'all': not ids,
            'branches': [{'id': b, 'name': names[b]} for b in ids]}


def analyze_batch(batch, line_ids=None, branch_ids=None) -> dict:
    """The exception-driven review table for one availability batch (§18):
    per line → match quality, company-level need, stock, internal cover, residual gap,
    this offer's effective cost vs history, scarcity, open cases — and a suggested buy
    that is NEVER just "everything the supplier offered" (§7).

    Read-only. One recommend() per DISTINCT item (the batch's offers for that item are
    passed in so sourcing compares them)."""
    from collections import defaultdict
    from django.db.models import Count, Sum
    from .engine import recommend
    from .engine.recommend import demand_for_branches, recommend_for_branches
    from .ingest import AUTO_MATCH_SINGLE
    from .models import SupplyCase

    qs = batch.lines.select_related('item').order_by('id')
    if line_ids is not None:
        qs = qs.filter(pk__in=list(line_ids))
    lines = list(qs)
    by_item = defaultdict(list)
    for ln in lines:
        if ln.item_id:
            by_item[ln.item_id].append(ln)

    scope = scope_info(batch, branch_ids)
    if scope['all']:
        recs = {iid: recommend(iid, branch_id=None, availability_lines=lns)
                for iid, lns in by_item.items()}
    else:
        # only the chosen branches' need (a supplier that delivers near some branches)
        per = demand_for_branches(list(by_item), scope['branch_ids'])
        recs = {iid: recommend_for_branches(iid, scope['branch_ids'], per_branch=per[iid],
                                            availability_lines=lns)
                for iid, lns in by_item.items()}
    branch_names = {b['id']: b['name'] for b in scope['branches']}
    vendor = batch.supplier if batch.supplier_id else None
    vendor_code = (vendor.softech_personcode if vendor else '') or ''
    approvals = approvals_for(lines, vendor_code=vendor_code, vendor=vendor)
    carried = carried_or_offered(vendor_code, [ln.item_id for ln in lines], exclude_batch=batch.pk)
    cases = {r['item_id']: r for r in
             SupplyCase.objects.filter(item_id__in=list(by_item), status__in=list(SupplyCase.OPEN_STATUSES))
             .values('item_id').annotate(n=Count('id'), waiting=Sum('customer_demand'))}

    rows, summary = [], defaultdict(int)
    for ln in lines:
        row = {'line_id': ln.id, 'raw_text': ln.raw_text, 'item_id': ln.item_id,
               # a split supplier line: every row of the group shares group_id (the original)
               'group_id': ln.split_from_id or ln.id, 'split': bool(ln.split_from_id),
               # matched from the learned memory (exact / close spelling / several items)
               'learned': bool((ln.match_reason or {}).get('learned')),
               'learned_group': bool((ln.match_reason or {}).get('learned_group_ids')),
               'item_name': ln.item.name if ln.item_id else '',
               'item_softech_id': ln.item.softech_id if ln.item_id else '',
               'match_score': ln.match_score, 'is_confirmed': ln.is_confirmed,
               'supplier_qty': _num(ln.supplier_qty), 'price': _num(ln.price),
               'foc_qty': _num(ln.foc_qty), 'discount_pct': _num(ln.discount_pct),
               'expiry': ln.expiry, 'flags': [],
               # distributor terms: bonus tiers, quota (max per pharmacy), promo pack, signals
               'bonus_buy': _num(ln.bonus_buy), 'bonus_tiers': ln.bonus_tiers or [],
               'quota': _num(ln.quota), 'promo': ln.promo, 'signals': ln.signals or [],
               'name_part': (ln.match_reason or {}).get('name_part', ''),
               'supplier_item_code': ln.supplier_item_code,
               # how the item was found: barcode / the supplier's own code / memory / name
               'via': (ln.match_reason or {}).get('via') or (
                   'memory' if (ln.match_reason or {}).get('learned') else 'name'),
               'approvals': approvals.get(ln.id, 0),
               'trust': trust_score(ln, approvals.get(ln.id, 0), ln.item_id in carried),
               # this supplier sells the item: SOFTECH itemssuppliers, or confirmed in its earlier lists
               'carried': ln.item_id in carried,
               # this supplier is the item's main supplier in SOFTECH (itemssuppliers)
               'main_supplier': bool(ln.item_id and vendor_code and
                                     (ln.item.supplier_code or '').strip() == vendor_code.strip()),
               'locked': batch.is_locked}
        conflict = (ln.match_reason or {}).get('vendor_code_conflict')
        if conflict:
            row['flags'].append('vendor_code_conflict')
            row['vendor_code_conflict'] = conflict
        if not ln.item_id:
            row['state'] = 'needs_match'
            row['flags'].append('unmatched')
        else:
            guard = [] if ln.is_confirmed else list((ln.match_reason or {}).get('review_flags') or [])
            if not ln.is_confirmed and (ln.match_score or 0) < AUTO_MATCH_SINGLE:
                row['flags'].append('low_confidence')
            row['flags'].extend(guard)
            rec = recs[ln.item_id]
            L, src, sc = rec['quantity_ledger'], rec['sourcing'], rec['scarcity']
            offer = next((o for o in src['options'] if o.get('availability_line_id') == ln.id), None)
            residual = L['residual_gap']
            supplier_qty = _num(ln.supplier_qty)
            hist = src['historical_best_deal']
            offer_eff = offer['effective_cost'] if offer else None
            # §13 per OFFER: only a line that actually quotes a price can be "pricier than
            # our best past deal" (2% tolerance, same as the sourcing engine).
            above = None
            if offer_eff is not None and hist and offer_eff > hist['effective_cost'] * 1.02:
                above = {**hist, 'current_best_effective': offer_eff,
                         'gap_pct': round((offer_eff / hist['effective_cost'] - 1) * 100, 1)}
            row.update({
                'required': L['required'], 'current_stock': L['current_stock'],
                'internal_cover': L['internally_allocated'],
                'overstock_elsewhere': L['transferable_surplus'],
                'residual_gap': residual, 'customer_demand': L['customer_demand'],
                'pending_orders': L['pending_orders'],
                # never more than offered, nor above the distributor's quota per pharmacy
                'suggested_buy': whole_units(residual, cap=min((c for c in (supplier_qty, _num(ln.quota)) if c),
                                                               default=None)),
                'offer_effective_cost': offer_eff,
                'best_effective_cost': (src['best'] or {}).get('effective_cost'),
                'historical_best': hist,
                'better_historical_deal': above,
                'scarcity': sc, 'reasons': rec['reasons'],
                'branches': [dict(b, branch_name=branch_names.get(b['branch_id'], ''))
                             for b in rec.get('branches', [])],
                'open_cases': (cases.get(ln.item_id) or {}).get('n', 0),
                'waiting_customers_qty': float((cases.get(ln.item_id) or {}).get('waiting') or 0),
            })
            if above:
                row['flags'].append('price_above_history')
            if sc['urgent']:
                row['flags'].append('urgent')
            needs_review = ('low_confidence' in row['flags'] or bool(guard)
                            or 'vendor_code_conflict' in row['flags'])
            row['state'] = ('needs_match' if needs_review
                            else 'buy' if residual > 0 else 'not_needed')
        summary[row['state']] += 1
        for f in row['flags']:
            summary[f] += 1
        rows.append(row)
    return {'batch_id': batch.id, 'lines': rows, 'scope': scope,
            'locked': batch.is_locked,
            'summary': {'total': len(rows), **dict(summary)}}


def carried_or_offered(vendor_code: str, item_ids, *, exclude_batch=None) -> set:
    """Items this supplier sells: SOFTECH lists it under the supplier (itemssuppliers), OR a
    person confirmed it in one of the supplier's earlier «وارد» lists — what a list is
    remembered for (owner 2026-10-08)."""
    from apps.catalog.supplier_links import carried_item_ids
    from .models import AvailabilityLine
    ids = [i for i in item_ids if i]
    out = set(carried_item_ids(vendor_code, ids)) if vendor_code else set()
    if vendor_code and ids:
        qs = AvailabilityLine.objects.filter(item_id__in=ids, is_confirmed=True,
                                             batch__supplier__softech_personcode=vendor_code)
        if exclude_batch:
            qs = qs.exclude(batch_id=exclude_batch)
        out |= set(qs.values_list('item_id', flat=True))
    return out


def _num(v):
    return float(v) if v is not None else None


def whole_units(need, *, cap=None) -> float:
    """A supplier order is placed in whole units: round the need UP to the next whole
    unit (never order 3.67 boxes), then cap at what the supplier actually offers."""
    import math
    need = float(need or 0)
    if need <= 0.001:
        return 0.0
    q = float(math.ceil(need - 1e-9))
    return float(min(q, cap)) if cap else q


def confirm_matches(batch, *, line_ids=None, staff=None) -> list:
    """Bulk-confirm matches in one action (§18: automate the obvious cases). Without
    ``line_ids`` only high-confidence auto-matches are confirmed; explicit ids confirm those
    lines (each must already carry an item). Teaches the vendor-scoped alias corpus."""
    from .ingest import AUTO_MATCH_SINGLE
    vendor_code = (batch.supplier.softech_personcode if batch.supplier_id and batch.supplier else '') or ''
    qs = batch.lines.filter(item__isnull=False, is_confirmed=False).select_related('item')
    if line_ids is not None:
        qs = qs.filter(pk__in=[int(i) for i in line_ids])
    else:
        qs = qs.filter(match_score__gte=AUTO_MATCH_SINGLE)
    from apps.shortage import learning
    from .models import AvailabilityLine
    done, groups = [], set()
    for ln in qs:
        if line_ids is None and (ln.match_reason or {}).get('review_flags'):
            continue                    # not "obvious": strength/form/name conflict or rival
        # a split line teaches its GROUP once (below), never each item as a single spelling
        grouped = bool(ln.split_from_id) or ln.siblings.exists()
        confirm_line(ln, ln.item, staff=staff, vendor_code=vendor_code, teach=not grouped)
        if grouped:
            groups.add(ln.split_from_id or ln.id)
        done.append(ln)
    for head in AvailabilityLine.objects.filter(pk__in=groups):
        ids = [head.item_id] + list(head.siblings.order_by('id').values_list('item_id', flat=True))
        if all(ids) and len(ids) > 1:
            learning.learn_alias_group(_learn_name(head), ids, source='availability', vendor_code=vendor_code)
    if done and not batch.lines.filter(is_confirmed=False, item__isnull=False).exists() \
            and batch.status == batch.STATUS_OPEN:
        batch.status = batch.STATUS_REVIEWED
        batch.save(update_fields=['status', 'updated_at'])
    return done
