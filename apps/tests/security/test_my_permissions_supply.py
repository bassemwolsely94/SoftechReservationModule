"""
/api/users/my-permissions/ tells a SOFTECH supply-group member what the server already allows: the
purchasing role's purchasing grants, whatever their app role (module_access.supply_member, Z-2).

UAT W2 (2026-11-19): the procurement screens got a matrix route guard; without this the browser
would have sent supply-group members away from screens the server serves them.
"""
from django.test import TestCase

from apps.tests.factories import make_user
from apps.users.models import ERPUser
from core.middleware import module_access

from .fixtures import seed_code_matrix


class MyPermissionsSupplyTests(TestCase):

    def setUp(self):
        seed_code_matrix()

    def tearDown(self):
        module_access.clear_cache()

    def _perms(self, username, role='salesperson'):
        _, _, client = make_user(username, role=role)
        res = client.get('/api/users/my-permissions/')
        self.assertEqual(res.status_code, 200)
        return res.json()['permissions']

    def test_supply_group_member_gets_the_purchasing_grants(self):
        ERPUser.objects.create(username='mp_store', full_name='Store Keeper', user_group='19', is_active=True)
        perms = self._perms('mp_store')
        self.assertTrue(perms.get('purchasing', {}).get('view'))
        # only the purchasing module — not the purchasing role's other modules
        self.assertFalse(perms.get('insurance', {}).get('view'))

    def test_other_staff_unchanged(self):
        perms = self._perms('mp_plain')
        self.assertFalse(perms.get('purchasing', {}).get('view'))

    def test_inactive_softech_user_is_not_a_supply_member(self):
        ERPUser.objects.create(username='mp_gone', full_name='Gone', user_group='19', is_active=False)
        perms = self._perms('mp_gone')
        self.assertFalse(perms.get('purchasing', {}).get('view'))
