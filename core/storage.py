"""
Signed, expiring URLs for uploaded files.

Uploads include prescriptions, insurance documents, payment proofs, HR receipts,
delivery photos, voice notes and chat attachments. They used to be served from
/media/ to anyone who knew (or guessed) the path. Now every FileField/ImageField
URL — in serializers, admin, templates, anywhere `.url` is called — carries an
HMAC signature and an expiry, and core.media.serve_media refuses the file without
a valid one. Nothing in the 29 upload fields or the React UI had to change: they
already render whatever `.url` returns.

Product imagery (products/, image_candidates/) and print assets
(insurance/watermarks/) stay public: they are stored as plain URLs in the DB,
shared on social/WhatsApp and shown on the customer portal.

Expiry is rounded up to the hour so a file keeps the same URL for at least an
hour (browser cache + no React re-render churn); MEDIA_URL_TTL sets the minimum
lifetime in seconds (default 6h).
"""
import hashlib
import hmac
import time
from urllib.parse import urlencode

from django.conf import settings
from django.core.files.storage import FileSystemStorage

PUBLIC_MEDIA_PREFIXES = ('products/', 'image_candidates/', 'insurance/watermarks/')


def is_public_media(name: str) -> bool:
    return name.replace('\\', '/').lstrip('/').startswith(PUBLIC_MEDIA_PREFIXES)


def _key() -> bytes:
    return hashlib.sha256(b'elrezeiky.media.' + settings.SECRET_KEY.encode()).digest()


def media_signature(name: str, expires: int) -> str:
    msg = f'{name}:{expires}'.encode()
    return hmac.new(_key(), msg, hashlib.sha256).hexdigest()[:32]


def sign_media_name(name: str, now: float | None = None) -> dict:
    ttl = int(getattr(settings, 'MEDIA_URL_TTL', 6 * 3600))
    now = time.time() if now is None else now
    expires = (int(now + ttl) // 3600 + 1) * 3600
    return {'exp': expires, 'sig': media_signature(name, expires)}


def verify_media_signature(name: str, exp, sig, now: float | None = None) -> bool:
    try:
        expires = int(exp)
    except (TypeError, ValueError):
        return False
    if expires < (time.time() if now is None else now):
        return False
    return hmac.compare_digest(media_signature(name, expires).encode(), str(sig or '').encode())


class SignedMediaStorage(FileSystemStorage):
    def url(self, name):
        base = super().url(name)
        if name is None or is_public_media(name):
            return base
        clean = name.replace('\\', '/').lstrip('/')
        return f'{base}?{urlencode(sign_media_name(clean))}'
