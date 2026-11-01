"""N2 / Task 1 - Device registry model and secret helpers."""
import hashlib
from types import SimpleNamespace

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
