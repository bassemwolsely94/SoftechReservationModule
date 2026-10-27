"""
apps/invoices/docnumber.py

Recover the PRINTED invoice / sales-order number from a scanned supplier page.

WHY THIS EXISTS
---------------
The page-boundary parser (``ocr._parse_page_signals``) reads whole-page RapidOCR
text, and RapidOCR's default models do NOT read Arabic. So when the "فاتورة
<number>" label is only in Arabic, the parser can't anchor on it and falls back to
"longest digit run" — which grabs the 1-D BARCODE (13–14 digits) instead of the
printed 10–11 digit invoice number. A barcode-length number then either MERGES
pages that share it or fails the SofTech lookup entirely. In the HQ benchmark these
showed up as the "NOT FOUND" invoices: 13260608845574, 1826060926554, 18260608355151…

THE FIX
-------
Two FREE, local signals refine the number, reconciled by a pure consensus:

  1. ``region_number`` — a high-DPI Arabic re-read of JUST the number zone (top
     band) via Tesseract ara+eng + the shared signal parser, so the "فاتورة <n>" /
     "أمر البيع <n>" anchors apply and we recover the label-printed number.
  2. ``decode_barcode`` — the 1-D barcode (zxing-cpp, OPTIONAL) ENCODES the same
     number, usually as [marker][invoice-number][check-digit]; it CONFIRMS a read
     or, when itself invoice-length, supplies one.

``best_number`` is pure and fully unit-tested. The image helpers degrade
gracefully when a library (zxing-cpp / Tesseract) is absent, and the refinement is
applied ONLY when the parsed number is missing or barcode-length — a clean printed
read is kept untouched (no regression, and the hi-DPI pass stays off the fast path).
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# A printed Egyptian pharmacy invoice / sales-order number is an 8–11 digit run
# (Ramco 1826060943 / 18260609255, PharmaOverseas 8822632985). 12+ digits means a
# barcode digit has leaked in, or we're reading the barcode itself (marker + number
# + check digit) — must be reduced/re-read, never trusted as-is.
_MIN_LEN, _MAX_LEN = 8, 11


def _digits(s) -> str:
    return re.sub(r'\D', '', str(s or ''))


def plausible(num) -> bool:
    """True when ``num`` looks like a printed invoice/SO number — not a barcode,
    not a zero-padded customer/licence code."""
    n = _digits(num)
    # a leading zero marks a zero-padded customer/licence code (e.g. 00010059),
    # never a printed invoice/SO number (Ramco 1826…, PharmaOverseas 8822…).
    return _MIN_LEN <= len(n) <= _MAX_LEN and not n.startswith('0')


def number_from_barcode(code, hint: str = '') -> str:
    """Reduce a decoded 1-D barcode to the embedded invoice number.

    - If a ``hint`` (a text/region read) is given and the barcode CONTAINS it, the
      barcode confirms the hint → return the hint.
    - Else if the raw barcode is itself invoice-length, return it.
    - Otherwise DON'T guess (stripping an unknown marker/check digit from a bare
      barcode is ambiguous and a confident-wrong number is worse than none) → ''.
    """
    raw = _digits(code)
    h = _digits(hint)
    if h and h in raw:
        return h
    if plausible(raw):
        return raw
    return ''


def number_in_barcode(text: str, barcode: str) -> str:
    """The longest PLAUSIBLE prefix of the text read that also appears in the
    barcode. This recovers the printed number when a trailing barcode check digit
    leaked into the whole-page read (e.g. text '182606077093', barcode
    '9118260607707' → '1826060770'). The text supplies the correct leading digits;
    the barcode validates where the real number ends. '' when nothing matches —
    which is the right answer, since a bare barcode can't be reduced unambiguously.
    """
    t = _digits(text)
    bc = _digits(barcode)
    if not t or not bc:
        return ''
    for length in range(min(len(t), _MAX_LEN), _MIN_LEN - 1, -1):
        pref = t[:length]
        if plausible(pref) and pref in bc:
            return pref
    return ''


def _lcs_len(a: str, b: str) -> int:
    """Length of the longest common CONTIGUOUS digit run of two strings."""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def consistent(a, b) -> bool:
    """True when two reads plausibly describe the SAME printed number — one
    contains the other, or they share a long (≥7) contiguous digit run. Guards the
    region read from REPLACING a value with an unrelated misread: region
    '720060884' vs text '13260608845574' shares only 6 digits → rejected, so the
    original (which the SofTech resolver can still try to truncate) is kept."""
    a, b = _digits(a), _digits(b)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    return _lcs_len(a, b) >= 7


def best_number(text_number: str = '', region_number: str = '',
                barcode: str = '') -> tuple[str, str, float]:
    """PURE consensus over the three reads. Returns (number, source, confidence).

    Priority is built around the one failure we're fixing — the parser grabbing the
    13–14 digit barcode:
      * a plausible printed TEXT read is kept (no regression), boosted if the
        barcode confirms it;
      * if the text is missing or barcode-length (implausible), the high-DPI Arabic
        REGION read recovers the printed number;
      * then a confirmed / invoice-length BARCODE;
      * else best-effort at low confidence (never worse than before).
    """
    t = _digits(text_number)
    r = _digits(region_number)
    bc = _digits(barcode)
    anchored = number_in_barcode(t, bc)        # barcode-validated text prefix
    bc_num = number_from_barcode(bc, hint=(r or t))

    def confirmed(n: str) -> bool:
        return bool(n and bc and (n in bc or n == bc_num))

    # already-clean printed read — keep it (no regression), boost if barcode agrees
    if plausible(t):
        return (t, 'text+barcode', 0.92) if confirmed(t) else (t, 'text', 0.70)
    # text implausible (a barcode digit leaked, or it IS the barcode): the most
    # reliable recovery is the longest clean text-prefix the barcode validates.
    if plausible(anchored):
        return anchored, 'text+barcode', 0.90
    # no barcode to anchor with → the high-DPI Arabic region read, but only when it
    # is CONSISTENT with the original read (else it's an unrelated misread — keep
    # the original so the SofTech resolver can still truncate it).
    if plausible(r) and (not t or consistent(r, t)):
        return (r, 'region+barcode', 0.95) if confirmed(r) else (r, 'region', 0.80)
    if plausible(bc_num):
        return bc_num, 'barcode', 0.65
    best = t or r or bc
    src = 'text' if t else 'region' if r else 'barcode' if bc else ''
    return best, src, 0.20


# ── image-dependent, best-effort helpers (degrade gracefully) ────────────────────

def decode_barcode(img) -> str:
    """Digits of the first readable 1-D barcode on the page via zxing-cpp.
    '' when zxing-cpp is absent, nothing decodes, or an error occurs."""
    try:
        import zxingcpp
    except Exception:
        return ''
    results = None
    try:
        results = zxingcpp.read_barcodes(img)
    except Exception:
        try:
            import numpy as np
            results = zxingcpp.read_barcodes(np.array(img.convert('RGB')))
        except Exception as e:
            logger.debug('barcode decode failed: %s', e)
            return ''
    for b in results or []:
        d = _digits(getattr(b, 'text', ''))
        if len(d) >= _MIN_LEN:
            return d
    return ''


def region_number(img) -> str:
    """High-DPI Arabic re-read of the number zone (top band) → the label-anchored
    printed number. Reuses Tesseract + the shared ``_parse_page_signals`` so the
    "فاتورة <n>" / "أمر البيع <n>" anchors do the work. '' if Tesseract is
    unavailable or nothing anchors."""
    from . import engines, ocr  # lazy: avoids an import cycle with ocr
    if not engines._tesseract_available():
        return ''
    try:
        from PIL import Image
        w, h = img.size
        crop = img.crop((0, 0, w, int(h * 0.30)))
        crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
        import pytesseract
        text = pytesseract.image_to_string(crop, lang='ara+eng', config='--psm 6 --oem 1')
    except Exception as e:
        logger.debug('region-number OCR failed: %s', e)
        return ''
    try:
        sig = ocr._parse_page_signals(text)
    except Exception:
        return ''
    return sig.get('doc_number') or ''


def refine_doc_number(img, text_number: str = '') -> dict:
    """Best-effort refinement of a page's doc number from the image.

    Pays for the (slightly costly) high-DPI Arabic pass ONLY when ``text_number`` is
    missing or barcode-length — a clean printed read is kept, so good pages stay on
    the fast path. Returns {number, source, confidence, candidates:{text,region,barcode}}.
    """
    text_n = _digits(text_number)
    bc = decode_barcode(img)
    region = ''
    if not plausible(text_n):
        # try the cheap barcode anchor first; only pay for the high-DPI Arabic pass
        # when the barcode can't validate a clean number (e.g. it didn't decode).
        anchored = number_in_barcode(text_n, bc) or number_from_barcode(bc, hint=text_n)
        if not plausible(anchored):
            region = region_number(img)
    num, source, conf = best_number(text_n, region, bc)
    return {
        'number': num,
        'source': source,
        'confidence': conf,
        'candidates': {'text': text_n, 'region': _digits(region), 'barcode': bc},
    }
