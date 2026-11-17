"""
UAT owner decision D5 (2026-11-17): the code follows the role matrix — the server too, not only the
menu. Phone alerts need settings view (read) / settings edit (change); publishing an announcement
needs settings create. The admin role always passes. Caught by e2e/menu-api.spec.js (a screen the
menu hides must be refused by its API).
"""
from django.test import TestCase

from apps.tests.factories import make_branch, make_user

from .fixtures import bearer_client, seed_code_matrix


class D5ServerGateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_code_matrix()
        cls.branch = make_branch('D5', softech_id='D51')
        cls.sup = make_user('d5_sup', role='supervisor', branch=cls.branch)[1]
        cls.admin = make_user('d5_admin', role='admin', branch=cls.branch, access_all=True)[1]

    def test_supervisor_without_settings_view_refused_phone_alerts(self):
        r = bearer_client(self.sup.user).get('/api/notifications/phone-alerts/policies/')
        self.assertEqual(r.status_code, 403, r.content[:200])

    def test_admin_reads_phone_alerts(self):
        r = bearer_client(self.admin.user).get('/api/notifications/phone-alerts/policies/')
        self.assertEqual(r.status_code, 200, r.content[:200])

    def test_supervisor_without_settings_create_cannot_publish(self):
        r = bearer_client(self.sup.user).post('/api/notifications/announcements/',
                                              {'title': 'x', 'body': 'y'}, format='json')
        self.assertEqual(r.status_code, 403, r.content[:200])

    def test_supervisor_with_the_grant_keeps_phone_alerts(self):
        from apps.users.models import RoleModuleAccess
        RoleModuleAccess.objects.update_or_create(role='supervisor', module='settings', action='view',
                                                  defaults={'is_allowed': True})
        from core.middleware import module_access
        module_access.clear_cache()
        r = bearer_client(self.sup.user).get('/api/notifications/phone-alerts/policies/')
        self.assertEqual(r.status_code, 200, r.content[:200])
