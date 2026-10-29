"""
Authorization — in-transit transfers and pick zones follow the `transfers` matrix (Batch 4, Z-7c;
owner decision 2026-10-28, map by screen).

Before (RBAC log mode = production): delivery (no transfers grant) read the in-transit list,
dashboards, scorecards, picking / stocking sheets and pick-zone setup; any role with a branch —
viewer and call center included — could add notes to a transfer; call center (HQ in the view's
own check, transfers view only in the matrix) could mark any transfer received; pick-zone
preview and classify answered every role.

Now: reads need transfers view (branch scoping in the view is unchanged); notes, receipts and
bulk sheet exports need a transfers grant beyond view (as the middleware); force-close / sync
and pick-zone edits keep admin / purchasing. Classifying items into pick zones is called from the
product screens: catalog view.
"""
from django.test import TestCase, override_settings

from apps.tests.factories import make_user
from core.middleware import module_access

from .fixtures import bearer_client, role_clients, seed_code_matrix
from .routes import Tripwire
from .sweep import sweep

MISSING = '/api/transits/987654321/'


class TransitsSweepTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.clients = role_clients()

    def tearDown(self):
        module_access.clear_cache()

    def test_no_role_gets_past_the_view_without_the_grant(self):
        res = sweep('log', self.clients, prefixes={'transits'})
        self.assertEqual(sorted(res.leaks), [])


@override_settings(RBAC_ENFORCEMENT='log')
class TransitsTests(TestCase):

    def setUp(self):
        seed_code_matrix()

    def tearDown(self):
        module_access.clear_cache()

    def _client(self, role):
        return bearer_client(make_user(f'z7c_{role}', role=role)[0])

    def _get(self, role, path):
        with Tripwire():
            return self._client(role).get(path)

    def _post(self, role, path, data=None):
        with Tripwire():
            return self._client(role).post(path, data or {}, format='json')

    def test_delivery_cannot_list_transits(self):
        self.assertEqual(self._get('delivery', '/api/transits/').status_code, 403)

    def test_delivery_cannot_read_pick_zone_setup(self):
        self.assertEqual(self._get('delivery', '/api/transits/pick-zones/').status_code, 403)

    def test_viewer_cannot_add_a_transit_note(self):
        self.assertEqual(self._post('viewer', MISSING + 'add-note/', {'body': 'x'}).status_code, 403)

    def test_call_center_cannot_mark_a_transit_received(self):
        self.assertEqual(self._post('call_center', MISSING + 'mark-received/').status_code, 403)

    def test_pharmacist_and_viewer_still_list_transits(self):
        self.assertEqual(self._get('pharmacist', '/api/transits/').status_code, 200)
        self.assertEqual(self._get('viewer', '/api/transits/').status_code, 200)

    def test_branch_staff_still_reach_a_receipt(self):
        # passes the permission layer; the transfer itself does not exist
        self.assertEqual(self._post('salesperson', MISSING + 'mark-received/').status_code, 404)

    def test_product_screens_still_classify_pick_zones(self):
        self.assertNotEqual(self._post('delivery', '/api/transits/pick-zones/classify-items/',
                                       {'item_ids': []}).status_code, 403)
