"""
READ-ONLY preview of a SOFTECH insurance-receipt price edit.  Shows exactly what a
re-price WOULD change — per line, the header re-foot, the tender, and the
`personnewbal` rebalance footprint — on HQ and (if reachable) the branch node.
Writes nothing.

Usage:
  manage.py preview_receipt_reprice --docno 549566 --branch 140 --set 121191=95
  manage.py preview_receipt_reprice --docno 914320 --branch 160 --set 128721=270 --set 87618=210
"""
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from apps.insurance.importer import _get_connection
from apps.insurance.reprice import recompute_line, refoot_header, _d, r2
from apps.branches.models import Branch

_DOCCODE = '115'
_LINE_COLS = ['itemcode', 'transqty', 'itemsaleprice', 'itemsaleprice_tax', 'itemsalestax',
              'transprice', 'transprice_total', 'additionaldiscp', 'custdiscp', 'newcostprice']
_HDR_COLS = ['docvalue', 'docvalue1', 'docvalue2', 'docvalue3', 'cust_branch_code', 'trans_time']


def _read_receipt(cur, docno, branch, doccode):
    cur.execute("SELECT " + ",".join(_LINE_COLS) +
                " FROM SOFTECHDB9.dbo.stktrans WHERE docnumber=CONVERT(numeric(6),?) "
                "AND branchcode=? AND doccode=?", [docno, branch, doccode])
    lines = [dict(zip(_LINE_COLS, r)) for r in cur.fetchall()]
    cur.execute("SELECT " + ",".join(_HDR_COLS) +
                " FROM SOFTECHDB9.dbo.stktransm WHERE docnumber=CONVERT(numeric(6),?) "
                "AND branchcode=? AND doccode=?", [docno, branch, doccode])
    hr = cur.fetchone()
    header = dict(zip(_HDR_COLS, hr)) if hr else None
    return lines, header


class Command(BaseCommand):
    help = 'READ-ONLY preview of a SOFTECH receipt re-price (no writes).'

    def add_arguments(self, parser):
        parser.add_argument('--docno', required=True)
        parser.add_argument('--branch', required=True)
        parser.add_argument('--doccode', default=_DOCCODE)
        parser.add_argument('--set', action='append', default=[], metavar='ITEMCODE=PRICE',
                            help='New public price for an item on this receipt (repeatable).')

    def handle(self, *args, **o):
        new_prices = {}
        for pair in o['set']:
            if '=' not in pair:
                raise CommandError(f'--set must be ITEMCODE=PRICE, got {pair!r}')
            code, price = pair.split('=', 1)
            new_prices[code.strip()] = Decimal(price.strip())
        if not new_prices:
            raise CommandError('Pass at least one --set ITEMCODE=PRICE.')

        docno, branch, doccode = o['docno'], o['branch'], o['doccode']
        hq = _get_connection(); hcur = hq.cursor()
        lines, header = _read_receipt(hcur, docno, branch, doccode)
        if not lines or not header:
            raise CommandError(f'Receipt #{docno} br{branch} doccode {doccode} not found on HQ.')

        self.stdout.write(self.style.SUCCESS(f'\n=== PREVIEW (read-only) #{docno} br{branch} ==='))
        new_lines = []
        for ln in lines:
            code = str(ln['itemcode']).strip()
            if code in new_prices:
                rc = recompute_line(new_price=new_prices[code], transqty=ln['transqty'],
                                    custdiscp=ln['custdiscp'], vat_rate=ln['additionaldiscp'])
                self.stdout.write(f"\n  LINE {code}  price {_d(ln['itemsaleprice'])} → {rc['itemsaleprice']}"
                                  f"  (VAT {_d(ln['additionaldiscp'])}%, contract {_d(ln['custdiscp'])}%, qty {_d(ln['transqty'])})")
                for f in ('itemsaleprice', 'itemsaleprice_tax', 'itemsalestax', 'transprice', 'transprice_total'):
                    old, new = _d(ln[f]), rc[f]
                    mark = '  <—' if r2(old) != r2(new) else ''
                    self.stdout.write(f"      {f:18} {str(old):>12} → {str(new):>12}{mark}")
                merged = dict(ln); merged.update({k: str(v) for k, v in rc.items()})
                new_lines.append(merged)
            else:
                new_lines.append(ln)

        # header re-foot (docvalue2/cost carried over unchanged)
        h = refoot_header([{'itemsaleprice': l['itemsaleprice'], 'transqty': l['transqty'],
                            'transprice_total': l['transprice_total'], 'itemsalestax': l['itemsalestax']}
                           for l in new_lines])
        self.stdout.write('\n  HEADER (stktransm):')
        for f, newv in (('docvalue1', h['docvalue1']), ('docvalue', h['docvalue']), ('docvalue3', h['docvalue3'])):
            old = _d(header[f]); mark = '  <—' if r2(old) != r2(newv) else ''
            self.stdout.write(f"      {f:10} {str(old):>12} → {str(newv):>12}{mark}")
        self.stdout.write(f"      docvalue2  {str(_d(header['docvalue2'])):>12}   (cost — unchanged)")
        self.stdout.write(f"      TENDER paymentvalue must become {h['docvalue']} (= new docvalue)")

        # personnewbal rebalance footprint (contract-client running Σ docvalue)
        ccode = str(header['cust_branch_code']).strip() if header['cust_branch_code'] else None
        net_delta = r2(h['docvalue']) - r2(_d(header['docvalue']))
        self.stdout.write(f"\n  personnewbal rebalance (contract client cust_branch_code={ccode}):")
        self.stdout.write(f"      net Δ = {net_delta:+}  → shifts this receipt and every LATER receipt of this client")
        if ccode and net_delta != 0:
            hcur.execute("SELECT COUNT(*) FROM SOFTECHDB9.dbo.stktransm WHERE cust_branch_code=? "
                         "AND doccode=? AND trans_time >= (SELECT trans_time FROM SOFTECHDB9.dbo.stktransm "
                         "WHERE docnumber=CONVERT(numeric(6),?) AND branchcode=? AND doccode=?)",
                         [ccode, doccode, docno, branch, doccode])
            n = hcur.fetchone()[0]
            self.stdout.write(f"      downstream receipts to rebalance (HQ, all branches): {n}")

        # HQ vs branch consistency note
        host = {b.softech_branch_id: b.effective_db_host for b in Branch.objects.all()}.get(branch)
        try:
            from config.sybase import get_branch_connection
            bcur = get_branch_connection(host, 5000).cursor()
            blines, bheader = _read_receipt(bcur, docno, branch, doccode)
            same = bheader and r2(_d(bheader['docvalue'])) == r2(_d(header['docvalue']))
            self.stdout.write(f"\n  branch node ({host}): reachable — HQ/branch currently "
                              + ('consistent' if same else 'INCONSISTENT (edit must hit both)'))
            bcur.close()
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"\n  branch node ({host}) unreachable — apply must be BLOCKED "
                                                 f"until reachable (can't keep nodes consistent): {str(e)[:40]}"))
        hcur.close()
        self.stdout.write(self.style.SUCCESS('\n(no changes written — preview only)'))
