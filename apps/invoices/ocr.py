"""
apps/invoices/ocr.py

OCR extraction for supplier invoice images AND PDFs.
Primary:   pytesseract (Tesseract 4+ with Arabic+English language packs)
Fallback:  easyocr (if installed) — Reader is a module-level singleton to avoid
           the expensive re-initialisation on every call (model loading ~3 s).
PDF:       pdf2image (poppler) converts each page to a PIL Image, then OCR runs
           on each page in sequence and text is concatenated.
Stub mode: if neither available, returns empty string.

Installation:
  pip install pytesseract pillow pdf2image
  # Tesseract binary: https://github.com/UB-Mannheim/tesseract/wiki
  # Poppler (for PDF): https://github.com/oschwartz10612/poppler-windows/releases
  # Set POPPLER_PATH in settings or env if not on PATH.
"""
import json
import logging
import re
import threading

from . import reconcile

logger = logging.getLogger('elrezeiky.invoices')

# Gemini model fallback chain — shared by the text and structured-JSON extractors.
# Prefer the floating alias (always resolves to the current flash model) first, so
# a server-side rename never leaves us calling a 404'd pin. Verified 2026-10-18 on the
# HQ benchmark run: 'gemini-flash-latest' succeeded while the old pins failed —
# gemini-2.5-flash → 503, gemini-2.5-flash-preview-05-20 → 404, gemini-2.0-flash →
# "no longer available, use models/gemini-3.8-flash". Keep a couple of concrete
# fallbacks after it in case the alias itself is ever unavailable.
_GEMINI_MODELS = [
    'gemini-flash-latest',
    'gemini-3.8-flash',
    'gemini-2.5-flash',
]


def _gemini_timeout_ms() -> int:
    """Per-call Gemini HTTP timeout in ms (settings.INVOICE_GEMINI_TIMEOUT seconds,
    default 60). Bounds a single call so a network/DNS drop can't hang the run —
    observed a 34-minute freeze on a mid-run DNS outage with no timeout set."""
    try:
        from django.conf import settings
        return int(float(getattr(settings, 'INVOICE_GEMINI_TIMEOUT', 60)) * 1000)
    except Exception:
        return 60000


def _genai_client(key):
    """genai.Client with a bounded HTTP timeout. Falls back to a plain client if
    this SDK build doesn't accept http_options (so an older google-genai keeps
    working, just without the cap)."""
    from google import genai
    try:
        from google.genai import types
        return genai.Client(
            api_key=key,
            http_options=types.HttpOptions(timeout=_gemini_timeout_ms()))
    except Exception:
        return genai.Client(api_key=key)


# ── Gemini key rotation + per-(key,model) quota cooldown ─────────────────────────
# The free tier is 20 requests/day PER MODEL PER PROJECT. With one key that caps a
# day's work fast; a SECOND key (GEMINI_API_KEY_2, a separate project) doubles it.
# And once a (key,model) returns 429 the daily quota is gone for hours, so we cool
# that pair down instead of re-hitting it on every subsequent call.
_gemini_cooldown: dict = {}   # (key_index, model) → epoch when it may be retried


def _gemini_keys() -> list:
    """Configured Gemini keys in priority order (primary, then the 2nd project)."""
    try:
        from django.conf import settings as s
    except Exception:
        return []
    keys = []
    for name in ('GEMINI_API_KEY', 'GEMINI_API_KEY_2'):
        k = (getattr(s, name, '') or '').strip()
        if k and k not in keys:
            keys.append(k)
    return keys


def _is_quota_error(exc) -> bool:
    s = str(exc)
    return '429' in s or 'RESOURCE_EXHAUSTED' in s


def _cool_seconds(exc) -> int:
    """Seconds to cool a quota-exhausted (key,model) pair — the API's own
    retryDelay when present (capped at 24h), else 1h."""
    m = re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+)", str(exc))
    if m:
        return min(int(m.group(1)), 24 * 3600)
    return 3600


def _gemini_generate(contents, config=None):
    """Call Gemini with KEY ROTATION + per-(key,model) quota COOLDOWN, honoring the
    per-call HTTP timeout. Tries every (key, model) pair in priority order, skipping
    pairs cooled down by a recent 429. On a quota error the pair is cooled for the
    API's retryDelay so an exhausted daily quota isn't re-hit on every call. Returns
    (response, 'key#<i>/<model>') or (None, None) when nothing usable is available."""
    import time
    keys = _gemini_keys()
    if not keys:
        return None, None
    now = time.time()
    tried = cooled = 0
    for ki, key in enumerate(keys):
        client = None
        for model_name in _GEMINI_MODELS:
            if _gemini_cooldown.get((ki, model_name), 0) > now:
                cooled += 1
                continue
            if client is None:
                client = _genai_client(key)
            tried += 1
            try:
                kwargs = {'config': config} if config is not None else {}
                resp = client.models.generate_content(
                    model=model_name, contents=contents, **kwargs)
                return resp, f'key#{ki + 1}/{model_name}'
            except Exception as exc:
                if _is_quota_error(exc):
                    cd = _cool_seconds(exc)
                    _gemini_cooldown[(ki, model_name)] = time.time() + cd
                    logger.warning('Gemini key#%d/%s quota-exhausted — cooling %ds',
                                   ki + 1, model_name, cd)
                else:
                    logger.warning('Gemini key#%d/%s failed: %s',
                                   ki + 1, model_name, str(exc)[:160])
                continue
    if tried == 0 and cooled:
        logger.warning('Gemini: every (key,model) pair is cooled down (quota) — using free OCR')
    return None, None


# ── easyocr singleton ────────────────────────────────────────────────────────
# Initialized once on first use (lazy); protected by a lock so concurrent
# invoice uploads don't create multiple Reader instances simultaneously.
_easyocr_reader      = None
_easyocr_reader_lock = threading.Lock()


def _get_easyocr_reader():
    """Return the module-level easyocr Reader, creating it if needed."""
    global _easyocr_reader
    if _easyocr_reader is not None:
        return _easyocr_reader
    with _easyocr_reader_lock:
        if _easyocr_reader is None:          # double-checked locking
            import easyocr
            logger.info('Initializing easyocr Reader (one-time startup cost)…')
            _easyocr_reader = easyocr.Reader(['ar', 'en'], gpu=False)
            logger.info('easyocr Reader ready.')
    return _easyocr_reader


def _is_pdf(path: str) -> bool:
    return path.lower().endswith('.pdf')


def _pdf_to_images(pdf_path: str) -> list:
    """Convert a PDF to a list of PIL Images (one per page)."""
    try:
        from pdf2image import convert_from_path
        import os
        poppler = os.environ.get('POPPLER_PATH')
        images  = convert_from_path(pdf_path, dpi=200, poppler_path=poppler)
        logger.info(f'PDF→images: {len(images)} page(s)')
        return images
    except ImportError:
        logger.warning('pdf2image not installed — cannot process PDF')
        return []
    except Exception as e:
        logger.warning(f'PDF conversion error: {e}')
        return []


