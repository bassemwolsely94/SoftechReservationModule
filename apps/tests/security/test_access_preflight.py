"""N3 final wave - `manage.py access_preflight`: the read-only pre-enforce checklist (C1 / I1 / I2 / I4)."""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.access import devices, preflight
from apps.access.models import Device, DeviceUser, ZonePolicy
from apps.tests.factories import make_branch, make_branch2, make_user
from apps.users.models import UserActivityLog

READY = dict(NETWORK_HEADER_TRUSTED=True, NETWORK_PROXY_KEY='k')


def _codes(items, level=None):
    return {i.code for i in items if level is None or i.level == level}


def _device(status='approved', branch=None, users=()):
    d = Device.objects.create(secret_hash=devices.hash_secret(devices.new_secret()), status=status,
                              branch=branch, last_seen=timezone.now())
    for p in users:
        DeviceUser.objects.create(device=d, user=p, last_seen=timezone.now())
    return d


@override_settings(**READY)
class PreflightTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        self.admin, self.admin_p, _ = make_user('pf_admin', role='admin')
        self.admin_p.mfa_enabled = True
        self.admin_p.save(update_fields=['mfa_enabled'])
        _, self.ph, _ = make_user('pf_ph', role='pharmacist', branch=self.branch)
        UserActivityLog.objects.create(target_user=self.ph, action='login_success', network='internal')
        _device(branch=self.branch, users=[self.ph])
        _device(users=[self.admin_p])
        _device(users=[self.admin_p])

    def test_ready_company_has_no_blockers(self):
        items = preflight.run()
        self.assertEqual(_codes(items, preflight.BLOCK), set(), [(i.code, i.names) for i in items])
        out = StringIO()
        call_command('access_preflight', stdout=out)
        self.assertIn('Ready for enforce', out.getvalue())

    @override_settings(NETWORK_HEADER_TRUSTED=False, NETWORK_PROXY_KEY='')
    def test_settings_block(self):
        self.assertTrue({'header', 'proxy_key'} <= _codes(preflight.run(), preflight.BLOCK))

    def test_no_internal_traffic_blocks(self):
        UserActivityLog.objects.all().delete()
        self.assertIn('internal_traffic', _codes(preflight.run(), preflight.BLOCK))

    def test_rider_without_2fa_blocks_and_is_named(self):
        _, rider, _ = make_user('pf_rider', role='delivery', branch=self.branch)
        item = next(i for i in preflight.run() if i.code == 'mfa_riders')
        self.assertEqual(item.level, preflight.BLOCK)
        self.assertIn(rider.full_name or 'pf_rider', item.names)

    def test_other_outside_role_without_2fa_blocks(self):
        make_user('pf_sup', role='supervisor')
        self.assertIn('mfa_users', _codes(preflight.run(), preflight.BLOCK))

    def test_inside_only_role_needs_no_2fa(self):
        # pharmacist Z3 / Z4 = none: never signs in from outside, so no 2FA needed
        self.assertNotIn('mfa_users', _codes(preflight.run()))

    def test_branch_without_approved_device_blocks(self):
        other = make_branch2()
        make_user('pf_ph2', role='salesperson', branch=other)
        item = next(i for i in preflight.run() if i.code == 'branch_devices')
        self.assertEqual(item.level, preflight.BLOCK)
        self.assertEqual(item.names, [other.name_ar or other.name])

    def test_one_admin_device_warns_none_blocks(self):
        Device.objects.filter(device_users__user=self.admin_p).first().delete()
        self.assertIn('admin_devices', _codes(preflight.run(), preflight.WARN))
        Device.objects.filter(device_users__user=self.admin_p).delete()
        self.assertIn('admin_devices', _codes(preflight.run(), preflight.BLOCK))

    def test_admin_z1_not_full_blocks(self):
        ZonePolicy.objects.filter(role='admin', zone='Z1').update(access='read_only')
        self.assertIn('admin_z1', _codes(preflight.run(), preflight.BLOCK))

    def test_missing_rows_warn(self):
        ZonePolicy.objects.filter(role='viewer', zone='Z4').delete()
        item = next(i for i in preflight.run() if i.code == 'rows')
        self.assertEqual(item.level, preflight.WARN)
        self.assertIn('viewer: Z4', item.names)

    def test_command_exits_1_on_blockers_and_writes_nothing(self):
        UserActivityLog.objects.all().delete()
        before = (Device.objects.count(), ZonePolicy.objects.count(), UserActivityLog.objects.count())
        with self.assertRaises(CommandError) as cm:
            call_command('access_preflight', stdout=StringIO())
        self.assertEqual(cm.exception.returncode, 1)
        self.assertIn('NOT ready', str(cm.exception))
        self.assertEqual(before, (Device.objects.count(), ZonePolicy.objects.count(),
                                  UserActivityLog.objects.count()))
