"""
apps/images/scorer.py

Image Quality & Product-Match Scoring Engine.

Scores produced for every image:

  quality_score    (0-1)  — intrinsic image quality
    - resolution
    - aspect ratio
    - white / light background
    - sharpness (Laplacian variance)
    - watermark penalty  ← NEW
    - file size

  confidence_score (0-1)  — product match likelihood
    - source type reliability
    - brand / strength / form in metadata

  watermark_score  (0-1)  — 0 = clean, 1 = definitely watermarked  ← NEW

  total_score = quality_score × 0.55 + confidence_score × 0.35 + clean_bonus × 0.10

Watermark Detection Strategy (zero external APIs):
  1. Corner text-density analysis — text-like high-contrast clusters in 4 corners
  2. Diagonal stripe detection — parallel high-contrast edges across the image
  3. Alpha-channel semi-transparency check (RGBA images)
  4. pytesseract corner OCR — optional, used if tesseract binary is available

Watermark Mitigation (auto-clean):
  If watermark_score > 0.45 and score is otherwise good, attempt:
  - Corner whiteout  — fill watermark corner region with its dominant bg colour
  - Luminance boost  — soften semi-transparent text overlays
  Returns a (possibly cleaned) image bytes alongside the score.
"""
from __future__ import annotations
import io
import logging
import re
import statistics
from typing import Optional

from PIL import Image, ImageFilter, ImageStat

logger = logging.getLogger('elrezeiky')

# ── Tuning ─────────────────────────────────────────────────────────────────────
MIN_DIM          = 150
PREFERRED_DIM    = 600
IDEAL_RATIO_LOW  = 0.75
IDEAL_RATIO_HIGH = 1.35
WHITE_THRESHOLD  = 228
MAX_FILE_BYTES   = 5_000_000

# Watermark thresholds
WM_CORNER_FRACTION   = 0.18   # analyse this fraction of each side as "corner"
WM_CONTRAST_THRESHOLD = 60    # local std dev above this = text-like
WM_CORNER_TEXT_LIMIT  = 0.12  # > 12 % text-like pixels in a corner → suspicious
WM_STRIPE_SCORE_LIMIT = 0.40  # FFT diagonal energy above this → diagonal watermark
WM_CLEAN_THRESHOLD    = 0.45  # above this watermark_score → attempt auto-clean

SOURCE_WEIGHTS = {
    'cache':         1.00,
    'openfoodfacts': 0.95,
    'openbeauty':    0.95,
    'drugs_com':     0.90,
    'rxlist':        0.85,
    'manufacturer':  0.90,
    'pharmacy_site': 0.80,
    'duckduckgo':    0.60,
    'bing':          0.55,
    'google':        0.55,
    'manual':        1.00,
    'ai_generated':  0.70,
}


# ── Public API ─────────────────────────────────────────────────────────────────

