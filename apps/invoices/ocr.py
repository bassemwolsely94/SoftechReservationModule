"""
apps/invoices/ocr.py

OCR extraction for supplier invoice images.
Primary:   pytesseract (Tesseract 4+ with Arabic+English language packs)
Fallback:  easyocr (if installed)
Stub mode: if neither available, returns the raw image path as placeholder text.

Installation:
  pip install pytesseract pillow
  # Also install Tesseract binary: https://github.com/UB-Mannheim/tesseract/wiki
  # And add Arabic tessdata: ara.traineddata → C:/Program Files/Tesseract-OCR/tessdata/
"""
import logging
import re

logger = logging.getLogger('elrezeiky.invoices')


def extract_text(image_path: str) -> str:
    """
    Extract raw text from an invoice image.
    Returns empty string if OCR is unavailable.
    """
    # Try pytesseract first
    try:
        import pytesseract
        from PIL import Image
        img  = Image.open(image_path)
        text = pytesseract.image_to_string(img, lang='ara+eng', config='--psm 6')
        logger.info(f'OCR via pytesseract: {len(text)} chars extracted')
        return text
    except ImportError:
        logger.warning('pytesseract not installed')
    except Exception as e:
        logger.warning(f'pytesseract error: {e}')

    # Try easyocr
    try:
        import easyocr
        reader = easyocr.Reader(['ar', 'en'], gpu=False)
        result = reader.readtext(image_path, detail=0)
        text   = '\n'.join(result)
        logger.info(f'OCR via easyocr: {len(text)} chars extracted')
        return text
    except ImportError:
        logger.warning('easyocr not installed')
    except Exception as e:
        logger.warning(f'easyocr error: {e}')

    # Stub
    logger.warning('No OCR engine available — returning stub text')
    return ''


# ── Line parser ────────────────────────────────────────────────────────────────

_QTY_PRICE_RE = re.compile(
    r'(\d[\d,]*\.?\d*)\s*[xX×*]\s*(\d[\d,]*\.?\d*)'   # "qty x price"
    r'|(\d[\d,]*\.?\d*)\s+(\d[\d,]*\.?\d*)'            # "qty price" side by side
)


def parse_lines(raw_text: str) -> list:
    """
    Heuristically parse raw OCR text into candidate invoice lines.
    Returns list of dicts: { raw_text, quantity, unit_price }
    """
    lines   = [l.strip() for l in raw_text.splitlines() if l.strip()]
    results = []

    for line in lines:
        # Skip very short lines, header-like, or pure numbers
        if len(line) < 3:
            continue
        # Skip pure numeric lines (totals, page numbers)
        if re.fullmatch(r'[\d\s,.]+', line):
            continue

        qty   = 1.0
        price = 0.0
        m = _QTY_PRICE_RE.search(line)
        if m:
            if m.group(1):
                qty, price = float(m.group(1).replace(',', '')), float(m.group(2).replace(',', ''))
            elif m.group(3):
                qty, price = float(m.group(3).replace(',', '')), float(m.group(4).replace(',', ''))

        # Clean line: remove the matched numbers, keep the name
        name = _QTY_PRICE_RE.sub('', line).strip(' -–:')
        if not name:
            name = line

        results.append({
            'raw_text':   line,
            'manual_name': name,
            'quantity':   qty,
            'unit_price': price,
        })

    return results
