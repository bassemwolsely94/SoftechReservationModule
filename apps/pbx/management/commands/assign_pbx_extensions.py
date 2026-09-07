"""
python manage.py assign_pbx_extensions

Bulk-assign Asterisk extensions to Django staff users from the CLI.

Usage examples
--------------
# Show all non-gateway extensions and their current staff assignment
python manage.py assign_pbx_extensions --list

# Show only unassigned extensions
python manage.py assign_pbx_extensions --list --unassigned

# Assign a single extension to a staff user
python manage.py assign_pbx_extensions --ext 10 --staff ahmed.salah

# Assign by staff ID instead of username
python manage.py assign_pbx_extensions --ext 11 --staff-id 7

# Clear staff assignment from an extension
python manage.py assign_pbx_extensions --ext 12 --clear

# Bulk-assign from a JSON file
#   File format: [{"ext": "10", "staff": "ahmed.salah"}, ...]
python manage.py assign_pbx_extensions --from-json assignments.json
"""
import json
from django.core.management.base import BaseCommand, CommandError
from apps.pbx.models import AgentExtension


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_staff(username_or_none, staff_id=None):
    from apps.users.models import StaffProfile
    from django.contrib.auth import get_user_model
    User = get_user_model()

    if staff_id:
        try:
            return StaffProfile.objects.get(pk=staff_id)
        except StaffProfile.DoesNotExist:
            raise CommandError(f'No StaffProfile with id={staff_id}')

    if username_or_none:
        # Try StaffProfile first
        sp = StaffProfile.objects.filter(user__username=username_or_none).first()
        if sp:
            return sp
        # Fallback: match by full name fragment
        sp = StaffProfile.objects.filter(user__first_name__icontains=username_or_none).first()
        if sp:
            return sp
        raise CommandError(
            f'No staff user found for "{username_or_none}". '
            f'Pass a Django username or use --staff-id.'
        )
    return None


def _get_ext(extension_str):
    try:
        return AgentExtension.objects.get(extension=extension_str)
    except AgentExtension.DoesNotExist:
        raise CommandError(f'Extension "{extension_str}" not found in database.')


def _type_badge(ext):
    badges = {
        'agent':   '[عامل]  ',
        'branch':  '[فرع]   ',
        'hq':      '[مقر]   ',
        'gateway': '[بوابة] ',
        'other':   '[؟]     ',
    }
    return badges.get(ext.extension_type, '        ')


def _reg_badge(ext):
    if ext.last_status.startswith('OK'):
        return '(OK)'
    if 'UNREACHABLE' in ext.last_status:
        return '(--)'
    return '(??)'


