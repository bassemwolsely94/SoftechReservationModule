"""
Authentication — the second factor can't be guessed or replayed (Batch 3, A-2;
owner decision 2026-10-27: 5 wrong codes per login, then log in again).

Before: /2fa/verify/ had no limit and the 5-minute login token took unlimited guesses; an
accepted 6-digit code worked again inside its ±30 s window; one login token could mint any
number of sessions.
"""
import pyotp
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from apps.tests.factories import make_user


PASSWORD = 'Attempts-A2-pw'


class SecondFactorAttemptTests(TestCase):

    def setUp(self):
        cache.clear()
        self.user, self.profile, me = make_user('a2_user', role='purchasing', password=PASSWORD)
        me.post('/api/auth/2fa/setup/', {}, format='json')
        self.profile.refresh_from_db()
        self.totp = pyotp.TOTP(self.profile.mfa_secret)
        r = me.post('/api/auth/2fa/enable/', {'code': self.totp.now()}, format='json')
        self.backup = r.data['backup_codes']
        cache.clear()                     # the enrolment code above must not count as "used"

    def _token(self):
        r = APIClient().post('/api/auth/login/', {'username': 'a2_user', 'password': PASSWORD}, format='json')
        return r.data['mfa_token']

    def _verify(self, token, code):
        return APIClient().post('/api/auth/2fa/verify/', {'mfa_token': token, 'code': code}, format='json')

    def _wrong(self):
        good = self.totp.now()
        return '000000' if good != '000000' else '111111'

    def test_five_wrong_codes_end_the_login(self):
        token = self._token()
        for _ in range(5):
            self.assertEqual(self._verify(token, self._wrong()).status_code, 401)
        r = self._verify(token, self.totp.now())
        self.assertEqual(r.status_code, 401, 'a 6th try was allowed on the same login')
        self.assertNotIn('access', r.data)

    def test_a_new_login_starts_fresh(self):
        token = self._token()
        for _ in range(5):
            self._verify(token, self._wrong())
        self.assertEqual(self._verify(self._token(), self.totp.now()).status_code, 200)

    def test_an_accepted_code_cannot_be_used_again(self):
        code = self.totp.now()
        self.assertEqual(self._verify(self._token(), code).status_code, 200)
        self.assertEqual(self._verify(self._token(), code).status_code, 401, 'code replayed')

    def test_a_login_token_opens_one_session_only(self):
        token = self._token()
        self.assertEqual(self._verify(token, self.backup[0]).status_code, 200)
        r = self._verify(token, self.backup[1])
        self.assertEqual(r.status_code, 401, 'one password login minted two sessions')
