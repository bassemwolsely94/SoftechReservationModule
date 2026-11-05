"""
apps/tests/security/test_d6_route_gate.py — round 2, owner decision D6.

130 views under a module prefix checked only IsAuthenticated, so in production (RBAC_ENFORCEMENT=log)
every signed-in staff member reached them whatever the matrix says. D6: give each the prefix's
module permission — core.permissions.RouteModulePermission, which asks module_access.required()
exactly as the middleware does, so it refuses what `enforce` would refuse and nothing more (no new
lockout; the role sweep's overblock baseline is the proof).

Left OUT of D6 (stop-and-ask areas — auth, POS, payments, customer money). Users, counselling cards
and cheque plans turned out to check inside the view (tests below pass); loyalty redeem / approve
does not: @pending('D-64') with the one-line diff in PENDING.md.
"""
import logging

from django.db import transaction
from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory

from apps.tests.factories import make_branch, make_user
from core.middleware.module_access import required
from core.permissions import RouteModulePermission

from .baseline import pending
from .fixtures import NON_ADMIN_ROLES, bearer_client, granted, seed_code_matrix
from .routes import Tripwire

_REFUSED = {401, 403, 405}


def _code(client, method, path):
    try:
        with transaction.atomic():
            r = client.get(path) if method == 'GET' else client.post(path, {}, format='json')
            transaction.set_rollback(True)
        return r.status_code
    except Exception as exc:          # noqa: BLE001
        return f'raised {type(exc).__name__}'


def _clear_cache():
    from django.core.cache import cache
    cache.clear()


class RouteModulePermissionTests(TestCase):
    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        seed_code_matrix()
        b = make_branch('بوابة', 'D6B')
        cls.users = {r: make_user(f'd6_{r}', role=r, branch=b)[0] for r in NON_ADMIN_ROLES + ['admin']}

    def _perm(self, user, method, path):
        req = getattr(APIRequestFactory(), method.lower())(path)
        req.user = user

        class V:
            def get(self): ...
            def post(self): ...
        return RouteModulePermission().has_permission(req, V())

    def test_matches_the_middleware_for_every_role(self):
        for path, method in (('/api/delivery/', 'GET'), ('/api/delivery/1/accept/', 'POST'),
                             ('/api/hr/leave-requests/', 'POST'), ('/api/loyalty/tiers/', 'GET'),
                             ('/api/products/', 'GET'), ('/api/referral/leads/', 'GET')):
            module, actions = required(path, method)
            for role, user in self.users.items():
                self.assertEqual(self._perm(user, method, path), granted(role, module, actions),
                                 f'{role} {method} {path}')

    def test_paths_the_middleware_does_not_check_pass(self):
        for path in ('/api/sync/freshness/', '/api/cheques/holidays/', '/api/incentives/my-progress/',
                     '/api/items/', '/api/branches/'):
            self.assertIsNone(required(path, 'GET'), path)
            self.assertTrue(self._perm(self.users['viewer'], 'GET', path), path)

    def test_admin_always_passes(self):
        self.assertTrue(self._perm(self.users['admin'], 'POST', '/api/delivery/1/accept/'))


# ── D6 exclusions: stop-and-ask, owner approves the diff (PENDING.md) ────────────────────────────

class D6PendingTests(TestCase):
    """In log mode, a role the matrix denies must be refused by the VIEW (403), before any lookup."""
    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        seed_code_matrix()
        b = make_branch('معلّق', 'D6P')
        cls.users = {r: make_user(f'd6p_{r}', role=r, branch=b)[0] for r in NON_ADMIN_ROLES}

    def _denied_reach(self, method, path):
        module, actions = required(path, method)
        reached = {}
        previous = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        try:
            with override_settings(RBAC_ENFORCEMENT='log', COUNSELLING_CONTENT_ENABLED=True), Tripwire():
                for role, user in self.users.items():
                    if granted(role, module, actions):
                        continue
                    code = _code(bearer_client(user), method, path)
                    if code not in _REFUSED:
                        reached[role] = code
        finally:
            logging.disable(previous)
            _clear_cache()   # rolled-back requests still write the cache (locks, throttles)
        return reached

    def test_staff_profile_detail_and_permissions_matrix_follow_users(self):
        self.assertEqual({**self._denied_reach('GET', '/api/users/staff/987654321/'),
                          **self._denied_reach('GET', '/api/users/permissions/')}, {})

    def test_counselling_assistant_and_cards_follow_pos(self):
        self.assertEqual({**self._denied_reach('GET', '/api/counselling/assistant/987654321/'),
                          **self._denied_reach('POST', '/api/counselling/cards/preview/'),
                          **self._denied_reach('POST', '/api/counselling/cards/send/')}, {})

    def test_cheque_plan_writes_follow_cheques(self):
        self.assertEqual({**self._denied_reach('POST', '/api/cheques/plans/987654321/activate/'),
                          **self._denied_reach('POST', '/api/cheques/plans/987654321/cancel/')}, {})

    @pending('D-64')
    def test_loyalty_redeem_and_approve_follow_customers(self):
        self.assertEqual({**self._denied_reach('POST', '/api/loyalty/customers/987654321/redeem/'),
                          **self._denied_reach('POST', '/api/loyalty/redemptions/987654321/approve/')}, {})
