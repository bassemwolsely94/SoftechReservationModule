"""
Bring the attendance machines in line with the corrected list (seed_attendance_devices.MACHINES).

Dry run by default; `--apply` writes. `--agent <name>` also assigns every live machine to that
collection agent (the agent must exist). Rows are matched by serial first, then by IP only when
exactly one not-yet-matched row has it, so two rows sharing an address never get mixed up, and a
machine is renamed in place, never duplicated. Safe to repeat. Every change is audited.
Prints counts and machine names only.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit.models import AuditLog
from apps.hr.models import AttendanceAgent, AttendanceDevice

from .seed_attendance_devices import MACHINES, machine_label, machine_serial


def plan(existing):
    """[(entry, row_or_None)] for the 16 machines. `existing` is a list of AttendanceDevice."""
    by_serial = {row.serial: row for row in existing}
    claimed = {}
    for name, serial, ip, _model, _live in MACHINES:
        row = by_serial.get(machine_serial(name, serial, ip))
        if row is not None:
            claimed[name] = row
    taken = {row.pk for row in claimed.values()}
    result = []
    for entry in MACHINES:
        name, ip = entry[0], entry[2]
        row = claimed.get(name)
        if row is None:
            same_ip = [r for r in existing if r.ip == ip and r.pk not in taken]
            if len(same_ip) == 1:
                row = same_ip[0]
                taken.add(row.pk)
        result.append((entry, row))
    return result


class Command(BaseCommand):
    help = 'Rename / close / add the attendance machines to match the corrected list. Dry run unless --apply.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='write the changes (default: dry run)')
        parser.add_argument('--agent', default='', help='assign every live machine to this agent')

    def handle(self, *args, **opts):
        apply = opts['apply']
        agent = None
        if opts['agent']:
            agent = AttendanceAgent.objects.filter(name=opts['agent']).first()
            if agent is None:
                raise CommandError('no attendance agent with that name')
        existing = list(AttendanceDevice.objects.select_related('agent'))
        created, renamed, closed, assigned, unchanged = [], [], [], [], 0
        with transaction.atomic():
            for (name, serial, ip, model, live), row in plan(existing):
                want = {'name': name, 'ip': ip, 'port': 4370, 'is_active': live,
                        'location_label': machine_label(name, live)}
                if agent is not None and live:
                    want['agent'] = agent
                if row is None:
                    created.append(name)
                    if apply:
                        row = AttendanceDevice.objects.create(
                            serial=machine_serial(name, serial, ip), model_name=model, **want)
                        AuditLog.log('hr_attendance_device_sync', obj=row, note='created',
                                     new_data={'name': name, 'is_active': live})
                    continue
                changes = {}
                for field, value in want.items():
                    current = getattr(row, field)
                    if field == 'agent':
                        if current is None or current.pk != value.pk:
                            changes[field] = [getattr(current, 'name', None), value.name]
                    elif current != value:
                        changes[field] = [current, value]
                if not changes:
                    unchanged += 1
                    continue
                if 'name' in changes:
                    renamed.append(name)
                if 'is_active' in changes and not live:
                    closed.append(name)
                if 'agent' in changes:
                    assigned.append(name)
                if apply:
                    for field, value in want.items():
                        setattr(row, field, value)
                    row.save()
                    AuditLog.log('hr_attendance_device_sync', obj=row, changes=changes, note='updated')
        mode = 'applied' if apply else 'DRY RUN (nothing written; use --apply)'
        self.stdout.write(
            f'{mode}: {len(created)} to create, {len(renamed)} renamed, {len(closed)} closed, '
            f'{len(assigned)} assigned to the agent, {unchanged} unchanged.')
        for label, names in (('create', created), ('rename', renamed), ('close', closed),
                             ('assign', assigned)):
            if names:
                self.stdout.write(f'  {label}: {", ".join(names)}')
