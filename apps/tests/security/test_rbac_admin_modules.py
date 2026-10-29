"""
Authorization — users, audit, sync and settings (Batch 4, Z-4).

Before (RBAC log mode = production): any logged-in role read the full staff list (phones,
e-mails, SOFTECH user names, permission flags) and any staff record; the SOFTECH user list;
the audit trail of ANY object (who changed what, before / after) and the abuse-flag counts;
the sync logs and scheduler state; every non-public system setting. Under enforce the other way
round broke: every screen's staff picker (tasks, demand, HR forms, follow-ups, incentives) and
the pricing branch-health panel were blocked for roles without users / sync.
"""
from django.test import TestCase, override_settings

from apps.config.models import SystemSetting
from apps.tests.factories import make_user
from core.middleware import module_access

from .fixtures import bearer_client, role_clients, seed_code_matrix
from .sweep import sweep

PREFIXES = {'users', 'audit', 'sync', 'config'}
PRIVATE = {'phone', 'email', 'softech_username', 'can_see_customer_phone', 'allowed_pos_channels'}
# Reviewed: settings look-up by key is a READ sent as POST; these roles hold settings view.
REVIEWED = {'pharmacist POST /api/config/settings/by_key/', 'purchasing POST /api/config/settings/by_key/'}


def _blocked_by_matrix(response):
    return response.status_code == 403 and 'module' in (response.json() if response.content else {})


class AdminModulesSweepTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.clients = role_clients()

    def tearDown(self):
        module_access.clear_cache()

    def test_no_role_gets_past_the_view_without_the_grant(self):
        res = sweep('log', self.clients, prefixes=PREFIXES)
        self.assertEqual(sorted(res.leaks - REVIEWED), [])


@override_settings(RBAC_ENFORCEMENT='log')
class StaffAndSettingsTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.sales, self.sales_profile, _ = make_user('z4_sales', role='salesperson')
        self.sales_profile.phone = '01000000000'
        self.sales_profile.save(update_fields=['phone'])
        self.supervisor = make_user('z4_super', role='supervisor')[0]

    def tearDown(self):
        module_access.clear_cache()

    def _rows(self, user):
        r = bearer_client(user).get('/api/users/staff/')
        self.assertEqual(r.status_code, 200)
        return r.data.get('results', r.data)

    def test_staff_picker_hides_private_fields(self):
        rows = self._rows(self.sales)
        self.assertTrue(rows)
        self.assertEqual(PRIVATE & set(rows[0]), set(), 'staff phones / e-mails shown to every role')

    def test_user_managers_see_the_full_record(self):
        self.assertIn('phone', self._rows(self.supervisor)[0])

    def test_staff_record_needs_users_view(self):
        r = bearer_client(self.sales).get(f'/api/users/staff/{self.sales_profile.pk}/')
        self.assertEqual(r.status_code, 403)

    def test_object_audit_trail_needs_audit_view(self):
        r = bearer_client(self.sales).get('/api/audit/logs/for-object/', {'model': 'Reservation', 'id': '1'})
        self.assertEqual(r.status_code, 403)

    def test_private_setting_hidden_without_settings_view(self):
        SystemSetting.objects.create(key='z4_private', label='private', value='x', is_public=False)
        SystemSetting.objects.create(key='z4_public', label='public', value='y', is_public=True)
        r = bearer_client(self.sales).get('/api/config/settings/')
        keys = {s['key'] for s in r.data.get('results', r.data)}
        self.assertIn('z4_public', keys)
        self.assertNotIn('z4_private', keys)


@override_settings(RBAC_ENFORCEMENT='enforce')
class SharedReadsUnderEnforceTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.client_ = bearer_client(make_user('z4_enf', role='salesperson')[0])

    def tearDown(self):
        module_access.clear_cache()

    def test_staff_picker_and_branch_health_stay_reachable(self):
        for path in ('/api/users/staff/', '/api/sync/branch-health/'):
            self.assertFalse(_blocked_by_matrix(self.client_.get(path)), f'{path} blocked under enforce')

    def test_sync_logs_still_blocked(self):
        self.assertTrue(_blocked_by_matrix(self.client_.get('/api/sync/logs/')))
