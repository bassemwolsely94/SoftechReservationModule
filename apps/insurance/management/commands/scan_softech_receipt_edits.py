"""
READ-ONLY forensic sweep — detect insurance receipts that were edited in SOFTECH
after we imported them, and flag any HQ↔branch inconsistency.

Two independent signals per receipt line:
  * EDITED      — SOFTECH's current value differs from our FROZEN import snapshot
                  (someone re-priced the receipt in SOFTECH after we imported it).
  * INCONSISTENT — the branch node and HQ disagree (an edit applied to one node but
                  not the other → the printed branch receipt won't match HQ).

Never writes anything.  Compares three sources per line:
  frozen (InsuranceClaimLine) | HQ stktrans | branch-node stktrans

Reachability: HQ is always used; each branch node is opened lazily and cached, and
skipped (with a warning) if its VPN link is down — so an offline branch degrades to
"EDITED-only" detection instead of failing the whole sweep.

Usage:
  manage.py scan_softech_receipt_edits --claim 74
  manage.py scan_softech_receipt_edits --all-draft --period 2026-08
  manage.py scan_softech_receipt_edits --claim 74 --out report.json
"""
import json
from decimal import Decimal
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

from apps.insurance.models import InsuranceClaim, InsuranceClaimLine, InsuranceClaimExclusion
from apps.insurance.importer import _get_connection
from apps.branches.models import Branch

# stktrans financial fields an insurance re-price edit could touch.
_FIELDS = ['transqty', 'itemsaleprice', 'itemsaleprice_tax', 'itemsalestax',
           'transprice', 'transprice_total', 'pharmacydiscp', 'additionaldiscp',
           'custdiscp', 'origintaxp']
_SEL = ("SELECT " + ",".join(_FIELDS) +
        " FROM SOFTECHDB9.dbo.stktrans WHERE docnumber=CONVERT(numeric(6),?) "
        "AND branchcode=? AND itemcode=? AND doccode=?")
# Insurance sales are the indirect-POS document type (doccode 115).
_DOCCODE = '115'
_Q = Decimal('0.01')


def _dec(v):
    return None if v is None else Decimal(str(v))


