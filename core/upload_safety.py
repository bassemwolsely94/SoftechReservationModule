"""
core/upload_safety.py — upload rules.

W-8: every uploaded file is capped as it streams in (UploadSizeLimitHandler) and Excel / CSV imports
stop at MAX_IMPORT_ROWS (capped_rows).

W-7 — what may go into a PUBLIC media folder (security Batch 6).

`products/`, `image_candidates/` and `insurance/watermarks/` are served without a signed link, so a
file there must BE what it claims and carry a name we chose: the client's content type and file
extension are ignored. Images are decoded by Pillow; PDFs and videos are checked by their magic bytes.
"""
from __future__ import annotations

import io
import uuid

from django.core.exceptions import RequestDataTooBig, ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadhandler import FileUploadHandler

IMAGE_FORMATS = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp', 'GIF': 'gif'}


def _image_ext(data: bytes) -> str | None:
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = img.format
            img.verify()
    except Exception:
        return None
    return IMAGE_FORMATS.get(fmt)


def _video_ext(data: bytes) -> str | None:
    if data[4:8] == b'ftyp':
        return 'mp4'
    if data[:4] == b'\x1a\x45\xdf\xa3':
        return 'webm'
    return None


def detect(data: bytes, kind: str) -> str | None:
    """Safe extension for `data` as `kind` (image | pdf | manual | video), or None."""
    if kind == 'image':
        return _image_ext(data)
    if kind in ('pdf', 'manual'):
        return 'pdf' if data[:5] == b'%PDF-' else _image_ext(data) if kind == 'manual' else None
    if kind == 'video':
        return _video_ext(data)
    return None


# ── Every upload / import: size (security Batch 6, W-8) ─────────────────────────────────────

def max_upload_bytes() -> int:
    from django.conf import settings
    return int(getattr(settings, 'MAX_UPLOAD_FILE_SIZE', 25 * 1024 * 1024))


class UploadSizeLimitHandler(FileUploadHandler):
    """First in FILE_UPLOAD_HANDLERS: counts each file as it streams in and stops the request
    (400, nothing stored) once one passes MAX_UPLOAD_FILE_SIZE — before it reaches memory / disk."""

    def receive_data_chunk(self, raw_data, start):
        if start + len(raw_data) > max_upload_bytes():
            raise RequestDataTooBig(f'upload over MAX_UPLOAD_FILE_SIZE ({max_upload_bytes()} bytes)')
        return raw_data

    def file_complete(self, file_size):
        return None                     # the next handler builds the file


def capped_rows(rows):
    """Yield import rows, stopping with a clear ValueError past MAX_IMPORT_ROWS (header included)."""
    from django.conf import settings
    limit = int(getattr(settings, 'MAX_IMPORT_ROWS', 50_000))
    for n, row in enumerate(rows):
        if n >= limit:
            raise ValueError(f'الملف أكبر من الحد المسموح ({limit} صف) — قسّمه إلى ملفات أصغر')
        yield row


def public_upload(f, kind: str = 'image', prefix: str = '') -> ContentFile:
    """The upload as a ContentFile named `<prefix><random>.<detected ext>`; ValidationError if it
    is not a real file of that kind (or too large)."""
    if f.size and f.size > max_upload_bytes():
        raise ValidationError('الملف أكبر من المسموح')
    data = f.read()
    ext = detect(data, kind)
    if ext is None:
        raise ValidationError('نوع الملف غير مدعوم أو الملف تالف')
    return ContentFile(data, name=f'{prefix}{uuid.uuid4().hex[:12]}.{ext}')
