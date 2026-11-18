from django.core.management.base import BaseCommand, CommandError

from apps.crews import cc_seed


class Command(BaseCommand):
    help = 'Seed the call-center crew «الكول سنتر» from CallCenterConfig (idempotent; piece 2b).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--reseed', action='store_true',
                            help='delete ONLY the seed rows (reason = seed reason), then seed '
                                 'again; hand-added rows and the crew rollups survive; audited')
        parser.add_argument('--without-pbx-agent-extensions', action='store_true',
                            help='do not seed the PBX agent extensions missing from '
                                 'CallCenterConfig (they are seeded by default)')

    def handle(self, *args, **o):
        if o['reseed'] and o['dry_run']:
            raise CommandError('--dry-run and --reseed cannot be combined.')
        kw = {'include_pbx_agent_extensions': not o['without_pbx_agent_extensions']}
        try:
            res = cc_seed.reseed(**kw) if o['reseed'] else cc_seed.seed(dry_run=o['dry_run'], **kw)
        except cc_seed.CcCrewNameTaken as exc:
            raise CommandError(str(exc))
        tag = 'DRY RUN ' if o['dry_run'] else ''
        self.stdout.write(f"{tag}crew={res['crew_id']} start={res['start']} "
                          f"created={len(res['created'])} skipped={len(res['skipped'])}")
        for it in res['created']:
            self.stdout.write(f"  + {it['kind']} {it['value']} employee={it['employee_id']} {it['label']}")
        if o['reseed']:
            # the crew's KPI rows were computed from the old membership
            self.stdout.write(self.style.WARNING(
                'Membership changed: run build_crew_rollups --since <first month> to rebuild the '
                "crew's KPI rollups (the board, targets and forecasts read them)."))
