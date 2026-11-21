"""
Admin resets a user's 2FA (UAT 2026-11-21: a user who lost both phone and backup codes could only
be cleared in the database).

POST /api/users/<pk>/reset-2fa/ {reason} — admin only (IsAdminRole, like forget-devices). Turns 2FA
off, clears the secret and every backup code, forgets every remembered device, and writes one
`mfa_reset` activity row with the reason. Password, role and lockout are left alone.
"""
import pyotp
from django.test import TestCase
from rest_framework.test import APIClient

from apps.config.models import SystemSetting
from apps.tests.factories import make_user
from apps.users import mfa
from apps.users.models import StaffProfile, UserActivityLog

PASSWORD = 'pw-reset2fa-123456'


def _enrol(profile):
    """2FA on for `profile` with a real secret and backup codes."""
    profile.mfa_secret = pyotp.random_base32()
    _plain, hashed = mfa.generate_backup_codes()
    profile.mfa_backup_codes = hashed
    profile.mfa_enabled = True
    profile.save(update_fields=['mfa_secret', 'mfa_backup_codes', 'mfa_enabled'])


def _remember(profile):
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


def _url(profile):
    return f'/api/users/{profile.pk}/reset-2fa/'


class AdminMfaResetTests(TestCase):

    def setUp(self):
        self.admin_user, self.admin_profile, self.admin = make_user('r2fa_admin', role='admin', password=PASSWORD)
        self.user, self.profile, _ = make_user('r2fa_target', role='purchasing', password=PASSWORD)
        _enrol(self.profile)

    def test_admin_resets_2fa(self):
        device_secret = _remember(self.profile)
        self.assertTrue(_remembered(device_secret, self.profile))
        password_before = self.user.password
        role_before = self.profile.role

        r = self.admin.post(_url(self.profile), {'reason': '  ضاع الموبايل وأكواد الاحتياط  '}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn('detail', r.data)

        self.profile.refresh_from_db()
        self.user.refresh_from_db()
        self.assertFalse(self.profile.mfa_enabled)
        self.assertEqual(self.profile.mfa_secret, '')
        self.assertEqual(self.profile.mfa_backup_codes, [])
        self.assertIsNone(self.profile.mfa_confirmed_at)
        self.assertFalse(_remembered(device_secret, self.profile))
        # nothing else touched
        self.assertEqual(self.user.password, password_before)
        self.assertEqual(self.profile.role, role_before)

        rows = UserActivityLog.objects.filter(action='mfa_reset')
        self.assertEqual(rows.count(), 1)
        row = rows.get()
        self.assertEqual(row.target_user, self.profile)
        self.assertEqual(row.changed_by, self.admin_profile)
        self.assertIn('ضاع الموبايل وأكواد الاحتياط', row.note)
        self.assertTrue(row.ip_address)
        self.assertLessEqual(len('mfa_reset'), 20)    # the office column is still varchar(20)

    def test_reason_required(self):
        for body in ({}, {'reason': ''}, {'reason': '   '}):
            r = self.admin.post(_url(self.profile), body, format='json')
            self.assertEqual(r.status_code, 400, body)
            self.assertIn('error', r.data)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.mfa_enabled)
        self.assertFalse(UserActivityLog.objects.filter(action='mfa_reset').exists())

    def test_admin_cannot_reset_own_2fa_here(self):
        _enrol(self.admin_profile)
        r = self.admin.post(_url(self.admin_profile), {'reason': 'اختبار'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.admin_profile.refresh_from_db()
        self.assertTrue(self.admin_profile.mfa_enabled)
        self.assertFalse(UserActivityLog.objects.filter(action='mfa_reset').exists())

    def test_non_admin_refused(self):
        for role in ('supervisor', 'pharmacist'):
            _u, _p, client = make_user(f'r2fa_{role}', role=role, password=PASSWORD)
            r = client.post(_url(self.profile), {'reason': 'اختبار'}, format='json')
            self.assertEqual(r.status_code, 403, role)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.mfa_enabled)
        self.assertFalse(UserActivityLog.objects.filter(action='mfa_reset').exists())

    def test_anonymous_refused(self):
        r = APIClient().post(_url(self.profile), {'reason': 'اختبار'}, format='json')
        self.assertIn(r.status_code, (401, 403))

    def test_unknown_user_404(self):
        r = self.admin.post('/api/users/999999/reset-2fa/', {'reason': 'اختبار'}, format='json')
        self.assertEqual(r.status_code, 404)


class SignInAfterResetTests(TestCase):
    """After a reset the next password sign-in goes to enrolment when the role requires 2FA
    (enforcement on), and straight in when it does not."""

    def setUp(self):
        SystemSetting.objects.update_or_create(key='security.mfa_enforced',
                                               defaults={'value': 'true', 'value_type': 'boolean'})
        _au, _ap, self.admin = make_user('r2fa_admin2', role='admin', password=PASSWORD)

    def _reset_then_login(self, username, role):
        _u, profile, _c = make_user(username, role=role, password=PASSWORD)
        _enrol(profile)
        r = self.admin.post(_url(profile), {'reason': 'فقد الهاتف'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        return APIClient().post('/api/auth/login/', {'username': username, 'password': PASSWORD},
                                format='json')

    def test_required_role_goes_to_enrolment(self):
        r = self._reset_then_login('r2fa_buyer', 'purchasing')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data.get('mfa_setup_required'), r.data)
        self.assertNotIn('access', r.data)
        # and the enrolment token really enrols: setup → enable completes the sign-in
        token = r.data['mfa_token']
        c = APIClient()
        s = c.post('/api/auth/2fa/setup/', {'mfa_token': token}, format='json')
        self.assertEqual(s.status_code, 200, s.data)
        e = c.post('/api/auth/2fa/enable/', {'mfa_token': token,
                                             'code': pyotp.TOTP(s.data['secret']).now()}, format='json')
        self.assertEqual(e.status_code, 200, e.data)
        self.assertIn('access', e.data)
        self.assertEqual(len(e.data['backup_codes']), 10)

    def test_role_without_2fa_signs_in(self):
        r = self._reset_then_login('r2fa_pharm', 'pharmacist')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn('access', r.data)
        self.assertFalse(r.data.get('mfa_required'))
        self.assertFalse(r.data.get('mfa_setup_required'))