# ── command ───────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = 'List and assign Asterisk extensions to Django staff users'

    def add_arguments(self, parser):
        parser.add_argument(
            '--list', action='store_true',
            help='List all non-gateway extensions with current staff assignments',
        )
        parser.add_argument(
            '--unassigned', action='store_true',
            help='With --list: show only unassigned extensions',
        )
        parser.add_argument(
            '--ext', metavar='EXTENSION',
            help='Extension number to assign (e.g. 10)',
        )
        parser.add_argument(
            '--staff', metavar='USERNAME',
            help='Django username of the staff member to assign',
        )
        parser.add_argument(
            '--staff-id', metavar='ID', type=int,
            help='StaffProfile PK to assign (alternative to --staff)',
        )
        parser.add_argument(
            '--clear', action='store_true',
            help='Remove the staff assignment from --ext',
        )
        parser.add_argument(
            '--from-json', metavar='FILE',
            help='Path to a JSON file with bulk assignments '
                 '[{"ext": "10", "staff": "ahmed.salah"}, ...]',
        )

    def handle(self, *args, **options):
        # ── --list ──────────────────────────────────────────────────────────
        if options['list']:
            self._do_list(unassigned_only=options['unassigned'])
            return

        # ── --from-json ─────────────────────────────────────────────────────
        if options['from_json']:
            self._do_from_json(options['from_json'])
            return

        # ── single-extension ops ─────────────────────────────────────────────
        if not options['ext']:
            self.print_help('manage.py', 'assign_pbx_extensions')
            return

        ext_obj = _get_ext(options['ext'])

        # --clear
        if options['clear']:
            old = ext_obj.staff.full_name if ext_obj.staff else '(none)'
            ext_obj.staff = None
            ext_obj.save(update_fields=['staff', 'updated_at'])
            self.stdout.write(
                self.style.WARNING(
                    f'ext {ext_obj.extension}: cleared (was {old})'
                )
            )
            return

        # --staff / --staff-id
        if not options['staff'] and not options['staff_id']:
            raise CommandError('Provide --staff USERNAME or --staff-id ID')

        staff_obj = _get_staff(options['staff'], options.get('staff_id'))

        # Check if another extension is already assigned to this staff
        existing = AgentExtension.objects.filter(staff=staff_obj).exclude(pk=ext_obj.pk).first()
        if existing:
            self.stdout.write(
                self.style.WARNING(
                    f'Warning: {staff_obj.full_name} is currently assigned to '
                    f'ext {existing.extension}. Reassigning...'
                )
            )
            existing.staff = None
            existing.save(update_fields=['staff', 'updated_at'])

        ext_obj.staff = staff_obj
        ext_obj.save(update_fields=['staff', 'updated_at'])
        self.stdout.write(
            self.style.SUCCESS(
                f'ext {ext_obj.extension} ({ext_obj.get_extension_type_display()}) '
                f'-> {staff_obj.full_name} (id={staff_obj.pk})'
            )
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    def _do_list(self, unassigned_only=False):
        qs = AgentExtension.objects.exclude(
            extension_type=AgentExtension.TYPE_GATEWAY
        ).select_related('staff__user').order_by('extension_type', 'extension')

        if unassigned_only:
            qs = qs.filter(staff__isnull=True)

        self.stdout.write('')
        self.stdout.write(
            f"{'EXT':<8} {'TYPE':<10} {'REG':<5} {'STAFF'}"
        )
        self.stdout.write('-' * 60)

        assigned = unassigned = 0
        for ext in qs:
            staff_str = ext.staff.full_name if ext.staff else '--- unassigned ---'
            self.stdout.write(
                f'{ext.extension:<8} {ext.extension_type:<10} '
                f'{_reg_badge(ext):<5} {staff_str}'
            )
            if ext.staff:
                assigned += 1
            else:
                unassigned += 1

        self.stdout.write('-' * 60)
        self.stdout.write(
            f'Total: {assigned + unassigned}  |  '
            f'Assigned: {assigned}  |  '
            f'Unassigned: {unassigned}'
        )
        self.stdout.write('')

        # Show gateway summary separately
        gw_qs = AgentExtension.objects.filter(extension_type=AgentExtension.TYPE_GATEWAY)
        if gw_qs.exists():
            self.stdout.write('Gateways:')
            for gw in gw_qs:
                gw_type = gw.get_gateway_type_display() if gw.gateway_type else 'unset'
                prefix  = f'  prefix={gw.call_prefix!r}' if gw.call_prefix else ''
                suffix  = f'  suffix={gw.call_suffix!r}' if gw.call_suffix else ''
                self.stdout.write(
                    f'  {gw.extension:<12} {gw_type}{prefix}{suffix}'
                )
            self.stdout.write('')

    def _do_from_json(self, filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f'Cannot read {filepath}: {exc}')

        if not isinstance(data, list):
            raise CommandError('JSON file must be a list: [{"ext": "10", "staff": "username"}, ...]')

        ok = fail = 0
        for row in data:
            ext_str   = str(row.get('ext', '')).strip()
            username  = str(row.get('staff', '')).strip()
            staff_id  = row.get('staff_id')

            if not ext_str:
                self.stdout.write(self.style.WARNING(f'Skipping row with no ext: {row}'))
                fail += 1
                continue

            try:
                ext_obj   = _get_ext(ext_str)
                staff_obj = _get_staff(username or None, staff_id)

                if not staff_obj:
                    self.stdout.write(self.style.WARNING(f'ext {ext_str}: no staff specified, skipped'))
                    fail += 1
                    continue

                # Release from previous extension if needed
                prev = AgentExtension.objects.filter(staff=staff_obj).exclude(pk=ext_obj.pk).first()
                if prev:
                    prev.staff = None
                    prev.save(update_fields=['staff', 'updated_at'])

                ext_obj.staff = staff_obj
                ext_obj.save(update_fields=['staff', 'updated_at'])
                self.stdout.write(
                    f'  ext {ext_str} -> {staff_obj.full_name}'
                )
                ok += 1

            except CommandError as exc:
                self.stdout.write(self.style.ERROR(f'  ext {ext_str}: {exc}'))
                fail += 1

        self.stdout.write('')
        self.stdout.write(
            self.style.SUCCESS(f'Done: {ok} assigned, {fail} failed.')
        )
