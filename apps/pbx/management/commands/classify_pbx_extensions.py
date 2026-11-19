"""
python manage.py classify_pbx_extensions [--apply]

Types PBX extensions from data (crews spec 5.6): call-center crew extensions -> agent, employee
extensions -> hq/branch by their dated assignment, then the owner-confirmed data file
(apps/pbx/data/confirmed_extension_types.json). Gateways are never touched.
Default is a dry run; --apply saves and writes one audit row. Run after sync_pbx_extensions.
Two employees (or two crews) on one extension: the first claim is kept (employees by hr_number,
crews by name) and the conflict is printed. The employee tier reads current
Employee.pbx_extensions (not dated) — review the dry run before --apply.
"""
from django.core.management.base import BaseCommand

from apps.pbx.classification import classify
from apps.pbx.models import AgentExtension


class Command(BaseCommand):
    help = 'Classify PBX extensions from crews, employee data and the confirmed file'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='save (default: dry run)')

    def handle(self, *args, **options):
        apply = options['apply']
        conflicts = []
        changes = classify(apply=apply, conflicts=conflicts)
        if conflicts:
            self.stdout.write(self.style.WARNING(
                f'{len(conflicts)} extension conflict(s) - first claim kept, review before --apply:'))
            for c in conflicts:
                self.stdout.write(f"  conflict ext={c['extension']:<12} kept {c['kept']}, "
                                  f"dropped {c['dropped']}")
        for c in changes:
            self.stdout.write(f"  ext={c['extension']:<12} {c['old']} -> {c['new']}  ({c['source']})")
        verb = 'Classified' if apply else 'Would classify (dry run, use --apply)'
        self.stdout.write(self.style.SUCCESS(f'{verb} {len(changes)} extensions.'))

        remaining = AgentExtension.objects.filter(extension_type='other', is_active=True)
        pending = {c['extension'] for c in changes}
        left = [e for e in remaining.order_by('extension') if apply or e.extension not in pending]
        if left:
            self.stdout.write(self.style.WARNING(
                f'\n{len(left)} extensions still typed as "other" - review in Admin:'))
            for ext in left:
                self.stdout.write(f'  ext={ext.extension:<12} ip={ext.last_ip or "-"}')
