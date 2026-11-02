"""N3 / Task 7 - admin zone-policy API and the two per-user external flags."""
from django.core.cache import cache
from django.test import TestCase

from apps.access.models import ZonePolicy
from apps.audit.models import AuditLog
from apps.tests.factories import make_admin, make_user
from apps.users.models import UserActivityLog

LIST = '/api/access/zone-policies/'


def _rows(resp):
    data = resp.json()
    return data['results'] if isinstance(data, dict) else data


class ZonePolicyApiTests(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        _, self.admin, self.api = make_admin('zp_admin')
        self.row = ZonePolicy.objects.filter(role='call_center', zone='Z3').first() or \
            ZonePolicy.objects.create(role='call_center', zone='Z3', access='listed')

    def url(self):
        return f'{LIST}{self.row.pk}/'

    def test_admin_only(self):
        for role in ('pharmacist', 'supervisor', 'delivery', 'purchasing'):
            _, _, c = make_user(f'zp_{role}', role=role)
            self.assertEqual(c.get(LIST).status_code, 403, role)
            self.assertEqual(c.patch(self.url(), {'export': True}, format='json').status_code, 403, role)
        self.row.refresh_from_db()
        self.assertFalse(self.row.export)

    def test_list_has_seeded_rows(self):
        r = self.api.get(LIST)
        self.assertEqual(r.status_code, 200)
        rows = _rows(r)
        self.assertEqual(len(rows), ZonePolicy.objects.count())
        self.assertIn('role_label', rows[0])

    def test_no_create_no_delete(self):
        self.assertEqual(self.api.post(LIST, {'role': 'viewer', 'zone': 'Z1'}, format='json').status_code, 405)
        self.assertEqual(self.api.delete(self.url()).status_code, 405)
        self.assertEqual(self.api.put(self.url(), {}, format='json').status_code, 405)

    def test_patch_audited_before_after(self):
        r = self.api.patch(self.url(), {'view_only': True, 'max_session_hours': 6}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.row.refresh_from_db()
        self.assertTrue(self.row.view_only)
        self.assertEqual(self.row.max_session_hours, 6)
        self.assertEqual(self.row.updated_by_id, self.admin.pk)
        log = AuditLog.objects.get(action='zone_policy_changed')
        self.assertEqual(log.user_id, self.admin.pk)
        self.assertNotEqual(log.changes['before'], log.changes['after'])
        self.assertEqual(log.changes['after']['max_session_hours'], 6)
        self.assertTrue(log.changes['after']['view_only'])

    def test_noop_patch_leaves_no_audit(self):
        self.api.patch(self.url(), {'export': self.row.export}, format='json')
        self.assertFalse(AuditLog.objects.filter(action='zone_policy_changed').exists())

    def test_modules_validated(self):
        r = self.api.patch(self.url(), {'modules': ['customers', 'not_a_module']}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.api.patch(self.url(), {'modules': 'customers'}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.api.patch(self.url(), {'modules': ['customers', 'customers', 'demand']}, format='json')
        self.assertEqual(r.status_code, 200)
        self.row.refresh_from_db()
        self.assertEqual(self.row.modules, ['customers', 'demand'])

    def test_max_session_hours_range(self):
        for bad in (0, 73, -1, 'x'):
            self.assertEqual(self.api.patch(self.url(), {'max_session_hours': bad}, format='json').status_code,
                             400, bad)
        for ok in (1, 72, None):
            self.assertEqual(self.api.patch(self.url(), {'max_session_hours': ok}, format='json').status_code,
                             200, ok)

    def test_access_choices_and_readonly_keys(self):
        self.assertEqual(self.api.patch(self.url(), {'access': 'god'}, format='json').status_code, 400)
        role, zone = self.row.role, self.row.zone
        r = self.api.patch(self.url(), {'role': 'viewer', 'zone': 'Z1', 'access': 'none'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.row.refresh_from_db()
        self.assertEqual((self.row.role, self.row.zone), (role, zone))

    def test_choices(self):
        r = self.api.get(LIST + 'choices/')
        self.assertEqual(r.status_code, 200)
        mods = {m['value'] for m in r.json()['modules']}
        self.assertIn('customers', mods)
        self.assertEqual({a['value'] for a in r.json()['access']}, {'none', 'read_only', 'listed', 'rider', 'full'})
        _, _, c = make_user('zp_ch', role='pharmacist')
        self.assertEqual(c.get(LIST + 'choices/').status_code, 403)

    def test_cache_invalidated(self):
        from apps.access.policy import policy_for
        policy_for('call_center', 'Z3')
        self.api.patch(self.url(), {'export': True}, format='json')
        self.assertTrue(policy_for('call_center', 'Z3').export)


class UserExternalFlagsTests(TestCase):

    def setUp(self):
        cache.clear()
        _, self.admin, self.api = make_admin('uf_admin')
        _, self.target, _ = make_user('uf_target', role='admin')

    def test_admin_sets_flags_and_it_is_logged(self):
        r = self.api.patch(f'/api/users/staff/{self.target.pk}/',
                           {'external_export': True, 'external_softech_write': True}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.target.refresh_from_db()
        self.assertTrue(self.target.external_export)
        self.assertTrue(self.target.external_softech_write)
        log = UserActivityLog.objects.get(target_user=self.target, action='permissions_changed')
        self.assertEqual(log.changed_by_id, self.admin.pk)
        self.assertEqual(log.old_value, {'external_export': False, 'external_softech_write': False})
        self.assertEqual(log.new_value, {'external_export': True, 'external_softech_write': True})

    def test_non_admin_cannot(self):
        _, _, c = make_user('uf_sup', role='supervisor')
        r = c.patch(f'/api/users/staff/{self.target.pk}/', {'external_export': True}, format='json')
        self.assertEqual(r.status_code, 403)
        self.target.refresh_from_db()
        self.assertFalse(self.target.external_export)

    def test_flags_listed(self):
        r = self.api.get('/api/users/staff/?page_size=200')
        rows = r.json().get('results', r.json())
        self.assertIn('external_export', rows[0])
