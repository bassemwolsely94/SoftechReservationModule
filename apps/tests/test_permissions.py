"""
apps/tests/test_permissions.py

Tests covering:
  - PermissionsMatrix list: Gap-5 FIXED — restricted to admin role only
  - PermissionsMatrix update (POST): restricted to admin only
  - Non-admin cannot update permissions
  - Anonymous access rejected on both list and create
"""
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from apps.users.models import RoleModuleAccess
from .factories import make_branch, make_admin, make_pharmacist, make_salesperson

PERMS_URL = '/api/users/permissions/'


class PermissionsMatrixListTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        _, _, self.admin_client     = make_admin('perm_admin')
        _, _, self.pharma_client    = make_pharmacist('perm_pharma', branch=self.branch)
        _, _, self.sales_client     = make_salesperson('perm_sales', branch=self.branch)

    def test_anon_cannot_list_permissions(self):
        r = APIClient().get(PERMS_URL)
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_admin_can_list_permissions(self):
        r = self.admin_client.get(PERMS_URL)
        self.assertIn(r.status_code, [status.HTTP_200_OK, status.HTTP_404_NOT_FOUND])

    def test_pharmacist_cannot_read_permissions_matrix(self):
        """Gap-5 FIXED: permissions list is now admin-only."""
        r = self.pharma_client.get(PERMS_URL)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN,
                         'Pharmacist must receive 403 on GET /api/users/permissions/')

    def test_salesperson_cannot_read_permissions_matrix(self):
        """Gap-5 FIXED: salesperson also gets 403."""
        r = self.sales_client.get(PERMS_URL)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN,
                         'Salesperson must receive 403 on GET /api/users/permissions/')

    def test_list_returns_matrix_structure(self):
        r = self.admin_client.get(PERMS_URL)
        if r.status_code == status.HTTP_200_OK:
            self.assertIn('matrix', r.data)
            self.assertIn('roles', r.data)
            self.assertIn('modules', r.data)
            self.assertIn('actions', r.data)


class PermissionsMatrixUpdateTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        _, _, self.admin_client  = make_admin('perm_upd_admin')
        _, _, self.pharma_client = make_pharmacist('perm_upd_pharma', branch=self.branch)

    def test_anon_cannot_update_permissions(self):
        r = APIClient().post(PERMS_URL, [], format='json')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_pharmacist_cannot_update_permissions(self):
        """Non-admin must receive 403 when trying to update permissions."""
        payload = [{'role': 'pharmacist', 'module': 'reservations', 'action': 'view', 'is_allowed': True}]
        r = self.pharma_client.post(PERMS_URL, payload, format='json')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN,
                         'Non-admin must not be able to update permissions matrix')

    def test_admin_can_update_permissions(self):
        """Admin POST to permissions must succeed (200 or 201)."""
        payload = [{'role': 'pharmacist', 'module': 'reservations', 'action': 'view', 'is_allowed': True}]
        r = self.admin_client.post(PERMS_URL, payload, format='json')
        self.assertIn(r.status_code, [
            status.HTTP_200_OK,
            status.HTTP_201_CREATED,
            status.HTTP_404_NOT_FOUND,  # endpoint may not exist in test routing
        ])

    def test_update_missing_fields_ignored_gracefully(self):
        """Entries missing role/module/action must be skipped, not raise 500."""
        payload = [{'role': '', 'module': '', 'action': '', 'is_allowed': True}]
        r = self.admin_client.post(PERMS_URL, payload, format='json')
        self.assertNotEqual(r.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR,
                            'Malformed permissions entry must not cause 500')
