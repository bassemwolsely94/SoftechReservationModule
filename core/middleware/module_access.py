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
    'pos-orders': 'pos', 'offers': 'offers', 'commerce': 'commerce',
    'reservations': 'reservations',
    'demand': 'demand',
    'transfers': 'transfers', 'transits': 'transfers',
    'followups': 'followups',
    'delivery': 'delivery',
    'customers': 'customers', 'loyalty': 'customers', 'referral': 'customers',
    'chronic': 'chronic', 'composition': 'chronic',
    'campaigns': 'campaigns', 'whatsapp': 'callcenter',    # WhatsApp inbox: call center screens (Z-8b)
    'vouchers': 'vouchers',
    'products': 'catalog', 'images': 'catalog', 'enrichment': 'catalog',
    'batches': 'catalog', 'vision': 'catalog',
    'stockcount': 'stockcount',
    'shortage': 'shortage',
    'purchasing': 'purchasing', 'procurement': 'purchasing',
    'supply': 'purchasing', 'forecasting': 'analytics',     # forecasting: Z-7b, map by screen
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
    # POS (bought-together, basket) and customer screens read these; the engine trigger is
    # checked against analytics (the view also limits it to admin / supervisor) — Z-1.
    'recommendations': 'analytics',
}

# Reads every screen makes whatever the role's modules — the menu's own permission map and the
# data-freshness bar. Only GET; writes under these prefixes stay checked (Batch 4, Z-1).
OPEN_READ_PATHS = ('/api/users/my-permissions/', '/api/sync/freshness/', '/api/sync/status/',
                   '/api/cheques/holidays/',    # public-holiday calendar, no business data (Z-3)
                   '/api/users/erp-permissions/me/',   # the caller's own SOFTECH group (Z-4)
                   '/api/sync/branch-health/',         # SOFTECH node up/down — pricing panel (Z-4)
                   '/api/pbx/my-extension/')           # the caller's own PBX extension — POS screen-pop (Z-8b)
# Exact paths, not prefixes: the staff picker list every screen loads (tasks, demand, HR forms,
# follow-ups, incentives) — slim fields for roles without users view; a record needs users (Z-4).
OPEN_READ_EXACT = ('/api/users/staff/',
                   '/api/incentives/my-progress/')     # the caller's own incentive progress (Z-9a)

# Never checked: own session/profile, notifications, personal dashboard, global
# search, in-app help (reading is for everyone; its views check help/edit for
# trainer edits), the external customer portal and inbound webhooks (own auth).
EXEMPT_PREFIXES = {'auth', 'notifications', 'personal', 'search', 'help', 'portal', 'social',
                   'gamification',   # own points open to all; its views check gamification/*
                   'tasks',          # every staff member's own task board (scoping: Batch 5)
                   'stock-audit'}    # own gate apps/stock_audit/access.py: RBAC stock_audit
                                     # + named branch managers the matrix doesn't know (Z-1)

# A POST needs a write grant. `export` is not one (Batch 4, Z-11a — overblock review decision 1):
# with it, roles holding view + export passed every POST and the views refused. POSTs that only
# compute or build an export keep taking it — analytics (reports, forecasts, refreshes), the
# transit sheets, QA filing — mapped explicitly in required().
_POST_ACTIONS = ('create', 'edit', 'approve', 'assign', 'finalize')
_EXPORT_POST = _POST_ACTIONS + ('export',)
_grants_cache = {'at': 0.0, 'by_role': {}, 'seeded': False, 'modules': frozenset()}


def _mode():
    mode = str(getattr(settings, 'RBAC_ENFORCEMENT', 'log') or 'log').lower()
    return mode if mode in ('off', 'log', 'enforce') else 'log'


def clear_cache():
    _grants_cache.update(at=0.0, by_role={}, seeded=False, modules=frozenset())


def _grants():
    now = time.monotonic()
    # RBAC_GRANTS_TTL is 0 under tests: a cached matrix would carry one test's rows into the next.
    if now - _grants_cache['at'] > float(getattr(settings, 'RBAC_GRANTS_TTL', 60)):
        from apps.users.models import RoleModuleAccess
        by_role, modules = {}, set()
        rows = RoleModuleAccess.objects.values_list('role', 'module', 'action', 'is_allowed')
        for role, module, action, allowed in rows:
            modules.add(module)                  # an explicit denial counts as seeded too
            if allowed:
                by_role.setdefault(role, set()).add((module, action))
        _grants_cache.update(at=now, by_role=by_role, seeded=bool(modules), modules=frozenset(modules))
    return _grants_cache['by_role'], _grants_cache['seeded']


