"""N3 / Task 5 - sign-in, refresh and 2FA follow the access zone; session caps; legacy remember
token removed."""
import time
from unittest import mock

import pyotp
from django.core import signing
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.access import devices, session_policy
from apps.access.models import Device
from apps.access.policy import REASON_MESSAGES
from apps.notifications.models import Notification
from apps.tests.factories import make_user
from apps.users import mfa
from apps.users.models import UserActivityLog

XHR = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36'
INSIDE = {'HTTP_X_ELR_NETWORK': 'internal'}
OUTSIDE = {'HTTP_X_ELR_NETWORK': 'external'}
HOUR = 3600
BLOCKED_LOGIN = 'الدخول من خارج شبكة الشركة غير متاح لدورك'

trusted = override_settings(NETWORK_HEADER_TRUSTED=True, NETWORK_PROXY_KEY='')


def _approved_device():
    secret = devices.new_secret()
    dev = Device.objects.create(secret_hash=devices.hash_secret(secret), name='جهاز', status='approved')
    return secret, dev


def _login(client, username, password='TestPass123', net=OUTSIDE, **body):
    return client.post('/api/auth/login/', {'username': username, 'password': password, **body},
                       format='json', HTTP_USER_AGENT=UA, **XHR, **net)


def _refresh(client, token, net=OUTSIDE):
    client.cookies['erp_refresh'] = str(token)
    return client.post('/api/auth/refresh/', {}, format='json', HTTP_USER_AGENT=UA, **XHR, **net)


def _token(user, zone, auth_at):
    t = RefreshToken.for_user(user)
    session_policy.stamp(t, zone, auth_at=auth_at)
    return t


class Base(TestCase):

    def setUp(self):
        cache.clear()                     # login throttle + policy cache
        self.addCleanup(cache.clear)


# ── unit: the interfaces ────────────────────────────────────────────────────────────────

class InterfaceTests(Base):

    def test_stamp_defaults_auth_at_to_now(self):
        user, _, _ = make_user('sp_stamp')
        t = RefreshToken.for_user(user)
        before = int(time.time())
        session_policy.stamp(t, 'Z3')
        self.assertEqual(t['zone'], 'Z3')
        self.assertGreaterEqual(t['auth_at'], before)
        self.assertEqual(AccessToken(str(t.access_token))['auth_at'], t['auth_at'])
        session_policy.stamp(t, 'Z1', auth_at=123)
        self.assertEqual((t['zone'], t['auth_at']), ('Z1', 123))

    def test_cap_hours_and_mfa_by_zone(self):
        _, admin, _ = make_user('sp_cap_a', role='admin')
        _, rider, _ = make_user('sp_cap_r', role='delivery')
        self.assertIsNone(session_policy.cap_hours(admin, 'Z1'))
        self.assertIsNone(session_policy.cap_hours(admin, 'Z2'))
        self.assertEqual(session_policy.cap_hours(admin, 'Z3'), 8)
        self.assertEqual(session_policy.cap_hours(rider, 'Z4'), 12)
        self.assertEqual(session_policy.cap_hours(rider, None), 12)       # signed-in, no zone = Z4
        self.assertFalse(session_policy.mfa_required_in_zone(admin, 'Z1'))
        self.assertFalse(session_policy.mfa_required_in_zone(admin, 'Z2'))
        self.assertTrue(session_policy.mfa_required_in_zone(admin, 'Z3'))
        self.assertTrue(session_policy.mfa_required_in_zone(rider, 'Z4'))
        self.assertIsNone(session_policy.cap_hours(None, 'Z4'))

    # Review Focus 2
    def test_token_without_auth_at_uses_iat(self):
        user, admin, _ = make_user('sp_iat', role='admin')
        t = RefreshToken.for_user(user)
        self.assertNotIn('auth_at', t.payload)
        t['iat'] = int(time.time()) - 9 * HOUR
        self.assertEqual(session_policy.refresh_allowed(admin, t, 'Z3'), (False, 'expired'))
        t['iat'] = int(time.time()) - 7 * HOUR
        self.assertEqual(session_policy.refresh_allowed(admin, t, 'Z3'), (True, None))
        # auth_at wins over iat when both are present
        t['auth_at'] = int(time.time()) - 9 * HOUR
        self.assertEqual(session_policy.refresh_allowed(admin, t, 'Z3'), (False, 'expired'))

    @trusted
    @override_settings(NETWORK_POLICY_ENFORCEMENT='enforce')
    def test_old_token_keeps_its_iat_as_auth_at_across_rotation(self):
        user, _, _ = make_user('sp_iat2', role='admin')
        secret, _ = _approved_device()
        t = RefreshToken.for_user(user)
        old_iat = int(time.time()) - 2 * HOUR
        t['iat'] = old_iat
        c = APIClient()
        c.cookies[devices.COOKIE] = secret
        r = _refresh(c, t)
        self.assertEqual(r.status_code, 200, r.data)
        new = RefreshToken(r.cookies['erp_refresh'].value)
        self.assertEqual(new['auth_at'], old_iat)
        self.assertEqual(new['zone'], 'Z3')
        self.assertEqual(AccessToken(r.cookies['erp_access'].value)['auth_at'], old_iat)


