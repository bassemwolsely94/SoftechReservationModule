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

logger = logging.getLogger('elrezeiky.invoices')

# Gemini model fallback chain — shared by the text and structured-JSON extractors.
_GEMINI_MODELS = [
    'gemini-2.5-flash',
    'gemini-2.5-flash-preview-05-20',
    'gemini-2.0-flash',
    'gemini-flash-latest',
]

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
    '- vendor_item_code is the short alphanumeric code printed by the supplier (e.g. "6594", "AT24 0457")\n'
    '- ONE product per line, 13 fields separated by |\n'
    '- Keep Arabic product names exactly as written\n'
    '- Include dosage form & strength (e.g. "نيفيلوب 5 مجم قرص", "Novonorm 14")\n'
    '- Numbers only for numeric fields — no currency symbols, no % signs, no commas in numbers\n'
    '- Leave a field empty if not visible, but always keep all 13 | separators\n'
    '- Do NOT output section headers (e.g. "اصناف خاضعة للضريبة"), totals, or explanatory text\n'
    '- Output the pipe-separated product list ONLY\n\n'
    'Example output:\n'
    'ايفيروسبان 100 ملى شراب | ماركيول للصناع | 25 | 2442687 | 2442687 | 08.2027 | 55.00 | 25 | 5.066 | 36.18 | 14 | 126.65 | 0\n'
    'سبازمو-ديجستين 30 قرص | فاركو للادوية | 30 | 6594 | 6594 | 09.2027 | 78.00 | 25 | 0 | 54.00 | 0 | 0 | 0\n'
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
    try:
        from django.conf import settings as dj_settings
        gemini_key = getattr(dj_settings, 'GEMINI_API_KEY', '') or ''
    except Exception:
        gemini_key = ''

    if gemini_key:
        try:
            import io as _io
            from google import genai
            from google.genai import types
            buf       = _io.BytesIO()
            img.save(buf, format='JPEG', quality=92)
            img_bytes = buf.getvalue()
            client    = genai.Client(api_key=gemini_key)
            for model_name in _GEMINI_MODELS:
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=[
                            types.Part.from_bytes(data=img_bytes, mime_type='image/jpeg'),
                            types.Part.from_text(text=_OCR_INVOICE_PROMPT),
                        ],
                    )
                    text = response.text.strip()
                    logger.info(f'OCR via Gemini/{model_name} ({label}): {len(text)} chars')
                    return text
                except Exception as model_exc:
                    logger.warning(f'Gemini model {model_name} failed on {label}: {model_exc}')
                    continue
            logger.warning(f'All Gemini models exhausted for {label}')
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

            results.append({
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
            })

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
    ``2027-08``, ``08-27``, ``Aug 2027``, ``31/08/2027``. SOFTECH stores a real
    datetime (the captured purchase line used the **1st of the month** for a
    month/year expiry, e.g. ``2028-02-01``), so a month/year input → ``YYYY-MM-01``.
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
                return _iso(_yy(m.group(1)), mo, 1)

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

    # Month/year (2 numeric parts)
    if len(nums) == 2:
        a, b = nums[0], nums[1]
        if len(a) == 4 or (int(a) > 12 and len(b) <= 2):   # yyyy mm
            return _iso(_yy(a), _clamp_month(b), 1)
        return _iso(_yy(b), _clamp_month(a), 1)             # mm yyyy / mm yy

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
        import datetime
        return datetime.date(year, month, min(day, 28) if month == 2 else day).isoformat()
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
    '     "vendor_item_code": string,  // CRITICAL: the supplier product code (كود الصنف / كود المورد)\n'
    '                                  // printed on THIS row in the item-code column. It may be all DIGITS\n'
    '                                  // (e.g. "643352") OR ALPHANUMERIC — letters+digits, sometimes with\n'
    '                                  // a letter prefix (e.g. "AT240457", "DEG075", "OGE2100", "YD502").\n'
    '                                  // Capture the WHOLE token exactly incl. any letters; present on\n'
    '                                  // almost every row — never leave blank if a code is visible.\n'
    '                                  // NOT the barcode, batch/التشغيلة, price, or quantity.\n'
    '     "batch_number": string,      // رقم التشغيلة/الباتش\n'
    '     "expiry_date": string,       // as printed, e.g. "08.2027"\n'
    '     "quantity": number,\n'
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