def score_image(
    image_bytes: bytes,
    source_type: str,
    brand: str = '',
    strength: str = '',
    dosage_form: str = '',
    metadata: Optional[dict] = None,
    auto_clean: bool = True,
) -> dict:
    """
    Score a downloaded image.

    Returns {
        quality_score, confidence_score, watermark_score, total_score,
        width, height, format, breakdown,
        cleaned_bytes,   # bytes if watermark was auto-cleaned, else None
        was_cleaned,     # bool
    }
    """
    metadata = metadata or {}

    try:
        img           = Image.open(io.BytesIO(image_bytes))
        fmt           = img.format or ''
        img_rgb       = img.convert('RGB')
        width, height = img_rgb.size
    except Exception as exc:
        logger.debug('PIL open failed: %s', exc)
        return _zero_score()

    breakdown: dict[str, float] = {}

    # ── 1. Resolution ──────────────────────────────────────────────────────────
    min_dim = min(width, height)
    if min_dim < MIN_DIM:
        return _zero_score()
    res_score = min(1.0, (min_dim - MIN_DIM) / (PREFERRED_DIM - MIN_DIM))
    breakdown['resolution'] = round(res_score, 3)

    # ── 2. Aspect ratio ────────────────────────────────────────────────────────
    ratio = height / width if width else 0
    if IDEAL_RATIO_LOW <= ratio <= IDEAL_RATIO_HIGH:
        ratio_score = 1.0
    else:
        deviation   = min(abs(ratio - IDEAL_RATIO_LOW), abs(ratio - IDEAL_RATIO_HIGH))
        ratio_score = max(0.0, 1.0 - deviation * 2)
    breakdown['aspect_ratio'] = round(ratio_score, 3)

    # ── 3. White background ────────────────────────────────────────────────────
    white_score = _score_white_background(img_rgb)
    breakdown['white_bg'] = round(white_score, 3)

    # ── 4. Sharpness ───────────────────────────────────────────────────────────
    sharp_score = _score_sharpness(img_rgb)
    breakdown['sharpness'] = round(sharp_score, 3)

    # ── 5. File size ───────────────────────────────────────────────────────────
    file_score = _score_file_size(len(image_bytes))
    breakdown['file_size'] = round(file_score, 3)

    # ── 6. Watermark detection ─────────────────────────────────────────────────
    wm_result     = detect_watermark(img_rgb, img)
    watermark_score = wm_result['watermark_score']
    breakdown['watermark'] = round(watermark_score, 3)
    breakdown.update({f'wm_{k}': round(v, 3) for k, v in wm_result['detail'].items()})

    # Penalty applied to quality: clean images get a bonus
    clean_bonus = max(0.0, 1.0 - watermark_score * 1.5)

    # ── Quality composite ──────────────────────────────────────────────────────
    quality_score = (
        res_score   * 0.28 +
        ratio_score * 0.14 +
        white_score * 0.23 +
        sharp_score * 0.18 +
        file_score  * 0.08 +
        clean_bonus * 0.09
    )

    # ── Confidence ─────────────────────────────────────────────────────────────
    source_weight    = SOURCE_WEIGHTS.get(source_type, 0.55)
    text_match       = _score_text_match(brand, strength, dosage_form, metadata)
    confidence_score = source_weight * 0.60 + text_match * 0.40
    breakdown['source_weight'] = round(source_weight, 3)
    breakdown['text_match']    = round(text_match, 3)

    # ── Total ──────────────────────────────────────────────────────────────────
    total_score = quality_score * 0.55 + confidence_score * 0.35 + clean_bonus * 0.10

    # ── Auto-clean watermark ───────────────────────────────────────────────────
    cleaned_bytes = None
    was_cleaned   = False
    if auto_clean and watermark_score > WM_CLEAN_THRESHOLD and quality_score > 0.3:
        cleaned_img = _clean_watermark(img_rgb, wm_result)
        if cleaned_img is not None:
            buf = io.BytesIO()
            cleaned_img.save(buf, format='JPEG', quality=88, optimize=True)
            cleaned_bytes = buf.getvalue()
            was_cleaned   = True
            # Recompute watermark score on the cleaned image to update total
            wm2           = detect_watermark(cleaned_img, cleaned_img)
            watermark_score = wm2['watermark_score']
            clean_bonus   = max(0.0, 1.0 - watermark_score * 1.5)
            total_score   = quality_score * 0.55 + confidence_score * 0.35 + clean_bonus * 0.10
            breakdown['watermark_after_clean'] = round(watermark_score, 3)

    return {
        'quality_score':    round(quality_score,    4),
        'confidence_score': round(confidence_score, 4),
        'watermark_score':  round(watermark_score,  4),
        'total_score':      round(min(total_score, 1.0), 4),
        'width':            width,
        'height':           height,
        'format':           fmt,
        'breakdown':        breakdown,
        'cleaned_bytes':    cleaned_bytes,
        'was_cleaned':      was_cleaned,
    }


# ── Watermark Detection ────────────────────────────────────────────────────────

