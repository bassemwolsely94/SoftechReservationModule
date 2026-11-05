"""
Keep unexpected exception text out of API responses.

Views that catch a broad `Exception` used to echo it to the browser
(`f'فشل الترحيل: {e}'`). Driver/database/network errors carry SOFTECH hostnames,
SQL fragments, table and column names. `public_error(request, exc)` logs the full
exception with a short reference code and returns what the caller may see:

  • admin role, or DEBUG → the technical text (as before) + the reference
  • everyone else        → only "مرجع: <ref>" — IT finds the details in the log

Deliberate, user-facing domain errors (ValueError, *Error classes raised with an
Arabic message) are NOT routed through this — they are meant to be shown.

N4: a SOFTECH gate refusal (SoftechAccessDenied / SoftechZoneWriteDenied) carries fixed
Arabic copy and nothing technical — it is logged, then shown as is to everyone.
"""
import logging
import re
import traceback
import uuid

from django.conf import settings

from core.exceptions import is_softech_refusal

logger = logging.getLogger('elrezeiky.errors')

DETAIL_ROLES = frozenset({'admin'})

# Round 2, R4: driver / library errors can carry credentials (a connection URL with user=/password=,
# an API key in a query string, a bearer token). The admin detail and the log keep the error text
# but never these values.
_SECRET_PAIR = re.compile(r"""(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?token|token)\s*[=:]\s*[^\s&;,)\]'"]+""")
_BEARER = re.compile(r'(?i)\bbearer\s+[A-Za-z0-9._~+/-]+=*')
_JWT = re.compile(r'\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*')
_SECRET_SETTINGS = ('SYBASE_PASSWORD', 'SECRET_KEY', 'PG_PASSWORD', 'WHATSAPP_TOKEN', 'META_ACCESS_TOKEN',
                    'SMS_API_KEY', 'GEMINI_API_KEY', 'COUNSEL_PHONE_HASH_KEY')


def redact(text) -> str:
    """`text` with credentials masked: key=value pairs, bearer / JWT tokens and the values of the
    secret settings themselves."""
    out = str(text)
    for name in _SECRET_SETTINGS:
        value = str(getattr(settings, name, '') or '')
        if len(value) >= 6:
            out = out.replace(value, '***')
    out = _SECRET_PAIR.sub(lambda m: f'{m.group(1)}=***', out)
    out = _BEARER.sub('Bearer ***', out)
    return _JWT.sub('***', out)


def public_error(request, exc) -> str:
    ref = uuid.uuid4().hex[:8]
    if is_softech_refusal(exc):
        logger.warning('[ref %s] %s %s — SOFTECH refused (%s): %s', ref, getattr(request, 'method', '?'),
                       getattr(request, 'path', '?'), getattr(exc, 'reason', None) or type(exc).__name__, exc)
        return str(exc)
    tb = redact(''.join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    logger.error('[ref %s] %s %s — %s: %s\n%s', ref, getattr(request, 'method', '?'),
                 getattr(request, 'path', '?'), type(exc).__name__, redact(exc), tb)
    profile = getattr(getattr(request, 'user', None), 'staff_profile', None)
    if settings.DEBUG or (profile is not None and profile.role in DETAIL_ROLES):
        return f'{redact(exc)[:300]} (مرجع: {ref})'
    return f'خطأ داخلي (مرجع: {ref})'
