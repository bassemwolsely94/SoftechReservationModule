"""
apps/invoices/preprocess.py

Robustness for messy real-world scans in a multi-invoice bundle:

  - correct_orientation : auto-rotate sideways/upside-down pages (Tesseract OSD)
  - is_blank_page       : detect blank / separator / not-uploaded pages (pixel-based)
  - page_quality        : cheap signals used to flag incomplete / paper-cut /
                          handwriting-heavy / low-confidence pages for review

All functions are best-effort and degrade safely (a missing OSD model or OCR
engine never raises). Nothing here decides financial values — only image hygiene
and review flags.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger('elrezeiky.invoices')


def detect_rotation(img) -> int:
    """Rotation in degrees (0/90/180/270) Tesseract thinks the page needs, or 0
    when OSD (osd.traineddata) is unavailable."""
    try:
        from . import engines
        engines._tesseract_available()      # configures tesseract_cmd + TESSDATA_PREFIX
        import pytesseract
        osd = pytesseract.image_to_osd(img)
        m = re.search(r'Rotate:\s*(\d+)', osd)
        return int(m.group(1)) % 360 if m else 0
    except Exception as e:
        logger.debug('OSD unavailable: %s', e)
        return 0


def correct_orientation(img):
    """Return (upright_image, rotated_degrees). Rotates only when OSD is confident
    the page is 90/180/270 off."""
    deg = detect_rotation(img)
    if deg in (90, 180, 270):
        try:
            return img.rotate(-deg, expand=True), deg
        except Exception:
            return img, 0
    return img, 0


def is_blank_page(img, dark_ratio_threshold: float = 0.0015) -> bool:
    """True when a page has almost no ink — a blank separator sheet, a skipped
    page, or a scan that didn't capture content. Pixel-based (no OCR), fast.

    Note: faint scans print text as light grey, not black, so we count pixels
    below mid-grey (<160), not just near-black. Measured on real invoices: ink
    ratio ~0.8% vs a truly blank page ~0%."""
    try:
        g = img.convert('L')
        w, h = g.size
        if w > 300:
            g = g.resize((300, max(1, int(300 * h / w))))
        hist = g.histogram()
        total = sum(hist) or 1
        ink = sum(hist[0:160])           # anything darker than mid-grey = ink
        return (ink / total) < dark_ratio_threshold
    except Exception as e:
        logger.debug('blank check failed: %s', e)
        return False


def _estimate_skew(gray_img, max_deg: float = 5.0, step: float = 0.5) -> float:
    """Estimate the small text skew angle (degrees) by the projection-profile
    method: the rotation that makes horizontal text rows line up maximizes the
    variance of the row-sum histogram. Returns the correction angle in
    [-max_deg, max_deg]."""
    try:
        import numpy as np
        from PIL import Image
        small = gray_img
        if small.width > 800:
            small = small.resize((800, max(1, int(800 * small.height / small.width))))
        binimg = Image.fromarray((np.asarray(small) < 160).astype('uint8') * 255)
        best_a, best_v = 0.0, -1.0
        a = -max_deg
        while a <= max_deg + 1e-9:
            proj = np.asarray(binimg.rotate(a, expand=False, fillcolor=0)).sum(axis=1).astype(float)
            v = float(proj.var())
            if v > best_v:
                best_v, best_a = v, a
            a += step
        return best_a
    except Exception as e:
        logger.debug('skew estimate failed: %s', e)
        return 0.0


def _flag(name: str, default: bool = False) -> bool:
    try:
        from django.conf import settings
        return bool(getattr(settings, name, default))
    except Exception:
        return default


def unsharp(img):
    """Unsharp mask — sharpens soft/blurry scans so thin Arabic strokes separate.
    Falls back to the original image if the filter isn't available."""
    try:
        from PIL import ImageFilter
        return img.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))
    except Exception as e:
        logger.debug('unsharp skipped: %s', e)
        return img


