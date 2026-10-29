"""
Authorization — stock counts, shortage lists, QA inspections, customer create and delivery
locations follow the matrix (Batch 4, Z-9c; owner decision 2026-10-28, map by screen).

Before (RBAC log mode = production): call center, salesperson, supervisor, delivery and viewer
(no stockcount grant beyond view) listed and opened stock-count sessions; delivery (no shortage
grant) read and created shortage lists, viewer created them and ran OCR / voice import on them;
viewer created QA inspections and delivery locations; salesperson, delivery and viewer created
customers; /api/insurance/, /api/replacement/, /api/stockcount/ and /api/shortage/ served router
indexes.

Now: stock counts = stockcount view / create-edit-finalize; shortage lists = shortage view /
create-edit-approve; QA inspections = hr (the middleware's module), writes any non-view grant —
the quality manager holds export; creating a customer = customers edit; delivery locations =
delivery create / edit.
"""
from django.test import TestCase, override_settings

from apps.tests.factories import make_user
from core.middleware import module_access

from .fixtures import bearer_client, role_clients, seed_code_matrix
from .routes import Tripwire
from .sweep import sweep

PREFIXES = {'stockcount', 'shortage', 'qa', 'customers', 'delivery', 'insurance', 'replacement'}


class RestSweepTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.clients = role_clients()

    def tearDown(self):
        module_access.clear_cache()

    def test_no_role_gets_past_the_view_without_the_grant(self):
        res = sweep('log', self.clients, prefixes=PREFIXES)
        self.assertEqual(sorted(res.leaks), [])


@override_settings(RBAC_ENFORCEMENT='log')
class RestTests(TestCase):

    def setUp(self):
        seed_code_matrix()

    def tearDown(self):
        module_access.clear_cache()

    def _call(self, role, method, path, data=None):
        c = bearer_client(make_user(f'z9c_{role}', role=role)[0])
        with Tripwire():
            return c.get(path) if method == 'get' else getattr(c, method)(path, data or {}, format='json')

    def test_call_center_cannot_list_stock_counts(self):
        self.assertEqual(self._call('call_center', 'get', '/api/stockcount/sessions/').status_code, 403)

    def test_salesperson_cannot_open_a_stock_count(self):
        self.assertEqual(self._call('salesperson', 'post', '/api/stockcount/sessions/').status_code, 403)

    def test_delivery_cannot_read_shortage_lists(self):
        self.assertEqual(self._call('delivery', 'get', '/api/shortage/lists/').status_code, 403)

    def test_viewer_cannot_create_a_shortage_list(self):
        self.assertEqual(self._call('viewer', 'post', '/api/shortage/lists/').status_code, 403)

    def test_viewer_cannot_create_a_qa_inspection(self):
        self.assertEqual(self._call('viewer', 'post', '/api/qa/inspections/').status_code, 403)

    def test_salesperson_cannot_create_a_customer(self):
        self.assertEqual(self._call('salesperson', 'post', '/api/customers/').status_code, 403)

    def test_viewer_cannot_add_a_delivery_location(self):
        self.assertEqual(self._call('viewer', 'post', '/api/delivery/customers/987654321/locations/').status_code, 403)

    def test_counters_and_quality_still_work(self):
        self.assertNotEqual(self._call('pharmacist', 'post', '/api/stockcount/sessions/').status_code, 403)
        self.assertEqual(self._call('quality_manager', 'get', '/api/stockcount/sessions/').status_code, 200)
        self.assertNotEqual(self._call('quality_manager', 'post', '/api/qa/inspections/').status_code, 403)

    def test_branch_staff_still_file_shortage_lists_and_call_center_customers(self):
        self.assertNotEqual(self._call('salesperson', 'post', '/api/shortage/lists/').status_code, 403)
        self.assertNotEqual(self._call('call_center', 'post', '/api/customers/').status_code, 403)
