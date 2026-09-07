"""
python manage.py derive_erp_permissions [--seed-map] [--show]

Seeds the SOFTECH-system → platform-module map (first run) and rebuilds the
derived group×module permissions. SOFTECH-authoritative — safe to re-run; it
fully rebuilds each time.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Derive platform module permissions from mirrored SOFTECH groups'

    def add_arguments(self, parser):
        parser.add_argument('--seed-map', action='store_true', help='Force re-seed the default system map')
        parser.add_argument('--show', action='store_true', help='Print derived permissions per group')

    def handle(self, *args, **opts):
        from apps.users.erp_permissions import seed_system_map, derive_group_permissions
        from apps.users.models import SoftechSystemMap, ErpGroupModulePermission, ErpUserGroup

        seeded = seed_system_map(force=opts['seed_map'])
        self.stdout.write(f'System map rows seeded: {seeded} (total {SoftechSystemMap.objects.count()})')

        n = derive_group_permissions()
        self.stdout.write(self.style.SUCCESS(f'Derived {n} group×module permission rows.'))

        if opts['show']:
            for g in ErpUserGroup.objects.all().order_by('usergroup'):
                perms = ErpGroupModulePermission.objects.filter(group=g, can_view=True)
                mods = ', '.join(f'{p.module}'
                                 f'{"+cost" if p.can_see_cost else ""}'
                                 f'{"/edit" if p.can_edit else ""}'
                                 for p in perms)
                line = f'  group {g.usergroup} {g.name[:20]:<20} → {mods or "(no mapped access)"}'
                self.stdout.write(line.encode('ascii', 'replace').decode('ascii'))