# ── refresh: caps and re-evaluation ─────────────────────────────────────────────────────

@trusted
@override_settings(NETWORK_POLICY_ENFORCEMENT='enforce')
class RefreshCapTests(Base):

    def test_external_session_capped_8h(self):
        user, _, _ = make_user('sp_8h', role='admin')
        secret, _ = _approved_device()
        auth_at = int(time.time())
        t = _token(user, 'Z3', auth_at)
        c = APIClient()
        c.cookies[devices.COOKIE] = secret
        with mock.patch.object(session_policy, '_now', return_value=auth_at + 7 * HOUR):
            ok = _refresh(c, t)
        self.assertEqual(ok.status_code, 200, ok.data)
        new = RefreshToken(ok.cookies['erp_refresh'].value)
        self.assertEqual(new['auth_at'], auth_at)                  # kept across rotation
        self.assertLessEqual(int(ok.cookies['erp_refresh']['max-age']), HOUR)   # the rest of the 8 h
        with mock.patch.object(session_policy, '_now', return_value=auth_at + 8 * HOUR + 60):
            r = _refresh(c, new)
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.data['reason'], 'expired')
        self.assertEqual(r.data['zone'], 'Z3')
        self.assertEqual(r.cookies['erp_refresh'].value, '')      # cleared

    def test_rider_capped_12h(self):
        user, _, _ = make_user('sp_12h', role='delivery')
        auth_at = int(time.time())
        c = APIClient()                                            # no device: Z4
        with mock.patch.object(session_policy, '_now', return_value=auth_at + 11 * HOUR):
            ok = _refresh(c, _token(user, 'Z4', auth_at))
        self.assertEqual(ok.status_code, 200, ok.data)
        with mock.patch.object(session_policy, '_now', return_value=auth_at + 12 * HOUR + 60):
            r = _refresh(APIClient(), _token(user, 'Z4', auth_at))
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.data['reason'], 'expired')

    def test_internal_session_not_capped(self):
        user, _, _ = make_user('sp_in', role='pharmacist')
        secret, _ = _approved_device()
        c = APIClient()
        c.cookies[devices.COOKIE] = secret
        r = _refresh(c, _token(user, 'Z1', int(time.time()) - 30 * HOUR), net=INSIDE)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(int(r.cookies['erp_refresh']['max-age']), 7 * 24 * HOUR)

    def test_internal_token_used_outside_reevaluated(self):
        user, _, _ = make_user('sp_reeval', role='pharmacist')
        secret, _ = _approved_device()
        c = APIClient()
        c.cookies[devices.COOKIE] = secret
        with self.assertLogs('elrezeiky.access', 'WARNING'):
            r = _refresh(c, _token(user, 'Z1', int(time.time())))
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.data, {'detail': REASON_MESSAGES['blocked'], 'zone': 'Z3', 'reason': 'blocked'})

    @override_settings(NETWORK_POLICY_ENFORCEMENT='log')
    def test_log_mode_only_logs_and_restamps_zone(self):
        user, _, _ = make_user('sp_log', role='pharmacist')
        auth_at = int(time.time()) - 20 * HOUR
        with self.assertLogs('elrezeiky.access', 'WARNING') as cm:
            r = _refresh(APIClient(), _token(user, 'Z1', auth_at))
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn('zone would-deny', '\n'.join(cm.output))
        new = RefreshToken(r.cookies['erp_refresh'].value)
        self.assertEqual((new['zone'], new['auth_at']), ('Z4', auth_at))
        self.assertEqual(int(r.cookies['erp_refresh']['max-age']), 7 * 24 * HOUR)   # no cap outside enforce


# ── sign-in ─────────────────────────────────────────────────────────────────────────────

