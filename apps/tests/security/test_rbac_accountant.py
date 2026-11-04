"""
apps/tests/security/test_rbac_accountant.py

Finance GL owner ruling: the `accountant` is a finance-department role — ledger {view, create,
approve, export}, finance {view, export}, cheques {view}, dashboard {view}, tasks; nothing else.
It is an all-branch role (core.branch_scope, ruling R7), so a view that only checks
IsAuthenticated / all-branch would let it through: RBAC_ENFORCED_ROLES makes the middleware
refuse it even while production runs RBAC_ENFORCEMENT=log.
"""
import importlib

from django.test import TestCase, override_settings

from apps.users.management.commands.seed_permissions import ALL_ACTIONS, ALL_MODULES, PERMISSIONS
from core.middleware import module_access

from .fixtures import bearer_client, seed_code_matrix
from .routes import Tripwire
from apps.tests.factories import make_user

DECIDED = {
    'ledger': {'view', 'create', 'approve', 'export'},
    'finance': {'view', 'export'},
    'cheques': {'view'},
    'dashboard': {'view'},
    'tasks': {'view', 'create', 'edit', 'delete', 'assign', 'finalize'},
}


class AccountantMatrixTests(TestCase):

    def test_code_matrix_is_the_decided_grant_and_nothing_else(self):
        self.assertEqual({m: a for m, a in PERMISSIONS['accountant'].items() if a}, DECIDED)

    def test_only_admin_and_accountant_hold_ledger(self):
        holders = {r for r, mods in PERMISSIONS.items() if mods.get('ledger')}
        self.assertEqual(holders, {'admin', 'accountant'})

    def test_migration_seeds_an_explicit_row_for_every_module(self):
        mig = importlib.import_module('apps.users.migrations.0051_accountant_explicit_denials')
        self.assertEqual(set(mig.MODULES), set(ALL_MODULES))
        self.assertEqual(mig.ACTIONS, ALL_ACTIONS)
        self.assertEqual(mig.GRANTED, DECIDED)


@override_settings(RBAC_ENFORCEMENT='log')
class AccountantEnforcedInLogModeTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.client = bearer_client(make_user('acc_rbac', role='accountant')[0])

    def tearDown(self):
        module_access.clear_cache()

    def _get(self, path):
        with Tripwire():
            return self.client.get(path)

    def test_modules_without_a_grant_are_refused(self):
        for path in ('/api/hr/', '/api/customers/', '/api/qa/', '/api/enrichment/', '/api/products/',
                     '/api/referral/', '/api/loyalty/customers/'):
            with self.subTest(path=path):
                self.assertEqual(self._get(path).status_code, 403)

    def test_ledger_write_needs_the_ledger_grant_not_finance(self):
        self.assertEqual(module_access.required('/api/finance/gl/entries/', 'POST')[0], 'ledger')
        self.assertEqual(module_access.required('/api/finance/reconciliation/unpaid/', 'GET')[0], 'finance')
        # each write needs exactly the view's grant: accountant holds create/approve, not edit
        req = module_access.required
        self.assertEqual(req('/api/finance/gl/entries/', 'POST'), ('ledger', ('create',)))
        self.assertEqual(req('/api/finance/gl/entries/5/', 'PUT'), ('ledger', ('create',)))
        self.assertEqual(req('/api/finance/gl/entries/5/', 'DELETE'), ('ledger', ('create',)))
        self.assertEqual(req('/api/finance/gl/entries/5/approve/', 'POST'), ('ledger', ('approve',)))
        self.assertEqual(req('/api/finance/gl/entries/approve/', 'POST'), ('ledger', ('approve',)))
        self.assertEqual(req('/api/finance/gl/entries/5/reverse/', 'POST'), ('ledger', ('approve',)))
        self.assertEqual(req('/api/finance/gl/accounts/1101/', 'PATCH'), ('ledger', ('edit',)))
        self.assertEqual(req('/api/finance/gl/accounts/import/', 'POST'), ('ledger', ('edit',)))

    def test_other_roles_keep_log_mode(self):
        self.assertEqual(module_access._mode_for('pharmacist'), 'log')
        self.assertEqual(module_access._mode_for('accountant'), 'enforce')

    @override_settings(RBAC_ENFORCEMENT='off')
    def test_off_stays_off(self):
        self.assertEqual(module_access._mode_for('accountant'), 'off')


class EnforcedRolesDoNotSeedTests(TestCase):
    """R17: an enforced role's rows (users.0051 writes accountant deny rows for every module) never
    end another role's fail-open on a module nobody else has rows for; the enforced role itself
    never fails open."""

    def setUp(self):
        from apps.users.models import RoleModuleAccess
        RoleModuleAccess.objects.all().delete()
        RoleModuleAccess.objects.create(role='accountant', module='replacement', action='view',
                                        is_allowed=False)
        module_access.clear_cache()
        self.ph = make_user('r17_ph', role='pharmacist')[1]
        self.acc = make_user('r17_acc', role='accountant')[1]

    def tearDown(self):
        module_access.clear_cache()

    def test_accountant_rows_do_not_seed_a_module(self):
        self.assertNotIn('replacement', module_access.seeded_modules())

    def test_other_roles_keep_the_unseeded_fallback(self):
        from core.permissions import matrix_allows
        from apps.replacement import authz
        self.assertTrue(matrix_allows(self.ph, 'replacement', 'view'))
        self.assertEqual(authz.role_allows(self.ph, 'create'),
                         self.ph.role in authz.FALLBACK_ROLES['create'])

    def test_enforced_role_never_fails_open(self):
        from core.permissions import matrix_allows
        self.assertFalse(matrix_allows(self.acc, 'replacement', 'view'))
        self.assertFalse(matrix_allows(self.acc, 'customers', 'view'))      # no rows at all