def extract_text(image_path: str) -> str:
    """
    Extract raw text from an invoice image or PDF.
    Returns empty string if OCR is unavailable.
    For PDFs, all pages are processed and text concatenated.
    """
    # ── PDF mode ──────────────────────────────────────────────────────────────
    if _is_pdf(image_path):
        images = _pdf_to_images(image_path)
        if not images:
            logger.warning('PDF yielded no images — falling back to empty text')
            return ''
        pages_text = []
        for page_num, img in enumerate(images, 1):
            page_text = _ocr_image_object(img, label=f'PDF page {page_num}')
            if page_text:
                pages_text.append(page_text)
        return '\n\n'.join(pages_text)

    # ── Image mode ────────────────────────────────────────────────────────────
    try:
        from PIL import Image
        img = Image.open(image_path)
    except Exception as e:
        logger.warning(f'Cannot open image: {e}')
        return ''
    return _ocr_image_object(img, label=image_path)


_OCR_INVOICE_PROMPT = (
    'This image is a supplier invoice for a pharmacy in Egypt (Arabic/English).\n\n'
    'Egyptian pharma invoices have these columns per product line:\n'
    '  اسم الصنف | اسم المورد | الكمية | كود الصنف (المورد) | رقم التشغيلة | تاريخ الصلاحية\n'
    '  | سعر الجمهور | خصم مطابقة% | خصم إضافي% (خ.ص.د) | سعر الصيدلي\n'
    '  | ض.ق.م% | هامش الموزع (مبلغ ج.م.) | هامش ربح الصيدلي (مبلغ ج.م.)\n\n'
    'Extract EVERY product line using this exact 13-field pipe-separated format:\n'
    '  item_name | manufacturer | quantity | vendor_item_code | batch_no | expiry_date\n'
    '  | public_price | discount_pct | extra_discount_pct | pharmacist_price\n'
    '  | vat_pct | distributor_margin_amt | pharmacist_margin_amt\n\n'
    'IMPORTANT:\n'
    '- distributor_margin_amt and pharmacist_margin_amt are MONETARY AMOUNTS (ج.م.), NOT percentages\n'
    '- vat_pct IS a percentage (e.g. 14)\n'
    '- vendor_item_code = ONLY a column titled كود الصنف / كود المورد / Item Code. If the invoice has no such\n'
    '  column, leave vendor_item_code EMPTY. Many invoices (e.g. Pharma Overseas) print only رقم التشغيلة.\n'
    '- batch_no = the رقم التشغيلة / Batch / Lot column. Write the WHOLE value in batch_no — never cut it,\n'
    '  never split one printed value across two fields, never copy the same value into both fields.\n'
    '- ONE product per line, 13 fields separated by |\n'
    '- Keep Arabic product names exactly as written\n'
    '- Include dosage form & strength (e.g. "نيفيلوب 5 مجم قرص", "Novonorm 14")\n'
    '- Numbers only for numeric fields — no currency symbols, no % signs, no commas in numbers\n'
    '- Leave a field empty if not visible, but always keep all 13 | separators\n'
    '- Do NOT output section headers (e.g. "اصناف خاضعة للضريبة"), totals, or explanatory text\n'
    '- Output the pipe-separated product list ONLY\n\n'
    'Example output:\n'
    '(an invoice WITH an item-code column, then one WITHOUT — batch only)\n'
    'ايفيروسبان 100 ملى شراب | ماركيول للصناع | 25 | 643352 | 2442687 | 08.2027 | 55.00 | 25 | 5.066 | 36.18 | 14 | 126.65 | 0\n'
    'سبازمو-ديجستين 30 قرص | فاركو للادوية | 30 |  | 6594 | 09.2027 | 78.00 | 25 | 0 | 54.00 | 0 | 0 | 0\n'
)


def _ocr_image_object(img, label: str = '') -> str:
    """
    Run OCR on a PIL Image object.
    Engine priority:
      1. Google Gemini (if GEMINI_API_KEY set) — best for handwriting
      2. EasyOCR (local, good for mixed scripts)
      3. pytesseract (printed text)
    Returns extracted text string.
    """
    # ── 1. Gemini ──────────────────────────────────────────────────────────────
    if _gemini_keys():
        try:
            import io as _io
            from google.genai import types
            buf       = _io.BytesIO()
            img.save(buf, format='JPEG', quality=92)
            contents = [
                types.Part.from_bytes(data=buf.getvalue(), mime_type='image/jpeg'),
                types.Part.from_text(text=_OCR_INVOICE_PROMPT),
            ]
            response, used = _gemini_generate(contents)
            if response is not None:
                text = (response.text or '').strip()
                logger.info(f'OCR via Gemini/{used} ({label}): {len(text)} chars')
                return text
            logger.warning(f'All Gemini keys/models exhausted for {label}')
        except ImportError:
            logger.warning('google-genai not installed — run: pip install google-genai')
        except Exception as e:
            logger.warning(f'Gemini OCR error on {label}: {e}')

    # ── 2. EasyOCR ─────────────────────────────────────────────────────────────
    try:
        import numpy as np
        reader = _get_easyocr_reader()
        result = reader.readtext(np.array(img), detail=0, paragraph=False)
        text   = '\n'.join(str(r) for r in result)
        logger.info(f'OCR via EasyOCR ({label}): {len(text)} chars')
        return text
    except ImportError:
        logger.warning('easyocr not installed')
    except Exception as e:
        logger.warning(f'EasyOCR error on {label}: {e}')

    # ── 3. pytesseract ─────────────────────────────────────────────────────────
    try:
        import pytesseract
        text = pytesseract.image_to_string(img, lang='ara+eng', config='--psm 11 --oem 1')
        logger.info(f'OCR via pytesseract ({label}): {len(text)} chars')
        return text
    except ImportError:
        logger.warning('pytesseract not installed')
    except Exception as e:
        logger.warning(f'pytesseract error on {label}: {e}')

    logger.warning(f'No OCR engine available for {label}')
    return ''


# ── Line parsers ───────────────────────────────────────────────────────────────

def _to_float(s: str) -> float:
    """Convert a string like '1,234.50' or '١٢٣' (Arabic digits) to float."""
    if not s:
        return 0.0
    # Map Arabic-Indic digits → ASCII
    s = s.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
    try:
        return float(s.replace(',', '').strip())
    except ValueError:
        return 0.0


_QTY_PRICE_RE = re.compile(
    r'(\d[\d,]*\.?\d*)\s*[xX×*]\s*(\d[\d,]*\.?\d*)'   # "qty x price"
    r'|(\d[\d,]*\.?\d*)\s+(\d[\d,]*\.?\d*)'            # "qty price" side by side
)

# Header keywords to skip (Arabic + English)
_HEADER_RE = re.compile(
    r'^(اسم|الصنف|كمية|سعر|خصم|صافي|إجمالي|total|qty|price|disc|item|name|code|#)\b',
    re.IGNORECASE,
)


def _flat(v: str) -> str:
    return re.sub(r'\s+', '', str(v or '')).upper()


