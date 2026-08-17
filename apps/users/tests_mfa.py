"""
Tests for TOTP two-factor authentication on the auth endpoints.

Covers the full login state machine:
  • no 2FA + no enforcement  → normal login (tokens)
  • enforcement on + required role + unenrolled → forced setup
  • setup → enable (returns tokens + one-time backup codes)
  • enrolled login → challenge → verify (correct / wrong / backup / reuse)
  • trusted-device token skips the challenge
"""
import pyotp
from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from apps.config.models import SystemSetting
from apps.users.models import StaffProfile


class TwoFactorAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='approver', password='pw123456')
        self.profile = StaffProfile.objects.create(user=self.user, role='purchasing')

    def _login(self, **extra):
        return self.client.post('/api/auth/login/',
                                {'username': 'approver', 'password': 'pw123456', **extra},
                                format='json')

    def _enforce(self, on=True):
        SystemSetting.objects.update_or_create(
            key='security.mfa_enforced',
            defaults={'value': 'true' if on else 'false', 'value_type': 'boolean'})

    def _enroll(self, mfa_token=None):
        """Run setup+enable; returns (secret, enable_response_data)."""
        body = {'mfa_token': mfa_token} if mfa_token else {}
        self.client.post('/api/auth/2fa/setup/', body, format='json')
        self.profile.refresh_from_db()
        secret = self.profile.mfa_secret
        code = pyotp.TOTP(secret).now()
        eb = {'code': code}
        if mfa_token:
            eb['mfa_token'] = mfa_token
        resp = self.client.post('/api/auth/2fa/enable/', eb, format='json')
        return secret, resp.data

    # ── Tests ──────────────────────────────────────────────────────────────────

    def test_normal_login_without_2fa(self):
        r = self._login()
        self.assertEqual(r.status_code, 200)
        self.assertIn('access', r.data)

    def test_enforcement_forces_setup_for_required_role(self):
        self._enforce(True)
        r = self._login()
        self.assertTrue(r.data.get('mfa_setup_required'))
        self.assertTrue(r.data.get('mfa_token'))
        self.assertNotIn('access', r.data)

    def test_forced_enrollment_completes_login(self):
        self._enforce(True)
        token = self._login().data['mfa_token']
        secret, data = self._enroll(mfa_token=token)
        self.assertIn('access', data)               # logged in after enrolling
        self.assertEqual(len(data['backup_codes']), 10)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.mfa_enabled)

    def test_enrolled_login_challenges_then_verifies(self):
        # Voluntary enrollment via an authenticated session
        self.client.force_authenticate(self.user)
        secret, _ = self._enroll()
        self.client.force_authenticate(None)

        r = self._login()
        self.assertTrue(r.data.get('mfa_required'))
        mfa_token = r.data['mfa_token']

        good = self.client.post('/api/auth/2fa/verify/',
                                {'mfa_token': mfa_token, 'code': pyotp.TOTP(secret).now()},
                                format='json')
        self.assertEqual(good.status_code, 200)
        self.assertIn('access', good.data)

    def test_verify_rejects_wrong_code(self):
        self.client.force_authenticate(self.user)
        self._enroll()
        self.client.force_authenticate(None)
        mfa_token = self._login().data['mfa_token']
        bad = self.client.post('/api/auth/2fa/verify/',
                               {'mfa_token': mfa_token, 'code': '000000'}, format='json')
        self.assertEqual(bad.status_code, 401)
        self.assertNotIn('access', bad.data)

    def test_backup_code_works_once(self):
        self.client.force_authenticate(self.user)
        _, data = self._enroll()
        backup = data['backup_codes'][0]
        self.client.force_authenticate(None)

        t1 = self._login().data['mfa_token']
        first = self.client.post('/api/auth/2fa/verify/',
                                 {'mfa_token': t1, 'code': backup}, format='json')
        self.assertIn('access', first.data)

        t2 = self._login().data['mfa_token']
        reuse = self.client.post('/api/auth/2fa/verify/',
                                 {'mfa_token': t2, 'code': backup}, format='json')
        self.assertEqual(reuse.status_code, 401)    # one-time only

    def test_trusted_device_skips_challenge(self):
        self.client.force_authenticate(self.user)
        secret, _ = self._enroll()
        self.client.force_authenticate(None)

        mfa_token = self._login().data['mfa_token']
        v = self.client.post('/api/auth/2fa/verify/',
                             {'mfa_token': mfa_token, 'code': pyotp.TOTP(secret).now(),
                              'remember_device': True}, format='json')
        device_token = v.data['device_token']
        self.assertTrue(device_token)

        r = self._login(device_token=device_token)
        self.assertIn('access', r.data)             # no challenge this time
        self.assertNotIn('mfa_required', r.data)
