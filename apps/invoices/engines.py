"""
apps/invoices/engines.py

Pluggable OCR engine layer for structured invoice extraction.

Two engines produce the SAME Gemini-shaped dict
``{supplier_name, invoice_number, …, lines:[{item_name, quantity, public_price, …}]}``
so the downstream parse_structured / matching pipeline is identical:

  - "gemini"  : the hosted Gemini JSON extractor (best accuracy, costs money)
  - "easyocr" : a FREE local structured extractor — easyocr(detail=1) word boxes
                reconstructed into a table (table_reconstruct) and mapped to fields

Engine choice: explicit arg → settings.INVOICE_OCR_ENGINE → "auto"
("auto" = gemini when a key is configured, else easyocr). This keeps the pharmacy
running with zero API cost when no key is present, and lets any invoice be
re-read with the free engine on demand.

SAFETY: the free engine never invents financial values. Without a per-distributor
column template (VendorProfile.ocr_profile['columns'], visual left→right field
names) it fills only item_name and a best-effort quantity, leaves prices at 0,
and marks every line with low confidence so the review workbench flags it. With a
template it maps the numeric columns deterministically. Column MEANING is only
ever taken from the template, never guessed.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger('elrezeiky.invoices')

# fields a per-vendor template may map, in the line dict parse_structured reads
_TEMPLATE_FIELDS = {
    'item_name', 'manufacturer', 'vendor_item_code', 'batch_number', 'expiry_date',
    'quantity', 'public_price', 'discount_pct', 'extra_discount_pct', 'special_discount_pct',
    'pharmacist_price', 'vat_pct', 'distributor_margin_amt', 'pharmacist_margin_amt',
    'bonus_qty', 'ignore',
}

def _norm_ar(s: str) -> str:
    """Normalize Arabic for robust keyword matching: strip diacritics/tatweel,
    unify alef forms, ya/alef-maqsura and ta-marbuta/ha."""
    import re as _re
    s = _re.sub(r'[ً-ْـ]', '', s or '')
    return (s.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا')
             .replace('ى', 'ي').replace('ة', 'ه'))


# rows containing any of these (normalized) are totals/section/header markers,
# never product rows.
_NONITEM_KW = tuple(_norm_ar(k) for k in (
    'اجمالي', 'إجمالي', 'الاجمالي', 'الإجمالي', 'صافي', 'المطلوب', 'المطلوب',
    'خاضعة للضريبة', 'غير خاضعة', 'عدد الأصناف', 'عدد العلب', 'عدد الاصناف',
    'total', 'اسم المورد', 'اسم الصنف', 'الكمية', 'سعر الجمهور', 'ختم العميل',
    'توقيع العميل', 'رسالة', 'سعر اساسي', 'كمية',
    # customer / document-header / footer rows (never products)
    'اسم الحساب', 'كود العميل', 'اسم العميل', 'دورة التوزيع', 'المندوب',
    'امر بيع', 'امر البيع', 'نوع الامر', 'التحصيل', 'تعديل الدفع', 'الدفع',
    'العنوان', 'الكود المكاني', 'تسجيل ضريبي', 'سجل تجاري', 'الفرع',
    # footer / totals rows + common OCR misreads (الدفع→الدقع, تعديل→تعجيل)
    'الدقع', 'تعجيل', 'تعديل', 'عروض', 'وفرت', 'الخصومات', 'قيمه الاصناف',
    'قيمة الاصناف', 'الهامش الثابت', 'هامش ثابت', 'للموزع', 'للصيدلي',
))


# Distinctive pharmaceutical dosage-form words. A row whose item-name cell contains
# one of these is a real product even when its price cell was not detected —
# distributor invoices print a form word on virtually every drug line, while
# customer/header/footer labels (الدفع، العنوان، نوع الأمر …) never do. This lets a
# row survive on a strong name alone, which matters for engines (e.g. PaddleOCR) that
# detect names well but miss many numeric cells. Only UNAMBIGUOUS words go here (each
# is a real-word substring of nothing common); short unit abbreviations (مل، مجم) are
# handled separately, digit-anchored, because bare 'مل' is a substring of الامل/كامل/
# شامل and would admit non-product rows. Stored _norm_ar-normalized (ة→ه, ى→ي, أإآ→ا,
# tashkeel stripped) so the test matches regardless of spelling noise.
_DRUG_FORM_WORDS = tuple(_norm_ar(k) for k in (
    'قرص', 'اقراص', 'كبسوله', 'كبسولات', 'امبول', 'امبوله', 'امبولات', 'فيال',
    'شراب', 'معلق', 'نقط', 'نقطه', 'قطره', 'كريم', 'مرهم', 'لبوس', 'تحاميل', 'بخاخ',
    'محلول', 'غسول', 'دهان', 'شامبو', 'سيرم', 'اكياس', 'حبيبات', 'فوار',
))

# A number immediately followed (optionally one space) by a dose unit — e.g. '4 مجم',
# '٥مجم', '500مج', '10 مل'. Digit-anchored so the short units can't match الامل/عامل.
_DOSE_UNIT_RE = re.compile(
    r'[0-9٠-٩]\s?(?:مجم|ملجم|مجرام|ميكروجرام|مج|مغ|جمم|جم|مل|وحده|يونت)')


def _has_drug_form(name: str) -> bool:
    """True when the name looks like a drug: it contains a distinctive dosage-form
    word (قرص، كبسولة، شراب …) OR a digit-anchored dose unit (4 مجم، 10 مل). A
    deterministic 'this is a product, not a header label' signal."""
    norm = _norm_ar(name or '')
    if any(k and k in norm for k in _DRUG_FORM_WORDS):
        return True
    return bool(_DOSE_UNIT_RE.search(norm))


def _is_price(s) -> bool:
    """A number that plausibly is a money/price value (not an order/barcode number)."""
    if not _is_number(s):
        return False
    digits = ''.join(c for c in str(s) if c.isdigit())
    if len(digits) > 7:
        return False
    try:
        return 0 < float(str(s).replace(',', '')) < 1_000_000
    except ValueError:
        return False


def score_extraction(data) -> float:
    """Quality score 0..1 for a structured result: the fraction of lines that have
    both a readable item name and a plausible price. Used to decide whether a free
    extraction is good enough or should escalate to Gemini."""
    if not data:
        return 0.0
    lines = data.get('lines') or []
    if not lines:
        return 0.0
    ok = 0
    for ln in lines:
        name = str(ln.get('item_name') or '').strip()
        priced = any(_is_price(ln.get(f)) for f in ('public_price', 'pharmacist_price', 'line_total'))
        if len(name) >= 3 and _arabic_ratio(name) >= 0.3 and priced:
            ok += 1
    return ok / len(lines)


def recall_ok(data, recall_factor: float = 0.7) -> bool:
    """True when the result captured enough of the invoice's products. Uses the
    printed item count (عدد الأصناف) when available: recall = lines / declared.
    No declared count → cannot judge recall, treat as OK (precision score governs)."""
    if not data:
        return False
    declared = data.get('_declared_count')
    lines = data.get('lines') or []
    if not declared or declared <= 0:
        return True
    return len(lines) >= declared * recall_factor


def confidence_ok(data, min_conf: float = 0.55) -> bool:
    """False when the free OCR's mean character confidence is low — a sign of a
    blurry scan or HANDWRITING, which the free engine reads poorly. Such invoices
    should escalate to Gemini (far better on handwriting). No confidence signal
    (e.g. Gemini result) → treat as OK."""
    if data is None:
        return False
    conf = data.get('_avg_confidence')
    if conf is None:
        return True
    return conf >= min_conf


def numbers_ok(data, min_frac: float = 0.5, tol: float = 0.02) -> bool:
    """False when most checkable lines' NUMBERS don't self-consistency-check —
    net ≈ public×(1−d1)(1−d2)(1−d3), or net ≈ line_total÷qty. A free extraction can
    have every name + a price present (so score_extraction/recall pass) yet have the
    numeric columns garbled; that result must still escalate to a semantic engine.
    Lines with no cross-check available are ignored; no checkable lines → OK (don't
    over-escalate a text-only or sparse page)."""
    if not data:
        return False
    lines = data.get('lines') or []
    checkable = good = 0
    for ln in lines:
        if not isinstance(ln, dict):
            continue

        def f(k):
            try:
                return float(ln.get(k) or 0)
            except (TypeError, ValueError):
                return 0.0
        P = f('public_price'); N = f('pharmacist_price')
        d1 = f('discount_pct'); d2 = f('extra_discount_pct'); d3 = f('special_discount_pct')
        Q = f('quantity'); LT = f('line_total')
        checks = []
        if N > 0 and P > 0:
            checks.append(abs(N - P * (1 - d1 / 100) * (1 - d2 / 100) * (1 - d3 / 100)) / N <= tol)
        if N > 0 and LT > 0 and Q > 0:
            checks.append(abs(N - LT / Q) / N <= tol)
        if checks:
            checkable += 1
            if any(checks):
                good += 1
    if checkable == 0:
        return True
    return (good / checkable) >= min_frac


# ── Engine registry ──────────────────────────────────────────────────────────
# Single source of truth for every structured-OCR engine. A spec knows its kind
# (free-local vs paid API), whether it's usable right now, its priority (lower is
# tried first within a kind), and how to run over an invoice's page images. New
# engines (PaddleOCR, Mistral, a fine-tuned local VLM, …) plug in via
# register_engine() at the bottom of this module — the dispatch (resolve_engine /
# best_free_engine / ocr.extract_structured_images) and the benchmark pick them up
# with NO further changes.

class EngineSpec:
    def __init__(self, name, kind, priority, available_fn, images_fn, note=''):
        self.name = name
        self.kind = kind                 # 'free' | 'api'
        self.priority = priority
        self._available_fn = available_fn
        self._images_fn = images_fn
        self.note = note

    def available(self) -> bool:
        try:
            return bool(self._available_fn())
        except Exception:
            return False

    def run(self, image_paths, vendor=None, extra_hints=''):
        return self._images_fn(image_paths, vendor, extra_hints)


_ENGINES: dict = {}


def register_engine(spec: 'EngineSpec'):
    _ENGINES[spec.name] = spec


def get_engine(name):
    return _ENGINES.get((name or '').strip().lower())


def all_engine_specs() -> list:
    """Every registered spec — FREE engines first, then by ascending priority."""
    return sorted(_ENGINES.values(), key=lambda s: (s.kind != 'free', s.priority))


def available_free_specs() -> list:
    return [s for s in all_engine_specs() if s.kind == 'free' and s.available()]


def available_api_specs() -> list:
    return [s for s in all_engine_specs() if s.kind == 'api' and s.available()]


def resolve_engine(explicit: str | None = None) -> str:
    """The engine NAME to use. An explicit/registered name wins; 'auto' (or an
    unknown name) picks the best available API engine, else the best free engine."""
    name = (explicit or '').strip().lower()
    if not name:
        try:
            from django.conf import settings
            name = (getattr(settings, 'INVOICE_OCR_ENGINE', '') or 'auto').strip().lower()
        except Exception:
            name = 'auto'
    if name in _ENGINES:
        return name
    api = available_api_specs()
    if api:
        return api[0].name
    return best_free_engine() or 'easyocr'


def best_free_engine() -> str | None:
    """The preferred available FREE structured engine (by registry priority:
    Tesseract → PaddleOCR → easyOCR)."""
    specs = available_free_specs()
    return specs[0].name if specs else None


def available_engines() -> list:
    return [s.name for s in all_engine_specs() if s.available()]


def _easyocr_available() -> bool:
    try:
        import easyocr  # noqa: F401
        return True
    except Exception:
        return False


def _ocr():
    from . import ocr
    return ocr


# ── Tesseract setup ─────────────────────────────────────────────────────────────

_tess_ready = None


def _tesseract_available() -> bool:
    """True when pytesseract + the Tesseract binary + the Arabic language pack are
    all usable. Honors settings.TESSERACT_CMD / TESSERACT_TESSDATA_PREFIX. Cached."""
    global _tess_ready
    if _tess_ready is not None:
        return _tess_ready
    _tess_ready = False
    try:
        import os
        import pytesseract
        from django.conf import settings
        cmd = getattr(settings, 'TESSERACT_CMD', '') or ''
        if not cmd:
            # fall back to the standard Windows install path
            win = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
            if os.path.exists(win):
                cmd = win
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd
        prefix = getattr(settings, 'TESSERACT_TESSDATA_PREFIX', '') or ''
        if not prefix:
            # portable default: the project's own ocr_tessdata/ (ara+eng+osd),
            # so it works on any machine via the repo/OneDrive without config.
            proj = os.path.join(str(getattr(settings, 'BASE_DIR', '')), 'ocr_tessdata')
            if os.path.exists(os.path.join(proj, 'ara.traineddata')):
                prefix = proj
        if prefix:
            os.environ['TESSDATA_PREFIX'] = prefix
        langs = pytesseract.get_languages()
        _tess_ready = 'ara' in langs
    except Exception as e:
        logger.info('Tesseract not available: %s', e)
        _tess_ready = False
    return _tess_ready


# ── free easyocr structured extractor ───────────────────────────────────────────

def _arabic_ratio(s: str) -> float:
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return 0.0
    ar = sum(1 for c in letters if '؀' <= c <= 'ۿ')
    return ar / len(letters)


def _is_number(s: str) -> bool:
    return bool(re.fullmatch(r'[\d.,]+', (s or '').strip())) and any(c.isdigit() for c in s)


def _as_int_qty(s: str):
    s = (s or '').strip().replace(',', '')
    if re.fullmatch(r'\d{1,4}', s):
        v = int(s)
        if 1 <= v <= 9999:
            return float(v)
    return None


def _boxes_from_easyocr(result) -> list[dict]:
    """Convert easyocr detail=1 output [(box, text, conf), …] to our box dicts."""
    boxes = []
    for box, text, conf in result:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        t = (str(text) or '').strip()
        if not t:
            continue
        boxes.append({
            'cx': sum(xs) / 4.0, 'cy': sum(ys) / 4.0,
            'w': max(xs) - min(xs), 'h': max(ys) - min(ys),
            'text': t, 'conf': float(conf) if conf is not None else 0.5,
        })
    return boxes


def _row_is_item(cells: list[str]) -> bool:
    joined = _norm_ar(' '.join(cells))
    if any(k in joined for k in _NONITEM_KW):
        return False
    has_name = any(_arabic_ratio(c) >= 0.5 and len(c) >= 3 for c in cells)
    has_num = any(_is_number(c) for c in cells)
    return has_name and has_num


def _line_from_cells_no_template(cells: list[str], name_col: int | None = None,
                                 engine: str = 'OCR') -> dict | None:
    """Safe default: item_name from the GLOBAL name column (identified across all
    rows), else the most-Arabic cell; + best-effort integer quantity. Prices left
    0 for the operator. The full row text is kept in notes for review."""
    if name_col is not None and 0 <= name_col < len(cells) and \
            _arabic_ratio(cells[name_col]) >= 0.4 and len(cells[name_col]) >= 3:
        name_cell = cells[name_col]
    else:
        name_cell = max(cells, key=lambda c: (_arabic_ratio(c), len(c)), default='')
    if _arabic_ratio(name_cell) < 0.4 or len(name_cell) < 3:
        return None
    qty = None
    for c in cells:
        if c == name_cell:
            continue
        q = _as_int_qty(c)
        if q is not None:
            qty = q
            break
    return {
        'item_name': name_cell,
        'quantity': qty or 1.0,
        'public_price': 0, 'discount_pct': 0, 'extra_discount_pct': 0,
        'pharmacist_price': 0, 'bonus_qty': 0,
        'confidence': 0.4,   # free-engine draft → workbench flags for verification
        'notes': f'استخراج مجاني ({engine}) — راجع الأسعار | ' + ' | '.join(cells)[:260],
    }


def _name_column(grid: list[list[str]]) -> int | None:
    """The column whose cells are most consistently Arabic text = the item-name
    column. Computed over all rows so one noisy row can't mislead it."""
    if not grid:
        return None
    ncol = max(len(r) for r in grid)
    scores = []
    for i in range(ncol):
        vals = [_arabic_ratio(r[i]) for r in grid if i < len(r) and r[i]]
        scores.append(sum(vals) / len(vals) if vals else 0.0)
    best = max(range(ncol), key=lambda i: scores[i]) if ncol else None
    return best if (best is not None and scores[best] >= 0.4) else None