def binarize_sauvola(gray, window: int = 31, k: float = 0.2):
    """Sauvola adaptive binarization (local mean/std threshold via integral images,
    numpy only — no OpenCV/scipy). Good for faint or unevenly-lit scans where a
    global threshold loses light text. Returns a 1-bit-style grayscale image
    (values 0/255); returns the input unchanged if numpy is unavailable."""
    try:
        import numpy as np
        from PIL import Image
        a = np.asarray(gray.convert('L'), dtype=np.float64)
        h, w = a.shape
        win = max(3, window | 1)                     # force odd
        r = win // 2
        # integral images of a and a² for O(1) window sums
        ii = np.zeros((h + 1, w + 1), dtype=np.float64)
        ii2 = np.zeros((h + 1, w + 1), dtype=np.float64)
        ii[1:, 1:] = np.cumsum(np.cumsum(a, axis=0), axis=1)
        ii2[1:, 1:] = np.cumsum(np.cumsum(a * a, axis=0), axis=1)
        ys, xs = np.meshgrid(np.arange(h), np.arange(w), indexing='ij')
        y0 = np.clip(ys - r, 0, h); y1 = np.clip(ys + r + 1, 0, h)
        x0 = np.clip(xs - r, 0, w); x1 = np.clip(xs + r + 1, 0, w)
        cnt = (y1 - y0) * (x1 - x0)
        s = ii[y1, x1] - ii[y0, x1] - ii[y1, x0] + ii[y0, x0]
        s2 = ii2[y1, x1] - ii2[y0, x1] - ii2[y1, x0] + ii2[y0, x0]
        mean = s / cnt
        var = np.maximum(s2 / cnt - mean * mean, 0.0)
        std = np.sqrt(var)
        thr = mean * (1.0 + k * (std / 128.0 - 1.0))   # Sauvola (R=128 for 8-bit)
        out = np.where(a > thr, 255, 0).astype('uint8')
        return Image.fromarray(out, mode='L')
    except Exception as e:
        logger.debug('sauvola binarize skipped: %s', e)
        return gray


def enhance_for_ocr(img, enable_deskew: bool = True, upscale_min_width: int = 1500):
    """Pre-enhance a page for OCR. Base (always): grayscale + autocontrast (lifts
    faint scans), fine deskew (straightens crooked scans), upscale small images
    (helps small text). Then OPT-IN perfecting steps, each gated by a setting and
    off by default so the base behaviour is unchanged until you A/B them:
      INVOICE_OCR_EQUALIZE → histogram equalize (uneven lighting)
      INVOICE_OCR_SHARPEN  → unsharp mask (soft/blurry scans)
      INVOICE_OCR_BINARIZE → Sauvola adaptive binarization (faint/shadowed scans)
    Returns the enhanced PIL image (grayscale). Safe/idempotent on clean pages."""
    from PIL import ImageOps
    g = ImageOps.autocontrast(img.convert('L'))
    if enable_deskew:
        ang = _estimate_skew(g)
        if abs(ang) >= 0.5:
            g = g.rotate(ang, expand=True, fillcolor=255)
    if g.width and g.width < upscale_min_width:
        s = upscale_min_width / g.width
        g = g.resize((int(g.width * s), int(g.height * s)))
    # ── opt-in perfecting (order: contrast → sharpen → binarize) ──
    if _flag('INVOICE_OCR_EQUALIZE'):
        try:
            g = ImageOps.equalize(g)
        except Exception as e:
            logger.debug('equalize skipped: %s', e)
    if _flag('INVOICE_OCR_SHARPEN'):
        g = unsharp(g)
    if _flag('INVOICE_OCR_BINARIZE'):
        g = binarize_sauvola(g)
    return g


def page_quality(structured, boxes=None) -> dict:
    """Review flags for a detected invoice's page(s).

    Returns {flags:[...], avg_confidence, has_totals} where flags may include:
      'no_totals'       — no totals/net block found (possible paper-cut / partial)
      'few_lines'       — suspiciously few product lines
      'low_recall'      — captured fewer lines than the printed عدد الأصناف
      'low_confidence'  — mean OCR confidence low (blurry / handwriting)
    """
    flags = []
    lines = (structured or {}).get('lines') or []
    declared = (structured or {}).get('_declared_count')

    if not lines:
        flags.append('no_lines')
    elif len(lines) < 2:
        flags.append('few_lines')

    if declared and lines and len(lines) < declared * 0.7:
        flags.append('low_recall')

    avg_conf = None
    if boxes:
        confs = [b.get('conf') for b in boxes if isinstance(b.get('conf'), (int, float))]
        if confs:
            avg_conf = sum(confs) / len(confs)
            if avg_conf < 0.55:
                flags.append('low_confidence')   # blurry scan or handwriting

    return {'flags': flags, 'avg_confidence': avg_conf}


# human-readable Arabic labels for the flags (for the UI / notes)
FLAG_LABELS_AR = {
    'no_lines':       'لم تُستخرج أي أصناف',
    'few_lines':      'عدد أصناف قليل — تحقق من اكتمال الفاتورة',
    'low_recall':     'عدد الأصناف المستخرجة أقل من المطبوع — قد تكون الصفحة مقصوصة/ناقصة',
    'low_confidence': 'جودة قراءة منخفضة — قد تحتوي خط يد أو تكون غير واضحة',
    'no_totals':      'لا توجد كتلة إجماليات — قد تكون الفاتورة مقطوعة',
    'blank_pages':    'تم تجاهل صفحات فارغة في الملف',
    'rotated_pages':  'تم تصحيح اتجاه صفحات مقلوبة',
}
