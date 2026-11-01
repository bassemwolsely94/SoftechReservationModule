"""N2 / Task 1 - Device registry model and secret helpers."""
import hashlib
from types import SimpleNamespace

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.access import devices
from apps.access.models import Device, DeviceUser
from apps.access.network import EXTERNAL, INTERNAL, NetworkInfo
from apps.tests.factories import make_branch, make_user


def _device(secret=None, **kw):
    secret = secret or devices.new_secret()
    kw.setdefault('name', 'جهاز')
    return secret, Device.objects.create(secret_hash=devices.hash_secret(secret), **kw)


class SecretTests(TestCase):

    def test_hash_is_sha256_and_secret_never_stored(self):
        secret = devices.new_secret()
        self.assertGreaterEqual(len(secret), 43)
        self.assertNotEqual(secret, devices.new_secret())
        self.assertEqual(devices.hash_secret(secret), hashlib.sha256(secret.encode()).hexdigest())
        _, dev = _device(secret)
        self.assertEqual(dev.secret_hash, devices.hash_secret(secret))
        self.assertNotIn(secret, [dev.secret_hash, str(dev.public_id), dev.name])
        self.assertEqual(devices.COOKIE, 'erp_device')

    def test_from_secret_none_unknown_retired(self):
        self.assertIsNone(devices.from_secret(None))
        self.assertIsNone(devices.from_secret(''))
        self.assertIsNone(devices.from_secret('nope'))
        s_ret, d_ret = _device(status='retired')
        self.assertIsNone(devices.from_secret(s_ret))
        s_pend, d_pend = _device()
        self.assertEqual(d_pend.status, 'pending')
        self.assertEqual(devices.from_secret(s_pend), d_pend)
        s_blk, d_blk = _device(status='blocked')
        self.assertEqual(devices.from_secret(s_blk), d_blk)


class KindTests(TestCase):

    def test_guess_kind(self):
        branch = make_branch()
        site = SimpleNamespace(branch_id=branch.id)
        iphone = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148'
        desktop = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120'
        internal = NetworkInfo(INTERNAL, '10.0.0.5', site)
        external = NetworkInfo(EXTERNAL, '1.2.3.4', None)
        self.assertEqual(devices.guess_kind(iphone, internal), 'phone')
        self.assertEqual(devices.guess_kind(desktop, internal), 'branch_pc')
        self.assertEqual(devices.guess_kind(desktop, external), 'personal_laptop')
        self.assertEqual(devices.guess_kind(desktop, NetworkInfo(INTERNAL, '10.0.0.5', None)), 'personal_laptop')
        self.assertEqual(devices.guess_kind('', external), 'personal_laptop')

    def test_snapshot(self):
        _, dev = _device(name='x')
        snap = devices.snapshot(dev)
        self.assertEqual(snap['name'], 'x')
        self.assertEqual(snap['status'], 'pending')
        self.assertNotIn('secret_hash', snap)


class DeviceUserTests(TestCase):

    def test_device_user_unique(self):
        _, dev = _device()
        _, profile, _ = make_user('dev_u1')
        DeviceUser.objects.create(device=dev, user=profile)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DeviceUser.objects.create(device=dev, user=profile)


# ── Task 2: enrollment at sign-in ─────────────────────────────────────────────────

from unittest import mock

import jwt as pyjwt
import pyotp
from django.conf import settings
from rest_framework.test import APIClient

from apps.notifications.models import Notification
from apps.users.models import UserActivityLog

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36'


def _login(client, username, password='TestPass123', **extra):
    return client.post('/api/auth/login/', {'username': username, 'password': password},
                       format='json', HTTP_USER_AGENT=UA, **extra)


