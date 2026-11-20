"""
/api/users/my-permissions/ also says which modules the matrix has seeded (role review, final fix C1).

The server fails open on a module nobody has a RoleModuleAccess row for (core.permissions.matrix_allows);
the menu and route guards need the same list so a module-only menu item falls back to its old role
list on such a database instead of vanishing.
"""
from django.test import TestCase

from apps.tests.factories import make_user
from apps.users.models import RoleModuleAccess
from core.middleware import module_access


class MyPermissionsSeededTests(TestCase):

    def setUp(self):
        RoleModuleAccess.objects.all().delete()
        module_access.clear_cache()

    def tearDown(self):
        module_access.clear_cache()

    def _get(self, username, role='pharmacist'):
        _, _, client = make_user(username, role=role)
        res = client.get('/api/users/my-permissions/')
        self.assertEqual(res.status_code, 200)
        return res.json()

    def test_no_rows_means_no_seeded_modules(self):
        body = self._get('mps_none')
        self.assertEqual(body['seeded'], [])
        self.assertEqual(body['permissions'], {})

    def test_one_seeded_module_is_the_only_one_listed(self):
        RoleModuleAccess.objects.create(role='pharmacist', module='followups', action='view', is_allowed=False)
        module_access.clear_cache()
        body = self._get('mps_one')
        self.assertEqual(body['seeded'], ['followups'])

    def test_admin_also_gets_the_list(self):
        RoleModuleAccess.objects.create(role='pharmacist', module='delivery', action='view', is_allowed=True)
        module_access.clear_cache()
        body = self._get('mps_admin', role='admin')
        self.assertEqual(body['seeded'], ['delivery'])
