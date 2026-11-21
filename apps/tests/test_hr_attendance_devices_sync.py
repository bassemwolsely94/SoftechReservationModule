"""
apps/tests/test_hr_attendance_devices_sync.py

Linked Gates Task 8: `sync_attendance_devices` brings the machine rows to the corrected 16-machine
list: dry run by default, rename in place (never a duplicate), closed machines marked, repeatable.
"""
import hashlib
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.audit.models import AuditLog
from apps.hr.models import AttendanceAgent, AttendanceDevice

CLOSED = 'مغلق'


def old_seed():
    """The five rows the office DB holds today."""
    rows = [('Alia', 'A2ML173860738', '192.168.30.15', 'Alia'),
            ('Ain Shams', 'OEG6090486091100521', '192.168.3.15', 'Ain Shams'),
            ('Giza', 'OEG6090486091100070', '192.168.4.15', 'Giza'),
            ('Mohsen', 'A2NC173960786', '192.168.70.15', 'Mohsen'),
            ('8', 'A8ME185060308', '192.168.5.15', '')]
    for name, serial, ip, label in rows:
        AttendanceDevice.objects.create(serial=serial, name=name, ip=ip, location_label=label)


def sync(*args):
    out = StringIO()
    call_command('sync_attendance_devices', *args, stdout=out)
    return out.getvalue()


class SyncDevicesTests(TestCase):

    def setUp(self):
        old_seed()

    def test_sync_dry_run_writes_nothing(self):
        before = list(AttendanceDevice.objects.order_by('pk').values())
        text = sync()
        self.assertIn('DRY RUN', text)
        self.assertEqual(list(AttendanceDevice.objects.order_by('pk').values()), before)
        self.assertFalse(AuditLog.objects.filter(action='hr_attendance_device_sync').exists())

    def test_sync_renames_giza_to_balegh(self):
        giza_pk = AttendanceDevice.objects.get(name='Giza').pk
        eight_pk = AttendanceDevice.objects.get(name='8').pk
        sync('--apply')
        self.assertEqual(AttendanceDevice.objects.get(pk=giza_pk).name, 'Balegh')
        self.assertEqual(AttendanceDevice.objects.get(pk=eight_pk).name, 'Zahar')
        self.assertFalse(AttendanceDevice.objects.filter(name__in=['Giza', '8']).exists())
        self.assertEqual(AttendanceDevice.objects.count(), 16)       # renamed in place, no duplicates
        self.assertEqual(AttendanceDevice.objects.filter(ip='192.168.4.15').count(), 1)
        self.assertTrue(AuditLog.objects.filter(action='hr_attendance_device_sync').exists())

    def test_sync_marks_closed(self):
        sync('--apply')
        closed = {'Head Office', 'Marian', 'Michael', 'Rashidi', 'Shady', 'Shoubra', 'Amany',
                  'Ehab', 'Aliaa'}
        got = {d.name: d for d in AttendanceDevice.objects.all()}
        for name in closed:
            self.assertFalse(got[name].is_active, name)
            self.assertEqual(got[name].location_label, CLOSED, name)
        for name in set(got) - closed:
            self.assertTrue(got[name].is_active, name)
            self.assertNotEqual(got[name].location_label, CLOSED, name)
        self.assertEqual(AttendanceDevice.objects.filter(ip='192.168.30.15').count(), 2)
        self.assertTrue(got['Alia'].is_active)       # Alia stays live next to the closed Aliaa

    def test_sync_idempotent(self):
        sync('--apply')
        snapshot = list(AttendanceDevice.objects.order_by('pk').values())
        audits = AuditLog.objects.filter(action='hr_attendance_device_sync').count()
        text = sync('--apply')
        self.assertEqual(list(AttendanceDevice.objects.order_by('pk').values()), snapshot)
        self.assertEqual(AuditLog.objects.filter(action='hr_attendance_device_sync').count(), audits)
        self.assertIn('0 to create', text)

    def test_sync_agent_assigns_live_machines_only(self):
        agent = AttendanceAgent.objects.create(name='office', token_hash=hashlib.sha256(b'x').hexdigest())
        sync('--apply', '--agent', 'office')
        self.assertEqual(set(AttendanceDevice.objects.filter(agent=agent).values_list('is_active', flat=True)),
                         {True})
        self.assertEqual(AttendanceDevice.objects.filter(agent=agent).count(), 7)
        self.assertFalse(AttendanceDevice.objects.filter(is_active=False, agent__isnull=False).exists())

    def test_sync_unknown_agent_is_an_error(self):
        with self.assertRaises(CommandError):
            sync('--apply', '--agent', 'nobody')
        self.assertEqual(AttendanceDevice.objects.count(), 5)
