"""
Authorization — the overblock review's decisions (Batch 4, Z-11d onward; owner 2026-10-28).

Each class is one decision: a role the matrix grants, on a screen it is shown, that a hard-coded
role list in the view refused.

- Z-11d (decision 2): confirming an external payment follows the matrix's finance approve
  (admin, purchasing — as the help says), not a hard-coded admin / pharmacist list. Pharmacists
  hold finance view only and stay refused.
- Z-11e (decision 3): the six lost-demand analytics pages follow the matrix's analytics view
  (pharmacist, supervisor, quality manager, viewer, call center, purchasing, admin), not a
  hard-coded admin / purchasing / call center list; roles without analytics view stay refused.
- Z-11f (decision 4, owner 2026-10-29): the omni wallboard opens to call-center agents; viewer
  stays out. Listen / whisper stay admin / supervisor (the PBX spy endpoint).
- Z-11g (decisions 5 + 6): the refresh-button rule. Purchasing (and the supply groups) may run
  the sales catch-up and the catalog sync, as a quick engine run; the two expiry syncs follow
  catalog edit (admin, pharmacist, purchasing) instead of Django staff, and refuse a second run
  while one started in the last 6 hours is still running.
- Z-11h (decisions 7 + 8): supervisors open the transfer discrepancy report; the quality manager
  opens the abuse-flag summary and a staff member's audit trail (supervisors stay out of those two;
  flag review / detection stay admin / purchasing).
- Z-11i (decision 9, owner 2026-10-29): the menus already showed these — supervisors now run
  stock counts (view / create / edit) and, with the call center, classify chronic items (chronic
  edit). Code matrix + data migration 0032 for the live matrix. (The mobile tab gating is UI.)
"""
from datetime import date, timedelta
from unittest import mock
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.payments.models import ExternalPayment
from apps.tests.factories import make_branch, make_user
from core.middleware import module_access

from .fixtures import bearer_client, seed_code_matrix


