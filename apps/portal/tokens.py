"""
apps/portal/tokens.py

Signed tokens for the customer self-service portal.

Two token types, each with its OWN salt so they are not interchangeable, and
neither is a JWT (so the staff `JWTAuthentication` will reject a portal token,
and these helpers will reject a staff JWT):

  1. magic-link token — WhatsApp'd to the customer; very short-lived and good
                         for ONE login (its `n` names a PortalLogin row).
  2. session token     — issued after the magic-link is exchanged; the customer
                         presents it as `Authorization: Portal <token>`. Its `s`
                         names the same row, so the session ends when the row is
                         revoked (security Batch 6, W-5).

Both carry the customer's globally-unique `softech_pic`. The customer id is
never trusted from the client — every authenticated request re-resolves the
Customer through the PortalLogin row.
"""
from django.conf import settings
from django.core import signing

MAGIC_SALT   = 'portal-magic-link'
SESSION_SALT = 'portal-session'

# Lifetimes (seconds). Overridable via .env; safe short defaults.
MAGIC_LINK_TTL = int(getattr(settings, 'PORTAL_MAGIC_LINK_TTL', 900))      # 15 min
SESSION_TTL    = int(getattr(settings, 'PORTAL_SESSION_TTL', 12 * 3600))   # 12 h


def make_magic_token(softech_pic: str, nonce: str) -> str:
    """Sign a short-lived magic-link token for the given customer PIC and PortalLogin nonce."""
    return signing.dumps({'pic': softech_pic, 'k': 'magic', 'n': nonce}, salt=MAGIC_SALT)


def read_magic_token(token: str) -> tuple[str, str] | None:
    """(softech_pic, nonce) if the magic token is valid & unexpired, else None."""
    try:
        data = signing.loads(token, salt=MAGIC_SALT, max_age=MAGIC_LINK_TTL)
    except signing.BadSignature:
        return None
    if not isinstance(data, dict) or data.get('k') != 'magic' or not data.get('pic') or not data.get('n'):
        return None
    return data['pic'], data['n']


def make_session_token(softech_pic: str, session_key: str) -> str:
    """Sign a portal session token for the given customer PIC and PortalLogin session key."""
    return signing.dumps({'pic': softech_pic, 'k': 'session', 's': session_key}, salt=SESSION_SALT)


def read_session_token(token: str) -> tuple[str, str] | None:
    """(softech_pic, session_key) if the session token is valid & unexpired, else None."""
    try:
        data = signing.loads(token, salt=SESSION_SALT, max_age=SESSION_TTL)
    except signing.BadSignature:
        return None
    if not isinstance(data, dict) or data.get('k') != 'session' or not data.get('pic') or not data.get('s'):
        return None
    return data['pic'], data['s']
