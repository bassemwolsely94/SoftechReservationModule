"""
RBAC — a role added to the registry (apps/users/roles.py) fails closed (roles registry, piece 3).

The ten roles of 2026-11 carry legacy_rbac_mode=True and keep following RBAC_ENFORCEMENT (log /
enforce) and the per-module "not seeded yet" fail-open exactly as before. A role added later
(legacy_rbac_mode=False, the default) — or any role string in the database the registry does not
know — is matrix-enforced in every mode: no grant row, no access.

The new role is planted with apps.tests.role_planting.planted_role(), which adds
Role('night_cashier', ...) to the registry and swaps every derived constant (and every module's
import-time copy of one) for the length of the block.
"""
from django.test import TestCase, override_settings

from apps.tests.factories import make_user
from apps.tests.role_planting import planted_role
from apps.users import roles
from apps.users.models import RoleModuleAccess
from core.middleware import module_access
from core.permissions import matrix_allows

EXISTING = ('admin', 'call_center', 'pharmacist', 'salesperson', 'purchasing', 'delivery',
            'viewer', 'supervisor', 'quality_manager', 'accountant')


class PlantedRoleHelperTests(TestCase):

    def test_planting_swaps_every_copy_and_restores(self):
        from apps.users import models as user_models
        from core import branch_scope
        with planted_role(all_branches=True) as role:
            self.assertEqual(role.key, 'night_cashier')
            self.assertTrue(roles.is_known('night_cashier'))
            self.assertIn('night_cashier', roles.ROLE_KEYS)
            self.assertNotIn('night_cashier', roles.LEGACY_RBAC_ROLES)
            self.assertIn('night_cashier', roles.MFA_REQUIRED_ROLES)
            self.assertIn(('night_cashier', 'Night cashier'), user_models.ROLE_CHOICES)
            self.assertIn('night_cashier', user_models.MFA_REQUIRED_ROLES)
            self.assertIn('night_cashier', branch_scope.ALL_BRANCH_ROLES)
        self.assertFalse(roles.is_known('night_cashier'))
        self.assertEqual(roles.ROLE_KEYS, EXISTING)
        self.assertIs(user_models.ROLE_CHOICES, roles.ROLE_CHOICES)
        self.assertNotIn('night_cashier', branch_scope.ALL_BRANCH_ROLES)


class NewRoleFailsClosedTests(TestCase):

    def setUp(self):
        RoleModuleAccess.objects.all().delete()
        module_access.clear_cache()

    def tearDown(self):
        module_access.clear_cache()

    @override_settings(RBAC_ENFORCEMENT='log', RBAC_ENFORCED_ROLES=())
    def test_new_role_enforced_in_log_mode(self):
        with planted_role():
            self.assertEqual(module_access._mode_for('night_cashier'), 'enforce')
            self.assertEqual(module_access._mode_for('pharmacist'), 'log')

    def test_unknown_db_role_enforced(self):
        self.assertTrue(module_access.is_enforced('legacy_garbage'))
        self.assertTrue(module_access.is_enforced(None))   # a profile whose role is empty

    def test_new_role_unseeded_module_denied(self):
        with planted_role():
            cashier = make_user('nr_cashier', role='night_cashier')[1]
            pharmacist = make_user('nr_ph', role='pharmacist')[1]
            self.assertFalse(matrix_allows(cashier, 'catalog', 'view'))
            self.assertTrue(matrix_allows(pharmacist, 'catalog', 'view'))   # unchanged fail-open

    def test_new_role_rows_do_not_seed_module(self):
        with planted_role():
            RoleModuleAccess.objects.create(role='night_cashier', module='catalog', action='view',
                                            is_allowed=True)
            module_access.clear_cache()
            self.assertIn('night_cashier', module_access.enforced_roles())
            self.assertNotIn('catalog', module_access.seeded_modules())

    def test_existing_roles_unchanged(self):
        for configured in ('accountant', ()):
            with override_settings(RBAC_ENFORCED_ROLES=configured):
                expected = module_access.enforced_roles()
                self.assertEqual(expected, frozenset({'accountant'} if configured else ()))
                for key in EXISTING:
                    with self.subTest(configured=configured, role=key):
                        self.assertEqual(module_access.is_enforced(key), key in expected)
