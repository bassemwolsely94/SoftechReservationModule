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


def _remember(profile):
    """An approved device on which 2FA is remembered for `profile` (N2); returns its cookie secret.
    (The legacy signed device_token was removed in N3.)"""
    from apps.access import devices
    from apps.access.models import Device
    secret = devices.new_secret()
    dev = Device.objects.create(secret_hash=devices.hash_secret(secret), name='جهاز', status='approved')
    devices.remember_mfa(dev, profile)
    return secret


def _remembered(secret, profile):
    from django.test import RequestFactory
    from apps.access import devices
    req = RequestFactory().get('/')
    req.COOKIES[devices.COOKIE] = secret
    return devices.mfa_remembered(req, StaffProfile.objects.select_related('user').get(pk=profile.pk))


class ForgetDevicesTests(TestCase):
    """Revocable "remember this device" (security batch N0, H7)."""

    def setUp(self):
        from apps.tests.factories import make_user
        self.user, self.profile, self.me = make_user('h7_me', role='purchasing', password=PASSWORD)
        self.other, self.other_profile, _ = make_user('h7_other', role='purchasing', password=PASSWORD)
        self.admin_user, self.admin_profile, self.admin = make_user('h7_admin', role='admin', password=PASSWORD)

    def test_forget_devices_invalidates_token(self):
        secret = _remember(self.profile)
        self.assertTrue(_remembered(secret, self.profile))
        r = self.me.post('/api/auth/2fa/forget-devices/', {}, format='json')
        self.assertEqual(r.status_code, 200)
        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.mfa_device_epoch, 1)
        self.assertFalse(_remembered(secret, self.profile))
        from apps.users.models import UserActivityLog
        row = UserActivityLog.objects.get(action='mfa_devices_forgotten')
        self.assertEqual(row.target_user, self.profile)
        self.assertEqual(row.changed_by, self.profile)

    def test_admin_forget_devices_other_user(self):
        from apps.users.models import UserActivityLog
        secret = _remember(self.profile)
        denied = self.me.post(f'/api/users/{self.other_profile.id}/forget-devices/', {}, format='json')
        self.assertEqual(denied.status_code, 403)
        self.assertFalse(UserActivityLog.objects.filter(action='mfa_devices_forgotten').exists())
        ok = self.admin.post(f'/api/users/{self.profile.id}/forget-devices/', {}, format='json')
        self.assertEqual(ok.status_code, 200)
        row = UserActivityLog.objects.get(action='mfa_devices_forgotten')
        self.assertEqual(row.target_user, self.profile)
        self.assertEqual(row.changed_by, self.admin_profile)
        self.assertFalse(_remembered(secret, self.profile))

    def test_other_users_tokens_unaffected(self):
        other_secret = _remember(self.other_profile)
        self.me.post('/api/auth/2fa/forget-devices/', {}, format='json')
        self.assertTrue(_remembered(other_secret, self.other_profile))
