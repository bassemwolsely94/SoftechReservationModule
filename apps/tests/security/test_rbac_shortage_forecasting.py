"""
Authorization — Market Shortage, Phantom Sales, Cash Optimization and Forecasting follow the
module of the people who use them (Batch 4, Z-7b; owner decision 2026-10-28, map by screen).

Before (RBAC log mode = production): every read under /api/purchasing/shortage|phantom|spike/
and /api/forecasting/ (KPI board, scenarios, backtests, accuracy) answered any logged-in role —
delivery and salesperson included; any role could confirm, exclude or reset a phantom-sales flag
(the engine's input), and create / edit / delete seasonality indices and forecast-accuracy
records (update-actual too); /api/forecasting/ served its router index.

Now: Market Shortage = `shortage` view (its flag / dismiss writes keep `shortage` approve);
Phantom and Cash Optimization reads = `analytics` view — phantom review = `shortage` approve
(the Market Shortage reviewers), spike confirm keeps `purchasing` edit/approve; Forecasting =
`analytics` view, every forecasting write = an analyst role (admin / supervisor / purchasing).
"""
from django.test import TestCase, override_settings

from apps.catalog.models import Item
from apps.tests.factories import make_item, make_user
from core.middleware import module_access

from .fixtures import bearer_client, role_clients, seed_code_matrix
from .routes import Tripwire
from .sweep import sweep

SCOPE = ('/api/purchasing/shortage/', '/api/purchasing/phantom/', '/api/purchasing/spike/', '/api/forecasting/')


class ShortageForecastingSweepTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.clients = role_clients()

    def tearDown(self):
        module_access.clear_cache()

    def test_no_role_gets_past_the_view_without_the_grant(self):
        res = sweep('log', self.clients, prefixes={'purchasing', 'forecasting'})
        self.assertEqual(sorted(l for l in res.leaks if any(p in l for p in SCOPE)), [])


@override_settings(RBAC_ENFORCEMENT='log')
class ShortageForecastingTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.item = make_item(name='Z7b item', softech_id='Z7B01')

    def tearDown(self):
        module_access.clear_cache()

    def _client(self, role):
        return bearer_client(make_user(f'z7b_{role}', role=role)[0])

    def _get(self, role, path):
        with Tripwire():
            return self._client(role).get(path)

    def test_delivery_cannot_read_market_shortage(self):
        self.assertEqual(self._get('delivery', '/api/purchasing/shortage/candidates/').status_code, 403)

    def test_salesperson_cannot_read_the_kpi_board(self):
        self.assertEqual(self._get('salesperson', '/api/forecasting/kpi-board/').status_code, 403)

    def test_salesperson_cannot_confirm_a_phantom_flag(self):
        r = self._client('salesperson').post('/api/purchasing/phantom/confirm/', {'item_id': self.item.pk}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertNotEqual(Item.objects.get(pk=self.item.pk).phantom_override, 'confirmed')

    def test_pharmacist_cannot_rewrite_forecast_accuracy(self):
        r = self._client('pharmacist').post('/api/forecasting/accuracy/987654321/update-actual/',
                                            {'actual_30d': 1}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_viewer_cannot_create_a_seasonality_index(self):
        r = self._client('viewer').post('/api/forecasting/seasonality/', {}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_pharmacist_still_reads_market_shortage_and_forecasting(self):
        self.assertEqual(self._get('pharmacist', '/api/purchasing/shortage/candidates/').status_code, 200)
        self.assertEqual(self._get('pharmacist', '/api/forecasting/runs/').status_code, 200)

    def test_supervisor_still_reads_scenarios_and_kpi_board(self):
        self.assertEqual(self._get('supervisor', '/api/forecasting/scenarios/').status_code, 200)
        self.assertNotEqual(self._get('supervisor', '/api/forecasting/kpi-board/').status_code, 403)

    def test_pharmacist_still_reviews_phantom_flags(self):
        r = self._client('pharmacist').post('/api/purchasing/phantom/confirm/', {'item_id': self.item.pk}, format='json')
        self.assertEqual(r.status_code, 200)
