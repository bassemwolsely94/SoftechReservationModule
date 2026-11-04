"""Finance GL Task 1 — `accountant` role and `ledger` RBAC module."""
from django.core.management import call_command
from django.test import TestCase

from apps.tests.factories import make_user
from core.permissions import matrix_allows

OTHER_ROLES = ['admin', 'call_center', 'pharmacist', 'salesperson', 'purchasing', 'delivery',
               'viewer', 'supervisor', 'quality_manager']


class LedgerPermissionTests(TestCase):
    def setUp(self):
        call_command('seed_permissions', verbosity=0)

    def test_accountant_has_ledger_view_create_approve_export(self):
        _, profile, _ = make_user('acct1', role='accountant')
        for action in ('view', 'create', 'approve', 'export'):
            self.assertTrue(matrix_allows(profile, 'ledger', action), action)
        self.assertTrue(matrix_allows(profile, 'finance', 'view'))
        self.assertTrue(matrix_allows(profile, 'finance', 'export'))
        self.assertTrue(matrix_allows(profile, 'cheques', 'view'))
        self.assertTrue(matrix_allows(profile, 'dashboard', 'view'))

    def test_accountant_lacks_ledger_edit_and_finalize(self):
        _, profile, _ = make_user('acct2', role='accountant')
        for action in ('edit', 'finalize', 'delete'):
            self.assertFalse(matrix_allows(profile, 'ledger', action), action)
        self.assertFalse(matrix_allows(profile, 'finance', 'edit'))
        self.assertFalse(matrix_allows(profile, 'cheques', 'edit'))

    def test_other_roles_have_no_ledger_access(self):
        for role in OTHER_ROLES:
            if role == 'admin':
                continue
            _, profile, _ = make_user(f'u_{role}', role=role)
            for action in ('view', 'create', 'edit', 'approve', 'export', 'finalize'):
                self.assertFalse(matrix_allows(profile, 'ledger', action), (role, action))

    def test_admin_bypasses(self):
        _, profile, _ = make_user('adm1', role='admin', access_all=True)
        for action in ('view', 'edit', 'finalize'):
            self.assertTrue(matrix_allows(profile, 'ledger', action))


class AccountantBranchScopeTests(TestCase):
    def test_accountant_sees_everything(self):
        from core import branch_scope
        _, profile, _ = make_user('acct_scope', role='accountant', access_all=False)
        self.assertFalse(profile.access_all_branches)
        self.assertTrue(branch_scope.sees_everything(profile))
