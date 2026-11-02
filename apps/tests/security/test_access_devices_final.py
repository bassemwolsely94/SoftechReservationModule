"""N2 final wave - lockout isolation, session enrolment on refresh, SPA-only enrolment, alert digest,
cookie flags, WebSocket, self-block and other review fixes."""
from unittest import mock

import jwt as pyjwt
import pyotp
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from rest_framework.test import APIClient

from apps.access import devices
from apps.access.models import Device, DeviceUser
from apps.audit.models import AuditLog
from apps.notifications.models import Notification
from apps.tests.factories import make_admin, make_user
from apps.users import mfa
from apps.users.models import UserActivityLog
from apps.users.views import LoginRateThrottle
from core.auth_cookies import user_from_request

XHR = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36'
PW = 'TestPass123'


def _post(client, url, data, xhr=True, **extra):
    if xhr:
        extra.update(XHR)
    return client.post(url, data, format='json', HTTP_USER_AGENT=UA, **extra)


def _login(client, username, xhr=True, **extra):
    return _post(client, '/api/auth/login/', {'username': username, 'password': PW}, xhr=xhr, **extra)


def _dev(**kw):
    secret = devices.new_secret()
    kw.setdefault('name', 'جهاز')
    return secret, Device.objects.create(secret_hash=devices.hash_secret(secret), **kw)


def _claims(token):
    return pyjwt.decode(token, options={'verify_signature': False})


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        p = mock.patch.object(LoginRateThrottle, 'allow_request', return_value=True)
        p.start()
        self.addCleanup(p.stop)


class LockoutIsolationTests(Base):

    def test_blocked_device_refusals_never_lock_the_account(self):
        user, profile, _ = make_user('f_lock')
        secret, _d = _dev(status='blocked')
        c = APIClient()
        c.cookies[devices.COOKIE] = secret
        for _ in range(6):
            self.assertEqual(_login(c, 'f_lock').status_code, 401)
        self.assertEqual(UserActivityLog.objects.filter(target_user=profile, action='login_refused_device').count(), 6)
        self.assertFalse(UserActivityLog.objects.filter(action__in=('login_failed', 'login_locked')).exists())
        self.assertEqual(_login(APIClient(), 'f_lock').status_code, 200)    # no cookie: signs in

    def test_locked_account_creates_no_device(self):
        make_user('f_locked')
        for _ in range(5):
            _post(APIClient(), '/api/auth/login/', {'username': 'f_locked', 'password': 'wrong'})
        r = _login(APIClient(), 'f_locked')
        self.assertEqual(r.status_code, 429)
        self.assertEqual(Device.objects.count(), 0)
        self.assertNotIn(devices.COOKIE, r.cookies)


class SpaOnlyEnrolmentTests(Base):

    def test_script_login_gets_no_device_and_no_claim(self):
        make_user('f_script')
        r = _login(APIClient(), 'f_script', xhr=False)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Device.objects.count(), 0)
        self.assertNotIn(devices.COOKIE, r.cookies)
        self.assertNotIn('dev', _claims(r.data['access']))

    def test_cookie_flags(self):
        make_user('f_flags')
        with override_settings(AUTH_COOKIE_SECURE=True):
            r = _login(APIClient(), 'f_flags')
        m = r.cookies[devices.COOKIE]
        self.assertTrue(m['secure'])
        self.assertTrue(m['httponly'])
        self.assertEqual(m['path'], '/')
        self.assertEqual(int(m['max-age']), devices.COOKIE_MAX_AGE)

    def test_enroll_failure_gives_no_dev_claim(self):
        make_user('f_fail')
        with mock.patch('apps.access.devices.from_secret', side_effect=RuntimeError('boom')):
            r = _login(APIClient(), 'f_fail')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('dev', _claims(r.data['access']))
        self.assertNotIn('dev', _claims(r.data['refresh']))


