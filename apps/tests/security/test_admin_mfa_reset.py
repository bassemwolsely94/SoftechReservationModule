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
        self.assertLessEqual(len(row.note), 255)     # office note column is varchar(255) until PR #288
        from apps.users.models import USER_ACTIVITY_ACTION_CHOICES
        self.assertIn('mfa_reset', dict(USER_ACTIVITY_ACTION_CHOICES))
        self.assertIsNotNone(self.profile.mfa_reset_at)

    def test_reason_length_capped_at_200(self):
        r = self.admin.post(_url(self.profile), {'reason': 'س' * 201}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('200', r.data['error'])
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.mfa_enabled)
        ok = self.admin.post(_url(self.profile), {'reason': 'س' * 200}, format='json')
        self.assertEqual(ok.status_code, 200, ok.data)
        row = UserActivityLog.objects.get(action='mfa_reset')
        self.assertIn('س' * 200, row.note)                       # never sliced
        self.assertLessEqual(len(row.note), 255)

    def test_user_without_2fa_refused(self):
        _u, plain, _c = make_user('r2fa_plain', role='pharmacist', password=PASSWORD)
        r = self.admin.post(_url(plain), {'reason': 'اختبار'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['error'], 'المصادقة الثنائية غير مفعّلة')
        self.assertFalse(UserActivityLog.objects.filter(action='mfa_reset').exists())

    def test_pending_secret_only_is_reset(self):
        _u, pending, _c = make_user('r2fa_pending', role='pharmacist', password=PASSWORD)
        pending.mfa_secret = pyotp.random_base32()
        pending.save(update_fields=['mfa_secret'])
        r = self.admin.post(_url(pending), {'reason': 'إعداد معلّق'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        pending.refresh_from_db()
        self.assertEqual(pending.mfa_secret, '')

    def test_reset_ends_every_session(self):
        from rest_framework_simplejwt.tokens import RefreshToken
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
        admin_raw = str(RefreshToken.for_user(self.admin_user))    # the admin's own session
        raws = [str(RefreshToken.for_user(self.user)) for _ in range(2)]
        self.assertEqual(OutstandingToken.objects.filter(user=self.user).count(), 2)

        r = self.admin.post(_url(self.profile), {'reason': 'ضاع الموبايل'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['sessions_ended'], 2)
        self.assertEqual(BlacklistedToken.objects.filter(token__user=self.user).count(), 2)
        for raw in raws:
            renew = APIClient().post('/api/auth/refresh/', {'refresh': raw}, format='json')
            self.assertEqual(renew.status_code, 401)
        rows = UserActivityLog.objects.filter(target_user=self.profile, action='mfa_reset')
        self.assertEqual(rows.count(), 1)
        self.assertIn('أُنهيت 2 جلسة', rows.get().note)
        # the admin's own session is untouched
        self.assertFalse(BlacklistedToken.objects.filter(token__user=self.admin_user).exists())
        self.assertFalse(BlacklistedToken.objects.filter(token__jti=RefreshToken(admin_raw)['jti']).exists())

    def test_rotated_cookie_session_ends_too(self):
        from rest_framework_simplejwt.tokens import RefreshToken
        from core.auth_cookies import REFRESH_COOKIE
        c = APIClient()
        c.cookies[REFRESH_COOKIE] = str(RefreshToken.for_user(self.user))
        rotated = c.post('/api/auth/refresh/', {}, format='json')
        self.assertEqual(rotated.status_code, 200, rotated.data)
        self.assertIn(REFRESH_COOKIE, rotated.cookies)              # a new refresh cookie came back

        r = self.admin.post(_url(self.profile), {'reason': 'ضاع الموبايل'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        again = c.post('/api/auth/refresh/', {}, format='json')     # the rotated cookie
        self.assertEqual(again.status_code, 401)

    def test_mfa_enabled_shown_to_admin_only(self):
        mine = self.admin.get('/api/users/staff/', {'search': 'r2fa_target'})
        self.assertEqual(mine.status_code, 200)
        row = next(x for x in mine.data['results'] if x['id'] == self.profile.pk)
        self.assertIs(row['mfa_enabled'], True)

        from apps.users.models import RoleModuleAccess
        RoleModuleAccess.objects.update_or_create(role='supervisor', module='users', action='view',
                                                  defaults={'is_allowed': True})
        _u, sup_profile, sup = make_user('r2fa_sup_list', role='supervisor', password=PASSWORD)
        from core.permissions import matrix_allows
        self.assertTrue(matrix_allows(sup_profile, 'users', 'view'))   # sees the full list serializer
        theirs = sup.get('/api/users/staff/', {'search': 'r2fa_target'})
        self.assertEqual(theirs.status_code, 200)
        rows = theirs.data['results'] if isinstance(theirs.data, dict) else theirs.data
        row = next(x for x in rows if x['id'] == self.profile.pk)
        self.assertIn('mfa_enabled', row)
        self.assertIsNone(row['mfa_enabled'])

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


class ReEnrolmentAfterResetTests(TestCase):
    """I3: a session signed in before the reset (a lost phone's still-valid access token) cannot
    enrol a new authenticator; a fresh sign-in can."""

    def setUp(self):
        _au, _ap, self.admin = make_user('r2fa_admin3', role='admin', password=PASSWORD)
        self.user, self.profile, _ = make_user('r2fa_lost', role='pharmacist', password=PASSWORD)
        _enrol(self.profile)

    def _reset(self):
        r = self.admin.post(_url(self.profile), {'reason': 'ضاع الموبايل'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)

    def test_token_from_before_the_reset_cannot_enrol(self):
        import time
        from rest_framework_simplejwt.tokens import RefreshToken
        old = RefreshToken.for_user(self.user)
        old['auth_at'] = int(time.time()) - 120              # signed in two minutes before the reset
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {old.access_token}')
        self._reset()

        s = c.post('/api/auth/2fa/setup/', {}, format='json')
        self.assertEqual(s.status_code, 403, s.data)
        self.assertEqual(s.data['error'], 'أعد تسجيل الدخول لتفعيل المصادقة الثنائية')
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.mfa_secret, '')
        e = c.post('/api/auth/2fa/enable/', {'code': '123456'}, format='json')
        self.assertIn(e.status_code, (400, 403))              # no pending secret → refused either way
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.mfa_enabled)

    def test_old_token_refused_at_enable_with_a_pending_secret(self):
        import time
        from rest_framework_simplejwt.tokens import RefreshToken
        old = RefreshToken.for_user(self.user)
        old['auth_at'] = int(time.time()) - 120
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {old.access_token}')
        self._reset()
        secret = pyotp.random_base32()                        # a pending secret planted some other way
        StaffProfile.objects.filter(pk=self.profile.pk).update(mfa_secret=secret)
        e = c.post('/api/auth/2fa/enable/', {'code': pyotp.TOTP(secret).now()}, format='json')
        self.assertEqual(e.status_code, 403, e.data)
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.mfa_enabled)

    def test_fresh_sign_in_enrols(self):
        self._reset()
        login = APIClient().post('/api/auth/login/', {'username': 'r2fa_lost', 'password': PASSWORD},
                                 format='json')
        self.assertEqual(login.status_code, 200, login.data)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {login.data["access"]}')
        s = c.post('/api/auth/2fa/setup/', {}, format='json')
        self.assertEqual(s.status_code, 200, s.data)
        e = c.post('/api/auth/2fa/enable/', {'code': pyotp.TOTP(s.data['secret']).now()}, format='json')
        self.assertEqual(e.status_code, 200, e.data)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.mfa_enabled)