class EnrollmentTests(TestCase):

    def setUp(self):
        cache.clear()      # the per-IP login throttle (10/min) is not under test
        self.addCleanup(cache.clear)
        self.user, self.profile, _ = make_user('enr_u1')

    def test_first_login_creates_pending_device_and_cookie(self):
        r = _login(APIClient(), 'enr_u1')
        self.assertEqual(r.status_code, 200)
        morsel = r.cookies[devices.COOKIE]
        self.assertTrue(morsel['httponly'])
        self.assertEqual(morsel['samesite'], 'Strict')
        dev = Device.objects.get()
        self.assertEqual(dev.status, 'pending')
        self.assertEqual(dev.owner, self.profile)
        self.assertEqual(dev.secret_hash, devices.hash_secret(morsel.value))
        self.assertNotEqual(dev.secret_hash, morsel.value)
        self.assertLessEqual(len(dev.name), 120)
        self.assertIn('Chrome', dev.name)
        self.assertTrue(DeviceUser.objects.filter(device=dev, user=self.profile).exists())
        log = UserActivityLog.objects.filter(action='login_success').latest('id')
        self.assertEqual(log.device, dev)

    def test_access_token_carries_dev_claim(self):
        r = _login(APIClient(), 'enr_u1')
        dev = Device.objects.get()
        claims = pyjwt.decode(r.cookies['erp_access'].value, options={'verify_signature': False})
        self.assertEqual(claims['dev'], str(dev.public_id))
        body = pyjwt.decode(r.data['access'], options={'verify_signature': False})
        self.assertEqual(body['dev'], str(dev.public_id))

    def test_second_login_same_cookie_reuses_device(self):
        c = APIClient()
        r1 = _login(c, 'enr_u1')
        c.cookies[devices.COOKIE] = r1.cookies[devices.COOKIE].value
        r2 = _login(c, 'enr_u1')
        self.assertEqual(Device.objects.count(), 1)
        self.assertNotIn(devices.COOKIE, r2.cookies)

    def test_second_user_same_browser_reuses_device(self):
        make_user('enr_u2')
        c = APIClient()
        r1 = _login(c, 'enr_u1')
        Device.objects.update(status='approved')
        c.cookies[devices.COOKIE] = r1.cookies[devices.COOKIE].value
        _login(c, 'enr_u2')
        self.assertEqual(Device.objects.count(), 1)
        self.assertEqual(DeviceUser.objects.count(), 2)
        self.assertEqual(Device.objects.get().status, 'approved')

    def test_unknown_cookie_gets_new_device(self):
        c = APIClient()
        c.cookies[devices.COOKIE] = 'forged-value'
        r = _login(c, 'enr_u1')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Device.objects.count(), 1)
        self.assertNotEqual(r.cookies[devices.COOKIE].value, 'forged-value')

    def test_retired_cookie_gets_new_device(self):
        secret, old = _device(status='retired')
        c = APIClient()
        c.cookies[devices.COOKIE] = secret
        r = _login(c, 'enr_u1')
        self.assertEqual(Device.objects.count(), 2)
        old.refresh_from_db()
        self.assertEqual(old.status, 'retired')
        self.assertNotEqual(r.cookies[devices.COOKIE].value, secret)

    def test_new_device_notifies_user_and_admins(self):
        _, admin, _ = make_user('enr_admin', role='admin')
        c = APIClient()
        r = _login(c, 'enr_u1')
        dev = Device.objects.get()
        key = f'device_new_{dev.pk}'
        self.assertEqual(Notification.objects.filter(dedup_key=key, recipient=self.profile).count(), 1)
        self.assertEqual(Notification.objects.filter(dedup_key=key, recipient=admin).count(), 1)
        c.cookies[devices.COOKIE] = r.cookies[devices.COOKIE].value
        before = Notification.objects.filter(dedup_key=key).count()
        _login(c, 'enr_u1')
        self.assertEqual(Notification.objects.filter(dedup_key=key).count(), before)

    def test_enroll_failure_does_not_break_login(self):
        with mock.patch('apps.access.devices.from_secret', side_effect=RuntimeError('boom')):
            r = _login(APIClient(), 'enr_u1')
        self.assertEqual(r.status_code, 200)
        self.assertIn('access', r.data)
        self.assertEqual(Device.objects.count(), 0)
        self.assertNotIn(devices.COOKIE, r.cookies)

    def test_failed_password_creates_no_device(self):
        r = _login(APIClient(), 'enr_u1', password='wrong')
        self.assertEqual(r.status_code, 401)
        self.assertEqual(Device.objects.count(), 0)
        self.assertNotIn(devices.COOKIE, r.cookies)

    def test_2fa_verify_path_enrolls(self):
        self.profile.mfa_enabled = True
        self.profile.mfa_secret = pyotp.random_base32()
        self.profile.save()
        c = APIClient()
        r = _login(c, 'enr_u1')
        self.assertTrue(r.data.get('mfa_required'))
        self.assertEqual(Device.objects.count(), 0)
        r2 = c.post('/api/auth/2fa/verify/', {'mfa_token': r.data['mfa_token'],
                                              'code': pyotp.TOTP(self.profile.mfa_secret).now()},
                    format='json', HTTP_USER_AGENT=UA)
        self.assertEqual(r2.status_code, 200, r2.data)
        dev = Device.objects.get()
        self.assertIn(devices.COOKIE, r2.cookies)
        claims = pyjwt.decode(r2.data['access'], options={'verify_signature': False})
        self.assertEqual(claims['dev'], str(dev.public_id))
        log = UserActivityLog.objects.filter(action='mfa_verified').latest('id')
        self.assertEqual(log.device, dev)