def _filter_sidebar(boxes: list[dict]) -> list[dict]:
    """Drop the vertical regulatory notes printed down the page margins (tall,
    narrow boxes hugging the far left/right edge) — they pollute the table grid."""
    if not boxes:
        return boxes
    xs = [b['cx'] for b in boxes]
    lo, hi = min(xs), max(xs)
    span = (hi - lo) or 1.0
    out = []
    for b in boxes:
        near_edge = (b['cx'] - lo) / span < 0.05 or (hi - b['cx']) / span < 0.03
        vertical = b.get('h', 0) > b.get('w', 1) * 1.3
        if near_edge and vertical:
            continue
        out.append(b)
    return out


def _line_from_cells_template(cells: list[str], columns: list[str],
                              engine: str = 'OCR') -> dict | None:
    """Map grid cells to fields using a per-vendor visual left→right template."""
    line = {}
    n = min(len(cells), len(columns))
    for i in range(n):
        field = (columns[i] or '').strip()
        if field not in _TEMPLATE_FIELDS or field == 'ignore':
            continue
        val = cells[i].strip()
        if field in ('item_name', 'manufacturer', 'vendor_item_code',
                     'batch_number', 'expiry_date'):
            line[field] = val
        else:
            line[field] = val  # numeric parse happens in parse_structured (_num)
    name = (line.get('item_name') or '').strip()
    if _arabic_ratio(name) < 0.3 or len(name) < 3:
        return None
    line.setdefault('quantity', 1.0)
    line['confidence'] = 0.55
    line['notes'] = f'استخراج مجاني ({engine}+قالب) — راجع'
    return line


