"""
apps/tests/security/test_named_grants.py — round 2, R3 step 4: the two NAMED per-user grants.

PIC analytics (doc 33, `can_pic_analytics`, PicAnalyticsAccess) and stock audit (doc 32,
`can_stock_audit`, StockAuditAccess) sit outside the role matrix: /api/pic-analytics/ and
/api/stock-audit/ are EXEMPT in ModuleAccessMiddleware and each app gates itself
(apps/<app>/access.py). So the role sweep proves nothing for them. This file sweeps EVERY route of
both apps, every method the view implements, with:

  • a pharmacist with no grant, and one whose grant was revoked → refused everywhere (the two
    "describe my own access" routes excepted, below);
  • a granted branch manager → refused on the management-only routes (grants, PIC exclusions,
    PIC calls tabs, stock-audit thresholds / refresh);
  • the same grantee asking for ANOTHER branch (?branch=<id or code>) → never sees that branch's
    marked record; admin (positive control) does.

Unit-level rules (cost hidden, revoke audited, …) stay in apps/tests/test_pic_access.py and
apps/tests/test_stock_audit_api.py; this file is the route-level net over them.
"""
import datetime as _dt
import logging
from decimal import Decimal

from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.pic_analytics.models import PicAnalyticsAccess, PicDayFact
from apps.stock_audit.models import StockAuditAccess, StockAuditFinding
from apps.tests.factories import make_branch, make_user

from .fixtures import bearer_client, seed_code_matrix
from .routes import Tripwire, api_routes, handles

MARK = 'CNRYGRANT'
METHODS = ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')
_REFUSED = {401, 403, 404, 405}

# Routes that answer an ungranted caller on purpose: they describe the CALLER's own access
# (can_view = false), carry no findings or PIC data.
# reason: the stock-audit screen reads its own flags + the rule catalogue before deciding what to show.
OWN_ACCESS_ROUTES = {'GET /api/stock-audit/me/'}

# Management only, never a named branch manager (access.py docstrings, doc 32 / doc 33 §5).
PIC_MANAGEMENT_ONLY = ('/api/pic-analytics/grants/', '/api/pic-analytics/exclusions/',
                       '/api/pic-analytics/calls/', '/api/pic-analytics/numbers/')
SA_MANAGEMENT_ONLY = ('/api/stock-audit/access/', '/api/stock-audit/refresh/')
SA_EDIT_ONLY = ('/api/stock-audit/rules/x/',)          # PUT / PATCH / POST on a rule = thresholds


def _routes(prefix):
    return sorted({p for p, _ in api_routes() if p.startswith(prefix)})


def _call(client, method, path, data=None):
    try:
        with transaction.atomic():
            if method == 'GET':
                r = client.get(path, data or {})
            elif method == 'DELETE':
                r = client.delete(path)
            else:
                r = getattr(client, method.lower())(path, {}, format='json')
            transaction.set_rollback(True)
        ctype = r.get('Content-Type', '')
        body = r.content.decode('utf-8', 'replace') if ('json' in ctype or ctype.startswith('text/')) else ''
        return r.status_code, body
    except Exception as exc:          # noqa: BLE001 — a crash is its own finding
        return f'raised {type(exc).__name__}', ''


@override_settings(RBAC_ENFORCEMENT='enforce')
def _clear_cache():
    from django.core.cache import cache
    cache.clear()


