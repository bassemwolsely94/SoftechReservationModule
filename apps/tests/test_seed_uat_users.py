"""seed_uat_users — UAT users for every role and branch shape on the UAT copy only
(docs/superpowers/plans/2026-11-16-role-uat.md, Task 3)."""
import io
import json
import tempfile
from datetime import timedelta
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.branches.models import Branch
from apps.config.models import SystemSetting
from apps.tests.factories import make_branch, make_branch2, make_user
from apps.users.models import RoleModuleAccess, StaffProfile

UAT = dict(UAT_SETTINGS=True, WRITER_INSTANCE=False, SOFTECH_READ_ONLY=True)
ROLES = ['admin', 'call_center', 'pharmacist', 'salesperson', 'purchasing', 'delivery',
         'viewer', 'supervisor', 'quality_manager', 'accountant']


class SeedUatUsersTest(TestCase):
    def setUp(self):
        self.a = make_branch('فرع أ', 'B01')
        self.b = make_branch2('فرع ب', 'B02')
        Branch.objects.filter(pk__in=[self.a.pk, self.b.pk]).update(kind=Branch.KIND_RETAIL)
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / '.uat-users.json'

    def tearDown(self):
        self.tmp.cleanup()

    def run_cmd(self, *args):
        buf = io.StringIO()
        call_command('seed_uat_users', '--branch-a', self.a.softech_branch_id,
                     '--branch-b', self.b.softech_branch_id, '--out', str(self.out), *args, stdout=buf)
        return buf.getvalue(), json.loads(self.out.read_text(encoding='utf-8'))

    def test_refuses_without_uat_settings(self):
        with self.assertRaises(CommandError):
            call_command('seed_uat_users', '--out', str(self.out))

    @override_settings(**UAT)
    def test_creates_all_shapes(self):
        _, data = self.run_cmd()
        users = {u['key']: u for u in data['users']}
        for role in ROLES:
            self.assertEqual(users[role]['role'], role)
            self.assertEqual(users[role]['branch'], self.a.softech_branch_id)
        for role in ['pharmacist', 'salesperson', 'viewer', 'delivery']:
            self.assertEqual(users[f'{role}@B']['branch'], self.b.softech_branch_id)
        multi = StaffProfile.objects.get(user__username=users['multi']['username'])
        self.assertEqual(list(multi.allowed_branches.all()), [self.b])
        restricted = StaffProfile.objects.get(user__username=users['restricted']['username'])
        self.assertEqual(restricted.role, 'supervisor')
        self.assertEqual(list(restricted.restricted_branches.all()), [self.b])
        hidden = StaffProfile.objects.get(user__username=users['phoneHidden']['username'])
        visible = StaffProfile.objects.get(user__username=users['phoneVisible']['username'])
        self.assertFalse(hidden.can_see_customer_phone)
        self.assertTrue(visible.can_see_customer_phone)
        self.assertEqual(data['branchA']['code'], self.a.softech_branch_id)

    @override_settings(**UAT)
    def test_does_not_touch_role_matrix(self):
        row = RoleModuleAccess.objects.create(role='viewer', module='reservations', action='delete', is_allowed=True)
        self.run_cmd()
        row.refresh_from_db()
        self.assertTrue(row.is_allowed)

    @override_settings(**UAT)
    def test_disables_2fa_for_real_users_and_enforcement(self):
        _, prof, _ = make_user('real_sup', role='supervisor', branch=self.a)
        prof.mfa_enabled, prof.mfa_secret = True, 'JBSWY3DPEHPK3PXP'
        prof.save()
        SystemSetting.objects.update_or_create(key='security.mfa_enforced', defaults={'value': 'true', 'value_type': 'bool'})
        _, data = self.run_cmd('--real', 'real_sup')
        prof.refresh_from_db()
        self.assertFalse(prof.mfa_enabled)
        self.assertEqual(prof.mfa_secret, '')
        self.assertIn('real:real_sup', {u['key'] for u in data['users']})
        from apps.users.mfa import mfa_enforced
        self.assertFalse(mfa_enforced())

    @override_settings(**UAT)
    def test_real_user_inactive_refused(self):
        user, _, _ = make_user('gone_user', role='pharmacist', branch=self.a)
        user.is_active = False
        user.save()
        with self.assertRaisesMessage(CommandError, 'gone_user'):
            self.run_cmd('--real', 'gone_user')

    @override_settings(**UAT)
    def test_real_user_without_profile_refused(self):
        User.objects.create_user('no_profile')
        with self.assertRaisesMessage(CommandError, 'no_profile'):
            self.run_cmd('--real', 'no_profile')

    @override_settings(**UAT)
    def test_real_auto_picks_recent_user_per_role(self):
        u_old, _, _ = make_user('old_pharma', role='pharmacist', branch=self.a)
        u_new, _, _ = make_user('new_pharma', role='pharmacist', branch=self.a)
        User.objects.filter(pk=u_old.pk).update(last_login=timezone.now() - timedelta(days=20))
        User.objects.filter(pk=u_new.pk).update(last_login=timezone.now() - timedelta(days=1))
        _, data = self.run_cmd('--real-auto')
        self.assertIn('real:new_pharma', {u['key'] for u in data['users']})
        self.assertNotIn('real:old_pharma', {u['key'] for u in data['users']})

    @override_settings(**UAT)
    def test_idempotent_and_password_reused(self):
        _, first = self.run_cmd()
        n = User.objects.filter(username__startswith='uat_').count()
        _, second = self.run_cmd()
        self.assertEqual(User.objects.filter(username__startswith='uat_').count(), n)
        self.assertEqual(first['password'], second['password'])
        user = User.objects.get(username=first['users'][0]['username'])
        self.assertTrue(user.check_password(first['password']))

    @override_settings(**UAT)
    def test_password_never_printed(self):
        out, data = self.run_cmd()
        self.assertNotIn(data['password'], out)