def separate_code_and_batch(code: str, batch: str) -> tuple:
    """(vendor_item_code, batch_number, fix) — repairs the reader putting ONE printed batch
    value into the supplier-code field (owner 2026-10-05; found on Pharma Overseas invoices,
    whose sheets carry رقم التشغيلة but no item-code column). Deterministic:
      1. same value in both fields             → it is the batch; code cleared   ('same')
      2. one is the start of the other          → the batch was cut; keep the whole
         value as the batch; code cleared                                       ('cut')
      3. a short 1–3 digit "code" next to a 4–5 character batch → one value split
         in two ('24426' + '87' = '2442687'); rejoin as the batch; code cleared  ('split')
    Anything else is left exactly as read (fix = '')."""
    code, batch = str(code or '').strip(), str(batch or '').strip()
    fc, fb = _flat(code), _flat(batch)
    if not fc or not fb:
        return code, batch, ''
    if fc == fb:
        return '', batch, 'same'
    if len(fb) >= 2 and fc.startswith(fb):
        return '', code, 'cut'
    if len(fc) >= 2 and fb.startswith(fc):
        return '', batch, 'cut'
    if fc.isdigit() and len(fc) <= 3 and 4 <= len(fb) <= 5:
        return '', batch + code, 'split'
    return code, batch, ''


FIX_NOTES = {'same': 'كود المورد كان نفس رقم التشغيلة — نُقل للتشغيلة',
             'cut': 'رقم التشغيلة كان مقطوعاً داخل كود المورد — جُمِع في التشغيلة',
             'split': 'رقم التشغيلة كان مقسوماً بين الحقلين — جُمِع في التشغيلة'}


def _clean_code_batch(line: dict) -> dict:
    code, batch, fix = separate_code_and_batch(line.get('vendor_item_code'), line.get('batch_number'))
    if fix:
        line['read_as'] = {'vendor_item_code': line.get('vendor_item_code'), 'batch_number': line.get('batch_number')}
        line['vendor_item_code'], line['batch_number'] = code, batch
        prev = (line.get('notes') or '').strip()
        line['notes'] = (prev + ' — ' + FIX_NOTES[fix]).strip(' —') if prev else FIX_NOTES[fix]
    return line


def parse_lines(raw_text: str) -> list:
    """
    Parse raw OCR/Gemini output into structured invoice line dicts.

    Primary path — 11-field pipe-separated (Gemini structured output):
        item_name | manufacturer | quantity | batch_no | expiry_date
        | public_price | discount_pct | extra_discount_pct | pharmacist_price
        | vat_pct | distributor_margin_pct

    Fallback path — free-text heuristic (EasyOCR / pytesseract output).

    Returns list of dicts with keys:
        raw_text, manual_name, manufacturer, batch_number, expiry_date,
        quantity, public_price, discount_pct, extra_discount_pct,
        unit_price, vat_pct, distributor_margin_pct
    """
    raw_lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
    results   = []

    # ── Detect whether output is pipe-separated ────────────────────────────────
    pipe_lines = [l for l in raw_lines if '|' in l]
    use_pipes  = len(pipe_lines) >= max(1, len(raw_lines) // 2)

    for line in raw_lines:
        if len(line) < 3:
            continue
        if re.fullmatch(r'[\d\s,.\-٠-٩]+', line):   # pure numbers → totals row
            continue
        if _HEADER_RE.match(line):                    # column header row
            continue

        if use_pipes and '|' in line:
            # ── 13-field pipe-separated (Gemini) ───────────────────────────────
            parts = [p.strip() for p in line.split('|')]
            while len(parts) < 13:
                parts.append('')

            name                   = parts[0].strip(' -–:')
            manufacturer           = parts[1].strip()
            quantity               = _to_float(parts[2]) or 1.0
            vendor_item_code       = parts[3].strip()
            batch_number           = parts[4].strip()
            expiry_date            = parts[5].strip()
            public_price           = _to_float(parts[6])
            discount_pct           = _to_float(parts[7])
            extra_discount_pct     = _to_float(parts[8])
            pharmacist_price       = _to_float(parts[9])
            vat_pct                = _to_float(parts[10])
            distributor_margin_amt = _to_float(parts[11])   # monetary amount ج.م.
            pharmacist_margin_amt  = _to_float(parts[12])   # monetary amount ج.م.

            if not name or len(name) < 2:
                continue

            # Derive pharmacist price if Gemini left it blank
            if pharmacist_price == 0 and public_price > 0:
                pharmacist_price = round(
                    public_price * (1 - discount_pct / 100) * (1 - extra_discount_pct / 100), 4
                )

            results.append(_clean_code_batch({
                'raw_text':               line,
                'manual_name':            name,
                'manufacturer':           manufacturer,
                'vendor_item_code':       vendor_item_code,
                'batch_number':           batch_number,
                'expiry_date':            expiry_date,
                'quantity':               quantity,
                'public_price':           public_price,
                'discount_pct':           discount_pct,
                'extra_discount_pct':     extra_discount_pct,
                'unit_price':             pharmacist_price,
                'vat_pct':                vat_pct,
                'distributor_margin_amt': distributor_margin_amt,
                'pharmacist_margin_amt':  pharmacist_margin_amt,
            }))

        else:
            # ── Free-text fallback (EasyOCR / pytesseract) ─────────────────────
            qty   = 1.0
            price = 0.0
            m = _QTY_PRICE_RE.search(line)
            if m:
                if m.group(1):
                    qty, price = _to_float(m.group(1)), _to_float(m.group(2))
                elif m.group(3):
                    qty, price = _to_float(m.group(3)), _to_float(m.group(4))

            name = _QTY_PRICE_RE.sub('', line).strip(' -–:') or line

            results.append({
                'raw_text':               line,
                'manual_name':            name,
                'manufacturer':           '',
                'vendor_item_code':       '',
                'batch_number':           '',
                'expiry_date':            '',
                'quantity':               qty,
                'public_price':           price,
                'discount_pct':           0.0,
                'extra_discount_pct':     0.0,
                'unit_price':             price,
                'vat_pct':                0.0,
                'distributor_margin_amt': 0.0,
                'pharmacist_margin_amt':  0.0,
            })

    return results


# ── Expiry normalization ─────────────────────────────────────────────────────

_MONTHS = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}


def normalize_expiry(raw: str) -> str:
    """
    Normalize a printed expiry to ISO ``YYYY-MM-DD``.

    Egyptian pharma invoices print expiries many ways: ``08.2027``, ``08/2027``,
    ``2027-08``, ``08-27``, ``Aug 2027``, ``31/08/2027``, ``5-5-28``. Like the SofTech
    screen, ``.`` ``-`` ``/`` are all separators and a full date is DAY first
    (dd mm yyyy or dd mm yy). A month/year expiry gets day = month (owner rule
    2026-10-31: ``09.2029`` → 09/09/2029, so day and month can't be confused).
    Returns ``''`` when nothing parseable is found (caller keeps the raw text).
    """
    if not raw:
        return ''
    s = str(raw).translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')).strip()
    low = s.lower()

    # Month name forms: "Aug 2027", "August 2027"
    for name, mo in _MONTHS.items():
        if name in low:
            m = re.search(r'(20\d{2}|\d{2})', low)
            if m:
                return _iso(_yy(m.group(1)), mo, mo)

    nums = re.findall(r'\d+', s)
    if not nums:
        return ''

    # Full date dd ? mm ? yyyy  (3 numeric parts)
    if len(nums) >= 3:
        a, b, c = nums[0], nums[1], nums[2]
        # decide which is the year (4 digits, or the >31 value)
        if len(c) == 4 or int(c) > 31:                 # dd mm yyyy
            return _iso(_yy(c), _clamp_month(b), _clamp_day(a))
        if len(a) == 4:                                 # yyyy mm dd
            return _iso(_yy(a), _clamp_month(b), _clamp_day(c))
        return _iso(_yy(c), _clamp_month(b), _clamp_day(a))   # dd mm yy (SofTech order)

    # Month/year (2 numeric parts) → day = month
    if len(nums) == 2:
        a, b = nums[0], nums[1]
        if len(a) == 4 or (int(a) > 12 and len(b) <= 2):   # yyyy mm
            mo = _clamp_month(b)
            return _iso(_yy(a), mo, mo)
        mo = _clamp_month(a)
        return _iso(_yy(b), mo, mo)                         # mm yyyy / mm yy

    return ''


