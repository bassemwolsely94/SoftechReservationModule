"""
UAT W2 (role UAT, 2026-11-19): screens whose menu entry was hidden but whose data API answered.

Owner decision 2026-11-19 (the per-screen split): for most screens the menu now follows the matrix;
three were narrowed on the server to the menu's audience —

* /api/forecasting/salesperson-board/ — each rep's sales against target: the analysts who set the
  targets (ANALYST_ROLES), reads included. analytics view alone let call center, pharmacists,
  viewers and the quality manager open it.
* /api/transfers/analytics/ — the Analytics hub's transfers report: analytics view, not the
  transfers grant a salesperson holds for their own requests.
* /api/qa/ — branch QA inspections: only roles the registry marks qa_inspections. Every role holds
  hr for its own self-service, so call center, purchasing, salesperson, delivery and viewer read
  inspections (and the ones with hr create could file them).
"""
from django.test import TestCase, override_settings

from apps.tests.factories import make_user
from apps.users.roles import QA_INSPECTION_ROLES, ROLE_KEYS
from core.middleware import module_access
from core.middleware.module_access import required

from .fixtures import bearer_client, seed_code_matrix

BOARD = '/api/forecasting/salesperson-board/'
TRANSFER_ANALYTICS = '/api/transfers/analytics/'
QA_LIST = '/api/qa/inspections/'


class _Base(TestCase):

    def setUp(self):
        seed_code_matrix()

    def tearDown(self):
        module_access.clear_cache()

    def _call(self, role, method, path):
        c = bearer_client(make_user(f'w2g_{role}', role=role)[0])
        return c.get(path) if method == 'get' else getattr(c, method)(path, {}, format='json')


@override_settings(RBAC_ENFORCEMENT='log')
class ViewGateTests(_Base):
    """The views refuse on their own (log mode: the middleware only logs)."""

    def test_salesperson_board_refuses_non_analysts(self):
        for role in ('call_center', 'pharmacist', 'viewer', 'quality_manager'):
            with self.subTest(role=role):
                self.assertEqual(self._call(role, 'get', BOARD).status_code, 403)

    def test_salesperson_board_still_serves_the_analysts(self):
        for role in ('supervisor', 'purchasing'):
            with self.subTest(role=role):
                self.assertEqual(self._call(role, 'get', BOARD).status_code, 200)

    def test_transfer_analytics_needs_analytics_view(self):
        self.assertEqual(self._call('salesperson', 'get', TRANSFER_ANALYTICS).status_code, 403)
        self.assertEqual(self._call('supervisor', 'get', TRANSFER_ANALYTICS).status_code, 200)

    def test_qa_inspections_refuse_roles_without_the_flag(self):
        for role in ('call_center', 'purchasing', 'salesperson', 'viewer', 'delivery', 'accountant'):
            with self.subTest(role=role):
                self.assertEqual(self._call(role, 'get', QA_LIST).status_code, 403)

    def test_hr_create_no_longer_files_an_inspection(self):
        for role in ('call_center', 'salesperson', 'purchasing'):
            with self.subTest(role=role):
                self.assertEqual(self._call(role, 'post', QA_LIST).status_code, 403)

    def test_qa_roles_still_work_inspections(self):
        for role in ('pharmacist', 'supervisor', 'quality_manager'):
            with self.subTest(role=role):
                self.assertEqual(self._call(role, 'get', QA_LIST).status_code, 200)
        self.assertNotEqual(self._call('quality_manager', 'post', QA_LIST).status_code, 403)


@override_settings(RBAC_ENFORCEMENT='enforce')
class MiddlewareMapTests(_Base):

    def test_transfer_analytics_maps_to_analytics(self):
        self.assertEqual(required(TRANSFER_ANALYTICS, 'GET'), ('analytics', ('view',)))
        # the rest of /api/transfers/ keeps the transfers module
        self.assertEqual(required('/api/transfers/', 'GET'), ('transfers', ('view',)))

    def test_salesperson_refused_by_the_middleware(self):
        res = self._call('salesperson', 'get', TRANSFER_ANALYTICS)
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json().get('module'), 'analytics')


class RegistryTests(TestCase):

    def test_qa_inspection_roles(self):
        self.assertEqual(QA_INSPECTION_ROLES, {'admin', 'pharmacist', 'supervisor', 'quality_manager'})
        self.assertTrue(QA_INSPECTION_ROLES <= set(ROLE_KEYS))
