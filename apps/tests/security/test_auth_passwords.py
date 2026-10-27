"""
Authentication — weak passwords are refused (Batch 3, A-5; owner decision 2026-10-27:
10 characters plus Django's checks).

Before: the only rule was "6 characters" (change-password, admin reset, create user), and
AUTH_PASSWORD_VALIDATORS was empty, so '123456', 'password' or the username itself were accepted.
"""
from django.core.cache import cache
from django.test import TestCase

from apps.tests.factories import make_admin, make_user
from apps.users.models import ERPUser


OLD = 'Old-Strong-pw-26'
STRONG = 'Rezeiky-Strong-2026'


class PasswordChangeRulesTests(TestCase):

    def setUp(self):
        cache.clear()
        self.user, _, self.me = make_user('a5_pharmacist', role='pharmacist', password=OLD)

    def _change(self, new):
        r = self.me.post('/api/auth/change-password/', {'old_password': OLD, 'new_password': new,
                                                        'confirm_password': new}, format='json')
        self.user.refresh_from_db()
        return r

    def _refused(self, new, why):
        r = self._change(new)
        self.assertEqual(r.status_code, 400, f'{why}: {new!r} accepted')
        self.assertTrue(r.data.get('error'))
        self.assertTrue(self.user.check_password(OLD), 'the old password was replaced')

    def test_nine_characters_refused(self):
        self._refused('Abc-12345', 'shorter than 10')

    def test_common_password_refused(self):
        self._refused('password123', 'on the common-passwords list')

    def test_all_digits_refused(self):
        self._refused('2026102719', 'digits only')

    def test_password_like_the_username_refused(self):
        self._refused('a5_pharmacist1', 'close to the username')

    def test_strong_password_accepted(self):
        self.assertEqual(self._change(STRONG).status_code, 200)
        self.assertTrue(self.user.check_password(STRONG))


class AdminResetRulesTests(TestCase):

    def setUp(self):
        cache.clear()
        _, _, self.admin = make_admin('a5_admin')
        self.user, self.profile, _ = make_user('a5_target', role='pharmacist', password=OLD)

    def _reset(self, new):
        r = self.admin.post(f'/api/users/staff/{self.profile.pk}/reset-password/',
                            {'new_password': new}, format='json')
        self.user.refresh_from_db()
        return r

    def test_short_password_refused(self):
        self.assertEqual(self._reset('Abc-1234').status_code, 400)
        self.assertTrue(self.user.check_password(OLD))

    def test_common_password_refused(self):
        self.assertEqual(self._reset('1234567890').status_code, 400)
        self.assertTrue(self.user.check_password(OLD))

    def test_strong_password_accepted(self):
        self.assertEqual(self._reset(STRONG).status_code, 200)
        self.assertTrue(self.user.check_password(STRONG))


class CreateUserRulesTests(TestCase):

    def setUp(self):
        cache.clear()
        _, _, self.admin = make_admin('a5_creator')
        ERPUser.objects.create(username='a5_new', full_name='Test Person', is_active=True)

    def _create(self, password):
        return self.admin.post('/api/users/staff/', {'username': 'a5_new', 'password': password,
                                                     'role': 'pharmacist'}, format='json')

    def test_weak_password_refused(self):
        r = self._create('qwerty12')
        self.assertEqual(r.status_code, 400, 'weak password accepted on create')
        self.assertIn('password', r.data)

    def test_strong_password_accepted(self):
        # Also failed before A-5: the user was saved, then the reply crashed (500) reading
        # `username` off the StaffProfile — the admin saw an error for a user that existed.
        self.assertEqual(self._create(STRONG).status_code, 201)