def _yy(y: str) -> int:
    y = int(y)
    return y if y >= 100 else 2000 + y


def _clamp_month(m) -> int:
    m = int(m)
    return min(max(m, 1), 12)


def _clamp_day(d) -> int:
    d = int(d)
    return min(max(d, 1), 31)


def _iso(year: int, month: int, day: int) -> str:
    try:
        import calendar
        import datetime
        last = calendar.monthrange(year, month)[1]
        return datetime.date(year, month, min(day, last)).isoformat()
    except Exception:
        return f'{year:04d}-{month:02d}-01'


# ── Structured JSON extraction (preferred — robust vs pipe-splitting) ─────────

_OCR_JSON_PROMPT = (
    'You are extracting a PHARMACY SUPPLIER INVOICE from Egypt (Arabic/English).\n'
    'Return ONLY a valid JSON object (no markdown fences, no commentary) shaped exactly:\n'
    '{\n'
    '  "supplier_name": string,        // the DISTRIBUTOR COMPANY printed as the header/logo brand at the top\n'
    '                                  // (e.g. "ibnsina pharma", "PharmaOverseas"). NOT a warehouse,\n'
    '                                  // branch, storage location, salesperson, or the buyer pharmacy.\n'
    '  "invoice_number": string,       // رقم الفاتورة / رقم مستند المورد\n'
    '  "invoice_date": string,         // YYYY-MM-DD if visible, else ""\n'
    '  "currency": string,             // default "EGP"\n'
    '  "declared_total": number,       // الإجمالي printed on the invoice, else 0\n'
    '  "lines": [{\n'
    '     "item_name": string,         // keep Arabic EXACTLY; include form & strength\n'
    '     "generic_name_en": string,   // the English generic/brand name you recognise for this drug, else ""\n'
    '     "manufacturer": string,\n'
    '     "vendor_item_code": string,  // the supplier product code — ONLY from a column titled\n'
    '                                  // كود الصنف / كود المورد / Item Code (e.g. "643352"). If the invoice\n'
    '                                  // has NO such column, return "". NEVER the batch/التشغيلة/Lot value,\n'
    '                                  // barcode, price or quantity.\n'
    '     "batch_number": string,      // رقم التشغيلة / Batch / Lot — the WHOLE value exactly as printed\n'
    '                                  // (e.g. "240808A", "AT24 0457", "2442687"); never cut it, never split\n'
    '                                  // it across two fields, never copy it into vendor_item_code.\n'
    '     "expiry_date": string,       // as printed, e.g. "08.2027"\n'
    '     "quantity": number,          // the PAID packs count\n'
    '     "bonus_qty": number,         // FOC/free bonus packs if printed on the SAME line (e.g. "10+1" → 1); else 0\n'
    '     "public_price": number,      // سعر الجمهور\n'
    '     "discount_pct": number,      // خصم مطابقة %\n'
    '     "extra_discount_pct": number,// خصم إضافي %\n'
    '     "pharmacist_price": number,  // سعر الصيدلي (net); 0 if not printed\n'
    '     "vat_pct": number,           // ض.ق.م %\n'
    '     "distributor_margin_amt": number,\n'
    '     "pharmacist_margin_amt": number,\n'
    '     "confidence": number         // 0..1 your confidence for THIS row\n'
    '  }]\n'
    '}\n'
    'Rules: numbers are plain (no %, no commas, no currency symbols). ONE object per product row.\n'
    'NEVER emit section headers (e.g. "اصناف خاضعة للضريبة"), totals, or notes as product rows.\n'
)


def vendor_prompt_hints(profile: dict) -> str:
    """Turn a VendorProfile.ocr_profile into a prompt snippet that tunes extraction
    for THIS distributor (appended to the base prompt when the vendor is known at
    upload). Keys: code_format, foc_style, tax_note, notes."""
    if not isinstance(profile, dict) or not profile:
        return ''
    bits = []
    cf = str(profile.get('code_format') or '').strip().lower()
    if cf == 'alphanumeric':
        bits.append('The supplier item code (vendor_item_code) is ALPHANUMERIC — letters+digits, '
                    'sometimes a letter prefix (e.g. AT240457, DEG075). Capture the whole token.')
    elif cf == 'numeric':
        bits.append('The supplier item code (vendor_item_code) is all DIGITS.')
    fs = str(profile.get('foc_style') or '').strip().lower()
    if fs == 'same_line':
        bits.append('Free/bonus packs are printed on the SAME line as "10+1" — put the paid count '
                    'in quantity and the bonus count in bonus_qty.')
    elif fs == 'separate_line':
        bits.append('Free/bonus packs appear as a SEPARATE line (free packs at price 0) after the paid line.')
    for k in ('tax_note', 'notes'):
        v = str(profile.get(k) or '').strip()
        if v:
            bits.append(v)
    if not bits:
        return ''
    return ('\n\nDISTRIBUTOR-SPECIFIC NOTES (this invoice is from a known distributor):\n- '
            + '\n- '.join(bits))


def _gemini_key():
    try:
        from django.conf import settings as dj_settings
        return getattr(dj_settings, 'GEMINI_API_KEY', '') or ''
    except Exception:
        return ''


