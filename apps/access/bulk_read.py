"""
Bulk-read anomaly alert and temporary block (N5).

Per user and clock hour we count the rows read from the customer endpoints (BULK_READ_PATHS) and
the exports taken. Only list bodies count (a page of `results` / `rows`, or a bare list), plus the
plain customer detail `/api/customers/<id>/` as one row; other dict bodies (Customer-360 parts,
stats) count nothing. The POS sale lookups (POS_FLOW_SEGMENTS) are never counted and never
blocked: refusing customer recognition in the middle of a sale is a POS-flow change. The first crossing of a limit in an hour writes one `bulk_read_alert` AuditLog
row and one admin digest; in `enforce` a non-admin is also blocked from those endpoints and from
exports for BULK_READ_BLOCK_MINUTES. Counters live in the cache (a lost cache only forgets a
count). Nothing here raises out to the caller's request.
"""
import json
import re
from datetime import timedelta
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


DEFAULT_PATHS = ('/api/customers/', '/api/pic-analytics/')

# Customer GETs the POS sale itself makes (apps/customers/views.py CustomerViewSet actions used by
# the cashier screen, POSCustomerModal and the call pop-up): recognise-on-type, the new-customer
# address autocomplete, the POS side-drawer summary, the repeat-order proposal and the digital
# receipt. Last path segment; never counted, never blocked (final review I3).
POS_FLOW_SEGMENTS = frozenset({'recognize', 'address-suggest', 'pos-summary', 'repeat-order',
                               'receipt'})

# the plain customer detail: one record (enumerating ids one by one still adds up)
_CUSTOMER_DETAIL = re.compile(r'^/api/customers/\d+/?$')

# the list keys of a dict body: DRF pagination (`results`) and the PIC Analytics lists (`rows`)
_LIST_KEYS = ('results', 'rows')


def paths():
    return tuple(getattr(settings, 'BULK_READ_PATHS', DEFAULT_PATHS))


def is_pos_flow(path):
    """True for a POS sale lookup under /api/customers/ (POS_FLOW_SEGMENTS)."""
    path = path or ''
    if not path.startswith('/api/customers/'):
        return False
    segments = [s for s in path.split('/') if s]
    return bool(segments) and segments[-1] in POS_FLOW_SEGMENTS


def is_bulk_path(path):
    """A counted (and, in enforce, blockable) read path: under BULK_READ_PATHS, not a POS lookup."""
    return any((path or '').startswith(p) for p in paths()) and not is_pos_flow(path)


def rows_in(response, path=None):
    """len() of a list body (a paginated `results`, a `rows` list, a bare list); 1 for the plain
    customer detail `/api/customers/<id>/`; 0 for any other body. Without `path` a non-list
    dict body counts 0."""
    try:
        data = getattr(response, 'data', None)
        if data is None:
            if getattr(response, 'streaming', False):
                return 0
            if 'json' not in (response.get('Content-Type') or '').lower():
                return 0
            data = json.loads(response.content)
        if isinstance(data, dict):
            for key in _LIST_KEYS:
                if isinstance(data.get(key), (list, tuple)):
                    return len(data[key])
            return 1 if data and _CUSTOMER_DETAIL.match(path or '') else 0
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


def record_counted(user, *, rows=0, export=False):
    """(kind, count): kind is 'rows' / 'exports' when a limit is first crossed this hour, else
    None; count is the counter value seen at the crossing."""
    crossed, count = None, 0
    try:
        if rows > 0:
            before, after = _add(user, 'rows', rows)
            if before < _limit('rows') <= after:
                crossed, count = 'rows', after
        if export:
            before, after = _add(user, 'exports', 1)
            if before < _limit('exports') <= after and crossed is None:
                crossed, count = 'exports', after
    except Exception:
        log.warning('bulk read counter failed', exc_info=True)
    return crossed, count


def record(user, *, rows=0, export=False):
    """Add to this hour's counters. 'rows' / 'exports' when a limit is first crossed, else None."""
    return record_counted(user, rows=rows, export=export)[0]


def _profile(user):
    """The StaffProfile, or None for a superuser / an account without one (never blocked)."""
    if getattr(user, 'is_superuser', False):
        return None
    try:
        return getattr(user, 'staff_profile', None)
    except Exception:
        return None


def blocked(user):
    """True while the profile's bulk_read_blocked_until is in the future (stored in the database,
    so `clear_bulk_block` in another process lifts it)."""
    try:
        profile = _profile(user)
        until = getattr(profile, 'bulk_read_blocked_until', None)
        if until is None:
            return False
        if until > timezone.now():
            return True
        # the user object may be stale (loaded before a clear / re-block): ask the database once
        model = type(profile)
        fresh = model.objects.filter(pk=profile.pk).values_list(
            'bulk_read_blocked_until', flat=True).first()
        if fresh and fresh > timezone.now():
            return True
        if fresh is not None:
            # expired: clear it (only if nobody re-blocked meanwhile) so later requests cost nothing
            model.objects.filter(pk=profile.pk, bulk_read_blocked_until=fresh).update(
                bulk_read_blocked_until=None)
        profile.bulk_read_blocked_until = None
        return False
    except Exception:
        return False


def _role(user):
    from . import session_policy
    return getattr(session_policy.subject(user), 'role', None) or 'viewer'


def alert(user, kind, request, count=None):
    """Audit row + admin digest for a crossing; in enforce, block a non-admin."""
    try:
        access = getattr(request, 'access', None)
        network = getattr(access, 'network', None)
        label_ar = getattr(network, 'label_ar', '') or ''
        label_en = ('Outside the network' if getattr(network, 'zone', None) == 'external'
                    else 'Inside the network' if network is not None else '')
        role = _role(user)
        if count is None:
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
        profile = _profile(user)
        if current == 'enforce' and role != 'admin' and profile is not None:
            minutes = int(getattr(settings, 'BULK_READ_BLOCK_MINUTES', 30))
            until = timezone.now() + timedelta(minutes=minutes)
            type(profile).objects.filter(pk=profile.pk).update(bulk_read_blocked_until=until)
            profile.bulk_read_blocked_until = until
    except Exception:
        log.error('bulk read alert failed', exc_info=True)
