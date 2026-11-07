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
import re
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
    'access': 'settings',     # trusted networks (admin only in the view); whoami is open below
    'tasks': 'tasks',         # own module since 2026-11-03 (owner); views check it too
    'counselling': 'counselling',   # Project 4 sheets; assistant + cards are POS (see required_access)
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
                   '/api/access/whoami/',              # the header badge «من أين أتصل؟» (N1)
                   '/api/incentives/my-progress/',     # the caller's own incentive progress (Z-9a)
                   '/api/audit/usage/')                # P-57: own gate (admin / HR / own branch)
# Exact paths any signed-in staff member may POST: the screen-usage beacon every page
# sends (P-57) — it records the caller's own visit and nothing else.
OPEN_WRITE_EXACT = ('/api/audit/screen-view/',)

# Never checked: own session/profile, notifications, personal dashboard, global
# search, in-app help (reading is for everyone; its views check help/edit for
# trainer edits), the external customer portal and inbound webhooks (own auth).
EXEMPT_PREFIXES = {'auth', 'notifications', 'personal', 'search', 'help', 'portal', 'social',
                   'gamification',   # own points open to all; its views check gamification/*
                   'stock-audit',    # own gate apps/stock_audit/access.py: RBAC stock_audit
                   'pic-analytics',  # own gate apps/pic_analytics/access.py: RBAC pic_analytics + named grants
                   'usage-print',    # own gate apps/usage_print/access.py: flag USAGE_PRINT_ENABLED + RBAC usage_print
                   'public',         # N6 anonymous surface (apps/access/public_urls.py), no business data
                   'csp-report',     # browsers' CSP reports — public, log only (core/csp.py, W-9)
                   'trace'}          # P-58 own gates apps/trace/views.py: parse = admin,
                                     # scan = pos create (sale) / invoices create (receive)
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


def _mode_for(role):
    """The mode for one caller. Roles in RBAC_ENFORCED_ROLES are enforced whenever the middleware
    is on (log or enforce): a role created after the matrix was reviewed has no legacy screens to
    observe in log mode, and many older views only check IsAuthenticated because every role then
    held their module (hr, customers, catalog …). Finance GL ruling: the `accountant` reaches
    ledger / finance / cheques / dashboard / tasks and nothing else, from day one."""
    mode = _mode()
    if mode == 'log' and role in enforced_roles():
        return 'enforce'
    return mode


def enforced_roles() -> frozenset:
    """settings.RBAC_ENFORCED_ROLES as a set of role names. A plain string (env value) is split on
    commas — never kept as a string, where `role in 'accountant'` would be a substring test."""
    roles = getattr(settings, 'RBAC_ENFORCED_ROLES', ('accountant',))
    if isinstance(roles, str):
        roles = roles.split(',')
    return frozenset(str(r).strip() for r in (roles or ()) if str(r).strip())


def matrix_enforced_for(user) -> bool:
    """True for a caller whose role the matrix is enforced for in every mode: views use it to gate
    data they hand any signed-in user (universal search, chatter) without narrowing legacy roles."""
    profile = getattr(user, 'staff_profile', None) if not hasattr(user, 'role') else user
    return bool(profile is not None and getattr(profile, 'role', None) in enforced_roles())


def clear_cache():
    _grants_cache.update(at=0.0, by_role={}, seeded=False, modules=frozenset())


def _grants():
    now = time.monotonic()
    # RBAC_GRANTS_TTL is 0 under tests: a cached matrix would carry one test's rows into the next.
    if now - _grants_cache['at'] > float(getattr(settings, 'RBAC_GRANTS_TTL', 60)):
        from apps.users.models import RoleModuleAccess
        by_role, modules = {}, set()
        enforced = enforced_roles()
        rows = RoleModuleAccess.objects.values_list('role', 'module', 'action', 'is_allowed')
        for role, module, action, allowed in rows:
            # an explicit denial counts as seeded too — but not an enforced role's rows (R17): the
            # accountant's deny rows must not end another role's fail-open on an unseeded module
            if role not in enforced:
                modules.add(module)
            if allowed:
                by_role.setdefault(role, set()).add((module, action))
        _grants_cache.update(at=now, by_role=by_role, seeded=bool(modules), modules=frozenset(modules))
    return _grants_cache['by_role'], _grants_cache['seeded']


