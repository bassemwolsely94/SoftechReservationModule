"""
Owner decisions 2026-11-03 (the last two left open by Batch 5):

1. Incentives payroll — all-branch quality managers and admins only. Every incentives route
   except the caller's own progress refuses any other role, even one the matrix grants, and a
   quality manager or admin without all-branch scope.
2. Tasks get their own module permission (`tasks`). Every role keeps today's access by default;
   switching a role's grant off in the matrix closes the task screens for it, server side.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.tests.factories import make_branch, make_user
from apps.users.management.commands.seed_permissions import ALL_MODULES, PERMISSIONS
from apps.users.models import RoleModuleAccess

from .fixtures import seed_code_matrix

PAYROLL_ROUTES = ('/api/incentives/programs/', '/api/incentives/rules/',
                  '/api/incentives/transactions/', '/api/incentives/settlements/',
                  '/api/incentives/adjustments/', '/api/incentives/logs/')


def _client(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


class IncentivesPayrollGateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_code_matrix()
        cls.branch = make_branch('Payroll A', softech_id='PRA')

    def _codes(self, user):
        api = _client(user)
        return {path: api.get(path).status_code for path in PAYROLL_ROUTES}

    def test_matrix_grants_incentives_to_quality_manager_and_admin_only(self):
        holders = sorted(r for r, mods in PERMISSIONS.items() if mods.get('incentives'))
        self.assertEqual(holders, ['admin', 'quality_manager'])

    def test_quality_manager_and_admin_see_payroll(self):
        for role in ('quality_manager', 'admin'):
            user = make_user(f'pay_{role}', role=role, branch=self.branch)[0]
            self.assertEqual(set(self._codes(user).values()), {200}, role)

    def test_purchasing_is_refused(self):
        user = make_user('pay_purchasing', role='purchasing', branch=self.branch)[0]
        self.assertEqual(set(self._codes(user).values()), {403})

    def test_matrix_grant_alone_does_not_open_it(self):
        # an admin-made matrix override for another role still can't open payroll
        RoleModuleAccess.objects.filter(role='pharmacist', module='incentives').update(is_allowed=True)
        from core.middleware import module_access
        module_access.clear_cache()
        user = make_user('pay_pharm', role='pharmacist', branch=self.branch, access_all=True)[0]
        self.assertEqual(set(self._codes(user).values()), {403})

    def test_quality_manager_restricted_to_branches_is_refused(self):
        user, profile, _ = make_user('pay_qm_narrow', role='quality_manager', branch=self.branch)
        profile.restricted_branches.add(make_branch('Payroll B', softech_id='PRB'))
        self.assertEqual(set(self._codes(user).values()), {403})

    def test_own_progress_stays_open(self):
        user, profile, _ = make_user('pay_self', role='pharmacist', branch=self.branch)
        profile.softech_user_id = '9901'
        profile.save(update_fields=['softech_user_id'])
        self.assertEqual(_client(user).get('/api/incentives/my-progress/').status_code, 200)


class TasksModulePermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_code_matrix()
        cls.branch = make_branch('Tasks A', softech_id='TKA')

    def test_tasks_is_a_matrix_module_every_role_keeps(self):
        self.assertIn('tasks', ALL_MODULES)
        for role, modules in PERMISSIONS.items():
            self.assertIn('view', modules.get('tasks', set()), role)
            self.assertIn('create', modules.get('tasks', set()), role)

    def test_granted_role_uses_tasks(self):
        user = make_user('tk_ok', role='pharmacist', branch=self.branch)[0]
        api = _client(user)
        self.assertEqual(api.get('/api/tasks/').status_code, 200)
        r = api.post('/api/tasks/', {'title': 'Count shelf 3', 'branch': self.branch.pk}, format='json')
        self.assertEqual(r.status_code, 201, r.content[:200])

    def test_revoked_role_is_refused_server_side(self):
        RoleModuleAccess.objects.filter(role='pharmacist', module='tasks').update(is_allowed=False)
        from core.middleware import module_access
        module_access.clear_cache()
        user = make_user('tk_no', role='pharmacist', branch=self.branch)[0]
        api = _client(user)
        self.assertEqual(api.get('/api/tasks/').status_code, 403)
        self.assertEqual(api.post('/api/tasks/', {'title': 'x'}, format='json').status_code, 403)
        self.assertEqual(api.get('/api/tasks/schedules/').status_code, 403)
