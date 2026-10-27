"""
python manage.py sync_ap_reconciliation
    [--party-type supplier|customer|both]
    [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--days 90]
    [--branch 130] [--personcode 4471]
    [--rowcount 100000] [--dry-run]

Phase-C batch 2 — READ-ONLY ingest of the SOFTECH A/P–A/R settlement data into
the PostgreSQL reconciliation mirror (ReconParty / APInvoice / Payment /
Allocation). Bounded by a date window (+ optional branch / personcode) so the
huge base tables are never scanned wholesale.

It fetches three feeds (stktransm / cheques / chequestrans) via
apps/finance/queries/sybase_reconciliation.py, hands them to the pure
apps/finance/recon_ingest.ingest(), records a ReconciliationRun, and flags the
historical problem set (payment vouchers with no allocation).

ABSOLUTE RULE: SELECT-only on SOFTECH. Nothing is written back to the ERP.
See docs/architecture/23_SOFTECH_AP_RECONCILIATION.md.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone


class Command(BaseCommand):
    help = 'READ-ONLY ingest of SOFTECH supplier/customer settlement data into the reconciliation mirror'

    def add_arguments(self, parser):
        parser.add_argument('--party-type', default='supplier',
                            choices=['supplier', 'customer', 'both'])
        parser.add_argument('--from', dest='date_from', default='', help='YYYY-MM-DD (inclusive)')
        parser.add_argument('--to', dest='date_to', default='', help='YYYY-MM-DD (inclusive)')
        parser.add_argument('--days', type=int, default=90,
                            help='window size when --from/--to omitted (default 90)')
        parser.add_argument('--branch', default='', help='limit to one SOFTECH branchcode')
        parser.add_argument('--personcode', default='', help='limit to one party personcode')
        parser.add_argument('--rowcount', type=int, default=100_000, help='per-feed row cap')
        parser.add_argument('--dry-run', action='store_true',
                            help='fetch + count only; do not upsert the mirror')

    def handle(self, *args, **o):
        from apps.finance.queries import sybase_reconciliation as q
        from apps.finance import recon_ingest
        from apps.finance.models import ReconciliationRun

        # ── resolve window ────────────────────────────────────────────────────
        today = timezone.now().date()
        date_to = o['date_to'] or today.isoformat()
        if o['date_from']:
            date_from = o['date_from']
        else:
            d_to = datetime.date.fromisoformat(date_to)
            date_from = (d_to - datetime.timedelta(days=o['days'])).isoformat()

        branch = o['branch'] or None
        personcode = o['personcode'] or None
        rc = o['rowcount']
        party_types = ['supplier', 'customer'] if o['party_type'] == 'both' else [o['party_type']]

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'AP/AR reconciliation ingest  {date_from} → {date_to}  '
            f'party={o["party_type"]} branch={branch or "all"} person={personcode or "all"} '
            f'{"[DRY-RUN]" if o["dry_run"] else ""}'))

        run = ReconciliationRun.objects.create(
            mode=ReconciliationRun.MODE_READONLY,
            status='running',
            party_type='' if o['party_type'] == 'both' else o['party_type'],
            date_from=datetime.date.fromisoformat(date_from),
            date_to=datetime.date.fromisoformat(date_to),
            params={k: o[k] for k in ('party_type', 'branch', 'personcode', 'days', 'dry_run')},
            triggered_by='sync_ap_reconciliation',
        )

        totals = {'invoices': 0, 'vouchers': 0, 'allocations': 0,
                  'unallocated_flagged': 0, 'skipped': 0, 'fetched': {}}
        try:
            for pt in party_types:
                invoices    = q.get_invoices(pt, date_from, date_to, branch, personcode, rowcount=rc)
                vouchers    = q.get_vouchers(pt, date_from, date_to, branch, personcode, rowcount=rc)
                allocations = q.get_allocations(pt, date_from, date_to, branch, personcode, rowcount=rc)

                for label, rows in (('invoices', invoices), ('vouchers', vouchers),
                                    ('allocations', allocations)):
                    if rows and isinstance(rows[0], dict) and '_error' in rows[0]:
                        raise CommandError(f'{pt} {label} read failed: {rows[0]["_error"]}')

                totals['fetched'][pt] = {
                    'invoices': len(invoices), 'vouchers': len(vouchers),
                    'allocations': len(allocations),
                }
                self.stdout.write(
                    f'  {pt}: fetched {len(invoices)} invoices, {len(vouchers)} vouchers, '
                    f'{len(allocations)} allocations')

                if o['dry_run']:
                    continue

                with transaction.atomic():
                    stats = recon_ingest.ingest(
                        invoices=invoices, vouchers=vouchers,
                        allocations=allocations, party_type=pt,
                    )
                for k in ('invoices', 'vouchers', 'allocations',
                          'unallocated_flagged', 'skipped'):
                    totals[k] += stats.get(k, 0)
                self.stdout.write(self.style.SUCCESS(
                    f'    upserted: {stats["invoices"]} inv / {stats["vouchers"]} vou / '
                    f'{stats["allocations"]} alloc — {stats["unallocated_flagged"]} unallocated flagged'))
        except Exception as e:
            run.status = 'failed'
            run.counts = totals
            run.notes = str(e)[:500]
            run.finished_at = timezone.now()
            run.save(update_fields=['status', 'counts', 'notes', 'finished_at'])
            raise

        # snapshot SOFTECH balances for the ingested parties (Phase F) → makes the
        # حصر equation's unexplained_variance meaningful. Best-effort: never fails
        # the ingest run.
        if not o['dry_run']:
            try:
                from apps.finance.models import ReconParty
                from apps.finance import recon_balances
                scope = ReconParty.objects.filter(party_type__in=party_types)
                if personcode:
                    scope = scope.filter(softech_personcode=personcode)
                codes = list(scope.values_list('softech_personcode', flat=True))
                brows = q.get_party_balances(codes) if codes else []
                if brows and not (isinstance(brows[0], dict) and '_error' in brows[0]):
                    bstats = recon_balances.apply_balances(brows)
                    totals['balances_snapshotted'] = bstats['updated']
                    self.stdout.write(f'  balances snapshotted: {bstats["updated"]} parties')
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'  balance snapshot skipped: {e}'))

        run.status = 'success'
        run.counts = totals
        run.finished_at = timezone.now()
        run.save(update_fields=['status', 'counts', 'finished_at'])

        self.stdout.write(self.style.SUCCESS(
            f'\nDONE run#{run.id}  invoices={totals["invoices"]} vouchers={totals["vouchers"]} '
            f'allocations={totals["allocations"]} unallocated={totals["unallocated_flagged"]} '
            f'skipped={totals["skipped"]}'))