# ── header-driven column mapping (per-distributor templates) ────────────────────
#
# Instead of hardcoding pixel columns per vendor, we read the invoice's OWN column
# headers to self-calibrate: each printed header word (normalized) maps to a field,
# and its x-position defines that column's centre. Data cells are then assigned to
# the nearest header column. This handles Ramco and PharmaOverseas (and new
# distributors) from one mechanism; a vendor can still override/extend the header
# synonyms via ocr_profile['header_synonyms'] = {field: [words...]}.

_HEADER_SYNONYMS = {
    'item_name':       ['اسم الصنف', 'الصنف'],
    'manufacturer':    ['اسم المورد', 'المورد', 'الشركة', 'المصنع'],
    'quantity':        ['الكمية', 'كمية', 'العدد'],
    'vendor_item_code':['كود الصنف', 'كود المورد', 'كود', 'الكود'],
    'batch_number':    ['التشغيلة', 'تشغيلة', 'رقم التشغيلة', 'تشغيل', 'اللوط'],
    'expiry_date':     ['الصلاحية', 'ت.الصلاحية', 'ت الصلاحية', 'الصلاحيه', 'تاريخ الصلاحية', 'انتهاء'],
    'public_price':    ['سعر الجمهور', 'الجمهور', 'جمهور'],
    'pharmacist_price':['سعر صيدلي', 'سعر الصيدلي', 'صيدلي', 'سعر الصيدلية'],
    'discount_pct':    ['خصم صيدلي', 'خصم مطابقة', 'خصم العبد', 'الخصم', 'خصم'],
    'line_total':      ['اجمالي الصنف', 'اجمالي القيمة', 'اجمالي القيمه', 'اجمالي', 'الاجمالي', 'القيمة', 'القيمه'],
}

# Fields whose presence (as a readable number) marks a product's MAIN text line —
# used to merge stacked sub-lines (item code / manufacturer) into one product.
_ANCHOR_FIELDS = ('quantity', 'public_price', 'pharmacist_price', 'line_total')

# string fields are joined; everything else is parsed as a number downstream
_STR_FIELDS = ('item_name', 'manufacturer', 'vendor_item_code', 'batch_number', 'expiry_date')


def _group_text_rows(boxes: list[dict]) -> list[list[dict]]:
    """Group boxes into text rows: by the engine's own line id (Tesseract) when
    present, else by geometric y-clustering. Rows are returned top→bottom."""
    from . import table_reconstruct as tr
    if boxes and all('row_key' in b for b in boxes):
        groups = {}
        for b in boxes:
            groups.setdefault(b['row_key'], []).append(b)
        return [g for _, g in sorted(groups.items(),
                                     key=lambda kv: sum(b['cy'] for b in kv[1]) / len(kv[1]))]
    return tr.group_rows(boxes)


def _header_synonyms(vendor):
    syn = {k: list(v) for k, v in _HEADER_SYNONYMS.items()}
    extra = (getattr(vendor, 'ocr_profile', None) or {}).get('header_synonyms') if vendor else None
    if isinstance(extra, dict):
        for field, words in extra.items():
            if isinstance(words, list):
                syn.setdefault(field, [])
                syn[field] = list(words) + syn[field]
    return syn


