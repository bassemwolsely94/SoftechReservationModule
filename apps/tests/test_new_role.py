"""A new permission role is one registry line: it shows with its label, is branch-scoped, needs MFA
and fails closed (roles registry, piece 3). Planted with apps.tests.role_planting.planted_role()."""
from django.test import TestCase, override_settings

from apps.tests.factories import make_branch, make_branch2, make_user, make_viewer
from apps.tests.role_planting import planted_role
from apps.tests.security.fixtures import bearer_client
from apps.users import roles
from apps.users.models import RoleModuleAccess
from core import branch_scope
from core.middleware import module_access

ROUTE = '/api/customers/'   # module 'customers' (MODULE_BY_PREFIX), reads gated


class NewRoleEndToEndTests(TestCase):

    def setUp(self):
        RoleModuleAccess.objects.all().delete()
        module_access.clear_cache()

    def tearDown(self):
        module_access.clear_cache()

    def test_listed_with_its_label(self):
        _, _, client = make_viewer()
        with planted_role():
            data = client.get('/api/auth/roles/').json()['roles']
        row = next(r for r in data if r['value'] == 'night_cashier')
        self.assertEqual(row['label_ar'], 'كاشير ليلي')
        self.assertEqual(row['label_en'], 'Night cashier')
        self.assertNotIn('night_cashier', [r['value'] for r in
                                           client.get('/api/auth/roles/').json()['roles']])

    def test_branch_scoped_to_own_branch(self):
        own, other = make_branch(), make_branch2()
        with planted_role():
            _, profile, _ = make_user('nc_scoped', role='night_cashier', branch=own)
            self.assertEqual(branch_scope.branch_ids(profile), {own.id})
            self.assertNotIn(other.id, branch_scope.branch_ids(profile))

    def test_mfa_required_by_default(self):
        with planted_role():
            self.assertIn('night_cashier', roles.MFA_REQUIRED_ROLES)
        self.assertNotIn('night_cashier', roles.MFA_REQUIRED_ROLES)

    @override_settings(RBAC_ENFORCEMENT='log', RBAC_ENFORCED_ROLES=())
    def test_unseeded_module_route_is_refused_in_log_mode(self):
        with planted_role():
            cashier = bearer_client(make_user('nc_http', role='night_cashier')[0])
            pharmacist = bearer_client(make_user('nc_ph', role='pharmacist')[0])
            self.assertEqual(cashier.get(ROUTE).status_code, 403)
            # the same route lets a legacy role through in log mode: the 403 is the new role's
            self.assertNotEqual(pharmacist.get(ROUTE).status_code, 403)
