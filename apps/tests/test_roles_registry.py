from django.test import SimpleTestCase

from apps.users import roles

LITERAL_CHOICES = [
    ('admin',           'Admin — Full Access'),
    ('call_center',     'Call Center — All Branches'),
    ('pharmacist',      'Pharmacist — Own Branch'),
    ('salesperson',     'Sales Person — Own Branch'),
    ('purchasing',      'Purchasing — HQ Only'),
    ('delivery',        'Delivery'),
    ('viewer',          'Viewer — Read Only'),
    ('supervisor',      'Supervisor — Call Center Supervisor'),
    ('quality_manager', 'Quality Manager — QA & Scoring'),
    ('accountant',      'Accountant — General Ledger'),
]


class RolesRegistryTests(SimpleTestCase):
    def test_role_choices_unchanged(self):
        self.assertEqual(roles.ROLE_CHOICES, LITERAL_CHOICES)

    def test_all_branch_roles_unchanged(self):
        self.assertEqual(roles.ALL_BRANCH_ROLES, (
            'admin', 'call_center', 'purchasing', 'supervisor', 'quality_manager', 'accountant'))

    def test_mfa_roles_unchanged(self):
        self.assertEqual(roles.MFA_REQUIRED_ROLES, frozenset({'admin', 'supervisor', 'purchasing'}))

    def test_legacy_roles_are_all_existing(self):
        self.assertEqual(roles.LEGACY_RBAC_ROLES, frozenset(k for k, _ in LITERAL_CHOICES))

    def test_every_role_has_labels(self):
        for r in roles.ROLES:
            self.assertTrue(r.label_ar and r.label_en, r.key)

    def test_unknown_role_label_is_key(self):
        self.assertEqual(roles.role_label('zzz'), 'zzz')
        self.assertFalse(roles.is_known('zzz'))
        self.assertTrue(roles.is_known('admin'))

    def test_labels_by_language(self):
        self.assertEqual(roles.role_label('admin'), 'مدير النظام')
        self.assertEqual(roles.role_label('admin', 'en'), 'Admin')

    def test_new_role_defaults_fail_closed(self):
        r = roles.Role('x', 'x', 'x', 'x')
        self.assertFalse(r.all_branches)
        self.assertTrue(r.mfa_required)
        self.assertFalse(r.legacy_rbac_mode)

    def test_as_api_shape_and_order(self):
        api = roles.as_api()
        self.assertEqual([a['value'] for a in api], list(roles.ROLE_KEYS))
        self.assertEqual(set(api[0]), {'value', 'label_ar', 'label_en', 'description'})

    def test_models_reexport(self):
        from apps.users import models
        from core import branch_scope
        self.assertIs(models.ROLE_CHOICES, roles.ROLE_CHOICES)
        self.assertEqual(models.MFA_REQUIRED_ROLES, roles.MFA_REQUIRED_ROLES)
        self.assertEqual(branch_scope.ALL_BRANCH_ROLES, roles.ALL_BRANCH_ROLES)
