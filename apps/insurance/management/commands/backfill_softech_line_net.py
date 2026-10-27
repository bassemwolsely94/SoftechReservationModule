"""
Backfill InsuranceClaimLine.softech_line_net from SOFTECH (stktrans.transprice_total).

READ-ONLY on SOFTECH.  Populates each frozen line's SOFTECH-own net so the بنود
drill-down can flag the exact item whose discount SOFTECH charged differently from
our uniform category rate (the driver of a prescription's softech_net_diff).

Match: (docnumber, branchcode, itemcode); when an item appears on several lines of
one receipt, SOFTECH rows are paired to our lines in itemcode order.

Usage:
  manage.py backfill_softech_line_net --claim 97
  manage.py backfill_softech_line_net --all-draft
  manage.py backfill_softech_line_net --missing-only   # only lines still NULL
"""
from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from apps.insurance.models import InsuranceClaim, InsuranceClaimLine, InsuranceClaimPrescription
from apps.insurance.importer import _get_connection, _safe, _to_decimal


class Command(BaseCommand):
    help = 'Backfill softech_line_net (SOFTECH transprice_total) on frozen lines.'

    def add_arguments(self, parser):
        parser.add_argument('--claim', type=int, action='append', default=[])
        parser.add_argument('--all-draft', action='store_true')
        parser.add_argument('--missing-only', action='store_true',
                            help='Only touch prescriptions that still have NULL lines.')

    def handle(self, *args, **o):
        if o['claim']:
            claims = list(InsuranceClaim.objects.filter(pk__in=o['claim']))
        elif o['all_draft']:
            claims = list(InsuranceClaim.objects.filter(status=InsuranceClaim.STATUS_DRAFT))
        else:
            raise CommandError('Pass --claim <id> (repeatable) or --all-draft.')

        conn = _get_connection(); cur = conn.cursor()
        SEL = ("SELECT itemcode, transprice_total FROM SOFTECHDB9.dbo.stktrans "
               "WHERE docnumber=CONVERT(numeric(6),?) AND branchcode=? AND doccode='115' "
               "ORDER BY itemcode")
        total_rx = total_lines = 0
        for claim in claims:
            rxs = InsuranceClaimPrescription.objects.filter(claim=claim)
            for rx in rxs:
                lines = list(rx.lines.all())
                if not lines:
                    continue
                if o['missing_only'] and all(l.softech_line_net is not None for l in lines):
                    continue
                try:
                    cur.execute(SEL, [rx.softech_docnumber, rx.softech_branchcode])
                    soft = defaultdict(list)
                    for r in cur.fetchall():
                        soft[_safe(r[0])].append(_to_decimal(r[1]))
                except Exception as e:
                    self.stdout.write(self.style.WARNING(
                        f'  rx #{rx.softech_docnumber}: SOFTECH read failed: {str(e)[:60]}'))
                    continue
                used = {}
                upd = []
                for ln in sorted(lines, key=lambda x: x.softech_itemcode):
                    q = soft.get(ln.softech_itemcode, [])
                    idx = used.get(ln.softech_itemcode, 0)
                    if idx < len(q):
                        ln.softech_line_net = q[idx]
                        used[ln.softech_itemcode] = idx + 1
                        upd.append(ln)
                if upd:
                    InsuranceClaimLine.objects.bulk_update(upd, ['softech_line_net'])
                    total_rx += 1; total_lines += len(upd)
            self.stdout.write(f'claim {claim.pk} «{claim.claim_number}»: done')
        cur.close(); conn.close()
        self.stdout.write(self.style.SUCCESS(
            f'Backfilled {total_lines} lines across {total_rx} prescriptions.'))
