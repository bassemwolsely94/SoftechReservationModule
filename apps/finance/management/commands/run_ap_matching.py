"""
python manage.py run_ap_matching [--party-type supplier|customer] [--personcode 4471]

Phase-C batch 3 — run the reconciliation MATCHING ENGINE over the already-ingested
mirror (run `sync_ap_reconciliation` first). Generates read-only MatchCandidates +
MatchEvidence and emits ReconExceptions. Creates NO allocations and writes NOTHING
to SOFTECH — proposals only, for human review (C-E).

See docs/architecture/23_SOFTECH_AP_RECONCILIATION.md.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Run the read-only A/P–A/R matching engine over the ingested mirror (proposals only)'

    def add_arguments(self, parser):
        parser.add_argument('--party-type', default='', choices=['', 'supplier', 'customer'])
        parser.add_argument('--personcode', default='', help='limit to one party personcode')

    def handle(self, *args, **o):
        from apps.finance import recon_engine

        run = recon_engine.run_matching(
            party_type=o['party_type'] or None,
            personcode=o['personcode'] or None,
            triggered_by='run_ap_matching(cli)',
        )
        c = run.counts
        self.stdout.write(self.style.SUCCESS(
            f'DONE run#{run.id} [{run.rules_version}] — {c.get("candidates", 0)} candidates, '
            f'{c.get("exceptions", 0)} exceptions across {c.get("parties", 0)} parties'))
