"""
python manage.py backfill_ap_reconciliation
    [--party-type supplier|customer|both] [--from-year 2019] [--to-year 2026]
    [--chunk month|year] [--match] [--rowcount 60000]

Phase-C — bulk, CHUNKED, READ-ONLY historical backfill of the whole estate into
the reconciliation mirror. Iterates the date range in month (default) or year
windows so no single query scans the multi-million-row base tables wholesale, and
snapshots SOFTECH balances at the end. Optionally runs the matching engine.

This is designed to run as a SCHEDULED off-hours job — one busy supplier already
yields ~13K invoices / ~24K candidate rows, so the full estate is large. It is
idempotent (update_or_create), so it can be re-run / resumed safely.

SELECT-only on SOFTECH; writes only the PostgreSQL mirror. Never touches SOFTECH.
See docs/architecture/23_SOFTECH_AP_RECONCILIATION.md.
"""
import calendar
import datetime

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone


def _month_windows(y0, y1):
    for y in range(y0, y1 + 1):
        for m in range(1, 13):
            last = calendar.monthrange(y, m)[1]
            yield (f'{y}-{m:02d}-01', f'{y}-{m:02d}-{last:02d}')


def _year_windows(y0, y1):
    for y in range(y0, y1 + 1):
        yield (f'{y}-01-01', f'{y}-12-31')


class Command(BaseCommand):
    help = 'Bulk chunked READ-ONLY backfill of the reconciliation mirror (schedule off-hours)'

    def add_arguments(self, parser):
        parser.add_argument('--party-type', default='supplier',
                            choices=['supplier', 'customer', 'both'])
        parser.add_argument('--from-year', type=int, default=2019)
        parser.add_argument('--to-year', type=int, default=timezone.now().year)
        parser.add_argument('--chunk', default='month', choices=['month', 'year'])
        parser.add_argument('--rowcount', type=int, default=60_000)
        parser.add_argument('--match', action='store_true', help='run matching after ingest')

    def handle(self, *args, **o):
        from apps.finance.queries import sybase_reconciliation as q
        from apps.finance import recon_ingest, recon_balances

        party_types = ['supplier', 'customer'] if o['party_type'] == 'both' else [o['party_type']]
        windows = (_month_windows if o['chunk'] == 'month' else _year_windows)(
            o['from_year'], o['to_year'])
        windows = list(windows)
        totals = {'invoices': 0, 'vouchers': 0, 'allocations': 0, 'chunks': 0, 'errors': 0}

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'Backfill {o["from_year"]}→{o["to_year"]} party={o["party_type"]} '
            f'chunk={o["chunk"]} ({len(windows)} windows)'))

        for (d_from, d_to) in windows:
            for pt in party_types:
                try:
                    inv = q.get_invoices(pt, d_from, d_to, rowcount=o['rowcount'])
                    vou = q.get_vouchers(pt, d_from, d_to, rowcount=o['rowcount'])
                    alloc = q.get_allocations(pt, d_from, d_to, rowcount=o['rowcount'])
                    for rows in (inv, vou, alloc):
                        if rows and isinstance(rows[0], dict) and '_error' in rows[0]:
                            raise RuntimeError(rows[0]['_error'])
                    with transaction.atomic():
                        s = recon_ingest.ingest(invoices=inv, vouchers=vou,
                                                allocations=alloc, party_type=pt)
                    for k in ('invoices', 'vouchers', 'allocations'):
                        totals[k] += s.get(k, 0)
                    if (s['invoices'] + s['vouchers']):
                        self.stdout.write(
                            f'  {d_from}..{d_to} {pt}: +{s["invoices"]}inv +{s["vouchers"]}vou '
                            f'+{s["allocations"]}alloc')
                except Exception as e:
                    totals['errors'] += 1
                    self.stdout.write(self.style.WARNING(f'  {d_from}..{d_to} {pt}: ERROR {str(e)[:120]}'))
            totals['chunks'] += 1

        # snapshot balances for everything ingested
        try:
            from apps.finance.models import ReconParty
            codes = list(ReconParty.objects.filter(party_type__in=party_types)
                         .values_list('softech_personcode', flat=True))
            for i in range(0, len(codes), 400):
                brows = q.get_party_balances(codes[i:i + 400])
                if brows and not (isinstance(brows[0], dict) and '_error' in brows[0]):
                    recon_balances.apply_balances(brows)
            self.stdout.write(f'  balances snapshotted for {len(codes)} parties')
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'  balance snapshot skipped: {e}'))

        if o['match']:
            from apps.finance import recon_engine
            for pt in party_types:
                run = recon_engine.run_matching(party_type=pt, triggered_by='backfill')
                self.stdout.write(f'  matching {pt}: run#{run.id} {run.counts}')

        self.stdout.write(self.style.SUCCESS(
            f'DONE — {totals["chunks"]} chunks, {totals["invoices"]} invoices, '
            f'{totals["vouchers"]} vouchers, {totals["allocations"]} allocations, '
            f'{totals["errors"]} errors'))