@override_settings(RBAC_ENFORCEMENT='log')
class _Base(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.branch = make_branch()

    def tearDown(self):
        module_access.clear_cache()

    def _as(self, role):
        user, profile, _ = make_user(f'z11_{role}', role=role, branch=self.branch)
        return bearer_client(user), user


class PaymentConfirmTests(_Base):

    def setUp(self):
        super().setUp()
        self.payment = ExternalPayment.objects.create(branch=self.branch, method=ExternalPayment.METHOD_INSTAPAY,
                                                      amount=Decimal('250.00'), payment_date=date(2026, 10, 27),
                                                      customer_name='Z11')

    def test_finance_approvers_confirm_a_payment(self):
        c, user = self._as('purchasing')
        r = c.post(f'/api/payments/{self.payment.pk}/confirm/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.payment.refresh_from_db()
        self.assertEqual((self.payment.status, self.payment.confirmed_by_id),
                         (ExternalPayment.STATUS_CONFIRMED, user.pk))

    def test_view_only_roles_still_cannot(self):
        for role in ('pharmacist', 'salesperson'):
            c, _ = self._as(role)
            self.assertEqual(c.post(f'/api/payments/{self.payment.pk}/confirm/', {}, format='json').status_code,
                             403, role)


DEMAND_ANALYTICS = ('dashboard', 'capture-leaderboard', 'lost-value-reconciliation', 'price-objections',
                    'purchase-suggestions', 'substitution-analytics')


class DemandAnalyticsTests(_Base):

    def test_analytics_viewers_open_the_lost_demand_pages(self):
        for role in ('pharmacist', 'supervisor', 'quality_manager', 'viewer'):
            c, _ = self._as(role)
            for page in DEMAND_ANALYTICS:
                self.assertEqual(c.get(f'/api/demand/{page}/').status_code, 200, f'{role} {page}')

    def test_roles_without_analytics_stay_out(self):
        for role in ('salesperson', 'delivery'):
            c, _ = self._as(role)
            for page in DEMAND_ANALYTICS:
                self.assertEqual(c.get(f'/api/demand/{page}/').status_code, 403, f'{role} {page}')


class WallboardTests(_Base):

    def test_call_center_agents_open_the_wallboard(self):
        c, _ = self._as('call_center')
        self.assertEqual(c.get('/api/omni/wallboard/').status_code, 200)

    def test_viewer_stays_out_and_listening_stays_supervisors(self):
        c, _ = self._as('viewer')
        self.assertEqual(c.get('/api/omni/wallboard/').status_code, 403)
        c, _ = self._as('call_center')
        self.assertEqual(c.post('/api/pbx/spy/', {'target_ext': '101', 'mode': 'listen'}, format='json').status_code, 403)


class RefreshButtonTests(_Base):

    def test_purchasing_runs_the_catch_up_and_the_catalog_sync(self):
        from apps.purchasing.models import DemandCalculationRun
        c, _ = self._as('purchasing')
        DemandCalculationRun.objects.create(status='running', calc_date=date.today())
        self.assertEqual(c.post('/api/purchasing/catchup/', {}, format='json').status_code, 409)  # past the gate
        with mock.patch('apps.purchasing.views.threading.Thread'):
            self.assertEqual(c.post('/api/purchasing/sync-items/', {}, format='json').status_code, 202)

    def test_catalog_editors_refresh_expiry_and_a_running_sync_is_not_doubled(self):
        from apps.batches.models import StockExpirySyncRun
        c, _ = self._as('pharmacist')
        StockExpirySyncRun.objects.create(status='running')
        self.assertEqual(c.post('/api/batches/stock-expiry/sync/', {}, format='json').status_code, 409)
        StockExpirySyncRun.objects.update(started_at=timezone.now() - timedelta(hours=7))   # a stale run
        with mock.patch('apps.batches.views.threading.Thread'):
            self.assertEqual(c.post('/api/batches/stock-expiry/sync/', {}, format='json').status_code, 202)

    def test_roles_without_the_grant_stay_out(self):
        for role, path in (('salesperson', '/api/purchasing/catchup/'), ('supervisor', '/api/batches/stock-expiry/sync/'),
                           ('call_center', '/api/batches/purchase-expiry/sync/')):
            c, _ = self._as(role)
            self.assertEqual(c.post(path, {}, format='json').status_code, 403, f'{role} {path}')


class OversightReportTests(_Base):

    def test_supervisors_open_the_discrepancy_report(self):
        c, _ = self._as('supervisor')
        self.assertEqual(c.get('/api/transfers/discrepancy-report/').status_code, 200)

    def test_quality_opens_the_flag_summary_and_a_staff_audit_trail(self):
        c, user = self._as('quality_manager')
        self.assertEqual(c.get('/api/audit/flags/summary/').status_code, 200)
        self.assertEqual(c.get('/api/audit/logs/for-user/', {'staff_id': user.staff_profile.pk}).status_code, 200)

    def test_the_rest_stay_out(self):
        c, _ = self._as('salesperson')
        self.assertEqual(c.get('/api/transfers/discrepancy-report/').status_code, 403)
        c, user = self._as('supervisor')
        self.assertEqual(c.get('/api/audit/flags/summary/').status_code, 403)
        self.assertEqual(c.get('/api/audit/logs/for-user/', {'staff_id': user.staff_profile.pk}).status_code, 403)
        c, _ = self._as('quality_manager')
        self.assertEqual(c.post('/api/audit/flags/run-detection/', {}, format='json').status_code, 403)


class MatrixScreenGapTests(_Base):

    def test_supervisors_run_stock_counts(self):
        c, _ = self._as('supervisor')
        self.assertNotEqual(c.post('/api/stockcount/sessions/', {}, format='json').status_code, 403)   # 400: validation ran

    def test_supervisors_and_call_center_classify_chronic_items(self):
        for role in ('supervisor', 'call_center'):
            c, _ = self._as(role)
            self.assertNotEqual(c.post('/api/chronic/items/987654321/classify/', {}, format='json').status_code,
                                403, role)

    def test_the_migration_grants_what_the_code_matrix_grants(self):
        import importlib
        from apps.users.management.commands.seed_permissions import PERMISSIONS
        mig = importlib.import_module('apps.users.migrations.0032_grant_supervisor_stockcount_chronic_edit')
        for role, modules in mig.GRANTS.items():
            for module, actions in modules.items():
                self.assertTrue(set(actions) <= PERMISSIONS[role][module], f'{role} {module}')

    def test_the_migration_leaves_an_unseeded_matrix_alone(self):
        # a fresh install has no rows for a module until seed_permissions runs; rows for two roles
        # only would mark the module "seeded" and lock every other role out (Z-5c fallback)
        import importlib
        from django.apps import apps as django_apps
        from apps.users.models import RoleModuleAccess
        mig = importlib.import_module('apps.users.migrations.0032_grant_supervisor_stockcount_chronic_edit')
        RoleModuleAccess.objects.filter(module__in=('chronic', 'stockcount')).delete()
        mig.grant(django_apps, None)
        self.assertFalse(RoleModuleAccess.objects.filter(module__in=('chronic', 'stockcount')).exists())

    def test_salesperson_still_cannot_classify(self):
        c, _ = self._as('salesperson')
        self.assertEqual(c.post('/api/chronic/items/987654321/classify/', {}, format='json').status_code, 403)