class NamedGrantSweepTests(TestCase):
    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        seed_code_matrix()
        cls.b1 = make_branch('منح أ', 'NGA')
        cls.b2 = make_branch('منح ب', 'NGB')
        _, cls.admin_p, _ = make_user('ng_admin', role='admin', branch=cls.b1, access_all=True)
        mk = {}
        for name in ('granted', 'ungranted', 'revoked'):
            u, p, _ = make_user(f'ng_{name}', role='pharmacist', branch=cls.b1)
            mk[name] = (u, p)
        cls.users = mk
        for model in (PicAnalyticsAccess, StockAuditAccess):
            model.objects.create(staff=mk['granted'][1], granted_by=cls.admin_p)
            model.objects.create(staff=mk['revoked'][1], granted_by=cls.admin_p,
                                 revoked_by=cls.admin_p, revoked_at=timezone.now())
        day = timezone.localdate() - _dt.timedelta(days=2)
        cls.period = {'from': (day - _dt.timedelta(days=5)).isoformat(), 'to': day.isoformat()}
        for b, pic in ((cls.b1, 'OWNPIC1'), (cls.b2, MARK)):
            PicDayFact.objects.create(pic=pic, day=day, branch=b, invoices=1, net=10)
            StockAuditFinding.objects.create(
                rule_code='sale_below_cost', dedup_key=f'{b.softech_branch_id}|ng', severity='warning',
                status='open', branchcode=b.softech_branch_id, itemcode='100001', doccode='115',
                docnumber=7, docdate=day, occurred_at=timezone.now(), softech_user='166',
                value_egp=Decimal('100'), message_ar=pic, message_en=pic, last_seen=timezone.now())

    def setUp(self):
        self.clients = {k: bearer_client(u) for k, (u, _) in self.users.items()}
        self.admin = bearer_client(self.admin_p.user)

    def _sweep(self, client, prefix):
        out = {}
        previous = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        try:
            with Tripwire():
                for path in _routes(prefix):
                    for m in METHODS:
                        if handles(path, m):
                            out[f'{m} {path}'] = _call(client, m, path)[0]
        finally:
            logging.disable(previous)
            _clear_cache()   # rolled-back requests still write the cache (locks, throttles)
        return out

    def test_routes_were_found(self):
        self.assertGreater(len(_routes('/api/pic-analytics/')), 20)
        self.assertGreater(len(_routes('/api/stock-audit/')), 10)

    def test_ungranted_and_revoked_are_refused_everywhere(self):
        for who in ('ungranted', 'revoked'):
            for prefix in ('/api/pic-analytics/', '/api/stock-audit/'):
                got = self._sweep(self.clients[who], prefix)
                open_ = sorted(k for k, code in got.items()
                               if code not in _REFUSED and k not in OWN_ACCESS_ROUTES)
                self.assertEqual(open_, [], f'{who} reached {prefix}: {[(k, got[k]) for k in open_]}')

    def test_own_access_route_says_no(self):
        code, body = _call(self.clients['ungranted'], 'GET', '/api/stock-audit/me/')
        self.assertEqual(code, 200)
        self.assertIn('"can_view":false', body.replace(' ', ''))
        self.assertNotIn(MARK, body)

    def test_grantee_refused_on_management_routes(self):
        got = {**self._sweep(self.clients['granted'], '/api/pic-analytics/'),
               **self._sweep(self.clients['granted'], '/api/stock-audit/')}
        mgmt = PIC_MANAGEMENT_ONLY + SA_MANAGEMENT_ONLY
        bad = sorted(k for k, code in got.items()
                     if k.split(' ', 1)[1].startswith(mgmt) and code not in _REFUSED)
        bad += sorted(k for k, code in got.items()
                      if k.split(' ', 1)[0] != 'GET' and k.split(' ', 1)[1].startswith(SA_EDIT_ONLY)
                      and code not in _REFUSED)
        self.assertEqual(bad, [], {k: got[k] for k in bad})

    def test_grantee_reaches_their_screens(self):
        """Positive control: the grant really opens the apps (otherwise 'refused' proves nothing)."""
        for path in ('/api/pic-analytics/access/', '/api/pic-analytics/overview/',
                     '/api/stock-audit/findings/', '/api/stock-audit/summary/'):
            code, _ = _call(self.clients['granted'], 'GET', path, self.period)
            self.assertEqual(code, 200, path)

    def test_grantee_never_sees_another_branch(self):
        """Every GET route, plain and with ?branch=<other branch id / code>: no branch-B marker."""
        asks = [{**self.period, **q} for q in (
            {}, {'branch': self.b2.pk}, {'branch': self.b2.softech_branch_id},
            {'branches': self.b2.pk}, {'branch_code': self.b2.softech_branch_id})]
        seen, admin_seen = [], []
        previous = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        try:
            with Tripwire():
                for prefix in ('/api/pic-analytics/', '/api/stock-audit/'):
                    for path in _routes(prefix):
                        if not handles(path, 'GET'):
                            continue
                        for q in asks:
                            code, body = _call(self.clients['granted'], 'GET', path, q)
                            if code == 200 and MARK in body:
                                seen.append(f'{path} {q}')
                        if MARK in _call(self.admin, 'GET', path, self.period)[1]:
                            admin_seen.append(path)
        finally:
            logging.disable(previous)
            _clear_cache()   # rolled-back requests still write the cache (locks, throttles)
        self.assertEqual(seen, [])
        self.assertTrue(any(p.startswith('/api/pic-analytics/') for p in admin_seen), admin_seen)
        self.assertTrue(any(p.startswith('/api/stock-audit/') for p in admin_seen), admin_seen)