# ── Task 3: device in the access context; blocked device ends sessions ────────────────

from django.test import RequestFactory  # noqa: E402

from apps.access import context as access_context  # noqa: E402


def _signed_in(username='t3_u1'):
    """A client signed in through the real login (so the token carries `dev`) + its device."""
    c = APIClient()
    r = _login(c, username)
    assert r.status_code == 200, r.data
    secret = r.cookies[devices.COOKIE].value
    c.cookies[devices.COOKIE] = secret
    return c, r, Device.objects.get(secret_hash=devices.hash_secret(secret))


class RevocationTests(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user, self.profile, _ = make_user('t3_u1')

    def _me(self, client):
        return client.get('/api/auth/me/')

    def test_blocked_device_access_token_refused(self):
        c, r, dev = _signed_in()
        self.assertEqual(self._me(c).status_code, 200)
        dev.status = 'blocked'
        dev.save()
        self.assertEqual(self._me(c).status_code, 401)

    def test_blocked_device_refresh_refused_and_cookies_cleared(self):
        c, r, dev = _signed_in()
        dev.status = 'blocked'
        dev.save()
        resp = c.post('/api/auth/refresh/', {}, format='json')
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.data['detail'], devices.BLOCKED_MESSAGE)
        self.assertEqual(resp.cookies['erp_access'].value, '')
        self.assertEqual(resp.cookies['erp_refresh'].value, '')

    def test_token_without_dev_claim_unaffected(self):
        from rest_framework_simplejwt.tokens import RefreshToken
        _device(status='blocked')
        tok = RefreshToken.for_user(self.user)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {tok.access_token}')
        self.assertEqual(self._me(c).status_code, 200)

    def test_retired_device_refused(self):
        c, r, dev = _signed_in()
        dev.status = 'retired'
        dev.save()
        self.assertEqual(self._me(c).status_code, 401)

    def test_unblock_restores(self):
        c, r, dev = _signed_in()
        dev.status = 'blocked'
        dev.save()
        self.assertEqual(self._me(c).status_code, 401)
        dev.status = 'approved'
        dev.save()
        self.assertEqual(self._me(c).status_code, 200)

    def test_blocked_device_cookie_refused_at_sign_in(self):
        secret, dev = _device(status='blocked')
        c = APIClient()
        c.cookies[devices.COOKIE] = secret
        before = Device.objects.count()
        r = _login(c, 't3_u1')
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.data['error'], devices.BLOCKED_MESSAGE)
        self.assertNotIn('access', r.data)
        for name in ('erp_access', 'erp_refresh', devices.COOKIE):
            self.assertNotIn(name, r.cookies)
        self.assertEqual(Device.objects.count(), before)
        log = UserActivityLog.objects.filter(action='login_failed').latest('id')
        self.assertEqual(log.note, 'device_blocked')

    def test_blocked_device_cookie_refused_at_2fa_verify(self):
        self.profile.mfa_enabled = True
        self.profile.mfa_secret = pyotp.random_base32()
        self.profile.save()
        c = APIClient()
        r = _login(c, 't3_u1')
        self.assertTrue(r.data.get('mfa_required'))
        secret, _dev = _device(status='blocked')
        c.cookies[devices.COOKIE] = secret
        r2 = c.post('/api/auth/2fa/verify/', {'mfa_token': r.data['mfa_token'],
                                              'code': pyotp.TOTP(self.profile.mfa_secret).now()},
                    format='json', HTTP_USER_AGENT=UA)
        self.assertEqual(r2.status_code, 401)
        self.assertEqual(r2.data['error'], devices.BLOCKED_MESSAGE)
        self.assertNotIn('access', r2.data)
        self.assertNotIn('erp_access', r2.cookies)

    def test_retired_cookie_still_signs_in(self):
        secret, _ = _device(status='retired')
        c = APIClient()
        c.cookies[devices.COOKIE] = secret
        self.assertEqual(_login(c, 't3_u1').status_code, 200)


