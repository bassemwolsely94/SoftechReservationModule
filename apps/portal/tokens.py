"""
apps/portal/tokens.py

Stateless, signed tokens for the customer self-service portal.

Two token types, each with its OWN salt so they are not interchangeable, and
neither is a JWT (so the staff `JWTAuthentication` will reject a portal token,
and these helpers will reject a staff JWT):

  1. magic-link token — emailed/WhatsApp'd to the customer; very short-lived.
  2. session token     — issued after the magic-link is exchanged; the customer
                         presents it as `Authorization: Portal <token>`.

Both encode ONLY the customer's globally-unique `softech_pic`. The customer id
is never trusted from the client — every authenticated request re-resolves the
Customer from the signed `pic` claim.
"""
from django.conf import settings
from django.core import signing

MAGIC_SALT   = 'portal-magic-link'
SESSION_SALT = 'portal-session'

# Lifetimes (seconds). Overridable via .env; safe short defaults.
MAGIC_LINK_TTL = int(getattr(settings, 'PORTAL_MAGIC_LINK_TTL', 900))      # 15 min
SESSION_TTL    = int(getattr(settings, 'PORTAL_SESSION_TTL', 12 * 3600))   # 12 h


def make_magic_token(softech_pic: str) -> str:
    """Sign a short-lived magic-link token for the given customer PIC."""
    return signing.dumps({'pic': softech_pic, 'k': 'magic'}, salt=MAGIC_SALT)


def read_magic_token(token: str) -> str | None:
    """Return the softech_pic if the magic token is valid & unexpired, else None."""
    try:
        data = signing.loads(token, salt=MAGIC_SALT, max_age=MAGIC_LINK_TTL)
    except signing.BadSignature:
        return None
    if not isinstance(data, dict) or data.get('k') != 'magic':
        return None
    return data.get('pic') or None


def make_session_token(softech_pic: str) -> str:
    """Sign a portal session token for the given customer PIC."""
    return signing.dumps({'pic': softech_pic, 'k': 'session'}, salt=SESSION_SALT)


def read_session_token(token: str) -> str | None:
    """Return the softech_pic if the session token is valid & unexpired, else None."""
    try:
        data = signing.loads(token, salt=SESSION_SALT, max_age=SESSION_TTL)
    except signing.BadSignature:
        return None
    if not isinstance(data, dict) or data.get('k') != 'session':
        return None
    return data.get('pic') or None
