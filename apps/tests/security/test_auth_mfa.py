"""
Authentication — the second factor can't be skipped (Batch 3, A-1).

After the password step an enrolled user gets a `login` pre-auth token, meant only for
/2fa/verify/. setup_2fa_view / enable_2fa_view accepted it too: with the password alone an
attacker installed their own authenticator secret over the real one, and /enable/ handed back
JWTs and fresh backup codes. /setup/ also overwrote an enrolled user's secret for any JWT caller.
"""
import pyotp
from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from apps.users.models import StaffProfile


PASSWORD = 'pw-A1-123456'


class SecondFactorBypassTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='enrolled', password=PASSWORD)
        self.profile = StaffProfile.objects.create(user=self.user, role='purchasing')
        owner = APIClient()                      # the real owner enrols from a logged-in session
        owner.force_authenticate(self.user)
        owner.post('/api/auth/2fa/setup/', {}, format='json')
        self.profile.refresh_from_db()
        self.secret = self.profile.mfa_secret
        r = owner.post('/api/auth/2fa/enable/', {'code': pyotp.TOTP(self.secret).now()}, format='json')
        assert r.status_code == 200, r.data
        self.profile.refresh_from_db()
        assert self.profile.mfa_enabled

    def _password_only_token(self):
        r = APIClient().post('/api/auth/login/', {'username': 'enrolled', 'password': PASSWORD},
                             format='json')
        assert r.data.get('mfa_required'), r.data
        return r.data['mfa_token']

    def test_login_token_cannot_install_a_new_secret(self):
        attacker = APIClient()
        r = attacker.post('/api/auth/2fa/setup/', {'mfa_token': self._password_only_token()}, format='json')
        self.assertIn(r.status_code, (401, 403))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.mfa_secret, self.secret, 'the real authenticator was replaced')

    def test_password_alone_never_yields_a_session(self):
        attacker = APIClient()
        token = self._password_only_token()
        s = attacker.post('/api/auth/2fa/setup/', {'mfa_token': token}, format='json')
        own_secret = s.data.get('secret') if s.status_code == 200 else pyotp.random_base32()
        r = attacker.post('/api/auth/2fa/enable/',
                          {'mfa_token': token, 'code': pyotp.TOTP(own_secret).now()}, format='json')
        self.assertNotIn('access', r.data or {}, 'JWTs issued without the second factor')
        self.assertNotIn('backup_codes', r.data or {})

    def test_enrolled_secret_not_overwritten_from_a_session(self):
        c = APIClient()
        c.force_authenticate(self.user)
        r = c.post('/api/auth/2fa/setup/', {}, format='json')
        self.assertEqual(r.status_code, 400)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.mfa_secret, self.secret)

    def test_real_second_factor_still_logs_in(self):
        r = APIClient().post('/api/auth/2fa/verify/', {'mfa_token': self._password_only_token(),
                                                       'code': pyotp.TOTP(self.secret).now()}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertIn('access', r.data)
