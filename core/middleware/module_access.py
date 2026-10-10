"""
Server-side module access control for the staff API, driven by the existing
RoleModuleAccess matrix (role × module × action).

Many API views only require IsAuthenticated, so the matrix — which already drives
what the React UI shows — was not enforced on the server: any logged-in user could
call any module's endpoints directly. This middleware closes that gap without
touching the ~60 view modules, and is rolled out in three steps via
settings.RBAC_ENFORCEMENT:

  off      — do nothing.
  log      — (default) let every request through, but log each one the matrix
             would deny ("elrezeiky.rbac" logger). Run this in production first
             and fix the matrix until the log is quiet.
  enforce  — return 403 for those requests.

URL prefix → module mapping is MODULE_BY_PREFIX below; unmapped prefixes are not
checked (they keep their view-level permissions). HTTP method → action:
  GET/HEAD/OPTIONS → view;  PUT/PATCH → edit;  DELETE → delete;
  POST → any of create / edit / approve / assign / finalize / export
         (POST is used for both creation and workflow actions).
Admins bypass the matrix (as StaffProfile.can_do does). Anonymous requests are
left to the views (which return 401/403 themselves).

Safety net: in enforce mode, if RoleModuleAccess is empty (matrix never seeded)
the middleware logs an error and falls back to log mode instead of locking
everyone but admins out.
"""
import logging
import time

from django.conf import settings
from django.http import JsonResponse

logger = logging.getLogger('elrezeiky.rbac')

# /api/<prefix>/ → RoleModuleAccess.module
MODULE_BY_PREFIX = {
    'pos-orders': 'pos', 'offers': 'pos', 'commerce': 'commerce',
    'reservations': 'reservations',
    'demand': 'demand',
    'transfers': 'transfers', 'transits': 'transfers',
    'followups': 'followups',
    'delivery': 'delivery',
    'customers': 'customers', 'loyalty': 'customers', 'referral': 'customers',
    'chronic': 'chronic', 'composition': 'chronic',
    'campaigns': 'campaigns', 'whatsapp': 'campaigns',
    'vouchers': 'vouchers',
    'products': 'catalog', 'images': 'catalog', 'enrichment': 'catalog',
    'batches': 'catalog', 'vision': 'catalog',
    'stockcount': 'stockcount',
    'shortage': 'shortage',
    'purchasing': 'purchasing', 'procurement': 'purchasing',
    'supply': 'purchasing', 'forecasting': 'purchasing',
    'invoices': 'invoices',
    'incentives': 'incentives',
    'cheques': 'cheques',
    'finance': 'finance', 'payments': 'finance',
    'callcenter': 'callcenter', 'omni': 'callcenter', 'pbx': 'callcenter',
    'hr': 'hr', 'qa': 'hr',
    'approvals': 'approvals', 'pricing-approvals': 'approvals',
    'insurance': 'insurance',
    'replacement': 'replacement',
    'analytics': 'analytics', 'insights': 'analytics',
    'dashboard': 'dashboard',
    'audit': 'audit',
    'sync': 'sync',
    'users': 'users',
}

# Prefixes every staff screen reads (pickers, lookups, theme); only their
# write methods are checked, against the module named here.
READ_OPEN_PREFIXES = {
    'items': 'catalog',
    'branches': 'settings',
    'config': 'settings',
}

# Never checked: own session/profile, notifications, personal dashboard, global
# search, in-app help (reading is for everyone; its views check help/edit for
# trainer edits), the external customer portal and inbound webhooks (own auth).
EXEMPT_PREFIXES = {'auth', 'notifications', 'personal', 'search', 'help', 'portal', 'social'}

_POST_ACTIONS = ('create', 'edit', 'approve', 'assign', 'finalize', 'export')
_GRANTS_TTL = 60.0
_grants_cache = {'at': 0.0, 'by_role': {}, 'seeded': False}


def _mode():
    mode = str(getattr(settings, 'RBAC_ENFORCEMENT', 'log') or 'log').lower()
    return mode if mode in ('off', 'log', 'enforce') else 'log'


def clear_cache():
    _grants_cache.update(at=0.0, by_role={}, seeded=False)


def _grants():
    now = time.monotonic()
    if now - _grants_cache['at'] > _GRANTS_TTL:
        from apps.users.models import RoleModuleAccess
        by_role = {}
        rows = RoleModuleAccess.objects.filter(is_allowed=True).values_list('role', 'module', 'action')
        for role, module, action in rows:
            by_role.setdefault(role, set()).add((module, action))
        _grants_cache.update(
            at=now, by_role=by_role,
            seeded=RoleModuleAccess.objects.exists(),
        )
    return _grants_cache['by_role'], _grants_cache['seeded']


def required(path, method):
    """(module, allowed_actions) the request needs, or None when not checked."""
    parts = path.split('/')
    if len(parts) < 3 or parts[1] != 'api':
        return None
    prefix = parts[2]
    if prefix in EXEMPT_PREFIXES:
        return None
    method = method.upper()
    safe = method in ('GET', 'HEAD', 'OPTIONS')
    if prefix in READ_OPEN_PREFIXES:
        if safe:
            return None
        module = READ_OPEN_PREFIXES[prefix]
    else:
        module = MODULE_BY_PREFIX.get(prefix)
        if module is None:
            return None
    if safe:
        return module, ('view',)
    if method in ('PUT', 'PATCH'):
        return module, ('edit',)
    if method == 'DELETE':
        return module, ('delete',)
    return module, _POST_ACTIONS


def _staff_profile(request):
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        from core.auth_cookies import user_from_request
        user = user_from_request(request)   # Bearer header or httpOnly cookie
        if user is None:
            return None   # anonymous / bad token — the view answers 401
    return getattr(user, 'staff_profile', None)


class ModuleAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        denied = self._check(request)
        if denied is not None:
            return denied
        return self.get_response(request)

    def _check(self, request):
        mode = _mode()
        if mode == 'off':
            return None
        need = required(request.path_info, request.method)
        if need is None:
            return None
        profile = _staff_profile(request)
        if profile is None or profile.role == 'admin':
            return None
        module, actions = need
        by_role, seeded = _grants()
        granted = by_role.get(profile.role, set())
        if any((module, a) in granted for a in actions):
            return None

        logger.warning(
            'RBAC %s: role=%s user=%s module=%s needs=%s %s %s',
            'DENY' if mode == 'enforce' and seeded else 'would-deny',
            profile.role, getattr(profile.user, 'username', '?'), module,
            '|'.join(actions), request.method, request.path_info,
        )
        if mode != 'enforce':
            return None
        if not seeded:
            logger.error('RBAC_ENFORCEMENT=enforce but RoleModuleAccess is empty — '
                         'not blocking (run manage.py seed_permissions)')
            return None
        return JsonResponse(
            {'detail': 'ليس لديك صلاحية على هذه الوحدة', 'module': module},
            status=403,
        )
