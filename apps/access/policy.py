"""
Zone policy (N3): what a role may do from each access zone.

The policy only NARROWS what the role's own module matrix grants (core/middleware/module_access.py);
it never widens it. `decide()` is pure apart from the cached policy lookup.
"""
import re
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from .zones import Z1, Z2, Z3, Z4

# Reachable in every zone for a signed-in user: the user's own session (any method).
ALWAYS_OPEN = (
    '/api/auth/',
    '/api/users/my-permissions/',
    '/api/notifications/',          # own inbox; announcements/ is READ_OPEN below
    '/api/access/whoami/',
    '/api/audit/screen-view/',
)
# Reachable in every zone for reading only: company announcements and the help centre (their
# create / edit / resolve calls follow the zone policy like any other write).
READ_OPEN = ('/api/help/', '/api/notifications/announcements/')
# ... plus these own-session writes under READ_OPEN.
OWN_SESSION_WRITES = (
    re.compile(r'^/api/notifications/announcements/\d+/ack/$'),
    # feedback/ POST is the «هل أفاد هذا الشرح؟» answer; its GET list and resolve stay trainers'
    re.compile(r'^/api/help/(ask|tour-event|onboarding/learned|feedback)/$'),
    re.compile(r'^/api/help/quizzes/[^/]+/submit/$'),
)

# The rider surface: (compiled regex on request.path_info, methods or None for any).
RIDER_PATHS = (
    (re.compile(r'^/api/delivery/app/'), None),
    (re.compile(r'^/api/delivery/\d+/$'), ('GET', 'HEAD', 'OPTIONS')),
    (re.compile(r'^/api/delivery/\d+/(accept|dispatch|complete|partial|unavailable|fail|collect-cash|items)/$'), None),
)

# I2 recovery: an admin on an unapproved browser inside the network (Z2) may still approve devices
# and fix the trusted networks, so one lost device cookie never locks the company out.
ADMIN_Z2_RECOVERY = ('/api/access/devices/', '/api/access/networks/')

REASON_MESSAGES = {
    'blocked': 'الدخول من خارج شبكة الشركة غير متاح لدورك',
    'read_only': 'هذا الجهاز غير معتمد — للعرض فقط',
    'module': 'هذه الشاشة غير متاحة من خارج شبكة الشركة',
    'export': 'التصدير متاح من داخل شبكة الشركة فقط',
}

_SAFE = ('GET', 'HEAD', 'OPTIONS')
_NO_POLICY = 'none'   # cached marker: no row for this (role, zone)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str | None
    zone: str | None


# ── policy lookup (cached 60 s, invalidated on save / delete) ────────────────

def _key(role, zone):
    return f'access:zone_policy:{role}:{zone}'


def invalidate_cache(*args, **kwargs):
    """Drop every cached (role, zone) policy; wired to ZonePolicy post_save / post_delete."""
    from .models import ZonePolicy
    from apps.users.models import ROLE_CHOICES
    roles = {r for r, _ in ROLE_CHOICES} | set(ZonePolicy.objects.values_list('role', flat=True))
    instance = kwargs.get('instance')
    if instance is not None:
        roles.add(instance.role)
    cache.delete_many([_key(r, z) for r in roles for z in ('Z1', 'Z2', 'Z3', 'Z4')])


def policy_for(role, zone):
    """The ZonePolicy row for (role, zone), or None."""
    from .models import ZonePolicy
    ttl = getattr(settings, 'ACCESS_POLICY_TTL', 60)
    if ttl:
        hit = cache.get(_key(role, zone))
        if hit is not None:
            return None if hit == _NO_POLICY else hit
    row = ZonePolicy.objects.filter(role=role, zone=zone).first()
    if ttl:
        cache.set(_key(role, zone), row if row is not None else _NO_POLICY, ttl)
    return row


# ── request classification ───────────────────────────────────────────────────

EXPORT_FORMATS = ('xlsx', 'xls', 'csv', 'excel')
# Whole path segments that mean a download: printouts and letters carry the same data out.
EXPORT_SEGMENTS = ('export', 'excel', 'print', 'cover-letter')
# POST routes where the body picks the export: path -> (key, value)
BODY_EXPORTS = {'/api/reservations/bulk/': ('action', 'export')}


def is_export(path, method=None, query=None, body=None):
    """A download request: a path segment in EXPORT_SEGMENTS (export, excel, print, cover-letter),
    `export-*` or `*-export`; a `?format=` of xlsx / xls / csv / excel; or a body-selected export
    (BODY_EXPORTS)."""
    path = path or ''
    for seg in path.split('/'):
        if seg in EXPORT_SEGMENTS or seg.startswith('export-') or seg.endswith('-export'):
            return True
    if query is not None:
        fmt = query.get('format')
        if isinstance(fmt, str) and fmt.strip().lower() in EXPORT_FORMATS:
            return True
    rule = BODY_EXPORTS.get(path)
    if rule and isinstance(body, dict) and body.get(rule[0]) == rule[1]:
        return True
    return False


def _is_always_open(path, method='GET'):
    if path.startswith(READ_OPEN):
        return method in _SAFE or any(rx.match(path) for rx in OWN_SESSION_WRITES)
    return path.startswith(ALWAYS_OPEN)


def _is_rider_path(path, method):
    for rx, methods in RIDER_PATHS:
        if rx.match(path) and (methods is None or method in methods):
            return True
    return False


def softech_write_allowed(profile, zone):
    """N4 hook: SOFTECH writes from a zone - the policy row, widened for admins in Z3 by the
    per-user flag."""
    zone = zone or Z4   # signed-in context failure is Z4, as decide()
    pol = policy_for(profile.role, zone)
    if pol is None:
        return zone in (Z1, Z2)    # a role without rows: open inside, closed outside
    if pol.softech_write:
        return True
    return zone == Z3 and profile.role == 'admin' and bool(getattr(profile, 'external_softech_write', False))


# ── the decision ─────────────────────────────────────────────────────────────

def decide(profile, zone, path, method, module=None, export_request=False):
    """Allow or refuse one request. `module` is what module_access.required() maps the path to."""
    if profile is None:
        return Decision(True, None, zone)          # anonymous: the view answers 401
    if zone is None:
        zone = Z4                                   # context failure: never "no policy"
    method = (method or 'GET').upper()
    if _is_always_open(path, method):
        return Decision(True, None, zone)
    if zone == Z2 and profile.role == 'admin' and path.startswith(ADMIN_Z2_RECOVERY):
        return Decision(True, None, zone)
    pol = policy_for(profile.role, zone)
    if pol is None:
        # a role added later without its four rows: open inside, blocked outside (never wide open)
        return Decision(zone in (Z1, Z2), None if zone in (Z1, Z2) else 'blocked', zone)
    safe = method in _SAFE

    def refuse(reason):
        return Decision(False, reason, zone)

    if pol.access == 'none':
        return refuse('blocked')
    if pol.access == 'rider':
        return Decision(True, None, zone) if _is_rider_path(path, method) else refuse('module')
    if pol.access == 'listed':
        if module is None:
            if not safe:
                return refuse('module')      # exempt / unmapped prefixes: reads only
        elif module not in (pol.modules or []):
            return refuse('module')
    if (pol.access == 'read_only' or (pol.access == 'listed' and pol.view_only)) and not safe:
        return refuse('read_only')
    if export_request and not pol.export:
        widened = (zone == Z3 and profile.role == 'admin'
                   and bool(getattr(profile, 'external_export', False)))
        if not widened:
            return refuse('export')
    return Decision(True, None, zone)