class ResolveTests(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def _req(self, secret):
        req = RequestFactory().get('/', REMOTE_ADDR='9.9.9.9')
        req.COOKIES[devices.COOKIE] = secret
        return req

    def test_device_resolve_is_cached(self):
        secret, dev = _device()
        req = self._req(secret)
        first = devices.resolve(req)
        self.assertEqual(first.public_id, str(dev.public_id))
        with self.assertNumQueries(0):
            second = devices.resolve(req)
        self.assertEqual(first, second)

    def test_unknown_cookie_cached_as_none(self):
        req = self._req('nope')
        self.assertIsNone(devices.resolve(req))
        with self.assertNumQueries(0):
            self.assertIsNone(devices.resolve(req))
        self.assertIsNone(devices.resolve(RequestFactory().get('/')))

    def test_last_seen_touched_once_per_window(self):
        secret, dev = _device()
        req = self._req(secret)
        devices.resolve(req)
        dev.refresh_from_db()
        self.assertIsNotNone(dev.last_seen)
        self.assertEqual(dev.last_ip, '9.9.9.9')
        Device.objects.filter(pk=dev.pk).update(last_seen=None)
        devices.resolve(req)
        dev.refresh_from_db()
        self.assertIsNone(dev.last_seen)          # second call inside the window: no touch
        cache.delete(f'access:devtouch:{dev.pk}')
        devices.resolve(req)
        dev.refresh_from_db()
        self.assertIsNotNone(dev.last_seen)

    def test_is_revoked(self):
        _, ok = _device()
        _, blk = _device(status='blocked')
        self.assertFalse(devices.is_revoked(None))
        self.assertFalse(devices.is_revoked('not-a-uuid'))
        self.assertFalse(devices.is_revoked(str(ok.public_id)))
        self.assertTrue(devices.is_revoked(str(blk.public_id)))

    def test_context_has_device(self):
        secret, dev = _device()
        ctx = access_context.for_request(self._req(secret))
        self.assertEqual(ctx.device.public_id, str(dev.public_id))
        self.assertIsNone(access_context.fallback().device)


class WhoamiDeviceTests(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        make_user('t3_u1')

    def test_whoami_device_null_when_anonymous(self):
        secret, _ = _device()
        c = APIClient()
        c.cookies[devices.COOKIE] = secret
        r = c.get('/api/access/whoami/')
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data['device'])

    def test_whoami_device_when_signed_in(self):
        c, _, dev = _signed_in()
        r = c.get('/api/access/whoami/')
        self.assertEqual(r.data['device']['status'], 'pending')
        self.assertEqual(r.data['device']['status_label'], 'بانتظار الاعتماد')
        self.assertEqual(r.data['device']['name'], dev.name)


# ── Task 4: "remember this device" on approved devices ────────────────────────────────

from datetime import timedelta  # noqa: E402

from django.utils import timezone  # noqa: E402


class RememberDeviceTests(TestCase):

    def setUp(self):
        cache.clear()      # the per-IP login throttle is not under test
        self.addCleanup(cache.clear)
        self.user, self.profile, _ = make_user('rem_u1')
        self.profile.mfa_enabled = True
        self.profile.mfa_secret = pyotp.random_base32()
        self.profile.save()

    def _code(self):
        return pyotp.TOTP(self.profile.mfa_secret).now()

    def _verify(self, c, remember=True):
        r = _login(c, 'rem_u1')
        self.assertTrue(r.data.get('mfa_required'))
        r2 = c.post('/api/auth/2fa/verify/', {'mfa_token': r.data['mfa_token'], 'code': self._code(),
                                              'remember_device': remember},
                    format='json', HTTP_USER_AGENT=UA)
        self.assertEqual(r2.status_code, 200, r2.data)
        return r2

    def _remembered_client(self, approve=True):
        c = APIClient()
        r2 = self._verify(c)
        dev = Device.objects.get()
        if approve:
            dev.status = 'approved'
            dev.save(update_fields=['status'])
        c2 = APIClient()
        c2.cookies[devices.COOKIE] = r2.cookies[devices.COOKIE].value
        return c2, dev, r2

    def test_remembered_on_approved_device_skips_2fa(self):
        c2, dev, r2 = self._remembered_client()
        link = DeviceUser.objects.get(device=dev, user=self.profile)
        self.assertIsNotNone(link.mfa_remembered_at)
        self.assertEqual(link.mfa_remembered_epoch, self.profile.mfa_device_epoch)
        self.assertIn('device_token', r2.data)
        r = _login(c2, 'rem_u1')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('mfa_required', r.data)
        self.assertIn('access', r.data)
        log = UserActivityLog.objects.filter(action='login_success').latest('id')
        self.assertEqual(log.note, 'mfa_skipped_device')
        self.assertEqual(log.device, dev)

    def test_remembered_on_pending_device_still_challenged(self):
        c2, dev, _ = self._remembered_client(approve=False)
        r = _login(c2, 'rem_u1')
        self.assertTrue(r.data.get('mfa_required'))

    def test_forget_devices_cancels_device_remember(self):
        from apps.users import mfa
        c2, dev, _ = self._remembered_client()
        mfa.forget_devices(self.profile, self.profile, '1.2.3.4')
        r = _login(c2, 'rem_u1')
        self.assertTrue(r.data.get('mfa_required'))

    def test_blocked_device_cancels_remember(self):
        c2, dev, _ = self._remembered_client()
        dev.status = 'blocked'
        dev.save(update_fields=['status'])
        cache.clear()
        r = _login(c2, 'rem_u1')
        self.assertEqual(r.status_code, 401)
        self.assertNotIn('access', r.data)

    def test_remember_expires_after_30_days(self):
        c2, dev, _ = self._remembered_client()
        DeviceUser.objects.filter(device=dev).update(mfa_remembered_at=timezone.now() - timedelta(days=31))
        r = _login(c2, 'rem_u1')
        self.assertTrue(r.data.get('mfa_required'))
        DeviceUser.objects.filter(device=dev).update(mfa_remembered_at=timezone.now() - timedelta(days=29))
        cache.clear()
        r = _login(c2, 'rem_u1')
        self.assertNotIn('mfa_required', r.data)

    def test_not_remembered_without_flag(self):
        c = APIClient()
        r2 = self._verify(c, remember=False)
        dev = Device.objects.get()
        dev.status = 'approved'
        dev.save(update_fields=['status'])
        c2 = APIClient()
        c2.cookies[devices.COOKIE] = r2.cookies[devices.COOKIE].value
        self.assertTrue(_login(c2, 'rem_u1').data.get('mfa_required'))

    def test_legacy_device_token_still_works(self):
        from apps.users import mfa
        token = mfa.make_device_token(self.user)
        r = APIClient().post('/api/auth/login/', {'username': 'rem_u1', 'password': 'TestPass123',
                                                  'device_token': token},
                             format='json', HTTP_USER_AGENT=UA)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('mfa_required', r.data)

    def test_password_change_cancels(self):
        c2, dev, _ = self._remembered_client()
        self.user.set_password('NewPass123!x')       # self-service change and admin reset both do this
        self.user.save(update_fields=['password'])
        r = _login(c2, 'rem_u1', password='NewPass123!x')
        self.assertTrue(r.data.get('mfa_required'))

    def test_2fa_disable_then_reenable_cancels(self):
        c2, dev, _ = self._remembered_client()
        self.profile.mfa_enabled = False
        self.profile.mfa_secret = ''
        self.profile.save()
        self.profile.mfa_secret = pyotp.random_base32()
        self.profile.mfa_enabled = True
        self.profile.save()
        self.assertTrue(_login(c2, 'rem_u1').data.get('mfa_required'))

    def test_other_users_remember_does_not_skip_for_another_user(self):
        c2, dev, _ = self._remembered_client()
        u2, p2, _ = make_user('rem_u2')
        p2.mfa_enabled = True
        p2.mfa_secret = pyotp.random_base32()
        p2.save()
        self.assertTrue(_login(c2, 'rem_u2').data.get('mfa_required'))

    def test_future_dated_remember_ignored(self):
        c2, dev, _ = self._remembered_client()
        DeviceUser.objects.filter(device=dev).update(mfa_remembered_at=timezone.now() + timedelta(days=5))
        self.assertTrue(_login(c2, 'rem_u1').data.get('mfa_required'))
