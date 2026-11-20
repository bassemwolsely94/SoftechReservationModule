"""
python manage.py delivery_stuck_autoclose [--apply]

C21: list (default) or close the delivery orders that are stuck open here although SOFTECH already
delivered (orderstatus 90) or cancelled (100) them. SOFTECH is only read. The rule and its safety
notes live in apps/delivery/stuck_close.py.

--apply is refused while the switch `delivery_stuck_autoclose_enabled` is off, so a dry run is the
only thing this command can do until the owner turns the switch on.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.delivery import stuck_close


class Command(BaseCommand):
    help = 'C21: list (dry run) or close delivery orders SOFTECH already finished.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='Close them (needs the switch delivery_stuck_autoclose_enabled on).')

    def handle(self, *args, **options):
        if options['apply'] and not stuck_close.is_enabled():
            raise CommandError('Switch delivery_stuck_autoclose_enabled is OFF — dry run only.')
        rec = stuck_close.run(apply=bool(options['apply']))
        self.stdout.write(f"[stuck-close] mode={rec['mode']} older-than={rec['min_age_hours']}h "
                          f"checked={rec['checked']}")
        for verdict, n in sorted(rec['counts'].items(), key=lambda kv: -kv[1]):
            self.stdout.write(f'  {verdict:<11} {n}')
        if rec['mode'] == 'apply':
            self.stdout.write(f"  closed={rec['closed']} cancelled={rec['cancelled']} sla_filled={rec['sla_filled']}")
        else:
            would = [r for r in rec['rows'] if r['verdict'] in (stuck_close.VERDICT_CLOSE, stuck_close.VERDICT_CANCEL)]
            for r in would[:50]:
                self.stdout.write(f"    order {r['id']}: {r['verdict']} (SOFTECH {r['softech_status']})")
            if len(would) > 50:
                self.stdout.write(f'    … and {len(would) - 50} more')
