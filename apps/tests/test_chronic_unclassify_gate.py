"""DELETE /api/chronic/items/<id>/unclassify/ follows the matrix's chronic delete (owner fix 2026-11-18).

ItemClassifierViewSet checked only the chronic module grant, so in RBAC log mode call_center,
pharmacist and supervisor could unlink an item's ingredient (role sweep). It now carries
RouteModuleDeletePermission like the other chronic viewsets; classify (POST) is unchanged."""
from django.db import transaction
from django.test import TestCase

from apps.tests.factories import make_branch, make_user
from apps.tests.security.fixtures import bearer_client, seed_code_matrix
from core.middleware.module_access import required

PATH = '/api/chronic/items/987654321/unclassify/'


class ChronicUnclassifyGateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_code_matrix()
        b = make_branch('مزمن', 'CUG')
        cls.users = {r: make_user(f'cug_{r}', role=r, branch=b)[0]
                     for r in ('call_center', 'pharmacist', 'supervisor', 'admin')}

    def _code(self, role, method, path):
        client = bearer_client(self.users[role])
        with transaction.atomic():
            r = getattr(client, method)(path, {}, format='json')
            transaction.set_rollback(True)
        return r.status_code

    def test_route_needs_the_chronic_delete_right(self):
        self.assertEqual(required(PATH, 'DELETE')[0], 'chronic')

    def test_roles_without_chronic_delete_are_refused(self):
        for role in ('call_center', 'pharmacist', 'supervisor'):
            self.assertEqual(self._code(role, 'delete', PATH), 403, role)

    def test_admin_still_reaches_the_view(self):
        self.assertNotEqual(self._code('admin', 'delete', PATH), 403)

    def test_reading_is_not_changed_by_the_delete_gate(self):
        self.assertNotEqual(self._code('pharmacist', 'get', '/api/chronic/items/summary/'), 403)
