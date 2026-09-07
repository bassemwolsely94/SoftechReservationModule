"""
apps/omni/crypto.py

Symmetric encryption for ChannelAccount provider credentials (doc 15 §2.6).

Key resolution:
  1. OMNI_CREDENTIALS_KEY env var (urlsafe-base64 32-byte Fernet key) — preferred;
     generate with:  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  2. Fallback: key derived from Django SECRET_KEY (SHA-256 → base64). Works out
     of the box, but rotating SECRET_KEY then invalidates stored credentials —
     set OMNI_CREDENTIALS_KEY in production.

Credentials are stored inside the existing JSONField as {"_enc": "<token>"} so
no schema change is needed and plaintext never reaches the database.
"""
import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet() -> Fernet:
    key = getattr(settings, 'OMNI_CREDENTIALS_KEY', '') or ''
    if not key:
        digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        key = base64.urlsafe_b64encode(digest).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_credentials(data: dict) -> dict:
    """dict → {"_enc": token}. Empty dict stays empty (nothing to protect)."""
    if not data:
        return {}
    token = _fernet().encrypt(json.dumps(data).encode()).decode()
    return {'_enc': token}


def decrypt_credentials(stored: dict) -> dict:
    """{"_enc": token} → dict. Tolerates legacy plaintext dicts and bad keys."""
    if not stored:
        return {}
    token = stored.get('_enc')
    if not token:
        # Legacy plaintext (pre-encryption rows) — return as-is
        return dict(stored)
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except (InvalidToken, ValueError):
        return {}
