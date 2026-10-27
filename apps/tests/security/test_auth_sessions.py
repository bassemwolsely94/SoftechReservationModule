"""
Authentication — a session ends when the account is disabled or its password reset
(Batch 3, A-3; owner decision 2026-10-27: password change / reset / 2FA reset cancel every
"remember this device").

Before: toggle-active flipped StaffProfile.is_active only — the access token kept working and
/refresh/ kept renewing it for as long as anyone liked; the admin password reset left every
refresh token alive; the 30-day trusted-device token survived a password change, an admin
reset and a 2FA reset.
"""
import pyotp
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from apps.tests.factories import make_admin, make_user


PASSWORD = 'Sessions-A3-pw'


class SessionEndTests(TestCase):

    def setUp(self):
        cache.clear()                                    # login throttle
        _, self.admin_profile, self.admin = make_admin('a3_admin')
        self.user, self.profile, _ = make_user('a3_user', role='pharmacist', password=PASSWORD)

    def _login(self, **extra):
        r = APIClient().post('/api/auth/login/', {'username': 'a3_user', 'password': PASSWORD, **extra},
                             format='json')
        return r.data

    def _bearer(self, access):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        return c

    def _refresh(self, refresh):
        return APIClient().post('/api/auth/refresh/', {'refresh': refresh}, format='json')

    def _disable(self):
        r = self.admin.post(f'/api/users/staff/{self.profile.pk}/toggle-active/', {}, format='json')
        assert r.status_code == 200 and r.data['is_active'] is False, r.data

    def test_disabled_account_access_token_stops_working(self):
        tokens = self._login()
        self._disable()
        self.assertEqual(self._bearer(tokens['access']).get('/api/auth/me/').status_code, 401)

    def test_disabled_account_cannot_refresh(self):
        tokens = self._login()
        self._disable()
        self.assertEqual(self._refresh(tokens['refresh']).status_code, 401)

    def test_admin_password_reset_ends_sessions(self):
        tokens = self._login()
        r = self.admin.post(f'/api/users/staff/{self.profile.pk}/reset-password/',
                            {'new_password': 'Brand-new-pw-2026'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._refresh(tokens['refresh']).status_code, 401)

    def test_active_account_still_refreshes(self):
        tokens = self._login()
        self.assertEqual(self._refresh(tokens['refresh']).status_code, 200)


class RememberedDeviceTests(TestCase):
    """A trusted-device token is cancelled by a password change, an admin reset or a 2FA reset."""

    def setUp(self):
        cache.clear()
        _, _, self.admin = make_admin('a3d_admin')
        self.user, self.profile, self.me = make_user('a3_dev', role='purchasing', password=PASSWORD)
        self.me.force_authenticate(self.user)
        self.me.post('/api/auth/2fa/setup/', {}, format='json')
        self.profile.refresh_from_db()
        self.secret = self.profile.mfa_secret
        self.me.post('/api/auth/2fa/enable/', {'code': pyotp.TOTP(self.secret).now()}, format='json')
        login = APIClient().post('/api/auth/login/', {'username': 'a3_dev', 'password': PASSWORD},
                                 format='json').data
        v = APIClient().post('/api/auth/2fa/verify/', {'mfa_token': login['mfa_token'],
                                                       'code': pyotp.TOTP(self.secret).now(),
                                                       'remember_device': True}, format='json')
        self.device = v.data['device_token']

    def _login_with_device(self, password=PASSWORD):
        return APIClient().post('/api/auth/login/', {'username': 'a3_dev', 'password': password,
                                                     'device_token': self.device}, format='json').data

    def test_remembered_device_skips_the_code(self):
        self.assertIn('access', self._login_with_device())

    def test_password_change_cancels_remembered_devices(self):
        r = self.me.post('/api/auth/change-password/', {'old_password': PASSWORD,
                                                        'new_password': 'Changed-pw-2026',
                                                        'confirm_password': 'Changed-pw-2026'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self._login_with_device('Changed-pw-2026').get('mfa_required'))

    def test_admin_reset_cancels_remembered_devices(self):
        self.admin.post(f'/api/users/staff/{self.profile.pk}/reset-password/',
                        {'new_password': 'Reset-by-admin-26'}, format='json')
        self.assertTrue(self._login_with_device('Reset-by-admin-26').get('mfa_required'))

    def test_2fa_reset_cancels_remembered_devices(self):
        self.me.post('/api/auth/2fa/disable/', {'password': PASSWORD,
                                                'code': pyotp.TOTP(self.secret).now()}, format='json')
        self.me.post('/api/auth/2fa/setup/', {}, format='json')
        self.profile.refresh_from_db()
        self.me.post('/api/auth/2fa/enable/', {'code': pyotp.TOTP(self.profile.mfa_secret).now()},
                     format='json')
        self.assertTrue(self._login_with_device().get('mfa_required'))
