"""
The extension → staff picker (/api/pbx/staff-choices/) must find staff whose name lives only in
softech_username (first/last name empty, username = a numeric code) — most real accounts look like that.
"""
from django.test import TestCase

from .factories import make_admin, make_pharmacist


class StaffChoicesTests(TestCase):

    def setUp(self):
        _, _, self.client_admin = make_admin()
        user, self.staff, _ = make_pharmacist('90001')
        user.first_name = user.last_name = ''
        user.save()
        self.staff.softech_username = 'Test AgentAlpha'
        self.staff.hr_code = 'HR-7731'
        self.staff.save()

    def _ids(self, q):
        r = self.client_admin.get('/api/pbx/staff-choices/', {'q': q})
        self.assertEqual(r.status_code, 200)
        return [s['id'] for s in r.data]

    def test_finds_by_softech_name(self):
        self.assertIn(self.staff.id, self._ids('agentalpha'))

    def test_finds_by_hr_code(self):
        self.assertIn(self.staff.id, self._ids('7731'))

    def test_shows_the_softech_name(self):
        r = self.client_admin.get('/api/pbx/staff-choices/', {'q': 'AgentAlpha'})
        self.assertEqual([s['name'] for s in r.data if s['id'] == self.staff.id], ['Test AgentAlpha'])

    def test_no_match(self):
        self.assertNotIn(self.staff.id, self._ids('zzz-nobody'))
