"""
python manage.py snapshot_ap_balances [--party-type supplier|customer] [--personcode 4471]

Phase-C batch F — READ-ONLY snapshot of each party's SOFTECH A/P balance
(personsdata: Σcredit−Σdebit = owed; personopencredit−personopendebit = opening)
onto ReconParty, and backfills name/ptclassifcode. Makes the حصر equation's
`unexplained_variance` meaningful. SELECT-only on SOFTECH.

See docs/architecture/23_SOFTECH_AP_RECONCILIATION.md.
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'READ-ONLY snapshot of SOFTECH party balances onto the reconciliation mirror'

    def add_arguments(self, parser):
        parser.add_argument('--party-type', default='', choices=['', 'supplier', 'customer'])
        parser.add_argument('--personcode', default='', help='limit to one personcode')

    def handle(self, *args, **o):
        from apps.finance.models import ReconParty
        from apps.finance.queries import sybase_reconciliation as q
        from apps.finance import recon_balances

        parties = ReconParty.objects.all()
        if o['party_type']:
            parties = parties.filter(party_type=o['party_type'])
        if o['personcode']:
            parties = parties.filter(softech_personcode=o['personcode'])

        codes = list(parties.values_list('softech_personcode', flat=True))
        if not codes:
            self.stdout.write('No parties to snapshot.')
            return

        rows = q.get_party_balances(codes)
        if rows and isinstance(rows[0], dict) and '_error' in rows[0]:
            raise CommandError(f'balance read failed: {rows[0]["_error"]}')

        stats = recon_balances.apply_balances(rows)
        self.stdout.write(self.style.SUCCESS(
            f'Snapshotted {stats["updated"]} parties ({stats["missing"]} not in mirror) '
            f'from {len(rows)} SOFTECH rows.'))
