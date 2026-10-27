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
"""
import logging
import uuid

from django.conf import settings

logger = logging.getLogger('elrezeiky.errors')

DETAIL_ROLES = frozenset({'admin'})


def public_error(request, exc) -> str:
    ref = uuid.uuid4().hex[:8]
    logger.error('[ref %s] %s %s — %s: %s', ref, getattr(request, 'method', '?'),
                 getattr(request, 'path', '?'), type(exc).__name__, exc,
                 exc_info=(type(exc), exc, exc.__traceback__))
    profile = getattr(getattr(request, 'user', None), 'staff_profile', None)
    if settings.DEBUG or (profile is not None and profile.role in DETAIL_ROLES):
        return f'{str(exc)[:300]} (مرجع: {ref})'
    return f'خطأ داخلي (مرجع: {ref})'
