"""GET /api/auth/roles/ serves the role registry; the permission matrix lists registry roles."""
from django.test import TestCase

from apps.users import roles

from .factories import make_admin, make_anon_client, make_viewer
from .role_planting import planted_role


class RolesApiTests(TestCase):
    def test_anonymous_is_rejected(self):
        self.assertEqual(make_anon_client().get('/api/auth/roles/').status_code, 401)

    def test_any_staff_role_gets_the_registry(self):
        _, _, client = make_viewer()
        res = client.get('/api/auth/roles/')
        self.assertEqual(res.status_code, 200)
        data = res.json()['roles']
        self.assertEqual(len(data), 10)
        self.assertEqual([r['value'] for r in data], [r.key for r in roles.ROLES])
        sup = next(r for r in data if r['value'] == 'supervisor')
        self.assertEqual(sup['label_ar'], 'مشرف')
        self.assertEqual(sup['label_en'], 'Supervisor')
        self.assertIn('description', sup)

    def test_planted_role_appears(self):
        _, _, client = make_viewer()
        with planted_role():
            values = [r['value'] for r in client.get('/api/auth/roles/').json()['roles']]
        self.assertIn('night_cashier', values)


class MatrixRolesTests(TestCase):
    def test_matrix_roles_come_from_registry_without_admin(self):
        _, _, client = make_admin()
        res = client.get('/api/users/permissions/')
        self.assertEqual(res.status_code, 200)
        data = res.json()['roles']
        values = [r['value'] for r in data]
        self.assertNotIn('admin', values)
        self.assertEqual(values, [r.key for r in roles.ROLES if r.key != 'admin'])
        qm = next(r for r in data if r['value'] == 'quality_manager')
        self.assertEqual(qm['label'], 'مدير الجودة')
        self.assertEqual(qm['label_en'], 'Quality manager')
