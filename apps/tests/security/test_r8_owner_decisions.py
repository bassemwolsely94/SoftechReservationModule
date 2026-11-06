"""R8 menu-vs-API owner decisions (2026-11-06): what each role is now refused or granted, on the
server, with the middleware in log mode (as in production) so the views' own checks are what answer.
"""
import importlib

from django.test import TestCase, override_settings

from apps.tests.factories import make_user
from apps.users.management.commands.seed_permissions import PERMISSIONS
from core.middleware import module_access

from .fixtures import bearer_client, seed_code_matrix


@override_settings(RBAC_ENFORCEMENT='log')
class _Base(TestCase):

    def setUp(self):
        seed_code_matrix()
        module_access.clear_cache()

    def tearDown(self):
        module_access.clear_cache()

    def _client(self, role):
        return bearer_client(make_user(f'r8_{role}', role=role)[0])


class ViewerRefusedTests(_Base):
    """Decisions 1 and 2: the viewer is refused on customer conversations and money screens."""

    REFUSED = ('/api/callcenter/calls/dashboard/', '/api/omni/conversations/', '/api/omni/accounts/',
               '/api/whatsapp/conversations/', '/api/pbx/live/', '/api/approvals/requests/pending/',
               '/api/pricing-approvals/', '/api/pricing-approvals/alignment/tiers/',
               '/api/purchasing/spike/summary/', '/api/purchasing/spike/candidates/',
               '/api/purchasing/spike/med-types/', '/api/purchasing/phantom/summary/',
               '/api/purchasing/phantom/candidates/', '/api/purchasing/phantom/excluded/',
               '/api/purchasing/phantom/med-types/')

    def test_refused(self):
        client = self._client('viewer')
        for path in self.REFUSED:
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 403)

    def test_viewer_keeps_its_report_screens(self):
        """analytics view stays: cash optimization and phantom sales are gated on their own routes."""
        self.assertIn('view', PERMISSIONS['viewer']['analytics'])
        client = self._client('viewer')
        for path in ('/api/demand/dashboard/', '/api/hr/leave-requests/'):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 200)

    def test_other_analytics_roles_still_open_the_gated_reports(self):
        for role in ('supervisor', 'quality_manager', 'purchasing', 'pharmacist'):
            client = self._client(role)
            for path in ('/api/purchasing/spike/summary/', '/api/purchasing/phantom/summary/'):
                with self.subTest(role=role, path=path):
                    self.assertEqual(client.get(path).status_code, 200)


class AuditorsAnsweredTests(_Base):
    """Decisions 1 and 2: the menu now shows these, so the server has to keep answering."""

    def test_quality_manager(self):
        client = self._client('quality_manager')
        for path in ('/api/callcenter/calls/dashboard/', '/api/omni/conversations/', '/api/omni/accounts/',
                     '/api/whatsapp/conversations/', '/api/payments/audit/statements/',
                     '/api/finance/reconciliation/candidates/', '/api/pricing-approvals/',
                     '/api/pricing-approvals/alignment/tiers/'):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 200)

    def test_supervisor_pricing_screens(self):
        client = self._client('supervisor')
        for path in ('/api/pricing-approvals/', '/api/pricing-approvals/alignment/tiers/'):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 200)

    def test_accountant_payment_audit(self):
        self.assertEqual(self._client('accountant').get('/api/payments/audit/statements/').status_code, 200)


class RefusedScreensFixedTests(_Base):
    """Decision 4: the four screens the menu showed and the server refused."""

    def test_accountant_opens_own_hr_requests_only(self):
        self.assertEqual(PERMISSIONS['accountant']['hr'], {'view', 'create'})
        client = self._client('accountant')
        self.assertEqual(client.get('/api/hr/leave-requests/').status_code, 200)

    def test_accountant_hr_grant_does_not_open_qa_inspections(self):
        client = self._client('accountant')
        self.assertEqual(client.get('/api/qa/inspections/').status_code, 403)
        self.assertEqual(client.post('/api/qa/inspections/', {}, format='json').status_code, 403)

    def test_supervisor_opens_supply_read_only(self):
        self.assertEqual(PERMISSIONS['supervisor']['purchasing'], {'view'})
        self.assertEqual(self._client('supervisor').get('/api/purchasing/rates/pushes/').status_code, 200)

    def test_pharmacist_stays_refused_on_reconciliation(self):
        self.assertEqual(self._client('pharmacist').get('/api/finance/reconciliation/candidates/').status_code, 403)

    def test_salesperson_list_opens_and_dashboard_stays_refused(self):
        client = self._client('salesperson')
        self.assertEqual(client.get('/api/demand/').status_code, 200)
        self.assertEqual(client.get('/api/demand/dashboard/').status_code, 403)


class MigrationTests(TestCase):

    def test_an_unseeded_module_stays_unseeded(self):
        """The accountant's deny rows alone must not make the migration write a row: that would mark
        the module seeded and lock every other role out of it (R17)."""
        from django.apps import apps as django_apps
        from apps.users.models import RoleModuleAccess as RMA
        mig = importlib.import_module('apps.users.migrations.0052_r8_owner_menu_decisions')
        RMA.objects.all().delete()
        RMA.objects.create(role='accountant', module='purchasing', action='view', is_allowed=False)
        mig.forwards(django_apps, None)
        self.assertEqual(RMA.objects.count(), 1)

    def test_migration_matches_the_code_matrix(self):
        mig = importlib.import_module('apps.users.migrations.0052_r8_owner_menu_decisions')
        for role, module, action in mig.GRANT:
            self.assertIn(action, PERMISSIONS[role][module])
        for role, module, action in mig.REVOKE:
            self.assertNotIn(action, PERMISSIONS[role].get(module, set()))
