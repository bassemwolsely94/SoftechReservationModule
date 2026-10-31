from django.test import SimpleTestCase

from apps.users.management.commands.seed_permissions import ALL_MODULES

from .permission_matrix import BRANCH_SCOPE, DOC, render


class PermissionMatrixDocTests(SimpleTestCase):
    def test_every_module_has_a_branch_scope_entry(self):
        self.assertEqual(sorted(set(ALL_MODULES) - set(BRANCH_SCOPE)), [])

    def test_document_matches_the_code(self):
        self.assertTrue(DOC.exists(), f'{DOC} missing — run permission_matrix.write()')
        self.assertEqual(DOC.read_text(encoding='utf-8'), render(),
                         'docs/security/PERMISSION_MATRIX.md is stale — regenerate it '
                         '(see apps/tests/security/permission_matrix.py)')
