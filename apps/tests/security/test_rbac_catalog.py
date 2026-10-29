"""
Authorization — the catalog family (expiry batches, product images, variant groups / bundles,
enrichment) follows the matrix (Batch 4, Z-9b; owner decision 2026-10-28, map by screen).

Before (RBAC log mode = production): any role with catalog view — salesperson, call center,
delivery, viewer, supervisor, quality manager — could start product-image jobs (bulk, revise
all), create variant groups and product bundles, bulk-approve enrichment suggestions, record
expiry disposal decisions and spawn expiry stock-count sessions.

Now: catalog reads = catalog view; catalog writes = catalog edit / approve; the expiry screen's
worklists and exports (POSTs that only compute) = catalog view, so supervisors and quality keep
them; spawning an expiry count = catalog edit or stockcount create; quarantining a batch =
approvals approve (the matrix's batch-quarantine grant); a near-expiry markdown request =
approvals create / approve, as every price-change request (Z-6).
"""
from django.test import TestCase, override_settings

from apps.tests.factories import make_user
from core.middleware import module_access

from .fixtures import bearer_client, role_clients, seed_code_matrix
from .routes import Tripwire
from .sweep import sweep

MISSING = '987654321'


class CatalogSweepTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.clients = role_clients()

    def tearDown(self):
        module_access.clear_cache()

    def test_no_role_gets_past_the_view_without_the_grant(self):
        res = sweep('log', self.clients, prefixes={'batches', 'images', 'items', 'enrichment'})
        self.assertEqual(sorted(res.leaks), [])


@override_settings(RBAC_ENFORCEMENT='log')
class CatalogTests(TestCase):

    def setUp(self):
        seed_code_matrix()

    def tearDown(self):
        module_access.clear_cache()

    def _post(self, role, path, data=None):
        c = bearer_client(make_user(f'z9b_{role}', role=role)[0])
        with Tripwire():
            return c.post(path, data or {}, format='json')

    def test_salesperson_cannot_start_image_jobs(self):
        self.assertEqual(self._post('salesperson', '/api/images/jobs/bulk/').status_code, 403)

    def test_supervisor_cannot_create_a_product_bundle(self):
        self.assertEqual(self._post('supervisor', '/api/items/bundles/').status_code, 403)

    def test_call_center_cannot_record_a_disposal_decision(self):
        self.assertEqual(self._post('call_center', '/api/batches/stock-expiry/disposal/').status_code, 403)

    def test_viewer_cannot_spawn_an_expiry_count(self):
        self.assertEqual(self._post('viewer', '/api/batches/stock-expiry/spawn-count/').status_code, 403)

    def test_salesperson_cannot_bulk_approve_enrichment(self):
        self.assertEqual(self._post('salesperson', '/api/enrichment/suggestions/bulk-approve/').status_code, 403)

    def test_quality_and_supervisors_still_work_the_expiry_lists(self):
        self.assertNotEqual(self._post('quality_manager', '/api/batches/purchase-expiry/candidates/').status_code, 403)
        self.assertNotEqual(self._post('supervisor', '/api/batches/stock-expiry/export/').status_code, 403)

    def test_quality_manager_still_quarantines_batches(self):
        self.assertEqual(self._post('quality_manager', f'/api/batches/{MISSING}/quarantine/').status_code, 404)

    def test_purchasing_still_spawns_expiry_counts_and_pharmacist_bundles(self):
        self.assertNotEqual(self._post('purchasing', '/api/batches/stock-expiry/spawn-count/').status_code, 403)
        self.assertNotEqual(self._post('pharmacist', '/api/items/bundles/').status_code, 403)