def seeded_modules() -> frozenset:
    """Modules that have at least one RoleModuleAccess row (allowed or not) of a role outside
    RBAC_ENFORCED_ROLES (R17 — enforced roles never change another role's seeding). A module nobody has a
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


def _analytics_write(method):
    """Analytics routes: a POST computes (export counts, Z-11a); a PUT / PATCH edits and a DELETE
    deletes, so export does not (Batch 4, Z-12 — it let view + export roles past on all three)."""
    method = method.upper()
    if method in ('GET', 'HEAD', 'OPTIONS'):
        return ('view',)
    if method in ('PUT', 'PATCH'):
        return ('edit',)
    if method == 'DELETE':
        return ('delete',)
    return _EXPORT_POST


_LINE_REMOVAL = re.compile(r'^/api/(?:'
    r'reservations/\d+/(?:lines|images)/\d+/delete/'
    r'|shortage/lists/\d+/items/\d+/delete/'
    r'|demand/\d+/items/\d+/'
    r'|supply/availability/\d+/lines/\d+/delete/'
    r'|invoices/invoices/\d+/lines/\d+/delete/'
    r'|items/bundles/\d+/items/\d+/'
    r'|items/variant-groups/\d+/members/\d+/'
    r'|products/[^/]+/(?:media/\d+|related/\d+/remove)/'
    r'|images/products/\d+/images/\d+/'
    r'|callcenter/calls/\d+/(?:items|attachments)/\d+/'
    r'|incentives/rules/\d+/(?:remove-item|clear-items)/'
    r')$')


def required(path, method):
    """(module, allowed_actions) the request needs, or None when not checked."""
    parts = path.split('/')
    if len(parts) < 3 or parts[1] != 'api':
        return None
    prefix = parts[2]
    if prefix in EXEMPT_PREFIXES or path in OPEN_WRITE_EXACT:
        return None
    # Small daily counts (Project 2) have their own gate, like /api/stock-audit/: every salesperson
    # counts their OWN blind list (the matrix gives salespeople read-only stockcount), and review is
    # for named branch managers + stock_audit management (apps/stockcount/daily/views.py)
    if prefix == 'stockcount' and parts[3:4] == ['daily']:
        return None
    method = method.upper()
    # Owner answer Q-7e (2026-11-05): removing a LINE from a document (reservation line / image, shortage
    # list item, demand item, availability line, invoice line, bundle item, variant member, product media /
    # relation / image, call item / attachment, incentive rule item) is editing that document: it asks what
    # a PATCH of the same path asks (the module's edit), not a module-wide `delete`.
    if method == 'DELETE' and _LINE_REMOVAL.match(path):
        return required(path, 'PATCH')
    # Owner answer Q-5 (2026-11-05): missed sales belong to the reservations module (suggestions are
    # confirmed into reservations, Project 3) — the view checks reservations too.
    if prefix == 'pos-orders' and parts[3:4] == ['missed-sales']:
        return 'reservations', (('view',) if method in ('GET', 'HEAD', 'OPTIONS') else ('create',))
    # Project 4: the switches are read by every staff screen; the drug assistant and the counselling
    # card are counter (POS) actions; approving / retiring a sheet needs counselling approve
    if prefix == 'counselling' and parts[3:4] == ['status']:
        return None
    if prefix == 'counselling' and parts[3:4] in (['assistant'], ['cards']):
        return 'pos', (('view',) if method in ('GET', 'HEAD', 'OPTIONS') else _POST_ACTIONS)
    if prefix == 'counselling' and len(parts) > 5 and parts[3] == 'content' and parts[5] in ('approve', 'retire'):
        return 'counselling', ('approve',)
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
    # General Ledger (finance-gl): its own `ledger` module, not `finance` — the accountant holds
    # ledger create/approve but only finance view. The views check the exact ledger action.
    # Writes need exactly what the view asks (apps/finance/gl/views.py): chart of accounts (PATCH,
    # import) = edit; approve / bulk approve / reverse = approve; drafts (POST, PUT, DELETE) = create.
    if prefix == 'finance' and parts[3:4] == ['gl']:
        if safe:
            return 'ledger', ('view',)
        if parts[4:5] == ['accounts']:
            return 'ledger', ('edit',)
        if parts[4:5] == ['entries'] and ('approve' in parts[5:7] or 'reverse' in parts[6:7]):
            return 'ledger', ('approve',)
        # Drafting engine (Plan 2): rule/map edits and party import/propose = edit; party confirm /
        # reject / create = approve; rule preview only computes = view; exceptions + drafting = create
        if parts[4:5] == ['rules']:
            return 'ledger', (('view',) if parts[5:6] == ['preview'] else ('edit',))
        if parts[4:5] == ['maps']:
            return 'ledger', ('edit',)
        if parts[4:5] == ['parties']:
            return 'ledger', (('edit',) if parts[5:6] in (['import'], ['propose']) else ('approve',))
        # Ruling P23: deciding on an accountant-edited entry SOFTECH changed = approve
        if parts[4:5] == ['exceptions'] and parts[6:7] in (['accept-softech'], ['keep-edit']):
            return 'ledger', ('approve',)
        # Close and reconcile (Plan 3): closing and reopening a month = finalize; a comparison refresh only
        # reads and recomputes = view; explaining a difference = approve; the checks and the closing-stock store
        # map = edit; the validation report = export. Corrections and the manual import = create.
        if parts[4:5] == ['periods'] and parts[6:7] in (['close'], ['reopen']):
            return 'ledger', ('finalize',)
        if parts[4:5] == ['compare'] and parts[5:6] == ['refresh']:
            return 'ledger', ('view',)
        if parts[4:5] == ['compare'] and parts[5:6] == ['checks']:
            return 'ledger', ('edit',)
        if parts[4:5] == ['compare'] and parts[5:6] == ['lines'] and parts[7:8] == ['explain']:
            return 'ledger', ('approve',)
        if parts[4:5] == ['closing-stock-stores']:
            return 'ledger', ('edit',)
        if parts[4:5] == ['validation']:
            return 'ledger', ('export',)
        return 'ledger', ('create',)
    # Market Shortage reads the engine's run status and the shortage screen the vendor list:
    # `shortage` view (purchasing holds it too) — owner decision 2026-10-28, map by screen (Z-7a)
    if safe and ((prefix == 'purchasing' and parts[3:5] in (['runs', 'latest'], ['runs', 'active']))
                 or (prefix == 'invoices' and parts[3:4] == ['vendors'])):
        return 'shortage', ('view',)
    # Market Shortage → shortage; Phantom / Cash Optimization reads → analytics, phantom review =
    # shortage (the Market Shortage reviewers), spike confirm = purchasing (Z-7b); P-27 dead stock (the same
    # Cash Optimization screen): reads analytics, decisions / strategic hold / recompute purchasing
    if prefix == 'purchasing' and parts[3:4] in (['shortage'], ['phantom'], ['spike'], ['dead-stock']):
        if safe:
            return ('shortage' if parts[3] == 'shortage' else 'analytics'), ('view',)
        if parts[3] in ('spike', 'dead-stock'):
            return 'purchasing', _POST_ACTIONS
        return 'shortage', ('approve',)       # flag / dismiss / phantom review: approve, as the views
    # P-33 (a): creating transfer proposals from a shortage list is the WhatsApp path's purchasing
    # write (its view checks can_supply_write), not a shortage-list edit
    if (not safe and prefix == 'shortage' and parts[3:4] == ['lists'] and len(parts) > 6
            and parts[5] == 'transfers'):
        return 'purchasing', _POST_ACTIONS
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
                    'stock-expiry/export', 'stock-expiry/disposal/export', 'return-window/export'):
            return 'catalog', ('view',)
        # P-29: supplier return policies belong to purchasing (owner 2026-10-31), not catalog editors
        if tail == 'return-window/policies':
            return 'purchasing', ('edit',)
        if parts[4:5] == ['quarantine']:
            return 'approvals', ('approve',)
        if tail == 'purchase-expiry/request-markdown':
            return 'approvals', ('create', 'approve')
        # disposal status: the screen (catalog view); the view decides who (managers approve,
        # finish and reopen; the drafter cancels their own draft — owner 2026-11-01)
        if parts[3:5] == ['stock-expiry', 'disposal'] and parts[6:7] == ['status']:
            return 'catalog', ('view',)
    # Sales targets sit beside the KPI board (analytics; edits keep their role check), and HR
    # self-service is every employee's own filing: any hr grant (Z-9a, map by screen)
    if prefix == 'incentives' and parts[3:4] == ['targets']:
        return 'analytics', _analytics_write(method)
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
        return 'analytics', _analytics_write(method)
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
        mode = _mode_for(profile.role)
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
        if not seeded and profile.role not in enforced_roles():
            logger.error('RBAC_ENFORCEMENT=enforce but RoleModuleAccess is empty — '
                         'not blocking (run manage.py seed_permissions)')
            return None
        return JsonResponse(
            {'detail': 'ليس لديك صلاحية على هذه الوحدة', 'module': module},
            status=403,
        )
