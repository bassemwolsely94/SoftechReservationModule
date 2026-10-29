"""
Authorization — lost demand and branch transfers follow the matrix (Batch 4, Z-8c; owner decision
2026-10-28, map by screen).

Before (RBAC log mode = production): delivery (no demand / transfers grant) and purchasing (no
demand grant) listed lost-demand records — customer names and phones — and transfer requests;
viewer, call center and delivery could create demand records and transfer requests.

Now: demand records = `demand` view / create-edit-approve-finalize (the per-action checks inside
stay); the demand dashboard family (dashboard, reconciliation, purchase suggestions, leaderboard,
substitution analytics, price objections) = analytics view, their admin / purchasing / call
center role sets unchanged; pushing purchase suggestions = purchasing; the product page's shelf
QR = catalog view; transfers = `transfers` view / create-edit-approve-finalize. The public
notify-me endpoints are unchanged.
"""
from django.test import TestCase, override_settings

from apps.tests.factories import make_user
from core.middleware import module_access

from .fixtures import bearer_client, role_clients, seed_code_matrix
from .routes import Tripwire
from .sweep import sweep


class DemandTransfersSweepTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.clients = role_clients()

    def tearDown(self):
        module_access.clear_cache()

    def test_no_role_gets_past_the_view_without_the_grant(self):
        res = sweep('log', self.clients, prefixes={'demand', 'transfers'})
        self.assertEqual(sorted(res.leaks), [])


@override_settings(RBAC_ENFORCEMENT='log')
class DemandTransfersTests(TestCase):

    def setUp(self):
        seed_code_matrix()

    def tearDown(self):
        module_access.clear_cache()

    def _call(self, role, method, path, data=None):
        c = bearer_client(make_user(f'z8c_{role}', role=role)[0])
        with Tripwire():
            return c.get(path) if method == 'get' else getattr(c, method)(path, data or {}, format='json')

    def test_delivery_cannot_list_lost_demand(self):
        self.assertEqual(self._call('delivery', 'get', '/api/demand/').status_code, 403)

    def test_purchasing_cannot_list_lost_demand_records(self):
        self.assertEqual(self._call('purchasing', 'get', '/api/demand/').status_code, 403)

    def test_viewer_cannot_record_demand(self):
        self.assertEqual(self._call('viewer', 'post', '/api/demand/').status_code, 403)

    def test_delivery_cannot_list_transfers(self):
        self.assertEqual(self._call('delivery', 'get', '/api/transfers/').status_code, 403)

    def test_call_center_cannot_request_a_transfer(self):
        self.assertEqual(self._call('call_center', 'post', '/api/transfers/').status_code, 403)

    def test_purchasing_still_reads_purchase_suggestions(self):
        self.assertNotEqual(self._call('purchasing', 'get', '/api/demand/purchase-suggestions/').status_code, 403)

    def test_salesperson_still_records_demand_and_viewer_reads_transfers(self):
        self.assertNotEqual(self._call('salesperson', 'post', '/api/demand/').status_code, 403)
        self.assertEqual(self._call('viewer', 'get', '/api/transfers/').status_code, 200)

    def test_product_page_still_prints_shelf_qr(self):
        self.assertNotEqual(self._call('delivery', 'get', '/api/demand/shelf-qr/').status_code, 403)
