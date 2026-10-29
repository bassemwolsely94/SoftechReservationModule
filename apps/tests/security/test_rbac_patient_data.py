"""
Authorization — patient data (chronic, composition, follow-ups, reservations) follows the matrix
(Batch 4, Z-8a; owner decision 2026-10-28, map by screen).

Before (RBAC log mode = production): any logged-in role — delivery included — could list
follow-up tasks and chronic-medication profiles (customer names / phones / conditions), read
reservations, and create / edit / delete chronic tags, ingredients, protocols and item
classifications, or generate follow-up tasks; purchasing (no follow-up or reservation grant)
read both.

Now: chronic reads = chronic view, every chronic write = chronic edit; composition reads =
chronic view (its writes keep catalog edit); follow-ups = followups view / create-edit;
reservations = reservations view / create-edit-approve-finalize, and the reservations analytics
report = analytics view. Branch scoping and the views' own role checks are unchanged.
"""
from django.test import TestCase, override_settings

from apps.tests.factories import make_user
from core.middleware import module_access

from .fixtures import bearer_client, role_clients, seed_code_matrix
from .routes import Tripwire
from .sweep import sweep


class PatientDataSweepTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.clients = role_clients()

    def tearDown(self):
        module_access.clear_cache()

    def test_no_role_gets_past_the_view_without_the_grant(self):
        res = sweep('log', self.clients, prefixes={'chronic', 'composition', 'followups', 'reservations'})
        self.assertEqual(sorted(res.leaks), [])


@override_settings(RBAC_ENFORCEMENT='log')
class PatientDataTests(TestCase):

    def setUp(self):
        seed_code_matrix()

    def tearDown(self):
        module_access.clear_cache()

    def _client(self, role):
        return bearer_client(make_user(f'z8a_{role}', role=role)[0])

    def _get(self, role, path):
        with Tripwire():
            return self._client(role).get(path)

    def _post(self, role, path, data=None):
        with Tripwire():
            return self._client(role).post(path, data or {}, format='json')

    def test_delivery_cannot_list_follow_up_tasks(self):
        self.assertEqual(self._get('delivery', '/api/followups/tasks/').status_code, 403)

    def test_purchasing_cannot_read_chronic_medication_profiles(self):
        self.assertEqual(self._get('purchasing', '/api/followups/chronic/').status_code, 403)

    def test_delivery_cannot_list_reservations(self):
        self.assertEqual(self._get('delivery', '/api/reservations/').status_code, 403)

    def test_salesperson_cannot_create_a_chronic_tag(self):
        self.assertEqual(self._post('salesperson', '/api/chronic/tags/', {'name': 'z8a'}).status_code, 403)

    def test_viewer_cannot_create_a_follow_up_task(self):
        self.assertEqual(self._post('viewer', '/api/followups/tasks/', {}).status_code, 403)

    def test_salesperson_still_works_reservations_and_follow_ups(self):
        self.assertEqual(self._get('salesperson', '/api/reservations/').status_code, 200)
        self.assertEqual(self._get('salesperson', '/api/followups/tasks/').status_code, 200)

    def test_pharmacist_still_edits_chronic_tags(self):
        self.assertNotEqual(self._post('pharmacist', '/api/chronic/tags/', {'name': 'z8a'}).status_code, 403)

    def test_purchasing_still_reads_reservation_analytics(self):
        self.assertNotEqual(self._get('purchasing', '/api/reservations/analytics/').status_code, 403)
