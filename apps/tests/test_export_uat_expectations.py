"""export_uat_expectations — what each UAT user should see, computed by the backend's own rules,
plus drift between the live role matrix and the code's seed_permissions
(docs/superpowers/plans/2026-11-16-role-uat.md, Task 4)."""
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.branches.models import Branch
from apps.customers.models import Customer
from apps.reservations.models import Reservation
from apps.tests.factories import make_branch, make_branch2
from apps.users.models import RoleModuleAccess

UAT = dict(UAT_SETTINGS=True, WRITER_INSTANCE=False, SOFTECH_READ_ONLY=True)


class ExportUatExpectationsTest(TestCase):
    def setUp(self):
        self.a = make_branch('فرع أ', 'B01')
        self.b = make_branch2('فرع ب', 'B02')
        Branch.objects.filter(pk__in=[self.a.pk, self.b.pk]).update(kind=Branch.KIND_RETAIL)
        call_command('seed_permissions', verbosity=0)   # the test DB starts empty; the copy never runs this
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.users = self.dir / '.uat-users.json'
        self.expected = self.dir / '.uat-expected.json'
        self.drift = self.dir / 'permission-drift.md'
        self.ca = Customer.objects.create(softech_pic='A1', name='عميل أ', phone='01012345678', preferred_branch=self.a)
        self.cb = Customer.objects.create(softech_pic='B1', name='عميل ب', phone='01198765432', preferred_branch=self.b)

    def tearDown(self):
        self.tmp.cleanup()

    def run_all(self):
        call_command('seed_uat_users', '--branch-a', 'B01', '--branch-b', 'B02', '--out', str(self.users))
        call_command('export_uat_expectations', '--users', str(self.users), '--out', str(self.expected),
                     '--drift', str(self.drift))
        return json.loads(self.expected.read_text(encoding='utf-8'))

    def test_refuses_without_uat_settings(self):
        with self.assertRaises(CommandError):
            call_command('export_uat_expectations', '--users', str(self.users), '--out', str(self.expected))

    @override_settings(**UAT)
    def test_perms_match_my_permissions_view(self):
        data = self.run_all()
        from django.contrib.auth.models import User
        client = APIClient()
        client.force_authenticate(User.objects.get(username='uat_salesperson'))
        live = client.get('/api/users/my-permissions/').json()['permissions']
        self.assertEqual(data['users']['salesperson']['perms'], live)

    @override_settings(**UAT)
    def test_branch_ids_from_branch_scope(self):
        data = self.run_all()
        self.assertEqual(sorted(data['users']['multi']['branchIds']), sorted([self.a.pk, self.b.pk]))
        self.assertFalse(data['users']['multi']['allBranches'])
        self.assertNotIn(self.b.pk, data['users']['restricted']['branchIds'])
        self.assertTrue(data['users']['call_center']['allBranches'])

    @override_settings(**UAT)
    def test_sees_phones_flag(self):
        data = self.run_all()
        self.assertFalse(data['users']['phoneHidden']['seesPhones'])
        self.assertTrue(data['users']['phoneVisible']['seesPhones'])

    @override_settings(**UAT)
    def test_reference_only_from_own_branch(self):
        Reservation.objects.filter(pk=-1)  # model import check
        data = self.run_all()
        pics_a = {c['pic'] for c in data['reference']['A']['customers']}
        pics_b = {c['pic'] for c in data['reference']['B']['customers']}
        self.assertEqual(pics_a, {'A1'})
        self.assertEqual(pics_b, {'B1'})
        self.assertEqual(data['reference']['A']['customers'][0]['phone'], '01012345678')

    @override_settings(**UAT)
    def test_drift_lists_changed_row(self):
        RoleModuleAccess.objects.filter(role='viewer', module='reservations', action='view').update(is_allowed=False)
        self.run_all()
        text = self.drift.read_text(encoding='utf-8')
        self.assertIn('| viewer | reservations | view |', text)

    @override_settings(**UAT)
    def test_no_drift_says_so(self):
        self.run_all()
        self.assertIn('No drift', self.drift.read_text(encoding='utf-8'))