@trusted
class SignInTests(Base):

    @override_settings(NETWORK_POLICY_ENFORCEMENT='enforce')
    def test_blocked_role_login_refused_enforce_only(self):
        make_user('sp_blk', role='pharmacist')
        bad = _login(APIClient(), 'sp_blk', password='wrong-password')
        self.assertEqual(bad.status_code, 401)                     # no account enumeration
        r = _login(APIClient(), 'sp_blk')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data, {'error': BLOCKED_LOGIN, 'zone': 'Z4', 'reason': 'blocked'})
        self.assertNotIn('erp_access', r.cookies)
        self.assertEqual(UserActivityLog.objects.filter(action='login_refused_zone').count(), 1)
        self.assertEqual(UserActivityLog.objects.filter(action='login_failed').count(), 1)   # only the bad password
        self.assertEqual(_login(APIClient(), 'sp_blk', net=INSIDE).status_code, 200)
        with override_settings(NETWORK_POLICY_ENFORCEMENT='log'):
            with self.assertLogs('elrezeiky.access', 'WARNING') as cm:
                ok = _login(APIClient(), 'sp_blk')
            self.assertEqual(ok.status_code, 200, ok.data)
            self.assertIn('zone would-deny', '\n'.join(cm.output))
        with override_settings(NETWORK_POLICY_ENFORCEMENT='off'):
            ok = _login(APIClient(), 'sp_blk')
            self.assertEqual(ok.status_code, 200, ok.data)
            claims = RefreshToken(ok.data['refresh'])
            self.assertEqual(claims['zone'], 'Z4')
            self.assertIn('auth_at', claims.payload)

    @override_settings(NETWORK_POLICY_ENFORCEMENT='enforce')
    def test_external_requires_2fa(self):
        user, profile, _ = make_user('sp_mfa', role='delivery')      # rider: allowed in Z4
        r = _login(APIClient(), 'sp_mfa')
        self.assertTrue(r.data.get('mfa_setup_required'), r.data)
        self.assertNotIn('access', r.data)
        inside = _login(APIClient(), 'sp_mfa', net=INSIDE)
        self.assertIn('access', inside.data)                         # Z2: no 2FA by zone
        profile.mfa_enabled = True
        profile.mfa_secret = pyotp.random_base32()
        profile.save()
        r = _login(APIClient(), 'sp_mfa')
        self.assertTrue(r.data.get('mfa_required'), r.data)
        with override_settings(NETWORK_POLICY_ENFORCEMENT='log'):
            profile.mfa_enabled = False
            profile.save()
            with self.assertLogs('elrezeiky.access', 'WARNING'):
                ok = _login(APIClient(), 'sp_mfa')
            self.assertIn('access', ok.data)                         # log mode does not force 2FA yet

    @override_settings(NETWORK_POLICY_ENFORCEMENT='enforce')
    def test_external_2fa_skipped_on_remembered_approved_device(self):
        user, profile, _ = make_user('sp_rem', role='admin')
        profile.mfa_enabled = True
        profile.mfa_secret = pyotp.random_base32()
        profile.save()
        secret, dev = _approved_device()
        devices.remember_mfa(dev, profile)
        c = APIClient()
        c.cookies[devices.COOKIE] = secret
        r = _login(c, 'sp_rem')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn('access', r.data)
        self.assertEqual(RefreshToken(r.data['refresh'])['zone'], 'Z3')

    def test_all_sign_in_paths_stamp_claims(self):
        user, profile, _ = make_user('sp_paths', role='admin')
        before = int(time.time())
        r = _login(APIClient(), 'sp_paths', net=INSIDE)
        self.assertEqual(RefreshToken(r.data['refresh'])['zone'], 'Z2')
        self.assertEqual(AccessToken(r.data['access'])['zone'], 'Z2')
        self.assertGreaterEqual(AccessToken(r.data['access'])['auth_at'], before)
        # forced enrolment (enable at login)
        c = APIClient()
        c.post('/api/auth/2fa/setup/', {'mfa_token': mfa.make_preauth_token(user, 'enroll')},
               format='json', **XHR, **OUTSIDE)
        profile.refresh_from_db()
        e = c.post('/api/auth/2fa/enable/', {'mfa_token': mfa.make_preauth_token(user, 'enroll'),
                                             'code': pyotp.TOTP(profile.mfa_secret).now()},
                   format='json', **XHR, **OUTSIDE)
        self.assertEqual(e.status_code, 200, e.data)
        self.assertEqual(RefreshToken(e.data['refresh'])['zone'], 'Z4')
        self.assertIn('auth_at', AccessToken(e.data['access']).payload)
        # verify
        cache.clear()
        v = APIClient().post('/api/auth/2fa/verify/', {'mfa_token': mfa.make_preauth_token(user, 'login'),
                                                       'code': pyotp.TOTP(profile.mfa_secret).now()},
                             format='json', **XHR, **INSIDE)
        self.assertEqual(v.status_code, 200, v.data)
        self.assertEqual(RefreshToken(v.data['refresh'])['zone'], 'Z2')
        self.assertIn('auth_at', RefreshToken(v.data['refresh']).payload)

    @override_settings(NETWORK_POLICY_ENFORCEMENT='enforce')
    def test_external_sign_in_cookie_capped(self):
        make_user('sp_ck', role='delivery')
        with override_settings(NETWORK_POLICY_ENFORCEMENT='log'):
            r = _login(APIClient(), 'sp_ck')
        self.assertEqual(int(r.cookies['erp_refresh']['max-age']), 7 * 24 * HOUR)
        user, profile, _ = make_user('sp_ck2', role='delivery')
        profile.mfa_enabled = True
        profile.mfa_secret = pyotp.random_base32()
        profile.save()
        v = APIClient().post('/api/auth/2fa/verify/', {'mfa_token': mfa.make_preauth_token(user, 'login'),
                                                       'code': pyotp.TOTP(profile.mfa_secret).now()},
                             format='json', **XHR, **OUTSIDE)
        self.assertEqual(v.status_code, 200, v.data)
        self.assertAlmostEqual(int(v.cookies['erp_refresh']['max-age']), 12 * HOUR, delta=3)

    def test_legacy_device_token_ignored(self):
        self.assertFalse(hasattr(mfa, 'make_device_token'))
        self.assertFalse(hasattr(mfa, 'valid_device_token'))
        user, profile, _ = make_user('sp_legacy', role='purchasing')
        profile.mfa_enabled = True
        profile.mfa_secret = pyotp.random_base32()
        profile.save()
        old = signing.dumps({'uid': user.id, 'fp': mfa._device_fingerprint(user)}, salt='mfa-device')
        r = _login(APIClient(), 'sp_legacy', net=INSIDE, device_token=old)
        self.assertTrue(r.data.get('mfa_required'), r.data)
        v = APIClient().post('/api/auth/2fa/verify/', {'mfa_token': r.data['mfa_token'],
                                                       'code': pyotp.TOTP(profile.mfa_secret).now(),
                                                       'remember_device': True},
                             format='json', **XHR, **INSIDE)
        self.assertEqual(v.status_code, 200, v.data)
        self.assertNotIn('device_token', v.data)

    @override_settings(NETWORK_POLICY_ENFORCEMENT='log')
    def test_login_alert_external(self):
        _, me, _ = make_user('sp_alert', role='admin')
        _, other_admin, _ = make_user('sp_alert_adm', role='admin')
        title = 'دخول من خارج الشبكة'
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(_login(APIClient(), 'sp_alert', net=INSIDE).status_code, 200)
        self.assertFalse(Notification.objects.filter(title__contains=title).exists())   # inside: no alert
        for _ in range(2):
            with self.captureOnCommitCallbacks(execute=True):
                r = _login(APIClient(), 'sp_alert')
            self.assertEqual(r.status_code, 200, r.data)
        mine = Notification.objects.filter(recipient=me, dedup_key__startswith='login_external_user_')
        self.assertEqual(mine.count(), 1)                               # dedup per hour
        digest = Notification.objects.filter(recipient=other_admin, title__contains=title,
                                             dedup_key__startswith='login_external_digest_')
        self.assertEqual(digest.count(), 1)

    @override_settings(NETWORK_POLICY_ENFORCEMENT='log')
    def test_alert_failure_never_breaks_sign_in(self):
        make_user('sp_alert2', role='admin')
        with mock.patch.object(Notification, 'send_to_user', side_effect=RuntimeError('down')):
            with self.captureOnCommitCallbacks(execute=True):
                r = _login(APIClient(), 'sp_alert2')
        self.assertEqual(r.status_code, 200, r.data)

    @override_settings(NETWORK_POLICY_ENFORCEMENT='log')
    def test_zone_failure_never_breaks_sign_in(self):
        make_user('sp_fail', role='admin')
        with mock.patch('apps.access.session_policy.policy_for', side_effect=RuntimeError('db')):
            r = _login(APIClient(), 'sp_fail')
        self.assertEqual(r.status_code, 200, r.data)
        with mock.patch('apps.access.session_policy.request_network', side_effect=RuntimeError('x')):
            r = _login(APIClient(), 'sp_fail', net=INSIDE)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(RefreshToken(r.data['refresh'])['zone'], 'Z4')
