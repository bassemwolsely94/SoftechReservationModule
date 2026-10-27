"""
apps/tests/test_pos_rbac.py

Commerce-OS Phase 1: the indirect-POS module (`pos`) is now part of the RBAC
matrix. Verifies the matrix is authoritative for the push gate (deny-by-default
for a role with no grant), independent of the PUSH_ROLES fallback.
"""
from django.test import TestCase, RequestFactory

from apps.users.models import MODULE_CHOICES, RoleModuleAccess
from apps.pos_orders.permissions import CanPushPosOrders
from .factories import make_user


class PosModuleRegisteredTests(TestCase):
    def test_pos_in_module_choices(self):
        keys = {k for k, _ in MODULE_CHOICES}
        self.assertIn('pos', keys)


class PosMatrixAuthorityTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        # 'viewer' is NOT in the PUSH_ROLES fallback → isolates the matrix path.
        self.user, self.profile, _ = make_user('rbac_viewer', role='viewer')

    def _push_allowed(self, user):
        req = self.rf.post('/api/pos-orders/1/push/')
        req.user = user
        return CanPushPosOrders().has_permission(req, view=None)

    def test_denied_without_grant(self):
        self.assertFalse(self._push_allowed(self.user))

    def test_allowed_with_matrix_grant(self):
        RoleModuleAccess.objects.create(role='viewer', module='pos', action='create', is_allowed=True)
        self.assertTrue(self._push_allowed(self.user))

    def test_can_do_reflects_grant(self):
        self.assertFalse(self.profile.can_do('pos', 'create'))
        RoleModuleAccess.objects.create(role='viewer', module='pos', action='create', is_allowed=True)
        self.assertTrue(self.profile.can_do('pos', 'create'))
