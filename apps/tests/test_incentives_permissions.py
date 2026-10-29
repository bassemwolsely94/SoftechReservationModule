"""
Incentives API permissions (core.permissions.MatrixPermission, module 'incentives').
Before 2026-10-26 every incentives endpoint only required a login: any staff member
could finalize payroll settlements, force a recalculation or read everyone's payouts.
Employees still see their own numbers through /my-progress/.
"""
from datetime import date

from django.test import TestCase

from apps.incentives.models import IncentiveProgram
from apps.tests.factories import make_branch, make_user
from apps.users.models import RoleModuleAccess
from core.middleware import module_access

GRANTS = {
    'purchasing':      {'view', 'create', 'edit', 'approve', 'export', 'finalize'},
    'quality_manager': {'view', 'export'},
}
PERIOD = {'period_start': '2026-09-01', 'period_end': '2026-09-30'}


class IncentivesPermissionTests(TestCase):
    def setUp(self):
        module_access.clear_cache()
        for role, actions in GRANTS.items():
            for a in actions:
                RoleModuleAccess.objects.create(role=role, module='incentives', action=a)
        self.branch = make_branch()
        self.program = IncentiveProgram.objects.create(
            name='برنامج', start_date=date(2026, 9, 1), end_date=date(2026, 9, 30))

    def tearDown(self):
        module_access.clear_cache()

    def _client(self, role):
        return make_user(f'inc_{role}', role=role, branch=self.branch)[2]

    def _url(self, suffix=''):
        return f'/api/incentives/programs/{self.program.pk}/{suffix}'

    def test_reads_need_view(self):
        for url in ('/api/incentives/programs/', '/api/incentives/settlements/',
                    '/api/incentives/transactions/', '/api/incentives/adjustments/', '/api/incentives/logs/'):
            self.assertEqual(self._client('pharmacist').get(url).status_code, 403, url)
            self.assertEqual(self._client('quality_manager').get(url).status_code, 200, url)

    def test_finalize_needs_finalize(self):
        r = self._client('quality_manager').post(self._url('finalize/'), PERIOD, format='json')
        self.assertEqual(r.status_code, 403)
        r = self._client('salesperson').post(self._url('finalize/'), PERIOD, format='json')
        self.assertEqual(r.status_code, 403)
        r = self._client('purchasing').post(self._url('finalize/'), PERIOD, format='json')
        self.assertNotEqual(r.status_code, 403)

    def test_calculate_needs_edit_and_force_needs_finalize(self):
        self.assertEqual(self._client('quality_manager').post(self._url('calculate/'), PERIOD,
                                                              format='json').status_code, 403)
        RoleModuleAccess.objects.create(role='supervisor', module='incentives', action='edit')
        module_access.clear_cache()
        r = self._client('supervisor').post(self._url('calculate/'), {**PERIOD, 'force': True}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_program_writes(self):
        c = self._client('quality_manager')
        self.assertEqual(c.patch(self._url(), {'name': 'x'}, format='json').status_code, 403)
        self.assertEqual(c.delete(self._url()).status_code, 403)
        # purchasing may edit but has no 'delete' grant for programs
        p = self._client('purchasing')
        self.assertEqual(p.patch(self._url(), {'name': 'جديد'}, format='json').status_code, 200)
        self.assertEqual(p.delete(self._url()).status_code, 403)
        self.assertTrue(IncentiveProgram.objects.filter(pk=self.program.pk).exists())

    def test_adjustments_need_create(self):
        r = self._client('quality_manager').post('/api/incentives/adjustments/', {}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_export_needs_export(self):
        RoleModuleAccess.objects.create(role='supervisor', module='incentives', action='view')
        module_access.clear_cache()
        self.assertEqual(self._client('supervisor').get(self._url('export-settlements/'),
                                                        PERIOD).status_code, 403)

    def test_my_progress_open_to_every_employee(self):
        r = self._client('salesperson').get('/api/incentives/my-progress/')
        self.assertNotEqual(r.status_code, 403)

    def test_admin_and_unseeded_matrix(self):
        self.assertNotEqual(self._client('admin').post(self._url('finalize/'), PERIOD, format='json').status_code, 403)
        RoleModuleAccess.objects.all().delete()
        module_access.clear_cache()
        self.assertEqual(self._client('pharmacist').get('/api/incentives/programs/').status_code, 200)
