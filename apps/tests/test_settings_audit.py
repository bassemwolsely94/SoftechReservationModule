"""
Settings screen audit (owner 2026-11-19): every write through /api/config/ — a setting's value
(single PATCH or bulk save), adding/deleting a setting, the theme, the pharmacy details and the
dropdown lists — leaves an AuditLog row with who, what and before → after. No-op saves leave none.
Synthetic data only.
"""
from django.test import TestCase

from apps.audit.models import AuditLog
from apps.config.models import DropdownOption, PharmacyProfile, SystemSetting
from apps.tests.factories import make_admin


class SettingsAuditTests(TestCase):

    def setUp(self):
        _, self.admin, self.c = make_admin('settings_audit_admin')
        self.s = SystemSetting.objects.create(key='test.audit_switch', label='مفتاح تجريبي',
                                              value='false', value_type='boolean')

    def _rows(self, action):
        return list(AuditLog.objects.filter(action=action).order_by('pk'))

    def test_patch_records_before_and_after(self):
        r = self.c.patch(f'/api/config/settings/{self.s.pk}/', {'value': 'true'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        [row] = self._rows('settings_changed')
        self.assertEqual(row.user_id, self.admin.pk)
        self.assertEqual(row.changes, {'value': ['false', 'true']})
        self.assertIn('test.audit_switch', row.note)

    def test_same_value_is_not_recorded(self):
        self.c.patch(f'/api/config/settings/{self.s.pk}/', {'value': 'false'}, format='json')
        self.assertEqual(self._rows('settings_changed'), [])

    def test_bulk_save_records_each_changed_key_only(self):
        SystemSetting.objects.create(key='test.audit_other', label='آخر', value='5', value_type='integer')
        r = self.c.post('/api/config/settings/bulk_update/',
                        {'test.audit_switch': 'true', 'test.audit_other': '5', 'test.missing': '1'},
                        format='json')
        self.assertEqual(r.status_code, 200, r.data)
        rows = self._rows('settings_changed')
        self.assertEqual([(x.note, x.changes) for x in rows],
                         [('test.audit_switch', {'value': ['false', 'true']})])

    def test_long_values_are_cut(self):
        self.c.patch(f'/api/config/settings/{self.s.pk}/', {'value': 'x' * 2000}, format='json')
        [row] = self._rows('settings_changed')
        self.assertLessEqual(len(row.changes['value'][1]), 501)

    def test_delete_is_recorded(self):
        r = self.c.delete(f'/api/config/settings/{self.s.pk}/')
        self.assertEqual(r.status_code, 204)
        [row] = self._rows('settings_deleted')
        self.assertEqual(row.changes, {'value': ['false', None]})

    def test_pharmacy_profile_changes_are_recorded(self):
        PharmacyProfile.get()
        r = self.c.patch('/api/config/pharmacy/', {'tagline_ar': 'شعار تجريبي'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        [row] = self._rows('pharmacy_profile_changed')
        self.assertEqual(row.changes['tagline_ar'][1], 'شعار تجريبي')

    def test_theme_change_is_recorded(self):
        r = self.c.put('/api/config/theme/', {'primary': '#123456'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        [row] = self._rows('theme_changed')
        self.assertEqual(row.changes['primary'][1], '#123456')
        self.c.put('/api/config/theme/', {'primary': '#123456'}, format='json')
        self.assertEqual(len(self._rows('theme_changed')), 1)

    def test_dropdown_add_edit_reorder_delete_are_recorded(self):
        r = self.c.post('/api/config/dropdowns/', {'dropdown_key': 'test_list', 'label': 'أ', 'value': 'a'},
                        format='json')
        self.assertEqual(r.status_code, 201, r.data)
        pk = r.data['id'] if 'id' in r.data else DropdownOption.objects.get(dropdown_key='test_list').pk
        self.c.patch(f'/api/config/dropdowns/{pk}/', {'label': 'ب'}, format='json')
        self.c.post('/api/config/dropdowns/reorder/', [{'id': pk, 'order': 7}], format='json')
        self.assertEqual(self.c.delete(f'/api/config/dropdowns/{pk}/').status_code, 204)
        rows = self._rows('dropdown_option_changed')
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[1].changes, {'label': ['أ', 'ب']})
        self.assertEqual(rows[2].changes, {'order': [[pk, 0, 7]]})
        self.assertTrue(all(x.user_id == self.admin.pk for x in rows))