class RefreshEnrolmentTests(Base):

    def _predeploy_session(self, username):
        c = APIClient()
        r = _login(c, username, xhr=False)          # no device, as before N2
        self.assertEqual(Device.objects.count(), 0)
        c.cookies['erp_refresh'] = r.cookies['erp_refresh'].value
        return c

    def test_pre_n2_session_is_enrolled_on_refresh(self):
        make_user('f_ref')
        c = self._predeploy_session('f_ref')
        r = _post(c, '/api/auth/refresh/', {})
        self.assertEqual(r.status_code, 200)
        dev = Device.objects.get()
        self.assertEqual(dev.status, 'pending')
        self.assertIn(devices.COOKIE, r.cookies)
        self.assertEqual(_claims(r.cookies['erp_access'].value)['dev'], str(dev.public_id))
        self.assertEqual(_claims(r.cookies['erp_refresh'].value)['dev'], str(dev.public_id))
        # the next refresh keeps the claim and makes no second device
        c.cookies[devices.COOKIE] = r.cookies[devices.COOKIE].value
        c.cookies['erp_refresh'] = r.cookies['erp_refresh'].value
        r2 = _post(c, '/api/auth/refresh/', {})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(Device.objects.count(), 1)
        self.assertEqual(_claims(r2.cookies['erp_access'].value)['dev'], str(dev.public_id))

    def test_refresh_without_spa_header_does_not_enrol(self):
        make_user('f_ref2')
        c = self._predeploy_session('f_ref2')
        r = _post(c, '/api/auth/refresh/', {}, xhr=False)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Device.objects.count(), 0)

    def test_refresh_with_blocked_cookie_does_not_stamp(self):
        make_user('f_ref3')
        c = self._predeploy_session('f_ref3')
        secret, _ = _dev(status='blocked')
        c.cookies[devices.COOKIE] = secret
        r = _post(c, '/api/auth/refresh/', {})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('dev', _claims(r.cookies['erp_access'].value))
        self.assertEqual(Device.objects.count(), 1)


class AlertTests(Base):

    def test_alerts_wait_for_commit_and_admins_get_one_digest_per_hour(self):
        make_user('f_al1')
        make_user('f_al2')
        _, admin, _ = make_user('f_al_admin', role='admin')
        _login(APIClient(), 'f_al1')
        self.assertEqual(Notification.objects.count(), 0)          # nothing before commit
        Device.objects.all().delete()
        with self.captureOnCommitCallbacks(execute=True):
            _login(APIClient(), 'f_al1')
        with self.captureOnCommitCallbacks(execute=True):
            _login(APIClient(), 'f_al2')
        self.assertEqual(Notification.objects.filter(recipient=admin, dedup_key__startswith='device_digest_').count(), 1)
        self.assertEqual(Notification.objects.filter(dedup_key__startswith='device_new_').count(), 2)

    def test_one_recipient_failing_does_not_stop_the_rest(self):
        _, p1, _ = make_user('f_al3')
        _, a1, _ = make_user('f_al_a1', role='admin')
        _, a2, _ = make_user('f_al_a2', role='admin')
        _, dev = _dev()
        real = Notification.send_to_user.__func__

        def flaky(cls, staff, *a, **kw):
            if staff.pk == a1.pk:
                raise RuntimeError('push down')
            return real(cls, staff, *a, **kw)
        with mock.patch.object(Notification, 'send_to_user', classmethod(flaky)):
            with self.assertLogs('elrezeiky.access', 'WARNING'):
                devices.notify_new_device(dev, p1)
        self.assertTrue(Notification.objects.filter(recipient=p1).exists())
        self.assertTrue(Notification.objects.filter(recipient=a2, dedup_key__startswith='device_digest_').exists())


class MfaPathTests(Base):

    def test_2fa_enable_at_login_enrols(self):
        user, profile, _ = make_user('f_enrol', role='admin')
        c = APIClient()
        _post(c, '/api/auth/2fa/setup/', {'mfa_token': mfa.make_preauth_token(user, 'enroll')})
        profile.refresh_from_db()
        token = mfa.make_preauth_token(user, 'enroll')
        r = _post(c, '/api/auth/2fa/enable/', {'mfa_token': token, 'code': pyotp.TOTP(profile.mfa_secret).now()})
        self.assertEqual(r.status_code, 200, r.data)
        dev = Device.objects.get()
        self.assertIn(devices.COOKIE, r.cookies)
        self.assertEqual(_claims(r.data['access'])['dev'], str(dev.public_id))

    def test_blocked_cookie_refused_at_2fa_enable_at_login(self):
        user, profile, _ = make_user('f_enrol2', role='admin')
        c = APIClient()
        _post(c, '/api/auth/2fa/setup/', {'mfa_token': mfa.make_preauth_token(user, 'enroll')})
        profile.refresh_from_db()
        secret, _ = _dev(status='blocked')
        c.cookies[devices.COOKIE] = secret
        r = _post(c, '/api/auth/2fa/enable/', {'mfa_token': mfa.make_preauth_token(user, 'enroll'),
                                               'code': pyotp.TOTP(profile.mfa_secret).now()})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.data['error'], devices.BLOCKED_MESSAGE)
        self.assertNotIn('access', r.data)
        self.assertFalse(UserActivityLog.objects.filter(action='login_failed').exists())

    def test_voluntary_enable_from_settings_sets_no_device_cookie(self):
        user, profile, _ = make_user('f_vol')
        c = APIClient()
        c.force_authenticate(user)
        _post(c, '/api/auth/2fa/setup/', {})
        profile.refresh_from_db()
        r = _post(c, '/api/auth/2fa/enable/', {'code': pyotp.TOTP(profile.mfa_secret).now()})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertNotIn(devices.COOKIE, r.cookies)
        self.assertEqual(Device.objects.count(), 0)

    def test_pending_device_earns_no_remember(self):
        _, profile, _ = make_user('f_rem')
        _, dev = _dev(status='pending')
        devices.remember_mfa(dev, profile)
        self.assertFalse(DeviceUser.objects.filter(device=dev, mfa_remembered_at__isnull=False).exists())
        dev.status = 'approved'
        devices.remember_mfa(dev, profile)
        self.assertTrue(DeviceUser.objects.filter(device=dev, mfa_remembered_at__isnull=False).exists())


