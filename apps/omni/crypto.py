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

Moving to OMNI_CREDENTIALS_KEY (go-live): rows written under the SECRET_KEY-derived key
still decrypt once the env key is set (MultiFernet tries the env key, then the derived
one), so the order "set the key, restart, then `manage.py omni_credentials --rekey
--apply`" never leaves a channel without its credentials. After the re-key every row is
under the env key alone, so it decrypts on a server with a different SECRET_KEY (the VPS).
"""
import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings


def env_key() -> str:
    return (getattr(settings, 'OMNI_CREDENTIALS_KEY', '') or '').strip()


def env_key_problem() -> str:
    """'' when OMNI_CREDENTIALS_KEY is empty or a valid Fernet key; else why not (never the value)."""
    key = env_key()
    if not key:
        return ''
    try:
        Fernet(key.encode())
    except (ValueError, TypeError):
        return 'it is not a Fernet key (44 characters of urlsafe base64)'
    return ''


def _derived_fernet() -> Fernet:
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _env_fernet() -> Fernet | None:
    key = env_key()
    return Fernet(key.encode()) if key else None


def _fernet():
    """Encrypts with the env key when set (else the derived key); decrypts with either."""
    primary = _env_fernet()
    if primary is None:
        return _derived_fernet()
    return MultiFernet([primary, _derived_fernet()])


def key_state(stored: dict) -> str:
    """How a stored credentials value reads: 'empty', 'plain' (legacy), 'env', 'derived' or 'unreadable'."""
    if not stored:
        return 'empty'
    token = stored.get('_enc')
    if not token:
        return 'plain'
    primary = _env_fernet()
    for state, f in (('env', primary), ('derived', _derived_fernet())):
        if f is None:
            continue
        try:
            f.decrypt(token.encode())
            return state
        except (InvalidToken, ValueError):
            pass
    return 'unreadable'


def rekey_credentials(stored: dict) -> dict:
    """Re-encrypt one stored value under the env key. Legacy plaintext gets encrypted too."""
    if _env_fernet() is None:
        raise ValueError('OMNI_CREDENTIALS_KEY is not set')
    token = (stored or {}).get('_enc')
    if not token:
        return encrypt_credentials(dict(stored or {}))
    return {'_enc': _fernet().rotate(token.encode()).decode()}


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
