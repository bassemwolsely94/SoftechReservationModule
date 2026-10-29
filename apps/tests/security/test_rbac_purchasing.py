"""
Authorization — the purchasing engine, ISR / rates, procurement and invoices follow the matrix
(Batch 4, Z-7a; owner decision 2026-10-28: map by screen — each endpoint follows the module of
the people who use its screen; purchasing = the code matrix + SOFTECH supply groups).

Before (RBAC log mode = production): every read under /api/purchasing/ (engine results, ISR and
rate pushes, branch requests, transfer recommendations, lost sales) and /api/procurement/
(supplier costs, margins, FOC, price control, tax burden) answered any logged-in role —
salesperson, delivery and call center included; /api/invoices/ and /api/supply/ served router
index pages. The ISR / rate writes were already admin + purchasing + supply groups (Z-2).

Kept: Market Shortage reads the engine's run status (runs/latest, runs/active) and the shortage
screen the main distributors (invoices/vendors/main) — both follow `shortage` view now.
Shortage / phantom / spike / forecasting are Z-7b, transits Z-7c.
"""
from django.test import TestCase, override_settings

from apps.tests.factories import make_user
from apps.users.models import ERPUser
from core.middleware import module_access

from .fixtures import bearer_client, role_clients, seed_code_matrix
from .routes import Tripwire
from .sweep import sweep

PREFIXES = {'purchasing', 'procurement', 'invoices', 'supply'}
LATER = ('/api/purchasing/shortage/', '/api/purchasing/phantom/', '/api/purchasing/spike/')   # Z-7b


class PurchasingSweepTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.clients = role_clients()

    def tearDown(self):
        module_access.clear_cache()

    def test_no_role_gets_past_the_view_without_the_grant(self):
        res = sweep('log', self.clients, prefixes=PREFIXES)
        self.assertEqual(sorted(l for l in res.leaks if not any(p in l for p in LATER)), [])


@override_settings(RBAC_ENFORCEMENT='log')
class PurchasingReadTests(TestCase):

    def setUp(self):
        seed_code_matrix()

    def tearDown(self):
        module_access.clear_cache()

    def _get(self, role, path, username=None):
        user = make_user(username or f'z7a_{role}', role=role)[0]
        with Tripwire():
            return bearer_client(user).get(path)

    def test_salesperson_cannot_read_procurement_margins(self):
        self.assertEqual(self._get('salesperson', '/api/procurement/margins/').status_code, 403)

    def test_delivery_cannot_read_isr_pushes(self):
        self.assertEqual(self._get('delivery', '/api/purchasing/isr/pushes/').status_code, 403)

    def test_supervisor_cannot_read_engine_results(self):
        self.assertEqual(self._get('supervisor', '/api/purchasing/summary/').status_code, 403)

    def test_delivery_cannot_read_the_vendor_list(self):
        self.assertEqual(self._get('delivery', '/api/invoices/vendors/main/').status_code, 403)

    def test_purchasing_still_reads_procurement(self):
        self.assertEqual(self._get('purchasing', '/api/procurement/margins/').status_code, 200)

    def test_pharmacist_still_reads_engine_status_for_market_shortage(self):
        self.assertNotEqual(self._get('pharmacist', '/api/purchasing/runs/latest/').status_code, 403)

    def test_pharmacist_still_reads_main_distributors_for_shortage(self):
        self.assertEqual(self._get('pharmacist', '/api/invoices/vendors/main/').status_code, 200)

    def test_supply_group_salesperson_still_reads_isr_pushes(self):
        ERPUser.objects.create(username='z7a_store', full_name='Store Keeper', user_group='19', is_active=True)
        self.assertEqual(self._get('salesperson', '/api/purchasing/isr/pushes/', 'z7a_store').status_code, 200)
