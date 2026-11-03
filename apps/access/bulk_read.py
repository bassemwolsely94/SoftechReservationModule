"""
Bulk-read anomaly alert and temporary block (N5).

Per user and clock hour we count the rows read from the customer endpoints (BULK_READ_PATHS) and
the exports taken. The first crossing of a limit in an hour writes one `bulk_read_alert` AuditLog
row and one admin digest; in `enforce` a non-admin is also blocked from those endpoints and from
exports for BULK_READ_BLOCK_MINUTES. Counters live in the cache (a lost cache only forgets a
count). Nothing here raises out to the caller's request.
"""
import json
import logging

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .audit import write_access_audit

log = logging.getLogger('elrezeiky.access')

AUDIT_ACTION = 'bulk_read_alert'
TITLE = 'قراءة بيانات بكمية غير معتادة'
BLOCK_MESSAGE = 'تم إيقاف قراءة بيانات العملاء مؤقتاً بسبب كمية غير معتادة — تواصل مع الإدارة'
COUNTER_TTL = 2 * 3600
MODES = ('off', 'log', 'enforce')


def mode():
    """off / log / enforce. An unknown value is log (access.W004 warns about it)."""
    value = str(getattr(settings, 'BULK_READ_ENFORCEMENT', 'log') or 'log').lower()
    return value if value in MODES else 'log'


def paths():
    return tuple(getattr(settings, 'BULK_READ_PATHS', ('/api/customers/',)))


def is_bulk_path(path):
    return any((path or '').startswith(p) for p in paths())


def rows_in(response):
    """len(results) of a paginated DRF body, len() of a list body, else 0."""
    try:
        data = getattr(response, 'data', None)
        if data is None:
            if getattr(response, 'streaming', False):
                return 0
            if 'json' not in (response.get('Content-Type') or '').lower():
                return 0
            data = json.loads(response.content)
        if isinstance(data, dict):
            results = data.get('results')
            return len(results) if isinstance(results, (list, tuple)) else 0
        if isinstance(data, (list, tuple)):
            return len(data)
    except Exception:
        pass
    return 0


def _hour():
    return timezone.now().strftime('%Y%m%d%H')


def _key(user, kind):
    return f'access:bulk:{user.pk}:{_hour()}:{kind}'


def _limit(kind):
    name, default = (('BULK_READ_ROWS_PER_HOUR', 3000) if kind == 'rows'
                     else ('BULK_EXPORTS_PER_HOUR', 30))
    return int(getattr(settings, name, default))


def _add(user, kind, amount):
    """(before, after) of this hour's counter."""
    key = _key(user, kind)
    cache.add(key, 0, COUNTER_TTL)
    try:
        after = cache.incr(key, amount)
    except ValueError:
        cache.set(key, amount, COUNTER_TTL)
        after = amount
    return after - amount, after


def record(user, *, rows=0, export=False):
    """Add to this hour's counters. 'rows' / 'exports' when a limit is first crossed, else None."""
    crossed = None
    try:
        if rows > 0:
            before, after = _add(user, 'rows', rows)
            if before < _limit('rows') <= after:
                crossed = 'rows'
        if export:
            before, after = _add(user, 'exports', 1)
            if before < _limit('exports') <= after and crossed is None:
                crossed = 'exports'
    except Exception:
        log.warning('bulk read counter failed', exc_info=True)
    return crossed


def blocked(user):
    try:
        return bool(cache.get(f'access:bulkblock:{user.pk}'))
    except Exception:
        return False


def _role(user):
    from . import session_policy
    return getattr(session_policy.subject(user), 'role', None) or 'viewer'


def alert(user, kind, request):
    """Audit row + admin digest for a crossing; in enforce, block a non-admin."""
    try:
        access = getattr(request, 'access', None)
        network = getattr(access, 'network', None)
        label_ar = getattr(network, 'label_ar', '') or ''
        label_en = ('Outside the network' if getattr(network, 'zone', None) == 'external'
                    else 'Inside the network' if network is not None else '')
        role = _role(user)
        count = cache.get(_key(user, kind)) or 0
        limit = _limit(kind)
        current = mode()
        username = user.get_username()
        extra = {'kind': kind, 'count': count, 'limit': limit, 'role': role, 'username': username,
                 'path': getattr(request, 'path', None), 'mode': current,
                 'rows': cache.get(_key(user, 'rows')) or 0,
                 'exports': cache.get(_key(user, 'exports')) or 0}
        write_access_audit(AUDIT_ACTION, user.pk, f'{kind} {count}/{limit}'[:255], extra,
                           label='bulk read')
        what_ar, what_en = (('صفوف مقروءة', 'rows read') if kind == 'rows'
                            else ('ملفات تصدير', 'exports'))
        body = (f'المستخدم {username} (الدور: {role}) بلغ {count} من {what_ar} في ساعة واحدة '
                f'(الحد {limit}) — {label_ar}.\n'
                f'User {username} (role: {role}) reached {count} {what_en} in one hour '
                f'(limit {limit}) — {label_en}.')
        from .devices import admin_digest
        admin_digest(TITLE, body, f'bulk-read:{user.pk}:{_hour()}:{kind}')
        if current == 'enforce' and role != 'admin':
            minutes = int(getattr(settings, 'BULK_READ_BLOCK_MINUTES', 30))
            cache.set(f'access:bulkblock:{user.pk}', 1, minutes * 60)
    except Exception:
        log.error('bulk read alert failed', exc_info=True)
