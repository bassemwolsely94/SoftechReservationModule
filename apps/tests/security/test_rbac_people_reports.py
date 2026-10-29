"""
Authorization — analytics, narrative insights, sales targets, incentives and HR shifts follow the
matrix (Batch 4, Z-9a; owner decision 2026-10-28, map by screen).

Before (RBAC log mode = production): salesperson and delivery (no analytics grant) read every
analytics report (sales, customers, churn, performance, inventory investment) and the narrative
insight reports; any role read the sales targets and reached their create (the edit-role check
ran after validation); any staff member could create a shift assignment — for anyone, themselves
included — or edit a shift template; /api/incentives/ and /api/insights/ served router indexes.

Now: analytics and insights reads = analytics view (insight writes keep their admin / supervisor
checks); sales targets sit on the KPI board's side: analytics view, writes still admin /
supervisor / purchasing; shift templates and assignments are written by managers only (admin /
supervisor / purchasing); a staff member's own incentive progress and HR self-service (check-in /
out, leave, permit, overtime, expense, advance) stay open to every role — viewer included.
"""
from django.test import TestCase, override_settings

from apps.tests.factories import make_user
from core.middleware import module_access

from .fixtures import bearer_client, role_clients, seed_code_matrix
from .routes import Tripwire
from .sweep import sweep

MISSING = '987654321'


class PeopleReportsSweepTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.clients = role_clients()

    def tearDown(self):
        module_access.clear_cache()

    def test_no_role_gets_past_the_view_without_the_grant(self):
        res = sweep('log', self.clients, prefixes={'analytics', 'insights', 'incentives', 'hr'})
        self.assertEqual(sorted(res.leaks), [])


@override_settings(RBAC_ENFORCEMENT='log')
class PeopleReportsTests(TestCase):

    def setUp(self):
        seed_code_matrix()

    def tearDown(self):
        module_access.clear_cache()

    def _call(self, role, method, path, data=None):
        c = bearer_client(make_user(f'z9a_{role}', role=role)[0])
        with Tripwire():
            return c.get(path) if method == 'get' else getattr(c, method)(path, data or {}, format='json')

    def test_salesperson_cannot_read_sales_analytics(self):
        self.assertEqual(self._call('salesperson', 'get', '/api/analytics/sales/').status_code, 403)

    def test_delivery_cannot_read_insight_reports(self):
        self.assertEqual(self._call('delivery', 'get', '/api/insights/reports/').status_code, 403)

    def test_salesperson_cannot_create_a_sales_target(self):
        self.assertEqual(self._call('salesperson', 'post', '/api/incentives/targets/').status_code, 403)

    def test_pharmacist_cannot_assign_shifts(self):
        self.assertEqual(self._call('pharmacist', 'post', '/api/hr/shift-assignments/').status_code, 403)

    def test_salesperson_cannot_edit_a_shift_template(self):
        self.assertEqual(self._call('salesperson', 'patch', f'/api/hr/shifts/{MISSING}/', {'name': 'x'}).status_code, 403)

    def test_everyone_still_reads_their_own_incentive_progress(self):
        self.assertNotEqual(self._call('delivery', 'get', '/api/incentives/my-progress/').status_code, 403)

    def test_viewer_still_checks_in(self):
        self.assertNotEqual(self._call('viewer', 'post', '/api/hr/attendance/check-in/').status_code, 403)

    def test_pharmacist_still_reads_targets_and_quality_reads_analytics(self):
        self.assertEqual(self._call('pharmacist', 'get', '/api/incentives/targets/').status_code, 200)
        self.assertEqual(self._call('quality_manager', 'get', '/api/analytics/sales/').status_code, 200)

    def test_supervisor_still_assigns_shifts(self):
        self.assertNotEqual(self._call('supervisor', 'post', '/api/hr/shift-assignments/').status_code, 403)
