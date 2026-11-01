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