def _detect_header_columns(rows: list[list[dict]], vendor=None):
    """Find the header row and return [(x_center, field), …] sorted by x, plus the
    row index of the detected header. A header word is matched by a normalized
    synonym appearing as a contiguous phrase in a box (or adjacent boxes)."""
    syn = _header_synonyms(vendor)
    # normalized synonym → field, longest first so "اسم الصنف" wins over "الصنف"
    phrases = sorted(
        [( _norm_ar(w), field) for field, words in syn.items() for w in words],
        key=lambda t: -len(t[0]))

    best = None  # (row_index, [(cx, field)...], score)
    for ri, row in enumerate(rows):
        row_sorted = sorted(row, key=lambda b: b['cx'])
        found = {}
        for b in row_sorted:
            nb = _norm_ar(b['text'])
            if not nb:
                continue
            for ph, field in phrases:
                if field in found:
                    continue
                if ph and (ph in nb or nb in ph):
                    found[field] = b['cx']
                    break
        if len(found) >= 3:
            cols = sorted(((cx, f) for f, cx in found.items()), key=lambda t: t[0])
            score = len(found)
            if best is None or score > best[2]:
                best = (ri, cols, score)
    if best is None:
        return None, None
    return best[1], best[0]


def _assign_field(cx, header_cols):
    """Nearest header column to this x-centre → its field."""
    return min(header_cols, key=lambda c: abs(cx - c[0]))[1]


def _columns_from_bands(vendor, boxes):
    """Build [(x_center, field)] from an explicit per-vendor column template:
    vendor.ocr_profile['column_bands'] = [{'field':..,'x0':f,'x1':f}, …] where x0/x1
    are fractions (0..1) of page width. Used when the printed headers are not OCR-
    legible (common on dense scans) — a deterministic, auditable per-distributor map."""
    bands = (getattr(vendor, 'ocr_profile', None) or {}).get('column_bands') if vendor else None
    if not isinstance(bands, list) or not bands:
        return None
    xs = [b['cx'] for b in boxes]
    lo, hi = (min(xs), max(xs)) if xs else (0.0, 1.0)
    span = (hi - lo) or 1.0
    cols = []
    for band in bands:
        f = band.get('field')
        try:
            x0, x1 = float(band['x0']), float(band['x1'])
        except (KeyError, TypeError, ValueError):
            continue
        if f:
            cols.append((lo + (x0 + x1) / 2.0 * span, f))
    return sorted(cols, key=lambda t: t[0]) or None


# ── built-in per-distributor templates (x-fraction column bands) ────────────────
# Calibrated 2026-10-17 from real specimens (رامكو.pdf / فارما اوفر.pdf, 300dpi).
# Each band is {field, x0, x1} as fractions of page width (RTL: item_name is the
# high-x/right side). Auto-selected by brand keywords found on the page, so no
# per-vendor config is required; ocr_profile['column_bands'] overrides.
_BUILTIN_TEMPLATES = {
    'ramco': {
        'keywords': ('رامكو', 'ramco'),
        'multiline': True,     # each product spans 2 stacked text lines
        'bands': [
            {'field': 'line_total',       'x0': 0.17,  'x1': 0.235},
            {'field': 'vat_pct',          'x0': 0.295, 'x1': 0.33},
            {'field': 'pharmacist_price', 'x0': 0.33,  'x1': 0.39},
            {'field': 'public_price',     'x0': 0.39,  'x1': 0.435},
            {'field': 'quantity',         'x0': 0.435, 'x1': 0.485},
            {'field': 'vendor_item_code', 'x0': 0.485, 'x1': 0.52},
            {'field': 'expiry_date',      'x0': 0.52,  'x1': 0.565},
            {'field': 'manufacturer',     'x0': 0.565, 'x1': 0.635},
            {'field': 'item_name',        'x0': 0.635, 'x1': 0.90},
        ],
    },
    'pharmaoverseas': {
        'keywords': ('فارما', 'pharmaoverseas', 'pharma over', 'over seas', 'overseas',
                     'مستقبل توزيع', 'pharmae'),
        'multiline': False,    # mostly one text line per product
        # Column order verified vs a grid-band OCR dump (page-28, header excluded) and
        # the vendor's own layout. The two fixed-margin columns sit LEFT of line_total
        # (low x) — previously unbanded, so they were dropped; now captured for display
        # (they are NOT cost — SOFTECH transprice is the net discounted base, verified).
        'bands': [
            {'field': 'distributor_margin_amt', 'x0': 0.10,  'x1': 0.155},  # هامش ثابت للموزع (leftmost)
            {'field': 'pharmacist_margin_amt',  'x0': 0.155, 'x1': 0.205},  # هامش ثابت للصيدلى
            # 0.205–0.25 ≈ VAT-total amount column (no model field → intentionally unbanded)
            {'field': 'line_total',       'x0': 0.25,  'x1': 0.305},
            {'field': 'pharmacist_price', 'x0': 0.305, 'x1': 0.345},
            {'field': 'discount_pct',     'x0': 0.345, 'x1': 0.378},
            {'field': 'vat_pct',          'x0': 0.378, 'x1': 0.41},
            {'field': 'public_price',     'x0': 0.41,  'x1': 0.455},
            {'field': 'expiry_date',      'x0': 0.455, 'x1': 0.495},
            {'field': 'batch_number',     'x0': 0.495, 'x1': 0.555},
            {'field': 'quantity',         'x0': 0.555, 'x1': 0.605},   # الكمية (was absorbed by manufacturer)
            {'field': 'manufacturer',     'x0': 0.605, 'x1': 0.70},
            # item_name right edge widened 0.92→0.965: PaddleOCR pushes some product
            # names to the far right (seen at xf 0.948) where the 0.92 edge clipped
            # them; the extra strip is page margin for other engines, so it's safe.
            {'field': 'item_name',        'x0': 0.70,  'x1': 0.965},
        ],
    },
}


def _is_paddle_engine(engine: str) -> bool:
    return 'paddle' in (engine or '').lower()


def _match_template(boxes, vendor, engine: str = ''):
    """Pick a column template: explicit ocr_profile['column_bands'] first, else a
    built-in template auto-selected by brand keywords printed on the page.
    Returns (bands_list, multiline_bool) or (None, False).

    Engine-specific bands: PaddleOCR reports LINE-level boxes whose column centres
    differ slightly from Tesseract's word boxes, so a template may carry a
    `bands_paddle` (built-in) or the vendor an `column_bands_paddle` (ocr_profile)
    variant, used only for the paddle engine; everything else keeps the default
    `bands`, so calibrating paddle never regresses Tesseract/easyOCR."""
    paddle = _is_paddle_engine(engine)
    prof = (getattr(vendor, 'ocr_profile', None) or {}) if vendor else {}
    if paddle and isinstance(prof.get('column_bands_paddle'), list) and prof['column_bands_paddle']:
        return prof['column_bands_paddle'], bool(prof.get('multiline'))
    if isinstance(prof.get('column_bands'), list) and prof['column_bands']:
        return prof['column_bands'], bool(prof.get('multiline'))
    blob = _norm_ar(' '.join(b['text'] for b in boxes)).lower()
    vname = _norm_ar(getattr(vendor, 'name', '') or '').lower() if vendor else ''
    for tpl in _BUILTIN_TEMPLATES.values():
        if any(_norm_ar(k).lower() in blob or (_norm_ar(k).lower() in vname) for k in tpl['keywords']):
            bands = tpl.get('bands_paddle') if (paddle and tpl.get('bands_paddle')) else tpl['bands']
            return bands, tpl['multiline']
    return None, False