def _json_from_text(text: str):
    """Parse a JSON object out of a model response, tolerating ```json fences."""
    if not text:
        return None
    t = text.strip()
    if t.startswith('```'):
        t = re.sub(r'^```[a-zA-Z]*\s*', '', t)
        t = re.sub(r'\s*```$', '', t).strip()
    try:
        return json.loads(t)
    except Exception:
        # last resort: grab the outermost {...}
        m = re.search(r'\{.*\}', t, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def _gemini_extract_json(img, extra_hints: str = '') -> dict | None:
    """Run Gemini in JSON mode on a PIL image; return the parsed dict or None."""
    if not _gemini_keys():
        return None
    try:
        import io as _io
        from google.genai import types
    except ImportError:
        logger.warning('google-genai not installed — structured OCR unavailable')
        return None

    buf = _io.BytesIO()
    img.save(buf, format='JPEG', quality=92)
    img_bytes = buf.getvalue()
    cfg = types.GenerateContentConfig(temperature=0, response_mime_type='application/json')
    resp, used = _gemini_generate([
        types.Part.from_bytes(data=img_bytes, mime_type='image/jpeg'),
        types.Part.from_text(text=_OCR_JSON_PROMPT + (extra_hints or '')),
    ], config=cfg)
    if resp is not None:
        data = _json_from_text(resp.text)
        if isinstance(data, dict) and data.get('lines'):
            logger.info('Structured OCR via Gemini/%s: %d line(s)', used, len(data['lines']))
            return data
    return None


# ── Page-boundary probe (multi-invoice PDF ingestion, Phase 1) ──────────────────
# A deliberately CHEAP, single-page vision call that reads only the signals the
# splitter needs to group pages into separate invoices — never the line items.
# One probe per page lets a 50-page distributor PDF be fanned out into the ~50
# invoices it actually contains (see apps/invoices/splitter.py).
_PAGE_PROBE_PROMPT = (
    'You are reading ONE page of a scanned Egyptian pharmacy supplier document '
    '(invoice فاتورة or priced-receipt اذن استلام مسعر), mostly Arabic, right-to-left.\n'
    'Return ONLY the page-identity header/footer fields as JSON — DO NOT read the line items:\n'
    '{\n'
    '  "doc_number": string,   // the printed invoice/receipt/sales-order number (رقم الفاتورة / رقم أمر البيع / barcode digits); "" if none\n'
    '  "doc_type": string,     // e.g. "فاتورة" or "اذن استلام مسعر" exactly as printed; "" if unclear\n'
    '  "page_index": number,   // the X in an "X / Y" or "Page X of Y" counter; 0 if none\n'
    '  "page_count": number,   // the Y in "X / Y" / "Page X of Y"; 0 if none\n'
    '  "date": string,         // the document date as printed; "" if none\n'
    '  "supplier_name": string,// the issuing distributor name if printed; "" if none\n'
    '  "has_totals": boolean   // true if this page shows an invoice totals/net block (إجمالي / صافي الفاتورة / المطلوب)\n'
    '}\n'
    'Numbers plain (no commas/%/currency). If a field is absent use "" or 0.'
)


# Keywords that mark an invoice totals / net block (end-of-invoice signal).
_TOTALS_KW = ('صافي الفاتور', 'المطلوب', 'الاجمالى', 'الإجمالي', 'اجمالي', 'إجمالي',
              'الاجمالي', 'grand total', 'net total', 'total due')


# RapidOCR (onnxruntime) singleton — the FREE, FAST engine used for the boundary
# probe. Benchmarked ~9s/page on CPU and best at the digit signals the splitter
# needs (invoice number, "1/1" counter). Its default models do not read Arabic,
# which is fine for boundaries (numeric) but is why structured line extraction
# uses a different engine.
_rapidocr_engine = None
_rapidocr_lock   = threading.Lock()


def _get_rapidocr():
    global _rapidocr_engine
    if _rapidocr_engine is None:
        with _rapidocr_lock:
            if _rapidocr_engine is None:
                from rapidocr_onnxruntime import RapidOCR
                _rapidocr_engine = RapidOCR()
    return _rapidocr_engine


def _ocr_text_rapidocr(img) -> str:
    """OCR a PIL image to raw text with RapidOCR (fast, free). '' if unavailable."""
    try:
        import numpy as np
        engine = _get_rapidocr()
        res, _ = engine(np.array(img.convert('RGB')))
        return '\n'.join(x[1] for x in res) if res else ''
    except ImportError:
        return ''
    except Exception as e:
        logger.warning('RapidOCR error: %s', e)
        return ''


def _ocr_text_free(img) -> str:
    """OCR a PIL image to raw text using the Arabic-capable free local engines
    (EasyOCR → pytesseract), never Gemini. Returns '' when none is available.
    Used where Arabic coverage matters more than speed."""
    # EasyOCR
    try:
        import numpy as np
        reader = _get_easyocr_reader()
        result = reader.readtext(np.array(img), detail=0, paragraph=False)
        return '\n'.join(str(r) for r in result)
    except ImportError:
        pass
    except Exception as e:
        logger.warning('free OCR (easyocr) error: %s', e)
    # pytesseract
    try:
        import pytesseract
        return pytesseract.image_to_string(img, lang='ara+eng', config='--psm 6 --oem 1')
    except ImportError:
        pass
    except Exception as e:
        logger.warning('free OCR (pytesseract) error: %s', e)
    return ''


def _parse_page_signals(text: str) -> dict:
    """
    PURE: pull boundary signals from a page's header/footer OCR text, independent
    of which OCR engine produced it (Gemini, EasyOCR, pytesseract, RapidOCR…).
    Returns {doc_number, doc_type, page_index, page_count, has_totals, has_header}.
    Grounded in the real specimens: Ramco footer "1 / 1" + "فاتورة 1826060925";
    PharmaOverseas "Page 1 of 1" + "اذن استلام مسعر" + barcode digits.
    """
    t = text or ''
    low = t.lower()

    # ── page counter "x of y" / "x / y" / "صفحة x من y" ──
    page_index = page_count = None
    m = (re.search(r'page\s+(\d+)\s+of\s+(\d+)', low)
         or re.search(r'صفحة\s*(\d+)\s*من\s*(\d+)', t)
         or re.search(r'(?<![\d/])(\d{1,2})\s*/\s*(\d{1,2})(?![\d/])', t))
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if 1 <= a <= 99 and 1 <= b <= 99 and a <= b:
            page_index, page_count = a, b

    # ── document number ──
    # STRONGLY prefer the invoice/sales-order number anchored to its printed label.
    # The CUSTOMER CODE (كود العميل, e.g. 00010059) is constant on every page of a
    # distributor's stack, so picking it would wrongly MERGE all those pages into
    # one invoice — it must never become the doc_number.
    doc_number = ''
    for pat in (r'فاتور[ةه]\s*[:#/]?\s*(\d{5,13})',
                r'(?:أمر|امر)\s*البيع\s*[:#]?\s*(\d{5,13})',
                r'(?:مطالبة)\s*[:#]?\s*(\d{6,13})'):
        mm = re.search(pat, t, re.I)
        if mm:
            doc_number = mm.group(1)
            break
    if not doc_number:
        # mask out customer/licence/location codes, then take the longest remaining
        # digit run (the barcode/invoice number — unique per invoice), skipping
        # all-zero-prefixed codes like 00010059.
        masked = re.sub(r'(?<!\S)(?:كود|رخصة|العميل|المكان\w*|تسجيل|ملف)\s*[:#]?\s*\d+', ' ', t)
        runs = [r for r in re.findall(r'\d{8,14}', masked) if not r.startswith('0000')]
        if runs:
            doc_number = max(runs, key=len)

    # ── doc type ──
    doc_type = ''
    if 'اذن استلام' in t or 'إذن استلام' in t:
        doc_type = 'اذن استلام مسعر'
    elif 'فاتور' in t:
        doc_type = 'فاتورة'

    has_totals = any(k in t or k in low for k in _TOTALS_KW)
    has_header = bool(doc_number) or bool(doc_type)
    return {
        'doc_number': doc_number,
        'doc_type': doc_type,
        'page_index': page_index,
        'page_count': page_count,
        'has_totals': has_totals,
        'has_header': has_header,
    }


def _crop_bands(img):
    """Return (top_band, bottom_band) PIL crops where invoice identity/totals live."""
    w, h = img.size
    top = img.crop((0, 0, w, int(h * 0.28)))
    bottom = img.crop((0, int(h * 0.80), w, h))
    return top, bottom


def _usable(sig) -> bool:
    return bool(sig and (sig['page_index'] or sig['doc_number'] or sig['has_totals']))


def probe_page_header_local(img) -> dict | None:
    """
    FREE boundary probe. Two tiers, fastest first:
      1. RapidOCR on the top+bottom bands (~fast, strong on the numeric signals).
      2. Only if that anchors NOTHING, one EasyOCR/pytesseract pass (slow, Arabic)
         as a last resort — so a sparse band never drags the 50-page bundle into
         per-page EasyOCR time.
    Returns a probe dict, or None when no usable signal is found / no engine.
    """
    try:
        top, bottom = _crop_bands(img)
    except Exception as e:
        logger.warning('local page probe crop failed: %s', e)
        return None

    # ── tier 1: RapidOCR (fast) ──
    text = (_ocr_text_rapidocr(top) + '\n' + _ocr_text_rapidocr(bottom)).strip()
    sig = _parse_page_signals(text) if text else None
    if _usable(sig):
        sig['supplier_name'] = ''
        _refine_doc_number(img, sig)
        return sig

    # ── tier 2: Arabic free chain (slow) — only when RapidOCR found nothing ──
    text2 = (_ocr_text_free(top) + '\n' + _ocr_text_free(bottom)).strip()
    if text2:
        sig = _parse_page_signals(text2)
        if _usable(sig):
            sig['supplier_name'] = ''
            _refine_doc_number(img, sig)
            return sig
    return None


def _refine_doc_number(img, sig) -> None:
    """Upgrade ``sig['doc_number']`` via the dedicated number pass (docnumber.py)
    when the parsed number is MISSING or barcode-length (implausible). This is the
    fix for RapidOCR grabbing the 13–14 digit barcode instead of the printed
    invoice number, which caused page merges and the SofTech 'NOT FOUND' lookups.
    A clean printed read is left untouched (never downgraded, stays on fast path)."""
    try:
        from . import docnumber as dn
    except Exception:
        return
    cur = sig.get('doc_number') or ''
    if dn.plausible(cur):
        return
    try:
        res = dn.refine_doc_number(img, cur)
    except Exception as e:
        logger.debug('doc-number refinement skipped: %s', e)
        return
    num = res.get('number') or ''
    if num and num != cur and res.get('confidence', 0) >= 0.6:
        logger.info('doc number refined %r → %r (%s, conf %.2f)',
                    cur, num, res.get('source'), res.get('confidence'))
        sig['doc_number'] = num
        sig['has_header'] = True


def probe_page_header(img, extra_hints: str = '') -> dict | None:
    """
    Read only the boundary signals from a single PIL page image, shaped for
    splitter.group_pages (doc_number, page_index, page_count, date, doc_type,
    supplier_name, has_header, has_totals).

    Engine policy (sustainable — no mandatory paid dependency): try the FREE
    local probe first (EasyOCR/pytesseract on the header/footer bands); only if
    that finds no usable signal AND a Gemini key is configured, fall back to the
    richer Gemini JSON probe. Returns None when nothing is available.
    """
    local = probe_page_header_local(img)
    if local is not None:
        return local

    if not _gemini_keys():
        return None
    try:
        import io as _io
        from google.genai import types
    except ImportError:
        return None
    buf = _io.BytesIO()
    img.save(buf, format='JPEG', quality=85)
    img_bytes = buf.getvalue()
    cfg = types.GenerateContentConfig(temperature=0, response_mime_type='application/json')
    resp, _used = _gemini_generate([
        types.Part.from_bytes(data=img_bytes, mime_type='image/jpeg'),
        types.Part.from_text(text=_PAGE_PROBE_PROMPT + (extra_hints or '')),
    ], config=cfg)
    if resp is not None:
        data = _json_from_text(resp.text)
        if isinstance(data, dict):
            dn = str(data.get('doc_number') or '').strip()
            sn = str(data.get('supplier_name') or '').strip()
            return {
                'doc_number': dn,
                'doc_type': str(data.get('doc_type') or '').strip(),
                'page_index': data.get('page_index') or None,
                'page_count': data.get('page_count') or None,
                'date': str(data.get('date') or '').strip(),
                'supplier_name': sn,
                'has_header': bool(dn or sn),
                'has_totals': bool(data.get('has_totals')),
            }
    return None


def probe_pdf_pages(pdf_path: str, out_dir: str, extra_hints: str = '') -> tuple[list[str], list[dict]]:
    """
    Render every page of a PDF and probe each for boundary signals.
    Returns ``(page_image_paths, probes)`` where probes[i] carries ``page=i`` and
    is ready for splitter.group_pages. A page that cannot be probed still yields a
    minimal probe (page only) so it is never dropped from the bundle.
    """
    from PIL import Image
    from . import pdf as pdfmod
    paths = pdfmod.render_pages(pdf_path, out_dir)
    probes: list[dict] = []
    for i, p in enumerate(paths):
        pr = None
        try:
            with Image.open(p) as im:
                pr = probe_page_header(im, extra_hints)
        except Exception as e:
            logger.warning('probe failed for page %d of %s: %s', i + 1, pdf_path, e)
        if pr is None:
            pr = {'has_header': True, 'has_totals': True}  # neutral → one-per-page fallback
        pr['page'] = i
        probes.append(pr)
    return paths, probes


def extract_structured(image_path: str, extra_hints: str = '',
                       engine: str | None = None, vendor=None) -> dict | None:
    """
    Preferred extractor: return a structured dict
    ``{supplier_name, invoice_number, invoice_date, currency, declared_total, lines:[...]}``.
    The engine is pluggable (see apps/invoices/engines): "gemini" (hosted JSON) or
    "easyocr" (free local structured). For PDFs every page is extracted and the
    line lists merged. Returns ``None`` when nothing could be extracted.
    """
    from . import engines
    requested = (engine or '').strip().lower()

    if _is_pdf(image_path):
        images = _pdf_to_images(image_path)
        if not images:
            return None
        eng = engines.resolve_engine(engine)
        if eng != 'gemini':
            return _free_merge_images(images, eng, vendor)
        return _merge_page_extracts(images, extra_hints)

    try:
        from PIL import Image
        img = Image.open(image_path)
    except Exception as e:
        logger.warning('Cannot open image for structured OCR: %s', e)
        return None

    # 'auto' → free-first, escalate to Gemini only when the free result is weak.
    if requested in ('', 'auto'):
        free_eng = engines.best_free_engine()
        has_gem = bool(_gemini_key())
        if free_eng and has_gem:
            free = engines.free_structured_image(img, free_eng, vendor=vendor)
            if (engines.score_extraction(free) >= _escalate_threshold()
                    and engines.recall_ok(free) and engines.confidence_ok(free)
                    and engines.numbers_ok(free)):
                return free
            logger.info('free OCR weak (score/recall/handwriting/numbers) — escalating to Gemini (single image)')
            return _gemini_extract_json(img, extra_hints) or free
        if has_gem:
            return _gemini_extract_json(img, extra_hints)
        if free_eng:
            return engines.free_structured_image(img, free_eng, vendor=vendor)
        return None

    eng = engines.resolve_engine(engine)
    if eng != 'gemini':
        return engines.free_structured_image(img, eng, vendor=vendor)
    return _gemini_extract_json(img, extra_hints)


def _escalate_threshold() -> float:
    try:
        from django.conf import settings as dj
        return float(getattr(dj, 'INVOICE_OCR_ESCALATE_THRESHOLD', 0.6))
    except Exception:
        return 0.6


def _gemini_images(image_paths: list[str], extra_hints: str = '') -> dict | None:
    """Gemini structured extraction over a list of page image files (merged)."""
    from PIL import Image
    imgs = []
    for p in image_paths:
        try:
            imgs.append(Image.open(p))
        except Exception as e:
            logger.warning('cannot open page image %s: %s', p, e)
    if not imgs:
        return None
    try:
        return _merge_page_extracts(imgs, extra_hints)
    finally:
        for im in imgs:
            try:
                im.close()
            except Exception:
                pass


# ── Mistral vision OCR (paid API, key-gated) ─────────────────────────────────────
# A paid alternative to Gemini that never hits the free-tier daily cap. Returns the
# SAME JSON {lines:[...]} shape as the Gemini path, so parse_structured handles it
# identically. Active only when MISTRAL_API_KEY is set AND the mistralai SDK is
# installed; otherwise reports unavailable and the dispatch skips it.
def _mistral_key() -> str:
    try:
        from django.conf import settings as s
        return (getattr(s, 'MISTRAL_API_KEY', '') or '').strip()
    except Exception:
        return ''


def _mistral_model() -> str:
    try:
        from django.conf import settings as s
        return (getattr(s, 'MISTRAL_OCR_MODEL', '') or 'pixtral-12b-latest').strip()
    except Exception:
        return 'pixtral-12b-latest'


def _mistral_available() -> bool:
    if not _mistral_key():
        return False
    try:
        import mistralai  # noqa: F401
        return True
    except Exception:
        return False


def _mistral_images(image_paths: list[str], extra_hints: str = '') -> dict | None:
    """Structured OCR over an invoice's page images via Mistral's vision model."""
    key = _mistral_key()
    if not key:
        return None
    try:
        from mistralai import Mistral
    except ImportError:
        logger.warning('mistralai not installed — Mistral OCR unavailable')
        return None
    import base64
    import io as _io
    from PIL import Image
    content = []
    for p in image_paths:
        try:
            with Image.open(p) as im:
                buf = _io.BytesIO()
                im.convert('RGB').save(buf, format='JPEG', quality=92)
                b64 = base64.b64encode(buf.getvalue()).decode()
                content.append({'type': 'image_url',
                                'image_url': f'data:image/jpeg;base64,{b64}'})
        except Exception as e:
            logger.warning('mistral image load failed %s: %s', p, e)
    if not content:
        return None
    content.append({'type': 'text', 'text': _OCR_JSON_PROMPT + (extra_hints or '')})
    try:
        client = Mistral(api_key=key)
        model = _mistral_model()
        resp = client.chat.complete(
            model=model,
            messages=[{'role': 'user', 'content': content}],
            response_format={'type': 'json_object'},
            temperature=0)
        data = _json_from_text(resp.choices[0].message.content)
        if isinstance(data, dict) and data.get('lines'):
            logger.info('Structured OCR via Mistral/%s: %d line(s)', model, len(data['lines']))
            return data
    except Exception as e:
        logger.warning('Mistral OCR failed: %s', str(e)[:160])
    return None


# ── Generic self-hosted / OpenAI-compatible VLM OCR (PaddleOCR-VL, Qwen2.5-VL, …) ─
# Point settings.VLM_OCR_URL at any /v1/chat/completions server (vLLM, Ollama, HF
# TGI) running a vision model. Returns the same JSON {lines:[...]} as the other
# engines, so the pipeline is identical. Lets a GPU box serve a local Arabic VLM
# that this CPU box can't run in-process — the path to beating Gemini for free.
def _vlm_config():
    try:
        from django.conf import settings as s
        return ((getattr(s, 'VLM_OCR_URL', '') or '').strip(),
                (getattr(s, 'VLM_OCR_MODEL', '') or '').strip(),
                (getattr(s, 'VLM_OCR_KEY', '') or '').strip())
    except Exception:
        return '', '', ''


def _vlm_available() -> bool:
    """True only when VLM_OCR_URL is a real, well-formed http(s) endpoint — NOT an
    unfilled copy-paste placeholder like http://<gpu-box>:8000/... (that would make
    every call fail with a DNS error and silently zero out a run)."""
    url, _model, _key = _vlm_config()
    if not url:
        return False
    from urllib.parse import urlparse
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ('http', 'https') or not p.hostname:
        return False
    low = url.lower()
    if any(b in low for b in ('<', '>', 'gpu-box', 'your-', 'example.', 'host:port')):
        return False
    return True


def _vlm_images(image_paths: list[str], extra_hints: str = '') -> dict | None:
    """Structured OCR over an invoice's pages via a self-hosted OpenAI-compatible
    vision endpoint (settings.VLM_OCR_URL)."""
    url, model, key = _vlm_config()
    if not url:
        return None
    try:
        import requests
    except ImportError:
        logger.warning('requests not installed — VLM OCR unavailable')
        return None
    import base64
    import io as _io
    from PIL import Image
    content = []
    for p in image_paths:
        try:
            with Image.open(p) as im:
                buf = _io.BytesIO()
                im.convert('RGB').save(buf, format='JPEG', quality=92)
                b64 = base64.b64encode(buf.getvalue()).decode()
                content.append({'type': 'image_url',
                                'image_url': {'url': f'data:image/jpeg;base64,{b64}'}})
        except Exception as e:
            logger.warning('vlm image load failed %s: %s', p, e)
    if not content:
        return None
    content.append({'type': 'text', 'text': _OCR_JSON_PROMPT + (extra_hints or '')})
    payload = {'model': model or 'default',
               'messages': [{'role': 'user', 'content': content}],
               'temperature': 0,
               'response_format': {'type': 'json_object'}}
    headers = {'Content-Type': 'application/json'}
    if key:
        headers['Authorization'] = f'Bearer {key}'
    try:
        r = requests.post(url, json=payload, headers=headers,
                          timeout=_gemini_timeout_ms() / 1000.0)
        r.raise_for_status()
        text = r.json()['choices'][0]['message']['content']
        data = _json_from_text(text)
        if isinstance(data, dict) and data.get('lines'):
            logger.info('Structured OCR via VLM/%s: %d line(s)', model or url, len(data['lines']))
            return data
    except Exception as e:
        logger.warning('VLM OCR failed (%s): %s', url, str(e)[:160])
    return None


def extract_structured_images(image_paths: list[str], extra_hints: str = '',
                              engine: str | None = None, vendor=None) -> dict | None:
    """
    Structured extraction over an explicit, ordered list of page IMAGE files that
    make up ONE invoice (a segment the splitter produced).

    Engine: an explicit registered name (tesseract / paddleocr / easyocr / gemini /
    mistral) is honored. In 'auto' mode (default) we run the best FREE engine first
    and ONLY escalate — to each available API engine in turn (Gemini, then Mistral)
    — when the free result scores below INVOICE_OCR_ESCALATE_THRESHOLD, maximizing
    free extraction while keeping the paid APIs as an accuracy safety net.
    """
    from . import engines
    requested = (engine or '').strip().lower()

    # explicit, registered engine → run it directly (if it's actually usable)
    if requested and requested != 'auto':
        spec = engines.get_engine(requested)
        if spec is None:
            logger.warning('unknown OCR engine %r — falling back to auto', requested)
        elif not spec.available():
            logger.warning('engine %r is configured but NOT available (misconfigured '
                           'URL/key, or dependency missing) — falling back to auto', requested)
        else:
            return spec.run(image_paths, vendor, extra_hints)

    # auto: best FREE first, escalate to each available API engine when weak
    free_eng = engines.best_free_engine()
    api_specs = engines.available_api_specs()
    if free_eng:
        free = engines.free_structured_images(image_paths, free_eng, vendor=vendor)
        if (free and engines.score_extraction(free) >= _escalate_threshold()
                and engines.recall_ok(free) and engines.confidence_ok(free)
                and engines.numbers_ok(free)):
            return free
        for api in api_specs:
            logger.info('free OCR weak (score/recall/handwriting/numbers) — escalating to %s', api.name)
            esc = api.run(image_paths, vendor, extra_hints)
            if esc:
                return esc
        return free
    for api in api_specs:
        esc = api.run(image_paths, vendor, extra_hints)
        if esc:
            return esc
    return None


def _free_merge_images(images, engine, vendor=None) -> dict | None:
    """Free structured extraction over already-open PIL images (merged)."""
    from . import engines
    merged = None
    for img in images:
        data = engines.free_structured_image(img, engine, vendor=vendor)
        if not data:
            continue
        if merged is None:
            merged = data
        else:
            merged.setdefault('lines', []).extend(data.get('lines') or [])
    return merged


def _merge_page_extracts(images, extra_hints: str = '') -> dict | None:
    """Run structured extraction on each PIL image and merge into one invoice dict."""
    merged = None
    for img in images:
        data = _gemini_extract_json(img, extra_hints)
        if not data:
            continue
        if merged is None:
            merged = data
        else:
            merged.setdefault('lines', []).extend(data.get('lines') or [])
    return merged


def _is_junk_line(name: str, code: str, public: float, net: float) -> bool:
    """Drop a parsed 'line' that is clearly NOT a product — the main source of
    over-extraction (125 ours vs 81 posted). Conservative on purpose (requires
    multiple junk signals) so real lines with a missing price are never dropped:
      • a name that is purely a number/punctuation (a total/qty leaked into the
        name column) — never a real drug name; or
      • a totals/section/footer phrase (engines._NONITEM_KW) with NO item code AND
        no price at all (a header/footer fragment, not a priced product row)."""
    n = (name or '').strip()
    if re.fullmatch(r'[\d\s.,:/%\-]+', n):
        return True
    try:
        from . import engines
        norm = engines._norm_ar(n)
        if (not code) and public <= 0 and net <= 0 \
                and any(k and k in norm for k in engines._NONITEM_KW):
            return True
    except Exception:
        pass
    return False


def parse_structured(data: dict):
    """
    Convert a structured Gemini dict into ``(header, line_dicts)`` where each line
    dict has the SAME keys ``parse_lines`` produces (so the matching loop is
    identical) plus ``ocr_confidence`` and a normalized ``expiry_date``.
    """
    header = {
        'supplier_name':  (data.get('supplier_name') or '').strip(),
        'invoice_number': str(data.get('invoice_number') or '').strip(),
        'invoice_date':   (data.get('invoice_date') or '').strip(),
        'currency':       (data.get('currency') or 'EGP').strip() or 'EGP',
        'declared_total': _num(data.get('declared_total')),
    }

    lines = []
    for ln in (data.get('lines') or []):
        name = (ln.get('item_name') or '').strip(' -–:')
        if not name or len(name) < 2:
            continue
        code     = str(ln.get('vendor_item_code') or '').strip()
        public   = _num(ln.get('public_price'))
        disc     = _num(ln.get('discount_pct'))
        extra    = _num(ln.get('extra_discount_pct'))
        special  = _num(ln.get('special_discount_pct'))
        net      = _num(ln.get('pharmacist_price'))
        vat      = _num(ln.get('vat_pct'))
        pm       = _num(ln.get('pharmacist_margin_amt'))
        dm       = _num(ln.get('distributor_margin_amt'))
        qty      = _num(ln.get('quantity')) or 1.0
        line_total = _num(ln.get('line_total'))
        # ── the money columns can come back slid one/two places (discount ← total
        # or net); put them back before anything derives from them ──
        shifted, shift_notes = reconcile.repair_column_shift({
            'public_price': public, 'disc_pct': disc, 'extra_disc_pct': extra,
            'net': net, 'quantity': qty, 'vat_pct': vat,
            'pharmacist_margin': pm, 'distributor_margin': dm,
        })
        if shift_notes:
            disc, extra = shifted['disc_pct'], shifted['extra_disc_pct']
            net, vat = shifted['net'], shifted['vat_pct']
            line_total = line_total or shifted['line_total']
        if net == 0 and public > 0:
            # سعر صيدلي as the distributor prints it: (public − margins) × discounts
            net = reconcile.paper_net(public, (disc, extra, special), pm, dm, vat)
        if _is_junk_line(name, code, public, net):
            continue
        # ── deterministic arithmetic self-repair: fix a garbled net/qty from the
        # line's own redundant numbers (paper formula, total÷qty). Pure math;
        # repairs flagged in notes for the operator to glance at. ──
        fixed, rec_notes = reconcile.reconcile_numbers({
            'public_price': public, 'disc_pct': disc, 'extra_disc_pct': extra,
            'special_disc_pct': special, 'net': net, 'quantity': qty,
            'line_total': line_total, 'vat_pct': vat,
            'pharmacist_margin': pm, 'distributor_margin': dm,
        })
        rec_notes = shift_notes + rec_notes
        net, qty = _num(fixed.get('net')), _num(fixed.get('quantity')) or qty
        raw_exp  = str(ln.get('expiry_date') or '').strip()
        base_notes = '، '.join(rec_notes)
        lines.append(_clean_code_batch({
            'raw_text':               json.dumps(ln, ensure_ascii=False)[:500],
            'manual_name':            name,
            'generic_name_en':        (ln.get('generic_name_en') or '').strip(),
            'manufacturer':           (ln.get('manufacturer') or '').strip(),
            'vendor_item_code':       str(ln.get('vendor_item_code') or '').strip(),
            'batch_number':           str(ln.get('batch_number') or '').strip(),
            'expiry_date':            normalize_expiry(raw_exp) or raw_exp,
            'quantity':               qty,
            'bonus_qty':              _num(ln.get('bonus_qty')),
            'public_price':           public,
            'discount_pct':           disc,
            'extra_discount_pct':     extra,
            'special_discount_pct':   special,
            'unit_price':             net,
            'vat_pct':                vat,
            'distributor_margin_amt': dm,
            'pharmacist_margin_amt':  pm,
            'ocr_confidence':         _conf(ln.get('confidence')),
            'notes':                  base_notes,
            '_reconciled':            bool(rec_notes),
        }))
    return header, lines


def _num(v) -> float:
    if v is None or v == '':
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    return _to_float(str(v))


def _conf(v):
    try:
        c = float(v)
    except (TypeError, ValueError):
        return None
    return min(max(c, 0.0), 1.0)
