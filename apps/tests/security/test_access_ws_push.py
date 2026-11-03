"""N5 / Task 3 - the server pushes `access.recheck` on disable, device and policy changes."""
from unittest import mock

from django.test import TestCase

from apps.access import devices
from apps.access.models import Device, DeviceUser, TrustedNetwork, ZonePolicy
from apps.tests.factories import make_user
from apps.users.sessions import end_sessions

SEND = 'channels.layers.InMemoryChannelLayer.group_send'


def _sent(m):
    return [(c.args[0], c.args[1]) for c in m.call_args_list]


class PushTests(TestCase):

    def test_end_sessions_pushes_user_group(self):
        user, _, _ = make_user('push_a')
        with mock.patch(SEND) as m, self.captureOnCommitCallbacks(execute=True):
            end_sessions(user)
        self.assertIn((f'access_user_{user.pk}', {'type': 'access.recheck'}), _sent(m))

    def test_block_device_pushes_its_users(self):
        u1, p1, _ = make_user('push_b1')
        u2, p2, _ = make_user('push_b2')
        dev = Device.objects.create(name='d', secret_hash=devices.hash_secret('x'), status='approved')
        DeviceUser.objects.create(device=dev, user=p1)
        DeviceUser.objects.create(device=dev, user=p2)
        with mock.patch(SEND) as m, self.captureOnCommitCallbacks(execute=True):
            devices.set_status(dev, 'blocked', p1)
        groups = {g for g, _ in _sent(m)}
        self.assertEqual(groups, {f'access_user_{u1.pk}', f'access_user_{u2.pk}'})

    def test_zone_policy_save_pushes_all(self):
        with mock.patch(SEND) as m, self.captureOnCommitCallbacks(execute=True):
            ZonePolicy.objects.update_or_create(role='pharmacist', zone='Z3',
                                                defaults={'access': 'none'})
        self.assertIn(('access_all', {'type': 'access.recheck'}), _sent(m))

    def test_trusted_network_save_pushes_all(self):
        with mock.patch(SEND) as m, self.captureOnCommitCallbacks(execute=True):
            TrustedNetwork.objects.create(name='n', cidr='10.9.0.0/16', kind='server')
        self.assertIn(('access_all', {'type': 'access.recheck'}), _sent(m))

    def test_push_failure_never_breaks_block(self):
        _, p1, _ = make_user('push_c')
        dev = Device.objects.create(name='d', secret_hash=devices.hash_secret('y'), status='approved')
        DeviceUser.objects.create(device=dev, user=p1)
        with mock.patch(SEND, side_effect=RuntimeError('layer down')), \
                self.captureOnCommitCallbacks(execute=True):
            devices.set_status(dev, 'blocked', p1)
        dev.refresh_from_db()
        self.assertEqual(dev.status, 'blocked')
