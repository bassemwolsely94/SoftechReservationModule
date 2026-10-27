"""
Image preprocessing for OCR — lifts accuracy on handwritten / photographed
pharmacy lists before they reach any OCR engine (Gemini vision, EasyOCR,
pytesseract).

Dependency-light: uses OpenCV + NumPy, which are already installed (EasyOCR
pulls them in). Every step degrades gracefully — on any failure the original
image is returned unchanged, so preprocessing can never break an OCR request.

Two profiles:
  • binarize=False (default) — deskew + CLAHE contrast + denoise + upscale, kept
    as a natural grayscale-on-RGB image. Best for VISION LLMs (Gemini/Claude)
    and EasyOCR, which read handwriting better from a clean natural image than
    from a harsh black-and-white threshold.
  • binarize=True — adds adaptive thresholding to a crisp bi-tonal image. Best
    for classical engines (pytesseract) on printed text.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def preprocess_for_ocr(image, *, binarize: bool = False, deskew: bool = True,
                       max_dim: int = 2000):
    """Return a cleaned PIL.Image ready for OCR. ``image`` is a PIL.Image.

    Never raises — returns the input image if anything goes wrong."""
    try:
        import cv2
        import numpy as np
        from PIL import Image
    except Exception:  # pragma: no cover - deps guaranteed in this env
        return image

    try:
        rgb = image.convert('RGB')
        arr = np.array(rgb)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

        # 1. Deskew (correct small camera/scan rotations only) ─────────────────
        if deskew:
            gray = _deskew(cv2, np, gray)

        # 2. CLAHE local contrast — rescues faint pencil / uneven lighting ─────
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)

        # 3. Edge-preserving denoise (bilateral keeps thin strokes) ────────────
        gray = cv2.bilateralFilter(gray, d=5, sigmaColor=40, sigmaSpace=40)

        # 4. Upscale small images (OCR accuracy climbs with resolution) ────────
        h, w = gray.shape
        longest = max(h, w)
        if longest < max_dim:
            scale = min(2.0, max_dim / longest)
            gray = cv2.resize(gray, (int(w * scale), int(h * scale)),
                              interpolation=cv2.INTER_CUBIC)

        # 5. Optional binarization for classical OCR ──────────────────────────
        if binarize:
            gray = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, blockSize=31, C=15)

        return Image.fromarray(gray).convert('RGB')
    except Exception as exc:
        logger.warning('preprocess_for_ocr failed (%s) — using original image', exc)
        return image


def _deskew(cv2, np, gray):
    """Estimate text skew and rotate upright. Corrects only small angles
    (0.5°–20°) so we never mangle an already-straight or oddly-cropped image."""
    try:
        inv = cv2.bitwise_not(gray)
        thr = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
        coords = np.column_stack(np.where(thr > 0))
        if len(coords) < 50:
            return gray
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = 90 + angle
        if abs(angle) < 0.5 or abs(angle) > 20:
            return gray
        h, w = gray.shape
        M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
        return cv2.warpAffine(gray, M, (w, h),
                              flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    except Exception:
        return gray