class RevokedAccessTests(Base):

    def _signed(self, username):
        make_user(username)
        c = APIClient()
        r = _login(c, username)
        c.cookies[devices.COOKIE] = r.cookies[devices.COOKIE].value
        return c, r, Device.objects.get()

    def test_bearer_header_with_blocked_dev_is_401(self):
        c, r, dev = self._signed('f_bearer')
        dev.status = 'blocked'
        dev.save()
        resp = APIClient().get('/api/auth/me/', HTTP_AUTHORIZATION=f'Bearer {r.data["access"]}')
        self.assertEqual(resp.status_code, 401)

    def test_user_from_request_none_for_revoked_dev(self):
        c, r, dev = self._signed('f_ufr')
        req = RequestFactory().get('/', HTTP_AUTHORIZATION=f'Bearer {r.data["access"]}')
        self.assertIsNotNone(user_from_request(req))
        dev.status = 'blocked'
        dev.save()
        # the user is worked out once per request (final wave F6): the next request is refused
        req = RequestFactory().get('/', HTTP_AUTHORIZATION=f'Bearer {r.data["access"]}')
        self.assertIsNone(user_from_request(req))
        req2 = RequestFactory().get('/')
        req2.COOKIES['erp_access'] = r.data['access']
        self.assertIsNone(user_from_request(req2))

    def test_websocket_refuses_revoked_device_token(self):
        from apps.notifications.middleware import JWTAuthMiddleware
        c, r, dev = self._signed('f_ws')
        fn = JWTAuthMiddleware.__dict__['_get_user_from_token'].func
        mw = JWTAuthMiddleware(None)
        self.assertTrue(fn(mw, r.data['access']).is_authenticated)
        dev.status = 'blocked'
        dev.save()
        self.assertFalse(fn(mw, r.data['access']).is_authenticated)


class AdminFixTests(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        p = mock.patch.object(LoginRateThrottle, 'allow_request', return_value=True)
        p.start()
        self.addCleanup(p.stop)
        self.admin_user, self.admin, self.api = make_admin('f_admin')

    def test_admin_cannot_block_or_retire_own_device(self):
        c = APIClient()
        r = _login(c, 'f_admin')
        self.assertEqual(r.status_code, 200, r.data)
        own = Device.objects.get()
        c.cookies[devices.COOKIE] = r.cookies[devices.COOKIE].value
        self.assertEqual(c.post(f'/api/access/devices/{own.pk}/block/', {'note': 'x'}, format='json', **XHR).status_code, 400)
        self.assertEqual(c.post(f'/api/access/devices/{own.pk}/retire/', {}, format='json', **XHR).status_code, 400)
        own.refresh_from_db()
        self.assertEqual(own.status, 'pending')
        _, other = _dev()
        self.assertEqual(c.post(f'/api/access/devices/{other.pk}/block/', {'note': 'x'}, format='json', **XHR).status_code, 200)

    def test_patch_retired_is_400_and_noop_not_audited(self):
        _, d = _dev(name='a')
        before = AuditLog.objects.filter(action='device_changed').count()
        r = self.api.patch(f'/api/access/devices/{d.pk}/', {'name': 'a'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(AuditLog.objects.filter(action='device_changed').count(), before)
        _, ret = _dev(status='retired')
        self.assertEqual(self.api.patch(f'/api/access/devices/{ret.pk}/', {'name': 'b'}, format='json').status_code, 400)

    def test_invalidate_runs_again_after_commit(self):
        _, d = _dev()
        with self.captureOnCommitCallbacks(execute=False) as cbs:
            devices.invalidate(d)
        cache.set(f'access:devrev:{d.public_id}', False, 60)
        for cb in cbs:
            cb()
        self.assertIsNone(cache.get(f'access:devrev:{d.public_id}'))

    def test_touch_records_network_too(self):
        secret, d = _dev()
        req = RequestFactory().get('/', REMOTE_ADDR='203.0.113.7')
        req.COOKIES[devices.COOKIE] = secret
        devices.resolve(req)
        d.refresh_from_db()
        self.assertEqual(d.last_ip, '203.0.113.7')
        self.assertTrue(d.last_network)
