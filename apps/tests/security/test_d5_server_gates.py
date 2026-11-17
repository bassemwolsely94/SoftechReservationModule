"""
UAT D5 + owner follow-up (2026-11-17): phone alerts and announcement publishing follow the role
matrix on the server too — their own module «التنبيهات والإعلانات» (`alerts`): view to read the
phone-alert screens, edit to change policies, create to publish. Seeded for admin + supervisor
(users 0058); any other role is refused unless the owner grants it. e2e/menu-api.spec.js checks that
a screen the menu hides is refused by its API.
"""
from django.test import TestCase

from apps.tests.factories import make_branch, make_user

from .fixtures import bearer_client, seed_code_matrix

POLICIES = '/api/notifications/phone-alerts/policies/'
ANNOUNCE = '/api/notifications/announcements/'


class AlertsModuleGateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_code_matrix()
        cls.branch = make_branch('D5', softech_id='D51')
        cls.sup = make_user('d5_sup', role='supervisor', branch=cls.branch)[1]
        cls.pharm = make_user('d5_pharm', role='pharmacist', branch=cls.branch)[1]
        cls.admin = make_user('d5_admin', role='admin', branch=cls.branch, access_all=True)[1]

    def _revoke(self, role, action):
        from apps.users.models import RoleModuleAccess
        from core.middleware import module_access
        RoleModuleAccess.objects.filter(role=role, module='alerts', action=action).update(is_allowed=False)
        module_access.clear_cache()

    def test_supervisor_reads_phone_alerts_by_default(self):
        self.assertEqual(bearer_client(self.sup.user).get(POLICIES).status_code, 200)

    def test_supervisor_publishes_by_default(self):
        r = bearer_client(self.sup.user).post(ANNOUNCE, {'title': 'x', 'body': 'y'}, format='json')
        self.assertNotEqual(r.status_code, 403, r.content[:200])

    def test_role_without_the_module_refused(self):
        c = bearer_client(self.pharm.user)
        self.assertEqual(c.get(POLICIES).status_code, 403)
        self.assertEqual(c.post(ANNOUNCE, {'title': 'x', 'body': 'y'}, format='json').status_code, 403)

    def test_matrix_change_takes_the_access_away(self):
        self._revoke('supervisor', 'view')
        self._revoke('supervisor', 'create')
        c = bearer_client(self.sup.user)
        self.assertEqual(c.get(POLICIES).status_code, 403)
        self.assertEqual(c.post(ANNOUNCE, {'title': 'x', 'body': 'y'}, format='json').status_code, 403)

    def test_admin_always_reads(self):
        self.assertEqual(bearer_client(self.admin.user).get(POLICIES).status_code, 200)
