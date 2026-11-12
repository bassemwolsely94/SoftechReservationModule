"""
Create the eight fingerprint machines of the design's table (docs/superpowers/specs/
2026-11-07-hr-attendance-stage1-design.md, "Machines"). Safe to repeat: a machine that already
exists (by serial) is left exactly as it is, so a screen edit is never overwritten.

No branch is guessed. The owner must still confirm where `Alia` and `8` stand, so their location
label is left empty; the other six use the name they have in the ZK program as their label.
"""
from django.core.management.base import BaseCommand

from apps.hr.models import AttendanceDevice

# (name in the ZK program, serial, IP, model, location label)
MACHINES = [
    ('HQ', 'A2NC173961011', '192.168.1.15', '', 'HQ'),
    ('Drg Store', 'A2ML182760598', '192.168.1.14', 'K12/ID', 'Drg Store'),
    ('BabAlhded', 'A2ML182760559', '192.168.1.13', 'K12/ID', 'BabAlhded'),
    ('Alia', 'A2ML173860738', '192.168.30.15', 'K12/ID', ''),
    ('Ain Shams', 'OEG6090486091100521', '192.168.3.15', 'K14', 'Ain Shams'),
    ('Giza', 'OEG6090486091100070', '192.168.4.15', 'K14', 'Giza'),
    ('Mohsen', 'A2NC173960786', '192.168.70.15', 'K14', 'Mohsen'),
    ('8', 'A8ME185060308', '192.168.5.15', 'K30/ID', ''),
]


class Command(BaseCommand):
    help = 'Create the eight attendance machines (idempotent; never overwrites an edit).'

    def handle(self, *args, **opts):
        created = 0
        for name, serial, ip, model, label in MACHINES:
            _, was_created = AttendanceDevice.objects.get_or_create(
                serial=serial,
                defaults={'name': name, 'ip': ip, 'port': 4370, 'model_name': model,
                          'location_label': label})
            created += was_created
        self.stdout.write(f'{created} machine(s) created, {len(MACHINES) - created} already there.')