def detect_watermark(img_rgb: Image.Image, img_orig: Image.Image) -> dict:
    """
    Multi-method watermark detection. Returns {watermark_score, detail}.
    watermark_score 0 = clean, 1 = definitely watermarked.
    """
    detail: dict[str, float] = {}
    scores: list[float]      = []

    # Method 1: Corner text-density analysis
    corner_score = _corner_text_density(img_rgb)
    detail['corner_text'] = corner_score
    scores.append(corner_score)

    # Method 2: Semi-transparent overlay (check original for alpha)
    alpha_score = _alpha_transparency_score(img_orig)
    detail['alpha_overlay'] = alpha_score
    scores.append(alpha_score * 0.7)   # lower weight

    # Method 3: Horizontal/vertical stripe pattern (repeated text rows)
    stripe_score = _stripe_pattern_score(img_rgb)
    detail['stripe_pattern'] = stripe_score
    scores.append(stripe_score)

    # Method 4: pytesseract corner OCR (optional — graceful fallback)
    ocr_score = _ocr_corner_score(img_rgb)
    if ocr_score is not None:
        detail['ocr_corners'] = ocr_score
        scores.append(ocr_score * 1.2)   # higher weight if available

    combined = min(1.0, statistics.mean(scores) if scores else 0.0)
    # Boost if multiple methods agree
    if sum(s > 0.5 for s in scores) >= 2:
        combined = min(1.0, combined * 1.3)

    return {'watermark_score': combined, 'detail': detail}


def _corner_text_density(img: Image.Image) -> float:
    """
    Analyse 4 corners for text-like high-contrast clusters.
    Returns 0-1 score.
    """
    w, h      = img.size
    cw        = max(30, int(w * WM_CORNER_FRACTION))
    ch        = max(30, int(h * WM_CORNER_FRACTION))
    gray      = img.convert('L')

    corners = [
        gray.crop((0,     0,     cw, ch)),          # top-left
        gray.crop((w-cw,  0,     w,  ch)),           # top-right
        gray.crop((0,     h-ch,  cw, h)),            # bottom-left
        gray.crop((w-cw,  h-ch,  w,  h)),            # bottom-right
    ]

    corner_scores = []
    for corner in corners:
        data = list(corner.getdata())
        if not data:
            continue
        # Local contrast: std dev of small 5×5 windows
        cw2, ch2 = corner.size
        high_contrast = 0
        total         = 0
        for y in range(0, ch2 - 5, 3):
            for x in range(0, cw2 - 5, 3):
                patch = []
                for dy in range(5):
                    for dx in range(5):
                        px = x + dx + (y + dy) * cw2
                        if px < len(data):
                            patch.append(data[px])
                if len(patch) > 4:
                    total += 1
                    if max(patch) - min(patch) > WM_CONTRAST_THRESHOLD:
                        high_contrast += 1
        if total > 0:
            corner_scores.append(high_contrast / total)

    if not corner_scores:
        return 0.0
    max_corner = max(corner_scores)
    # Watermarks rarely fill all 4 corners; 1 high corner is suspicious
    return min(1.0, max_corner / WM_CORNER_TEXT_LIMIT)


def _alpha_transparency_score(img: Image.Image) -> float:
    """
    Detect semi-transparent overlay pixels (common in digital watermarks).
    Only meaningful for RGBA/LA images.
    """
    if img.mode not in ('RGBA', 'LA'):
        return 0.0
    alpha_channel = list(img.split()[-1].getdata())
    if not alpha_channel:
        return 0.0
    # Semi-transparent: alpha in range [30, 200]
    semi = sum(1 for a in alpha_channel if 30 < a < 200)
    frac = semi / len(alpha_channel)
    # > 5 % semi-transparent pixels = suspicious
    return min(1.0, frac / 0.05)