def _gemini_extract_json(img) -> dict | None:
    """Run Gemini in JSON mode on a PIL image; return the parsed dict or None."""
    key = _gemini_key()
    if not key:
        return None
    try:
        import io as _io
        from google import genai
        from google.genai import types
    except ImportError:
        logger.warning('google-genai not installed — structured OCR unavailable')
        return None

    buf = _io.BytesIO()
    img.save(buf, format='JPEG', quality=92)
    img_bytes = buf.getvalue()
    client = genai.Client(api_key=key)
    cfg = types.GenerateContentConfig(temperature=0, response_mime_type='application/json')

    for model_name in _GEMINI_MODELS:
        try:
            resp = client.models.generate_content(
                model=model_name,
                contents=[
                    types.Part.from_bytes(data=img_bytes, mime_type='image/jpeg'),
                    types.Part.from_text(text=_OCR_JSON_PROMPT),
                ],
                config=cfg,
            )
            data = _json_from_text(resp.text)
            if isinstance(data, dict) and data.get('lines'):
                logger.info('Structured OCR via Gemini/%s: %d line(s)', model_name, len(data['lines']))
                return data
        except Exception as exc:
            logger.warning('Gemini JSON model %s failed: %s', model_name, exc)
            continue
    return None


def extract_structured(image_path: str) -> dict | None:
    """
    Preferred extractor: return a structured dict
    ``{supplier_name, invoice_number, invoice_date, currency, declared_total, lines:[...]}``
    using Gemini JSON mode. For PDFs every page is extracted and the line lists are
    merged (header taken from the first page that has one). Returns ``None`` when
    Gemini is unavailable or yields nothing — the caller then falls back to the
    text+``parse_lines`` heuristic.
    """
    if _is_pdf(image_path):
        images = _pdf_to_images(image_path)
        if not images:
            return None
        merged = None
        for img in images:
            data = _gemini_extract_json(img)
            if not data:
                continue
            if merged is None:
                merged = data
            else:
                merged.setdefault('lines', []).extend(data.get('lines') or [])
        return merged

    try:
        from PIL import Image
        img = Image.open(image_path)
    except Exception as e:
        logger.warning('Cannot open image for structured OCR: %s', e)
        return None
    return _gemini_extract_json(img)


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
        public   = _num(ln.get('public_price'))
        disc     = _num(ln.get('discount_pct'))
        extra    = _num(ln.get('extra_discount_pct'))
        net      = _num(ln.get('pharmacist_price'))
        if net == 0 and public > 0:
            net = round(public * (1 - disc / 100) * (1 - extra / 100), 4)
        raw_exp  = str(ln.get('expiry_date') or '').strip()
        lines.append({
            'raw_text':               json.dumps(ln, ensure_ascii=False)[:500],
            'manual_name':            name,
            'generic_name_en':        (ln.get('generic_name_en') or '').strip(),
            'manufacturer':           (ln.get('manufacturer') or '').strip(),
            'vendor_item_code':       str(ln.get('vendor_item_code') or '').strip(),
            'batch_number':           str(ln.get('batch_number') or '').strip(),
            'expiry_date':            normalize_expiry(raw_exp) or raw_exp,
            'quantity':               _num(ln.get('quantity')) or 1.0,
            'public_price':           public,
            'discount_pct':           disc,
            'extra_discount_pct':     extra,
            'unit_price':             net,
            'vat_pct':                _num(ln.get('vat_pct')),
            'distributor_margin_amt': _num(ln.get('distributor_margin_amt')),
            'pharmacist_margin_amt':  _num(ln.get('pharmacist_margin_amt')),
            'ocr_confidence':         _conf(ln.get('confidence')),
        })
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