class Command(BaseCommand):
    help = 'READ-ONLY: detect SOFTECH-edited / HQ↔branch-inconsistent insurance receipts.'

    def add_arguments(self, parser):
        parser.add_argument('--claim', type=int, action='append', default=[])
        parser.add_argument('--all-draft', action='store_true')
        parser.add_argument('--period', type=str, default=None,
                            help='YYYY-MM to scope --all-draft to one month.')
        parser.add_argument('--branch', type=str, default=None,
                            help='Only scan receipts from this branch code.')
        parser.add_argument('--doccode', type=str, default=_DOCCODE)
        parser.add_argument('--out', type=str, default=None,
                            help='Write the full structured report to this JSON file.')
        parser.add_argument('--limit', type=int, default=0,
                            help='Stop after N receipts (0 = all).')

    def handle(self, *args, **opts):
        if opts['claim']:
            claims = list(InsuranceClaim.objects.filter(pk__in=opts['claim']))
        elif opts['all_draft']:
            qs = InsuranceClaim.objects.filter(status=InsuranceClaim.STATUS_DRAFT)
            if opts['period']:
                y, m = opts['period'].split('-')
                qs = qs.filter(period_from__year=int(y), period_from__month=int(m))
            claims = list(qs)
        else:
            raise CommandError('Pass --claim <id> (repeatable) or --all-draft.')

        doccode = opts['doccode']
        branch_hosts = {b.softech_branch_id: b.effective_db_host
                        for b in Branch.objects.all()}
        branch_ports = {b.softech_branch_id: b.effective_db_port
                        for b in Branch.objects.all()}

        hq = _get_connection()
        hcur = hq.cursor()
        branch_curs = {}          # branch code -> cursor | None (None = unreachable)
        report = []               # per-receipt divergence records
        counts = {'receipts': 0, 'edited': 0, 'inconsistent': 0, 'lines_checked': 0}
        by_branch = defaultdict(lambda: {'receipts': 0, 'edited': 0, 'inconsistent': 0})

        def branch_cur(code):
            if code in branch_curs:
                return branch_curs[code]
            host, port = branch_hosts.get(code), branch_ports.get(code, 5000)
            cur = None
            try:
                from config.sybase import get_branch_connection
                cur = get_branch_connection(host, port).cursor()
            except Exception as e:
                self.stdout.write(self.style.WARNING(
                    f'  branch {code} node unreachable ({host}) — EDITED-only for its receipts: {str(e)[:50]}'))
            branch_curs[code] = cur
            return cur

        for claim in claims:
            excl = set(InsuranceClaimExclusion.objects.filter(prescription__claim=claim)
                       .values_list('prescription_id', flat=True))
            lines = list(InsuranceClaimLine.objects.filter(prescription__claim=claim)
                         .exclude(prescription_id__in=excl)
                         .select_related('prescription'))
            # group lines by receipt
            by_rx = defaultdict(list)
            for ln in lines:
                by_rx[(ln.prescription.softech_docnumber,
                       ln.prescription.softech_branchcode)].append(ln)

            for (docno, branch), rx_lines in by_rx.items():
                if opts['branch'] and branch != opts['branch']:
                    continue
                if opts['limit'] and counts['receipts'] >= opts['limit']:
                    break
                counts['receipts'] += 1
                by_branch[branch]['receipts'] += 1
                bcur = branch_cur(branch)
                rx_edits = []
                for ln in rx_lines:
                    counts['lines_checked'] += 1
                    code = ln.softech_itemcode
                    hcur.execute(_SEL, [docno, branch, code, doccode])
                    hrow = hcur.fetchone()
                    hv = dict(zip(_FIELDS, [_dec(v) for v in hrow])) if hrow else None
                    bv = None
                    if bcur is not None:
                        bcur.execute(_SEL, [docno, branch, code, doccode])
                        brow = bcur.fetchone()
                        bv = dict(zip(_FIELDS, [_dec(v) for v in brow])) if brow else None

                    frozen_price = _dec(ln.unit_price)
                    frozen_total = _dec(ln.line_total)
                    # EDITED: HQ price/total differs from what we froze at import
                    edited = bool(hv and (hv['itemsaleprice'] != frozen_price
                                          or hv['transprice_total'] != frozen_total))
                    # INCONSISTENT: HQ vs branch differ on any tracked field
                    inconsistent_fields = ({k: (str(hv.get(k)), str(bv.get(k)))
                                            for k in _FIELDS if hv and bv and hv.get(k) != bv.get(k)}
                                           if (hv and bv) else {})
                    if edited or inconsistent_fields:
                        rx_edits.append({
                            'itemcode': code, 'item_name': ln.item_name,
                            'frozen': {'unit_price': str(frozen_price), 'line_total': str(frozen_total),
                                       'qty': str(_dec(ln.quantity)), 'category': ln.item_category},
                            'hq': {k: str(v) for k, v in hv.items()} if hv else None,
                            'branch': {k: str(v) for k, v in bv.items()} if bv else None,
                            'edited': edited,
                            'inconsistent_fields': inconsistent_fields,
                        })
                if rx_edits:
                    rec_edited = any(e['edited'] for e in rx_edits)
                    rec_incon = any(e['inconsistent_fields'] for e in rx_edits)
                    if rec_edited:
                        counts['edited'] += 1; by_branch[branch]['edited'] += 1
                    if rec_incon:
                        counts['inconsistent'] += 1; by_branch[branch]['inconsistent'] += 1
                    report.append({
                        'claim_id': claim.pk, 'claim_number': claim.claim_number,
                        'docnumber': docno, 'branch': branch,
                        'edited': rec_edited, 'inconsistent': rec_incon,
                        'lines': rx_edits,
                    })

        hcur.close()
        # ── print summary ──
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f"Scanned {counts['receipts']} receipts / {counts['lines_checked']} lines · "
            f"EDITED (SOFTECH≠import): {counts['edited']} · "
            f"INCONSISTENT (HQ≠branch): {counts['inconsistent']}"))
        for br, s in sorted(by_branch.items()):
            if s['edited'] or s['inconsistent']:
                self.stdout.write(f"  branch {br}: {s['edited']} edited, {s['inconsistent']} inconsistent "
                                  f"(of {s['receipts']} scanned)")
        for rec in report[:60]:
            tag = ('EDITED' if rec['edited'] else '') + (' INCONSISTENT' if rec['inconsistent'] else '')
            self.stdout.write(f"\n#{rec['docnumber']} br{rec['branch']} «{rec['claim_number']}» [{tag.strip()}]")
            for e in rec['lines']:
                flags = ('E' if e['edited'] else '') + ('C' if e['inconsistent_fields'] else '')
                self.stdout.write(f"    [{flags}] {e['itemcode']} {e['item_name'][:22]:22} "
                                  f"frozen={e['frozen']['unit_price']} "
                                  f"HQ={e['hq']['itemsaleprice'] if e['hq'] else '—'} "
                                  f"br={e['branch']['itemsaleprice'] if e['branch'] else '—'}")
                if e['inconsistent_fields']:
                    self.stdout.write(f"        HQ≠branch: {e['inconsistent_fields']}")

        if opts['out']:
            with open(opts['out'], 'w', encoding='utf-8') as f:
                json.dump({'counts': counts, 'by_branch': dict(by_branch), 'receipts': report},
                          f, ensure_ascii=False, indent=2)
            self.stdout.write(self.style.SUCCESS(f'\nFull report → {opts["out"]}'))