def _stripe_pattern_score(img: Image.Image) -> float:
    """
    Detect repeating text rows (diagonal or horizontal watermark patterns)
    by analysing row-level variance signature.
    """
    thumb = img.copy()
    thumb.thumbnail((200, 200))
    gray  = thumb.convert('L')
    w, h  = gray.size

    row_variances = []
    for y in range(h):
        row = [gray.getpixel((x, y)) for x in range(w)]
        if len(row) > 1:
            row_variances.append(statistics.pvariance(row))

    if len(row_variances) < 10:
        return 0.0

    # Look for periodic peaks (text rows create high-variance stripes)
    peaks = [i for i in range(1, len(row_variances)-1)
             if row_variances[i] > row_variances[i-1]
             and row_variances[i] > row_variances[i+1]
             and row_variances[i] > statistics.mean(row_variances) * 2]

    # If peaks occur at regular intervals → repeating watermark text rows
    if len(peaks) < 3:
        return 0.0
    gaps       = [peaks[i+1] - peaks[i] for i in range(len(peaks)-1)]
    gap_std    = statistics.pstdev(gaps) if len(gaps) > 1 else float('inf')
    gap_mean   = statistics.mean(gaps) if gaps else 1
    regularity = 1.0 - min(1.0, gap_std / (gap_mean + 1))
    # Requires both regularity and enough peaks relative to image height
    density    = len(peaks) / h
    return min(1.0, regularity * density * 10)


def _ocr_corner_score(img: Image.Image) -> Optional[float]:
    """
    Use pytesseract to detect text in corner regions.
    Returns 0-1 if tesseract is available, None if not installed.
    """
    try:
        import pytesseract
        w, h  = img.size
        cw    = max(60, int(w * WM_CORNER_FRACTION * 1.5))
        ch    = max(60, int(h * WM_CORNER_FRACTION * 1.5))
        corners = [
            img.crop((0,    0,    cw, ch)),
            img.crop((w-cw, 0,    w,  ch)),
            img.crop((0,    h-ch, cw, h)),
            img.crop((w-cw, h-ch, w,  h)),
        ]
        total_chars = 0
        for corner in corners:
            text = pytesseract.image_to_string(
                corner.resize((corner.width * 2, corner.height * 2)),
                config='--psm 6 --oem 1',
            ).strip()
            total_chars += len(text)
        # > 5 characters detected in corners → likely watermark text
        return min(1.0, total_chars / 20)
    except Exception:
        return None


# ── Watermark Cleaning ────────────────────────────────────────────────────────

def _clean_watermark(img: Image.Image, wm_result: dict) -> Optional[Image.Image]:
    """
    Attempt to reduce visible watermark.

    Strategy:
      1. Identify which corner(s) have the highest watermark signal
      2. Fill those regions with the dominant background colour of that corner
         (works well for white/light-bg product images — most pharmacy images)
      3. Apply a mild Gaussian blur to the filled region to avoid hard edges

    Returns cleaned PIL Image or None if cleaning not feasible.
    """
    try:
        from PIL import ImageDraw, ImageFilter as IF

        result = img.copy()
        draw   = ImageDraw.Draw(result)
        w, h   = result.size
        cw     = max(40, int(w * WM_CORNER_FRACTION * 1.4))
        ch     = max(40, int(h * WM_CORNER_FRACTION * 1.4))

        gray   = img.convert('L')

        corner_boxes = [
            (0,    0,    cw,   ch),          # top-left
            (w-cw, 0,    w,    ch),           # top-right
            (0,    h-ch, cw,   h),            # bottom-left
            (w-cw, h-ch, w,    h),            # bottom-right
        ]

        for box in corner_boxes:
            corner_gray = gray.crop(box)
            data        = list(corner_gray.getdata())
            if not data:
                continue

            # High-contrast density in this corner
            hi_contrast = sum(
                1 for i in range(len(data))
                if i % corner_gray.width < corner_gray.width - 1
                and abs(int(data[i]) - int(data[min(i+1, len(data)-1)])) > WM_CONTRAST_THRESHOLD
            )
            text_pct = hi_contrast / len(data) if data else 0

            if text_pct > WM_CORNER_TEXT_LIMIT * 0.6:
                # Compute dominant background colour (use the surrounding outer border)
                corner_rgb = img.crop(box)
                border_pxs = []
                pixels     = corner_rgb.load()
                bx, by     = corner_rgb.size
                for x in range(bx):
                    border_pxs.append(pixels[x, 0])
                    border_pxs.append(pixels[x, by-1])
                for y in range(by):
                    border_pxs.append(pixels[0, y])
                    border_pxs.append(pixels[bx-1, y])

                if border_pxs:
                    avg_r = int(statistics.mean(p[0] for p in border_pxs))
                    avg_g = int(statistics.mean(p[1] for p in border_pxs))
                    avg_b = int(statistics.mean(p[2] for p in border_pxs))
                    fill  = (avg_r, avg_g, avg_b)
                else:
                    fill  = (255, 255, 255)   # default white

                draw.rectangle(box, fill=fill)

        # Soft blur on the filled areas to blend edges
        result = result.filter(IF.GaussianBlur(radius=2))
        # But we don't want to blur the whole image — composite: blur only where we drew
        mask        = Image.new('L', (w, h), 0)
        mask_draw   = ImageDraw.Draw(mask)
        for box in corner_boxes:
            mask_draw.rectangle(box, fill=200)
        mask        = mask.filter(IF.GaussianBlur(radius=6))
        blended     = Image.composite(result, img, mask)
        return blended

    except Exception as exc:
        logger.debug('Watermark clean failed: %s', exc)
        return None


