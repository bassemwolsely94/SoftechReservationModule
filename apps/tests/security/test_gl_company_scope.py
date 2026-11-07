"""
apps/tests/security/test_gl_company_scope.py — round 2, R4 step 4.

The General Ledger (apps/finance/gl, doc 35) has no branch field to scope by: it is company-level
finance (owner decision B-1, ruling R7). Its only branch rule is "all-branch users only"
(views.AllBranchOnly → core.branch_scope.sees_everything). The canary sweep cannot see that — there
is no branch row to plant — so this test checks it directly:

  • every branch-scoped role, even holding EVERY ledger action in the matrix, is refused on every
    /api/finance/gl/ route and method — in log mode (the view's own check) and in enforce mode;
  • a branch user lifted to all branches (access_all_branches) passes the branch rule, so the test
    proves it is the branch rule, not a missing grant, that refuses;
  • positive control: the accountant (all-branch role, code matrix) reads the chart of accounts.
"""
import logging

from django.db import transaction
from django.test import TestCase, override_settings

from apps.tests.factories import make_branch, make_user
from apps.users.management.commands.seed_permissions import ALL_ACTIONS
from apps.users.models import ROLE_CHOICES, RoleModuleAccess
from core.branch_scope import ALL_BRANCH_ROLES
from core.middleware import module_access

from .fixtures import bearer_client, seed_code_matrix
from .routes import Tripwire, api_routes, handles

PREFIX = '/api/finance/gl/'
METHODS = ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')
BRANCH_ROLES = [r for r, _ in ROLE_CHOICES if r not in ALL_BRANCH_ROLES]


def _routes():
    return sorted({p for p, _ in api_routes() if p.startswith(PREFIX)})


def _code(client, method, path):
    try:
        with transaction.atomic():
            if method == 'GET':
                r = client.get(path)
            elif method == 'DELETE':
                r = client.delete(path)
            else:
                r = getattr(client, method.lower())(path, {}, format='json')
            transaction.set_rollback(True)
        return r.status_code
    except Exception as exc:          # noqa: BLE001
        return f'raised {type(exc).__name__}'


def _clear_cache():
    from django.core.cache import cache
    cache.clear()


class GlCompanyScopeTests(TestCase):
    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        seed_code_matrix()
        # every role holds every ledger action: only the all-branch rule can refuse now
        RoleModuleAccess.objects.filter(module='ledger', action__in=ALL_ACTIONS).update(is_allowed=True)
        module_access.clear_cache()
        cls.branch = make_branch('دفتر', 'GLB')
        cls.users = {r: make_user(f'gl_{r}', role=r, branch=cls.branch)[0] for r in BRANCH_ROLES}
        cls.lifted = make_user('gl_lifted', role='pharmacist', branch=cls.branch, access_all=True)[0]
        cls.accountant = make_user('gl_acc', role='accountant', branch=cls.branch)[0]

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        module_access.clear_cache()

    def _sweep(self, user, mode):
        client = bearer_client(user)
        out = {}
        previous = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        try:
            with override_settings(RBAC_ENFORCEMENT=mode), Tripwire():
                for path in _routes():
                    for m in METHODS:
                        if handles(path, m):
                            out[f'{m} {path}'] = _code(client, m, path)
        finally:
            logging.disable(previous)
            _clear_cache()   # rolled-back requests still write the cache (locks, throttles)
        return out

    def test_there_are_gl_routes_and_branch_roles(self):
        self.assertGreater(len(_routes()), 15)
        self.assertIn('pharmacist', BRANCH_ROLES)
        self.assertNotIn('accountant', BRANCH_ROLES)

    def test_branch_roles_refused_on_every_gl_route(self):
        for mode in ('log', 'enforce'):
            for role, user in self.users.items():
                got = self._sweep(user, mode)
                bad = {k: v for k, v in got.items() if v not in (401, 403, 405)}
                self.assertEqual(bad, {}, f'{role} ({mode}) reached the company ledger')

    def test_refusal_is_the_branch_rule(self):
        """The same pharmacist lifted to all branches gets past the gate on the reads."""
        client = bearer_client(self.lifted)
        with override_settings(RBAC_ENFORCEMENT='log'), Tripwire():
            self.assertEqual(_code(client, 'GET', f'{PREFIX}accounts/'), 200)

    def test_accountant_reads_the_chart_of_accounts(self):
        client = bearer_client(self.accountant)
        with override_settings(RBAC_ENFORCEMENT='enforce'), Tripwire():
            self.assertEqual(_code(client, 'GET', f'{PREFIX}accounts/'), 200)