# ── Round 2, R3 step 4: the other modules built after Batch 4 ────────────────────────────────────

NEW_MATRIX_PREFIXES = {'counselling', 'tasks', 'pos-orders'}    # pos-orders carries missed-sales


class NewModuleRoleSweepTests(TestCase):
    """Counselling (Project 4), tasks (own module since 2026-11-03) and missed sales (Project 3,
    module `pos`): every role × route × method, with their feature flags ON and real records behind
    the detail routes, in both middleware modes. Unlike the whole-project sweep these modules start
    clean: no leak, no crash, no unproven detail route without a reason."""
    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        from .fixtures import role_clients
        from .sweep import protected_routes, seed_detail_paths, sweep
        from .canary import Planter
        from apps.users.models import StaffProfile
        seed_code_matrix()
        branch = make_branch()
        clients = role_clients(branch)
        admin = StaffProfile.objects.select_related('user').get(user__username='sec_admin')
        routes = [p for p in protected_routes() if p.split('/')[2] in NEW_MATRIX_PREFIXES]
        previous = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        try:
            with Tripwire():
                cls.seeded = seed_detail_paths(clients['admin'], Planter(branch, admin.user, admin), routes)
        finally:
            logging.disable(previous)
            _clear_cache()   # rolled-back requests still write the cache (locks, throttles)
        cls.log = sweep('log', clients, prefixes=NEW_MATRIX_PREFIXES, seeded=cls.seeded)
        cls.enforce = sweep('enforce', clients, prefixes=NEW_MATRIX_PREFIXES, seeded=cls.seeded)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        from core.middleware import module_access
        module_access.clear_cache()

    def test_missed_sales_and_counselling_routes_are_swept(self):
        from .sweep import protected_routes
        routes = list(protected_routes())
        self.assertGreater(self.log.classified, 300)
        for part in ('/api/pos-orders/missed-sales/', '/api/counselling/content/', '/api/tasks/'):
            self.assertTrue(any(p.startswith(part) for p in routes), part)

    # Owner question Q-5 (R3_enforce_readiness.md): missed sales live under /api/pos-orders/ (the
    # middleware maps it to `pos`) but the view checks `reservations` (suggestions are confirmed INTO
    # reservations, Project 3). Quality manager and viewer hold reservations view, not pos view, so in
    # log mode the view lets them read the list. Kept until the owner picks the module.
    MISSED_SALES_MODULE_QUESTION = {
        'quality_manager GET /api/pos-orders/missed-sales/',
        'quality_manager GET /api/pos-orders/missed-sales/987654321/',
        'viewer GET /api/pos-orders/missed-sales/',
        'viewer GET /api/pos-orders/missed-sales/987654321/',
    }

    def test_no_leak_in_either_mode(self):
        self.assertEqual(sorted(self.enforce.leaks), [])
        self.assertEqual(sorted(self.log.leaks - self.MISSED_SALES_MODULE_QUESTION), [])

    def test_no_crash(self):
        self.assertEqual(sorted(self.log.crashes | self.enforce.crashes), [])

    def test_denied_roles_never_reach_softech_or_outside(self):
        self.assertEqual(sorted(self.log.softech_reach | self.enforce.softech_reach
                                | self.log.outside_reach | self.enforce.outside_reach), [])