# ── Standard helpers ───────────────────────────────────────────────────────────

def _zero_score() -> dict:
    return {
        'quality_score': 0.0, 'confidence_score': 0.0,
        'watermark_score': 0.0, 'total_score': 0.0,
        'width': 0, 'height': 0, 'format': '', 'breakdown': {},
        'cleaned_bytes': None, 'was_cleaned': False,
    }


def _score_white_background(img: Image.Image) -> float:
    w, h        = img.size
    border_size = max(5, min(w, h) // 20)
    border_px   = []
    pixels      = img.load()
    for x in range(w):
        for y in range(border_size):
            border_px.append(pixels[x, y])
            border_px.append(pixels[x, h - 1 - y])
    for y in range(h):
        for x in range(border_size):
            border_px.append(pixels[x, y])
            border_px.append(pixels[w - 1 - x, y])
    if not border_px:
        return 0.5
    light = sum(1 for r, g, b in border_px
                if r > WHITE_THRESHOLD and g > WHITE_THRESHOLD and b > WHITE_THRESHOLD)
    return light / len(border_px)


def _score_sharpness(img: Image.Image) -> float:
    try:
        thumb = img.copy()
        thumb.thumbnail((300, 300))
        gray  = thumb.convert('L')
        lap   = gray.filter(ImageFilter.Kernel(
            size=3, kernel=(-1, -1, -1, -1, 8, -1, -1, -1, -1), scale=1,
        ))
        variance = ImageStat.Stat(lap).var[0]
        return min(1.0, variance / 500.0)
    except Exception:
        return 0.5


def _score_file_size(size_bytes: int) -> float:
    if size_bytes < 5_000:
        return 0.0
    if size_bytes > MAX_FILE_BYTES:
        return 0.5
    if 20_000 <= size_bytes <= 500_000:
        return 1.0
    if size_bytes < 20_000:
        return 0.4 + 0.6 * (size_bytes / 20_000)
    return max(0.5, 1.0 - (size_bytes - 500_000) / MAX_FILE_BYTES)


def _score_text_match(brand: str, strength: str, form: str, metadata: dict) -> float:
    if not any([brand, strength, form]):
        return 0.5
    search_text = ' '.join(str(v) for v in metadata.values()).lower()
    score, checks = 0.0, 0
    if brand:
        checks += 1
        if brand.lower() in search_text:
            score += 1.0
    if strength:
        checks += 1
        num = re.sub(r'[^\d.]', '', strength)
        if num and num in search_text:
            score += 0.8
    if form:
        checks += 1
        if form.lower() in search_text:
            score += 0.6
    return (score / checks) if checks else 0.5


# ── Perceptual hash ────────────────────────────────────────────────────────────

def compute_phash(image_bytes: bytes) -> str:
    try:
        import imagehash
        img = Image.open(io.BytesIO(image_bytes))
        return str(imagehash.phash(img))
    except Exception as exc:
        logger.debug('pHash failed: %s', exc)
        return ''


def are_duplicates(phash1: str, phash2: str, threshold: int = 10) -> bool:
    if not phash1 or not phash2:
        return False
    try:
        import imagehash
        return (imagehash.hex_to_hash(phash1) - imagehash.hex_to_hash(phash2)) <= threshold
    except Exception:
        return False
