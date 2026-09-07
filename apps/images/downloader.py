"""
apps/images/downloader.py

Downloads candidate images, validates content-type, strips EXIF,
and saves to MEDIA_ROOT/image_candidates/.

All bandwidth/compute costs live here.
No external API calls — pure HTTP download + Pillow processing.
"""
from __future__ import annotations
import io
import logging
import os
import urllib.request
from typing import Optional

from django.core.files.base import ContentFile

logger = logging.getLogger('elrezeiky')

_UA      = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/124.0.0.0 Safari/537.36'
)
_TIMEOUT = 20           # seconds
_MAX_DOWNLOAD_BYTES = 8_000_000   # 8 MB safety cap

VALID_CONTENT_TYPES = {
    'image/jpeg': 'jpg',
    'image/jpg':  'jpg',
    'image/png':  'png',
    'image/webp': 'webp',
    'image/gif':  'gif',
    'image/bmp':  'bmp',
}


def download_image(url: str) -> Optional[tuple[bytes, str]]:
    """
    Download image at URL.
    Returns (raw_bytes, extension) or None on any failure.
    Extension derived from Content-Type header.
    """
    try:
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent':  _UA,
                'Accept':      'image/webp,image/apng,image/*,*/*;q=0.8',
                'Referer':     'https://www.google.com/',
            },
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            content_type = resp.headers.get('Content-Type', '').split(';')[0].strip().lower()
            ext          = VALID_CONTENT_TYPES.get(content_type, '')
            if not ext:
                # Fallback: guess from URL
                url_lower = url.lower().split('?')[0]
                for e in ['jpg', 'jpeg', 'png', 'webp', 'gif']:
                    if url_lower.endswith('.' + e):
                        ext = 'jpg' if e == 'jpeg' else e
                        break
                if not ext:
                    logger.debug('Unsupported content-type %s for %s', content_type, url)
                    return None

            data = b''
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                data += chunk
                if len(data) > _MAX_DOWNLOAD_BYTES:
                    logger.debug('Image too large at %s', url)
                    return None

    except Exception as exc:
        logger.debug('Download failed for %s: %s', url, exc)
        return None

    if len(data) < 1000:   # < 1 KB — almost certainly an error page
        return None

    return data, ext


def strip_exif_and_normalise(image_bytes: bytes, ext: str) -> Optional[bytes]:
    """
    Strip EXIF metadata (privacy) and re-encode as JPEG for consistency.
    Returns clean JPEG bytes, or None on failure.
    """
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(image_bytes))
        # Convert non-RGB modes (RGBA, P, L, …) to RGB
        if img.mode not in ('RGB',):
            img = img.convert('RGB')

        # Resize if outrageously large (> 2000px on longest side)
        max_side = 2000
        if max(img.size) > max_side:
            img.thumbnail((max_side, max_side), Image.LANCZOS)

        # Save without EXIF
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=88, optimize=True)
        return buf.getvalue()
    except Exception as exc:
        logger.debug('Image processing failed: %s', exc)
        return None


def make_content_file(image_bytes: bytes, softech_id: str, suffix: str = '') -> ContentFile:
    """Wrap bytes into Django ContentFile with a deterministic filename."""
    filename = f'{softech_id}{suffix}.jpg'
    return ContentFile(image_bytes, name=filename)
