"""
apps/tests/security/test_d6_route_gate.py — round 2, owner decision D6.

130 views under a module prefix checked only IsAuthenticated, so in production (RBAC_ENFORCEMENT=log)
every signed-in staff member reached them whatever the matrix says. D6: give each the prefix's
module permission — core.permissions.RouteModulePermission, which asks module_access.required()
exactly as the middleware does, so it refuses what `enforce` would refuse and nothing more (no new
lockout; the role sweep's overblock baseline is the proof).

Left OUT of D6 (stop-and-ask areas — auth, POS, payments, customer money). Users, counselling cards
and cheque plans turned out to check inside the view (tests below pass); loyalty redeem / approve
got RouteModulePermission on the owner's answer Q-3 (2026-11-05).
"""
import logging

from django.db import transaction
from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory

from apps.tests.factories import make_branch, make_user
from core.middleware.module_access import required
from core.permissions import RouteModulePermission

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

    def test_loyalty_redeem_and_approve_follow_customers(self):
        self.assertEqual({**self._denied_reach('POST', '/api/loyalty/customers/987654321/redeem/'),
                          **self._denied_reach('POST', '/api/loyalty/redemptions/987654321/approve/')}, {})


@override_settings(RBAC_ENFORCEMENT='log', MISSED_SALES_ENABLED=True)
class OwnerAnswersR3Tests(TestCase):
    """Owner answers to R3_enforce_readiness.md (2026-11-05), checked in log mode — the view's own rule."""

    @classmethod
    def setUpTestData(cls):
        seed_code_matrix()
        b = make_branch('أجوبة', 'OAB')
        cls.c = {r: bearer_client(make_user(f'oa_{r}', role=r, branch=b)[0]) for r in NON_ADMIN_ROLES}

    def _code(self, role, method, path):
        with Tripwire():
            return _code(self.c[role], method, path) if method in ('GET', 'POST') else \
                getattr(self.c[role], method.lower())(path, {}, format='json').status_code

    def test_q7a_customer_writes_follow_the_matrix(self):
        for role in ('viewer', 'salesperson', 'delivery', 'quality_manager', 'purchasing'):
            self.assertEqual(self._code(role, 'PATCH', '/api/customers/987654321/'), 403, role)
            self.assertEqual(self._code(role, 'POST', '/api/customers/987654321/notes/'), 403, role)
        for role in NON_ADMIN_ROLES:
            self.assertEqual(self._code(role, 'DELETE', '/api/customers/987654321/'), 403, role)
        self.assertNotEqual(self._code('pharmacist', 'PATCH', '/api/customers/987654321/'), 403)

    def test_q3_loyalty_redeem_and_approve_need_the_grant(self):
        self.assertEqual(self._code('delivery', 'POST', '/api/loyalty/redemptions/987654321/approve/'), 403)
        self.assertEqual(self._code('viewer', 'POST', '/api/loyalty/customers/987654321/redeem/'), 403)

    def test_q7b_q7d_qa_inspections_and_insight_rules_follow_the_matrix(self):
        self.assertEqual(self._code('call_center', 'PUT', '/api/qa/inspections/987654321/'), 403)
        self.assertEqual(self._code('viewer', 'PUT', '/api/insights/rules/987654321/'), 403)
        self.assertEqual(self._code('pharmacist', 'DELETE', '/api/insights/rules/987654321/'), 403)

    def test_q7e_lines_need_edit_records_need_delete(self):
        # a reservation / shortage line: the document's edit is enough (salesperson holds it)
        self.assertNotEqual(self._code('salesperson', 'DELETE', '/api/reservations/987654321/lines/987654321/delete/'), 403)
        self.assertEqual(required('/api/demand/1/items/2/', 'DELETE'), ('demand', ('edit',)))
        # a whole record: the matrix's delete
        self.assertEqual(self._code('pharmacist', 'DELETE', '/api/demand/987654321/'), 403)
        self.assertEqual(self._code('pharmacist', 'DELETE', '/api/transfers/987654321/'), 403)
        self.assertEqual(self._code('call_center', 'DELETE', '/api/chronic/tags/987654321/'), 403)
        self.assertNotEqual(self._code('purchasing', 'DELETE', '/api/transfers/987654321/'), 403)

    def test_q5_missed_sales_are_the_reservations_module(self):
        self.assertEqual(required('/api/pos-orders/missed-sales/', 'GET'), ('reservations', ('view',)))
        for role in ('quality_manager', 'viewer'):
            self.assertNotEqual(self._code(role, 'GET', '/api/pos-orders/missed-sales/'), 403, role)


class Migration0052SeedingTests(TestCase):
    """users.0052 must not end fail-open on a module nobody seeded (CI on PR 75: transfers and supply
    answered 403 to everyone on a fresh database, because the accountant's deny rows looked like seeding)."""

    def _grant(self):
        import importlib

        from django.apps import apps
        importlib.import_module('apps.users.migrations.0052_round2_owner_grants_delete_analytics').grant(apps, None)

    def setUp(self):
        from apps.users.models import RoleModuleAccess
        self.RMA = RoleModuleAccess
        RoleModuleAccess.objects.all().delete()

    def test_accountant_rows_alone_are_not_seeding(self):
        self.RMA.objects.create(role='accountant', module='transfers', action='view', is_allowed=False)
        self._grant()
        self.assertFalse(self.RMA.objects.filter(role='purchasing', module='transfers').exists())

    def test_seeded_module_gets_the_grant(self):
        self.RMA.objects.create(role='pharmacist', module='transfers', action='view', is_allowed=True)
        self._grant()
        self.assertTrue(self.RMA.objects.get(role='purchasing', module='transfers', action='delete').is_allowed)
        self.assertFalse(self.RMA.objects.filter(role='purchasing', module='incentives').exists())