def _group_products_by_ygap(rows):
    """Cluster text rows into PRODUCTS by vertical gap — a product's stacked
    sub-lines sit within ~2 line-heights; a bigger gap starts a new product.
    Threshold is based on the median box HEIGHT (robust to evenly-spaced rows,
    unlike a median-gap threshold). Handles the Ramco 2-line layout."""
    if not rows:
        return []
    heights = [b.get('h', 0) for r in rows for b in r if b.get('h')]
    med_h = sorted(heights)[len(heights) // 2] if heights else 0
    thr = (med_h * 2.0) if med_h else None
    cys = [sum(b['cy'] for b in r) / len(r) for r in rows]
    order = sorted(range(len(rows)), key=lambda i: cys[i])
    if thr is None:
        gaps = sorted(cys[order[i + 1]] - cys[order[i]] for i in range(len(order) - 1)) if len(order) > 1 else [0]
        thr = (gaps[len(gaps) // 2] * 1.8) if gaps else 1e-6
    products, cur = [], []
    prev_cy = None
    for i in order:
        cy = cys[i]
        if prev_cy is not None and (cy - prev_cy) > thr and cur:
            products.append(cur)
            cur = []
        cur.extend(rows[i])
        prev_cy = cy
    if cur:
        products.append(cur)
    return products


def _fnum(s) -> float:
    try:
        return float(str(s).replace(',', '').strip())
    except (ValueError, AttributeError):
        return 0.0


def _qty_sanity(ln: dict) -> None:
    """Catch gross quantity misreads (e.g. 2→82) by cross-checking against the line
    total: for these invoices إجمالي القيمة ≈ سعر الصيدلي × الكمية, so the expected
    qty = line_total / pharmacist_price. When the read qty is missing or wildly off
    (>3× or <⅓ of expected) and the expected value is close to an integer, replace
    it and flag the correction for review. Never fabricates when the math is unclear."""
    total = _fnum(ln.get('line_total'))
    cost  = _fnum(ln.get('pharmacist_price'))
    if total <= 0 or cost <= 0:
        return
    expected = total / cost
    if not (0.5 <= expected <= 9999):
        return
    er = round(expected)
    if er <= 0 or abs(er - expected) > 0.15 * max(1, er):   # not near an integer → unsure
        return
    read = _fnum(ln.get('quantity'))
    if read <= 0 or read > er * 3 or read < er / 3.0:
        ln['quantity'] = str(er)
        ln['notes'] = (str(ln.get('notes', '')) + ' | الكمية مُصحّحة (الإجمالي÷الصيدلي)')[:300]


def _group_products_by_namerow(rows, is_name_box, max_gap):
    """Anchor each product on its NAME row, then attach nearby satellite rows
    (a product's numbers/code/manufacturer line) to the nearest name row by
    vertical distance. Generalizes across layouts: single-line invoices give one
    name row per product (no satellites); 2-line layouts (Ramco) pair the numbers
    line with the name line above/below it. `max_gap` caps how far a satellite may
    attach (keeps unrelated rows apart)."""
    def rcy(r):
        return sum(b['cy'] for b in r) / len(r)

    rows = sorted(rows, key=rcy)
    name_rows = [r for r in rows if any(is_name_box(b) for b in r)]
    if not name_rows:
        return []
    products = {i: list(nr) for i, nr in enumerate(name_rows)}
    name_cys = [rcy(nr) for nr in name_rows]
    for r in rows:
        if any(r is nr for nr in name_rows):
            continue
        j = min(range(len(name_rows)), key=lambda k: abs(rcy(r) - name_cys[k]))
        if abs(rcy(r) - name_cys[j]) <= max_gap:
            products[j].extend(r)
    return [products[i] for i in range(len(name_rows))]


def _structured_by_bands(boxes, bands, multiline, vendor=None, engine='OCR',
                         page_w=None) -> dict | None:
    """Map data cells to fields using calibrated x-fraction column bands, grouping
    a product's text lines by vertical gap. Deterministic & auditable. Band
    fractions are of PAGE WIDTH, so page_w must be the real image width (falls
    back to the box x-extent when unknown)."""
    from . import table_reconstruct as tr
    # Geometric y-clustering (not the engine's text-line ids) so same-row word
    # fragments merge while distinct product rows stay apart.
    rows = tr.group_rows(boxes)
    # restrict to the data band: drop rows that are totals/section/header markers
    data_rows = []
    for r in rows:
        joined = _norm_ar(' '.join(b['text'] for b in r))
        if any(k in joined for k in _NONITEM_KW):
            continue
        data_rows.append(r)
    if not data_rows:
        return None

    if page_w and page_w > 0:
        lo, span = 0.0, float(page_w)
    else:
        xs = [b['cx'] for b in boxes]
        lo = min(xs) if xs else 0.0
        span = ((max(xs) - lo) if xs else 1.0) or 1.0

    def field_for(cx):
        xf = (cx - lo) / span
        for band in bands:
            if band['x0'] <= xf <= band['x1']:
                return band['field']
        return None

    def is_name_box(b):
        return field_for(b['cx']) == 'item_name' and _arabic_ratio(b['text']) >= 0.5

    # Name-row-anchored grouping generalizes single-line (Pharma) and 2-line
    # (Ramco) layouts: each product is a name row + its nearest satellite rows.
    heights = [b.get('h', 0) for r in data_rows for b in r if b.get('h')]
    med_h = sorted(heights)[len(heights) // 2] if heights else 20
    max_gap = med_h * (2.6 if multiline else 1.2)
    products = _group_products_by_namerow(data_rows, is_name_box, max_gap)

    _PRICE_FIELDS = ('public_price', 'pharmacist_price', 'line_total')

    def _pick_number(vals, price=False):
        """Prefer a RapidOCR-sourced number (digit-specialist), else any; honour
        the price-plausibility filter for price fields."""
        ok = _is_price if price else _is_number
        rapid = [t for t, s in vals if s == 'rapid' and ok(t)]
        if rapid:
            return rapid[0]
        return next((t for t, s in vals if ok(t)), '')

    lines = []
    for prod in products:
        buckets = {}
        for b in sorted(prod, key=lambda x: (-x['cx'])):   # RTL reading order
            f = field_for(b['cx'])
            if f:
                buckets.setdefault(f, []).append((b['text'], b.get('src', 't')))
        # name = only the Arabic tokens in the name band (drop latin/garbage)
        name_toks = [t for t, s in buckets.get('item_name', []) if _arabic_ratio(t) >= 0.5]
        name = ' '.join(name_toks).strip()
        has_price = any(_is_price(v) for f in _PRICE_FIELDS for v, s in buckets.get(f, []))
        # A real product row is proven by EITHER a plausible price OR a dosage-form
        # word in the name (قرص/كبسولة/مجم …). Requiring a price dropped every row
        # whose numeric cells the engine missed — fatal for PaddleOCR, which detects
        # names well but misses ~half the numbers — while header/customer/footer rows
        # (whose "number" is an order/phone/barcode) never carry a form word, so this
        # stays precise. The name-only rows still reach the matcher, which only needs
        # the name; the operator fills the price in review.
        name_only = _has_drug_form(name) and not has_price
        if len(name) < 3 or not (has_price or _has_drug_form(name)):
            continue
        # guard: a name with too many tokens means several products were merged
        # into one (grouping failed) — drop it rather than emit a wrong line.
        if len(name.split()) > 7:
            continue
        ln = {'confidence': 0.5 if name_only else 0.65,
              'notes': (f'استخراج مجاني ({engine} — قالب الموزّع) — '
                        + ('لم تُقرأ الأسعار، أدخلها يدويًا' if name_only else 'راجع الأسعار'))}
        for f, vals in buckets.items():
            if f == 'item_name':
                ln['item_name'] = name
            elif f in _STR_FIELDS:
                ln[f] = ' '.join(t for t, s in vals).strip()
            elif f in _PRICE_FIELDS:
                ln[f] = _pick_number(vals, price=True)
            else:
                ln[f] = _pick_number(vals, price=False)
        _qty_sanity(ln)                      # catch gross qty misreads (2→82)
        ln.setdefault('quantity', ln.get('quantity') or '1')
        lines.append(ln)
    if not lines:
        return None
    return {'supplier_name': getattr(vendor, 'name', '') if vendor else '',
            'lines': lines, '_engine': f'{engine}/template'}


def _structured_header_driven(boxes, vendor=None, engine='OCR') -> dict | None:
    """Map data cells to fields using the invoice's own column headers (self-
    calibrating), or an explicit per-vendor column-band template when headers are
    not legible. Stacked sub-lines are merged into one product via a numeric anchor."""
    rows = _group_text_rows(boxes)
    # explicit per-vendor template wins; else read the invoice's own headers
    header_cols = _columns_from_bands(vendor, boxes)
    hdr_idx = -1
    if not header_cols:
        header_cols, hdr_idx = _detect_header_columns(rows, vendor)
    if not header_cols:
        return None
    if hdr_idx is None:
        hdr_idx = -1
    fields_present = {f for _, f in header_cols}
    anchors = [f for f in _ANCHOR_FIELDS if f in fields_present]
    if not anchors:
        return None

    products = []   # each: {field: [texts]}
    cur = None

    def row_is_anchor(assigned):
        return any(_is_number(assigned.get(f, '')) for f in anchors)

    for ri, row in enumerate(rows):
        if ri <= hdr_idx:
            continue
        joined = _norm_ar(' '.join(b['text'] for b in row))
        if any(k in joined for k in _NONITEM_KW):
            if cur:             # totals / section header → close current product
                products.append(cur)
            cur = None
            continue
        # assign each box to a field, collecting text per field (reading order)
        assigned = {}
        for b in sorted(row, key=lambda x: x['cx']):
            f = _assign_field(b['cx'], header_cols)
            assigned.setdefault(f, []).append(b['text'])
        assigned = {f: ' '.join(ts).strip() for f, ts in assigned.items()}

        if row_is_anchor(assigned):
            if cur:
                products.append(cur)
            cur = {f: [v] for f, v in assigned.items() if v}
        elif cur is not None:
            # a stacked sub-line (item code / manufacturer / name wrap) → merge
            for f, v in assigned.items():
                if v:
                    cur.setdefault(f, []).append(v)
    if cur:
        products.append(cur)

    lines = []
    for p in products:
        name = ' '.join(p.get('item_name', [])).strip()
        if _arabic_ratio(name) < 0.3 or len(name) < 3:
            continue
        ln = {'confidence': 0.6,
              'notes': f'استخراج مجاني ({engine} — قالب أعمدة) — راجع الأسعار'}
        for f, vals in p.items():
            if f in _STR_FIELDS:
                ln[f] = ' '.join(vals).strip()
            else:
                # numeric field: take the first clean number among the cell's values
                num = next((v for v in vals if _is_number(v)), (vals[0] if vals else ''))
                ln[f] = num
        ln.setdefault('quantity', '1')
        lines.append(ln)
    if not lines:
        return None
    return {'supplier_name': getattr(vendor, 'name', '') if vendor else '',
            'lines': lines, '_engine': f'{engine}/headers'}


def _declared_item_count(boxes) -> int | None:
    """Read the printed item count (عدد الأصناف N) so recall can be checked.
    Robust to OCR noise: normalizes ض→ص (الأصناف often misread الأضناف) and looks
    for a small number next to the phrase in either token order. Returns int/None."""
    import re as _re
    txt = _norm_ar(' '.join(b['text'] for b in boxes)).replace('ض', 'ص')
    m = _re.search(r'عدد\s*الا?صناف', txt)
    if not m:
        return None
    tail = txt[m.end():m.end() + 10]
    head = txt[max(0, m.start() - 10):m.start()]
    for seg in (tail, head):
        nums = _re.findall(r'\b(\d{1,3})\b', seg)
        if nums:
            try:
                return int(nums[0])
            except ValueError:
                pass
    return None


def _structured_from_boxes(boxes: list[dict], vendor=None, engine: str = 'OCR',
                           page_w=None) -> dict | None:
    """Shared box→invoice-dict reconstruction used by every free box engine
    (easyOCR, Tesseract). Returns a Gemini-shaped dict or None.

    Strategy: (1) per-distributor column template (built-in, auto-detected by
    brand, or ocr_profile override); (2) header-driven self-calibration from the
    invoice's own headers; (3) the safe generic name+quantity draft."""
    from . import table_reconstruct as tr
    boxes = _filter_sidebar(boxes)
    if not boxes:
        return None

    declared = _declared_item_count(boxes)
    _confs = [b.get('conf') for b in boxes if isinstance(b.get('conf'), (int, float))]
    avg_conf = (sum(_confs) / len(_confs)) if _confs else None

    def _done(result):
        if result and declared:
            result['_declared_count'] = declared
        if result and avg_conf is not None:
            result['_avg_confidence'] = round(avg_conf, 3)
        return result

    # (1) per-distributor column template (built-in, auto-detected by brand, or
    #     ocr_profile override) — best for the dense main-distributor layouts.
    bands, multiline = _match_template(boxes, vendor, engine)
    if bands:
        bd = _structured_by_bands(boxes, bands, multiline, vendor, engine, page_w)
        if bd and bd.get('lines'):
            return _done(bd)

    # (2) header-driven — self-calibrates from the invoice's own headers
    hd = _structured_header_driven(boxes, vendor, engine)
    if hd and hd.get('lines'):
        return _done(hd)

    # Prefer the engine's own line grouping (Tesseract block/par/line) when present
    # — it is cleaner than geometric y-clustering; else fall back to y-clustering.
    if all('row_key' in b for b in boxes):
        groups = {}
        for b in boxes:
            groups.setdefault(b['row_key'], []).append(b)
        rows = [g for _, g in sorted(groups.items(),
                                     key=lambda kv: sum(b['cy'] for b in kv[1]) / len(kv[1]))]
        cols = tr.cluster_columns(boxes)
        table = {'columns': cols, 'rows': tr.assemble_grid(boxes, cols, rows)}
    else:
        table = tr.reconstruct_table(boxes)
    columns = None
    if vendor is not None:
        cols = (getattr(vendor, 'ocr_profile', None) or {}).get('columns')
        if isinstance(cols, list) and cols:
            columns = cols

    name_col = None if columns else _name_column(table['rows'])
    lines = []
    for cells in table['rows']:
        if not _row_is_item(cells):
            continue
        ln = (_line_from_cells_template(cells, columns, engine) if columns
              else _line_from_cells_no_template(cells, name_col, engine))
        if ln:
            lines.append(ln)
    if not lines:
        return None
    return _done({'supplier_name': getattr(vendor, 'name', '') if vendor else '',
                  'lines': lines, '_engine': engine})


# ── easyOCR box producer ────────────────────────────────────────────────────────

def easyocr_structured_image(img, vendor=None) -> dict | None:
    """Free structured extraction of ONE page image via easyOCR word boxes."""
    try:
        import numpy as np
        from . import ocr
    except ImportError:
        return None
    try:
        reader = ocr._get_easyocr_reader()
        result = reader.readtext(np.array(img.convert('RGB')), detail=1, paragraph=False)
    except Exception as e:
        logger.warning('easyocr structured read failed: %s', e)
        return None
    return _structured_from_boxes(_boxes_from_easyocr(result), vendor, 'easyOCR',
                                  page_w=getattr(img, 'width', None))


# ── Tesseract box producer (free, fast, Arabic) ─────────────────────────────────

def _boxes_from_tesseract(data: dict) -> list[dict]:
    """Convert pytesseract image_to_data(DICT) output to our box dicts."""
    boxes = []
    n = len(data.get('text', []))
    for i in range(n):
        t = (data['text'][i] or '').strip()
        if not t:
            continue
        try:
            conf = float(data['conf'][i])
        except (TypeError, ValueError):
            conf = -1.0
        if conf < 0:          # tesseract emits -1 for non-text blocks
            continue
        left, top = data['left'][i], data['top'][i]
        w, h = data['width'][i], data['height'][i]
        boxes.append({
            'cx': left + w / 2.0, 'cy': top + h / 2.0,
            'w': float(w), 'h': float(h),
            'text': t, 'conf': conf / 100.0,
            # Tesseract's own text-line identity → clean native row grouping
            'row_key': (data.get('block_num', [0] * n)[i],
                        data.get('par_num', [0] * n)[i],
                        data.get('line_num', [0] * n)[i]),
        })
    return boxes


def _rapid_upscale() -> float:
    """Factor to UPSCALE the page before RapidOCR reads digits. Bigger numerals →
    better digit recognition on dense Arabic invoices (RapidOCR is the digit
    specialist in the voting path). settings.INVOICE_OCR_RAPID_UPSCALE, default 2.0;
    1.0 disables. Coordinates are rescaled back so they align with Tesseract boxes."""
    try:
        from django.conf import settings
        return max(1.0, float(getattr(settings, 'INVOICE_OCR_RAPID_UPSCALE', 2.0)))
    except Exception:
        return 2.0


def _boxes_from_rapidocr(img):
    """RapidOCR word boxes (fast, best at digits) tagged src='rapid'. Used to
    vote/override the numeric columns where Tesseract is weaker. The page is
    upscaled first (see _rapid_upscale) so digits read cleaner, then box coordinates
    are divided back to the original scale. [] if unavailable."""
    try:
        import numpy as np
        from PIL import Image
        from . import ocr
        rgb = img.convert('RGB')
        s = _rapid_upscale()
        if s > 1.0 and rgb.width:
            rgb = rgb.resize((int(rgb.width * s), int(rgb.height * s)), Image.LANCZOS)
        engine = ocr._get_rapidocr()
        res, _ = engine(np.array(rgb))
    except Exception as e:
        logger.debug('rapidocr boxes unavailable: %s', e)
        return []
    out = []
    for item in (res or []):
        box, text = item[0], str(item[1] or '').strip()
        if not text:
            continue
        xs = [p[0] / s for p in box]        # rescale to the original image frame
        ys = [p[1] / s for p in box]
        out.append({'cx': sum(xs) / 4.0, 'cy': sum(ys) / 4.0,
                    'w': max(xs) - min(xs), 'h': max(ys) - min(ys),
                    'text': text, 'conf': 0.9, 'src': 'rapid'})
    return out


def _field_voting_enabled() -> bool:
    try:
        from django.conf import settings
        return bool(getattr(settings, 'INVOICE_OCR_FIELD_VOTING', False))
    except Exception:
        return False


def tesseract_structured_image(img, vendor=None) -> dict | None:
    """Free structured extraction of ONE page image via Tesseract (ara+eng).
    With field-voting enabled, RapidOCR number boxes are merged in so the numeric
    columns use the digit-specialist engine while names stay from Tesseract."""
    if not _tesseract_available():
        return None
    # pre-enhance (autocontrast + deskew + upscale) unless disabled
    try:
        from django.conf import settings
        if getattr(settings, 'INVOICE_OCR_ENHANCE', True):
            from . import preprocess
            img = preprocess.enhance_for_ocr(img)
    except Exception as e:
        logger.debug('enhance skipped: %s', e)
    try:
        import pytesseract
        data = pytesseract.image_to_data(
            img, lang='ara+eng', config='--psm 6 --oem 1',
            output_type=pytesseract.Output.DICT)
    except Exception as e:
        logger.warning('tesseract structured read failed: %s', e)
        return None
    boxes = _boxes_from_tesseract(data)
    engine_label = 'Tesseract'
    if _field_voting_enabled():
        rapid_nums = [b for b in _boxes_from_rapidocr(img) if _is_number(b['text'])]
        if rapid_nums:
            boxes = boxes + rapid_nums     # numeric fields will prefer src='rapid'
            engine_label = 'Tesseract+RapidOCR'
    return _structured_from_boxes(boxes, vendor, engine_label,
                                  page_w=getattr(img, 'width', None))


# ── per-engine, multi-page helpers ──────────────────────────────────────────────

def _structured_images(image_paths: list[str], per_image, vendor=None) -> dict | None:
    """Run a per-image free extractor over one invoice's pages and merge."""
    from PIL import Image
    merged = None
    for p in image_paths:
        try:
            with Image.open(p) as im:
                data = per_image(im, vendor=vendor)
        except Exception as e:
            logger.warning('structured extract failed on %s: %s', p, e)
            data = None
        if not data:
            continue
        if merged is None:
            merged = data
        else:
            merged.setdefault('lines', []).extend(data.get('lines') or [])
    return merged


def easyocr_structured_images(image_paths: list[str], vendor=None) -> dict | None:
    return _structured_images(image_paths, easyocr_structured_image, vendor)


def tesseract_structured_images(image_paths: list[str], vendor=None) -> dict | None:
    return _structured_images(image_paths, tesseract_structured_image, vendor)


# ── PaddleOCR box producer (free, local, Arabic; CPU-capable) ────────────────────
# A free structured engine alongside Tesseract/easyOCR. Optional dependency: active
# only when `paddleocr` is importable (pip install paddleocr paddlepaddle). The
# PaddleOCR API has shifted across 2.x/3.x, so construction tolerates both.
_paddle_engine = None


def _paddle_url() -> str:
    try:
        from django.conf import settings
        return (getattr(settings, 'PADDLE_OCR_URL', '') or '').strip()
    except Exception:
        return ''


def _paddleocr_available() -> bool:
    # usable either via the HTTP sidecar (PADDLE_OCR_URL, works on any Python) OR an
    # in-process paddleocr install (only where paddlepaddle has a wheel, i.e. ≤3.12).
    if _paddle_url():
        return True
    try:
        import paddleocr  # noqa: F401
        return True
    except Exception:
        return False


def _paddle_http_boxes(img):
    """Fetch PP-OCRv5 word boxes from the PaddleOCR sidecar (ocr_sidecar/). POSTs the
    page as JPEG, expects {'boxes': [{cx,cy,w,h,text,conf}, …]} in the ORIGINAL image
    frame. [] on any error (engine then yields nothing → auto falls back)."""
    url = _paddle_url()
    if not url:
        return []
    try:
        import io
        import requests
        buf = io.BytesIO()
        img.convert('RGB').save(buf, format='JPEG', quality=92)
        r = requests.post(url, files={'image': ('page.jpg', buf.getvalue(), 'image/jpeg')},
                          timeout=120)
        r.raise_for_status()
        boxes = r.json().get('boxes') or []
        out = []
        for b in boxes:
            t = str(b.get('text') or '').strip()
            if not t:
                continue
            out.append({'cx': float(b['cx']), 'cy': float(b['cy']),
                        'w': float(b.get('w') or 0), 'h': float(b.get('h') or 0),
                        'text': t, 'conf': float(b.get('conf') or 0.9)})
        return out
    except Exception as e:
        logger.warning('paddle sidecar unavailable (%s): %s', url, str(e)[:120])
        return []


def _get_paddleocr():
    global _paddle_engine
    if _paddle_engine is None:
        from paddleocr import PaddleOCR
        for kwargs in ({'use_angle_cls': True, 'lang': 'arabic', 'show_log': False},
                       {'use_angle_cls': True, 'lang': 'arabic'},
                       {'lang': 'arabic'}):
            try:
                _paddle_engine = PaddleOCR(**kwargs)
                break
            except Exception:
                continue
    return _paddle_engine


def _boxes_from_paddleocr(img):
    """PaddleOCR word boxes → our box dicts. [] if unavailable/empty."""
    try:
        import numpy as np
        eng = _get_paddleocr()
        if eng is None:
            return []
        try:
            res = eng.ocr(np.array(img.convert('RGB')), cls=True)
        except TypeError:
            res = eng.ocr(np.array(img.convert('RGB')))
    except Exception as e:
        logger.debug('paddleocr boxes unavailable: %s', e)
        return []
    pages = res or []
    lines = pages[0] if (pages and isinstance(pages[0], list)) else pages
    out = []
    for item in (lines or []):
        try:
            box, payload = item[0], item[1]
            text, conf = (payload[0], payload[1]) if isinstance(payload, (list, tuple)) else (payload, 0.9)
        except Exception:
            continue
        text = str(text or '').strip()
        if not text:
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        out.append({'cx': sum(xs) / 4.0, 'cy': sum(ys) / 4.0,
                    'w': max(xs) - min(xs), 'h': max(ys) - min(ys),
                    'text': text, 'conf': float(conf or 0.9)})
    return out


def paddleocr_structured_image(img, vendor=None) -> dict | None:
    # Prefer the HTTP sidecar (works on Python 3.14); fall back to in-process paddle.
    boxes = _paddle_http_boxes(img) if _paddle_url() else _boxes_from_paddleocr(img)
    if not boxes:
        return None
    label = 'PaddleOCR/sidecar' if _paddle_url() else 'PaddleOCR'
    return _structured_from_boxes(boxes, vendor, label, page_w=getattr(img, 'width', None))


def paddleocr_structured_images(image_paths: list[str], vendor=None) -> dict | None:
    return _structured_images(image_paths, paddleocr_structured_image, vendor)


# ── unified free dispatcher ─────────────────────────────────────────────────────

def free_structured_image(img, engine: str, vendor=None) -> dict | None:
    if engine == 'tesseract':
        return tesseract_structured_image(img, vendor=vendor)
    if engine == 'paddleocr':
        return paddleocr_structured_image(img, vendor=vendor)
    return easyocr_structured_image(img, vendor=vendor)


def free_structured_images(image_paths: list[str], engine: str, vendor=None) -> dict | None:
    spec = get_engine(engine)
    if spec is not None and spec.kind == 'free':
        return spec.run(image_paths, vendor)
    if engine == 'tesseract':
        return tesseract_structured_images(image_paths, vendor=vendor)
    if engine == 'paddleocr':
        return paddleocr_structured_images(image_paths, vendor=vendor)
    return easyocr_structured_images(image_paths, vendor=vendor)


# ── register the built-in engines (free first, then the API engines) ─────────────
register_engine(EngineSpec(
    'tesseract', 'free', 10, lambda: _tesseract_available(),
    lambda p, v, h: tesseract_structured_images(p, vendor=v),
    'Tesseract ara+eng + RapidOCR digit voting (fast, CPU)'))
register_engine(EngineSpec(
    'paddleocr', 'free', 20, lambda: _paddleocr_available(),
    lambda p, v, h: paddleocr_structured_images(p, vendor=v),
    'PaddleOCR PP-OCRv5 Arabic — via sidecar (PADDLE_OCR_URL) on Py3.14, else in-process'))
register_engine(EngineSpec(
    'easyocr', 'free', 30, lambda: _easyocr_available(),
    lambda p, v, h: easyocr_structured_images(p, vendor=v),
    'EasyOCR ar+en (slow on CPU)'))
register_engine(EngineSpec(
    'gemini', 'api', 10, lambda: bool(_ocr()._gemini_keys()),
    lambda p, v, h: _ocr()._gemini_images(p, h),
    'Google Gemini (free tier 20/day/model/key; rotates keys)'))
register_engine(EngineSpec(
    'mistral', 'api', 20, lambda: bool(_ocr()._mistral_available()),
    lambda p, v, h: _ocr()._mistral_images(p, h),
    'Mistral vision OCR (paid; MISTRAL_API_KEY)'))
register_engine(EngineSpec(
    'vlm', 'api', 30, lambda: bool(_ocr()._vlm_available()),
    lambda p, v, h: _ocr()._vlm_images(p, h),
    'Self-hosted VLM via OpenAI-compatible endpoint (VLM_OCR_URL; e.g. PaddleOCR-VL)'))