def seeded_modules() -> frozenset:
    """Modules that have at least one RoleModuleAccess row (allowed or not). A module nobody has a
    row for isn't seeded yet — a fresh install, or a module whose rows a migration hasn't added
    (Batch 4, Z-5c)."""
    _grants()
    return _grants_cache['modules']


def supply_member(profile) -> bool:
    """In a SOFTECH supply group (apps.purchasing.access): the replenishment team works the
    purchasing screens with the `purchasing` role's grants whatever its app role (owner
    2026-10-02, confirmed for the server 2026-10-27 — Batch 4, Z-2)."""
    from apps.purchasing.access import in_supply_group
    try:
        return in_supply_group(profile.user)
    except Exception:
        return False


def required(path, method):
    """(module, allowed_actions) the request needs, or None when not checked."""
    parts = path.split('/')
    if len(parts) < 3 or parts[1] != 'api':
        return None
    prefix = parts[2]
    if prefix in EXEMPT_PREFIXES:
        return None
    method = method.upper()
    # POS alternatives live under /api/composition/ (chronic) but belong to the POS module
    if prefix == 'composition' and len(parts) > 3 and parts[3] == 'alternatives':
        return 'pos', (('view',) if method in ('GET', 'HEAD', 'OPTIONS') else _POST_ACTIONS)
    # The checkout's two offer calls are POS actions; managing offers is the `offers` module (Z-5)
    if prefix == 'offers' and len(parts) > 3 and parts[3] in ('evaluate', 'apply-to-order'):
        return 'pos', (('view',) if method in ('GET', 'HEAD', 'OPTIONS') else _POST_ACTIONS)
    # Doctor-referral stats is a report (menu: Analytics), not a POS screen (Z-5b)
    if prefix == 'pos-orders' and len(parts) > 3 and parts[3] == 'referral-stats':
        return 'analytics', (('view',) if method in ('GET', 'HEAD', 'OPTIONS') else _EXPORT_POST)
    safe = method in ('GET', 'HEAD', 'OPTIONS')
    # Market Shortage reads the engine's run status and the shortage screen the vendor list:
    # `shortage` view (purchasing holds it too) — owner decision 2026-10-28, map by screen (Z-7a)
    if safe and ((prefix == 'purchasing' and parts[3:5] in (['runs', 'latest'], ['runs', 'active']))
                 or (prefix == 'invoices' and parts[3:4] == ['vendors'])):
        return 'shortage', ('view',)
    # Market Shortage → shortage; Phantom / Cash Optimization reads → analytics, phantom review =
    # shortage (the Market Shortage reviewers), spike confirm = purchasing (Z-7b)
    if prefix == 'purchasing' and parts[3:4] in (['shortage'], ['phantom'], ['spike']):
        if safe:
            return ('shortage' if parts[3] == 'shortage' else 'analytics'), ('view',)
        if parts[3] == 'spike':
            return 'purchasing', _POST_ACTIONS
        return 'shortage', ('approve',)       # flag / dismiss / phantom review: approve, as the views
    # Vouchers (Z-9d): each write needs exactly the grant its view asks — issue create, assign
    # assign, cancel / edit edit, redeem (OTP send / verify) and finishing a redemption document
    # approve or finalize, the eligibility check view
    if not safe and prefix == 'vouchers' and parts[3:4] in (['vouchers'], ['documents']):
        if parts[3] == 'documents':
            return 'vouchers', ('approve', 'finalize')
        verb = parts[5] if len(parts) > 6 else ''
        need = {'': ('create',) if method == 'POST' else ('edit',), 'assign': ('assign',), 'cancel': ('edit',),
                'generate-otp': ('approve',), 'verify-otp': ('approve',), 'validate': ('view',)}.get(verb)
        if need is not None:
            return 'vouchers', (('delete',) if method == 'DELETE' else need)
    # Expiry screen (Z-9b, map by screen): worklists / exports are POSTs that only compute (catalog
    # view — supervisors and quality use the screen); quarantine is the matrix's batch-quarantine
    # grant (approvals approve); a markdown request is a price-change request (approvals, Z-6)
    if not safe and prefix == 'batches':
        tail = '/'.join(parts[3:-1])
        if tail in ('purchase-expiry/candidates', 'purchase-expiry/rebalance-suggest', 'purchase-expiry/export',
                    'stock-expiry/export', 'stock-expiry/disposal/export'):
            return 'catalog', ('view',)
        if parts[4:5] == ['quarantine']:
            return 'approvals', ('approve',)
        if tail == 'purchase-expiry/request-markdown':
            return 'approvals', ('create', 'approve')
    # Sales targets sit beside the KPI board (analytics; edits keep their role check), and HR
    # self-service is every employee's own filing: any hr grant (Z-9a, map by screen)
    if prefix == 'incentives' and parts[3:4] == ['targets']:
        return 'analytics', (('view',) if safe else _EXPORT_POST)
    if (not safe and prefix == 'hr' and (parts[3:5] in (['attendance', 'check-in'], ['attendance', 'check-out'])
                                         or parts[4:5] == ['submit'])):
        return 'hr', ('view',)
    # Lost demand (Z-8c, map by screen): the demand dashboard family is an analytics page (its
    # views keep their admin / purchasing / call center role sets); pushing purchase suggestions
    # is purchasing work; the shelf QR prints from the product page (catalog)
    if prefix == 'demand' and parts[3:5] == ['purchase-suggestions', 'push']:
        return 'purchasing', _POST_ACTIONS
    if safe and prefix == 'demand' and parts[3:4] and parts[3] in ('dashboard', 'lost-value-reconciliation', 'purchase-suggestions', 'capture-leaderboard', 'substitution-analytics', 'price-objections'):
        return 'analytics', ('view',)
    if safe and prefix == 'demand' and parts[3:4] == ['shelf-qr']:
        return 'catalog', ('view',)
    # Approving / rejecting / queueing (= sending) a campaign needs approve, as the views (Z-8b)
    if prefix == 'campaigns' and not safe and parts[4:5] in (['approve'], ['reject'], ['queue']):
        return 'campaigns', ('approve',)
    # Composition editing is catalog work (the views check catalog edit); the reservations
    # analytics report sits under Analytics (purchasing reads it) — Z-8a, map by screen
    if prefix == 'composition' and not safe:
        return 'catalog', (('edit',) if method in ('PUT', 'PATCH') else
                           ('delete',) if method == 'DELETE' else _POST_ACTIONS)
    if safe and prefix == 'reservations' and parts[3:4] == ['analytics']:
        return 'analytics', ('view',)
    # Pick-zone classify runs from the product screens (catalog); preview only computes (Z-7c)
    if prefix == 'transits' and parts[3:5] == ['pick-zones', 'classify-items']:
        return 'catalog', ('view',)
    if prefix == 'transits' and parts[3:5] == ['pick-zones', 'preview']:
        return 'transfers', ('view',)
    # Z-11a — POSTs that compute, export or are the caller's own filing, now that export is no
    # write: the transit picking / stocking sheets (a list of transfers in the body); QA filing by
    # the quality manager on hr view + export (as the view); call scoring and transcript correction
    # (the views keep their QA role checks); a count's item preview; an incentive dry run; and
    # cancelling one's own HR request (the queryset is the caller's own, as submit — Z-9a)
    if not safe and prefix == 'transits' and parts[3:4] in (['export-picking'], ['export-stocking']):
        return 'transfers', _EXPORT_POST
    if method == 'POST' and prefix == 'qa':
        return 'hr', _EXPORT_POST
    if method == 'POST' and ((prefix == 'callcenter' and parts[3:4] == ['calls'] and parts[5:6] == ['quality'])
                             or (prefix == 'callcenter' and parts[3:4] == ['transcripts'] and parts[5:6] == ['correct'])
                             or (prefix == 'stockcount' and parts[5:6] == ['preview-items'])
                             or (prefix == 'incentives' and parts[3:4] == ['programs'] and parts[5:6] == ['simulate'])):
        return MODULE_BY_PREFIX[prefix], ('view',)
    if method == 'POST' and prefix == 'hr' and parts[5:6] == ['cancel']:
        return 'hr', ('view',)
    # Forecasting writes (PUT / PATCH / DELETE too): the views' analyst-role checks decide (Z-7b)
    if prefix == 'forecasting' and not safe:
        return 'analytics', _EXPORT_POST
    if safe and (path.startswith(OPEN_READ_PATHS) or path in OPEN_READ_EXACT):
        return None
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
    return module, (_EXPORT_POST if module == 'analytics' else _POST_ACTIONS)


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
        if module == 'purchasing' and supply_member(profile) and any(
                (module, a) in by_role.get('purchasing', set()) for a in actions):
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
