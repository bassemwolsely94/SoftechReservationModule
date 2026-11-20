"""UAT B-04: a JWT sign-in updates auth_user.last_login (it stopped in 2026-07, so "last seen" was wrong)."""
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from .factories import make_branch, make_user


class LastLoginTests(TestCase):

    def setUp(self):
        cache.clear()       # login throttle
        self.user, _, _ = make_user('b04_user', role='admin', branch=make_branch(), access_all=True,
                                    password='Secret123')
        self.client = APIClient()

    def _login(self, password='Secret123'):
        return self.client.post('/api/auth/login/', {'username': 'b04_user', 'password': password}, format='json')

    def test_a_sign_in_sets_last_login(self):
        self.assertIsNone(self.user.last_login)
        self.assertEqual(self._login().status_code, 200)
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.last_login)

    def test_a_wrong_password_does_not(self):
        self.assertNotEqual(self._login('wrong-one').status_code, 200)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.last_login)
