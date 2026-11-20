"""
Create the fingerprint machines (Linked Gates' Device table as read 2026-11-20: 16 rows).
Safe to repeat: a machine that already exists (by serial) is left exactly as it is, so a screen
edit is never overwritten. To rename / close / assign existing rows use `sync_attendance_devices`.

A machine whose serial isn't known yet gets the placeholder `UNREAD-<ip>` (`UNREAD-<ip>-closed-dup`
for the second row on a shared address); the agent never contacts those (closed, or no agent).
"""
from django.core.management.base import BaseCommand

from apps.hr.models import AttendanceDevice

CLOSED_LABEL = 'مغلق'
PLACEHOLDER_PREFIX = 'UNREAD-'

# (name as in Linked Gates, serial or None, IP, model, live)
MACHINES = [
    ('Ain Shams', 'OEG6090486091100521', '192.168.3.15', 'K14', True),
    ('Alia', 'A2ML173860738', '192.168.30.15', 'K12/ID', True),
    ('Aliaa', None, '192.168.30.15', '', False),     # closed duplicate of Alia's address (LG id 4021)
    ('Amany', None, '192.168.20.15', '', False),
    ('BabElhadid', 'A2ML182760559', '192.168.1.13', 'K12/ID', True),
    ('Balegh', 'OEG6090486091100070', '192.168.4.15', 'K14', True),   # seeded earlier as "Giza"
    ('Ehab', None, '192.168.9.15', '', False),
    ('Head Office', 'A2NC173961011', '192.168.1.15', '', False),
    ('Marian', None, '192.168.10.15', '', False),
    ('Michael', None, '192.168.11.15', '', False),
    ('Mohsen', 'A2NC173960786', '192.168.70.15', 'K14', True),
    ('Rashidi', None, '192.168.2.15', '', False),
    ('Shady', None, '192.168.80.15', '', False),
    ('Shoubra', None, '192.168.12.15', '', False),
    ('Wearhouse', 'A2ML182760598', '192.168.1.14', 'K12/ID', True),   # seeded earlier as "Drg Store"
    ('Zahar', 'A8ME185060308', '192.168.5.15', 'K30/ID', True),       # seeded earlier as "8"
]


def machine_serial(name, serial, ip):
    """The serial to store: the real one, or a placeholder that is unique per row."""
    if serial:
        return serial
    return f'{PLACEHOLDER_PREFIX}{ip}' + ('-closed-dup' if name == 'Aliaa' else '')


def machine_label(name, live):
    return name if live else CLOSED_LABEL


class Command(BaseCommand):
    help = 'Create the attendance machines that do not exist yet (idempotent; never overwrites an edit).'

    def handle(self, *args, **opts):
        created = 0
        for name, serial, ip, model, live in MACHINES:
            _, was_created = AttendanceDevice.objects.get_or_create(
                serial=machine_serial(name, serial, ip),
                defaults={'name': name, 'ip': ip, 'port': 4370, 'model_name': model,
                          'location_label': machine_label(name, live), 'is_active': live})
            created += was_created
        self.stdout.write(f'{created} machine(s) created, {len(MACHINES) - created} already there.')