class UsagePrintGateTests(TestCase):
    """Project 5: /api/usage-print/ is EXEMPT in the middleware (own gate apps/usage_print/access.py:
    flag USAGE_PRINT_ENABLED + RBAC usage_print), so no role sweep covers it."""
    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        from apps.users.management.commands.seed_permissions import PERMISSIONS
        from apps.users.models import ROLE_CHOICES
        seed_code_matrix()
        b = make_branch('طباعة', 'UPB')
        cls.users = {r: make_user(f'up_{r}', role=r, branch=b)[0] for r, _ in ROLE_CHOICES}
        cls.has = {r: PERMISSIONS.get(r, {}).get('usage_print', set()) for r in cls.users}
        cls.has['admin'] = {'view', 'create', 'edit'}

    def _sweep(self, user):
        client = bearer_client(user)
        out = {}
        previous = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        try:
            with Tripwire():
                for path in _routes('/api/usage-print/'):
                    for m in METHODS:
                        if handles(path, m):
                            out[f'{m} {path}'] = _call(client, m, path)[0]
        finally:
            logging.disable(previous)
            _clear_cache()   # rolled-back requests still write the cache (locks, throttles)
        return out

    def test_routes_exist(self):
        self.assertGreaterEqual(len(_routes('/api/usage-print/')), 4)

    @override_settings(USAGE_PRINT_ENABLED=True)
    def test_roles_without_the_grant_are_refused(self):
        for role, user in self.users.items():
            got = self._sweep(user)
            if 'view' not in self.has[role]:
                bad = {k: v for k, v in got.items() if v not in _REFUSED}
                self.assertEqual(bad, {}, f'{role} has no usage_print view')
            elif 'edit' not in self.has[role]:
                bad = {k: v for k, v in got.items()
                       if '/settings/' in k and not k.startswith('GET') and v not in _REFUSED}
                self.assertEqual(bad, {}, f'{role} has no usage_print edit')

    @override_settings(USAGE_PRINT_ENABLED=False)
    def test_switch_off_closes_it_for_everyone(self):
        got = self._sweep(self.users['admin'])
        bad = {k: v for k, v in got.items() if v not in _REFUSED | {503}}
        self.assertEqual(bad, {})


@override_settings(COUNSELLING_CONTENT_ENABLED=True)
class CounsellingCurationReadTests(TestCase):
    """Round 2 R3 (owner default §8 Q5, matrix wins): the «يحتاج محتوى» list — the counselling
    screen's first tab — and similar-item suggestions are READS: every `counselling → view` holder
    gets them; writing and linking still need edit."""
    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        seed_code_matrix()
        b = make_branch('إرشاد', 'CSB')
        cls.sup = make_user('cs_sup', role='supervisor', branch=b)[0]
        cls.sales = make_user('cs_sales', role='salesperson', branch=b)[0]

    def test_view_holders_read_the_needs_queue(self):
        from apps.users.management.commands.seed_permissions import PERMISSIONS
        for user in (self.sup, self.sales):
            role = user.staff_profile.role
            if 'view' not in PERMISSIONS.get(role, {}).get('counselling', set()):
                continue
            self.assertEqual(bearer_client(user).get('/api/counselling/content/needs/').status_code, 200, role)

    def test_view_holders_still_cannot_link(self):
        c = bearer_client(self.sup)
        self.assertIn(c.post('/api/counselling/content/1/link/', {}, format='json').status_code, (403, 404))
