"""
python manage.py sync_ap_return_links [--from 2019-01-01] [--to today]

Mirror SOFTECH's return→purchase links: return lines (stktrans doccode 120) that
carry r_doccode='10' + r_docnumber + r_docdate name the purchase invoice they return.
Aggregated per (return, purchase) and stored as finance.ReturnLink. Quarter-sized
windows keep each HQ query light. Read-only on SOFTECH; idempotent.
"""
import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand


def _quarters(d0: datetime.date, d1: datetime.date):
    cur = datetime.date(d0.year, ((d0.month - 1) // 3) * 3 + 1, 1)
    while cur <= d1:
        nm = cur.month + 3
        nxt = datetime.date(cur.year + (nm > 12), (nm - 1) % 12 + 1, 1)
        yield cur, nxt
        cur = nxt


class Command(BaseCommand):
    help = 'Sync return→purchase links (stktrans.r_docnumber) into finance.ReturnLink'

    def add_arguments(self, parser):
        parser.add_argument('--from', dest='date_from', default='2019-01-01')
        parser.add_argument('--to', dest='date_to', default='')

    def handle(self, *args, **o):
        from apps.finance.models import APInvoice, ReturnLink
        from apps.finance.queries.sybase_reconciliation import DB, _rows

        d0 = datetime.date.fromisoformat(o['date_from'])
        d1 = datetime.date.fromisoformat(o['date_to']) if o['date_to'] else datetime.date.today()
        returns = {(r.branchcode, str(r.docnumber).split('.')[0], r.docdate): r
                   for r in APInvoice.objects.filter(doccode='120')}
        purchases = {(p.branchcode, str(p.docnumber).split('.')[0], p.docdate): p
                     for p in APInvoice.objects.filter(doccode='10')}
        total = linked = unresolved = 0
        for a, b in _quarters(d0, d1):
            sql = f"""
                SELECT t.branchcode, t.docnumber, t.docdate, t.r_docnumber, t.r_docdate,
                       SUM(t.transprice_total) AS amt
                FROM   {DB}.stktrans t
                WHERE  t.doccode = '120' AND t.r_doccode = '10' AND t.r_docnumber > 0
                  AND  t.docdate >= '{a.month}-{a.day}-{a.year}' AND t.docdate < '{b.month}-{b.day}-{b.year}'
                GROUP  BY t.branchcode, t.docnumber, t.docdate, t.r_docnumber, t.r_docdate
            """
            try:
                rows = _rows(sql, [], rowcount=50_000)
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f'  {a}: failed {str(exc)[:80]}'))
                continue
            if rows and '_error' in rows[0]:
                self.stdout.write(self.style.WARNING(f"  {a}: {rows[0]['_error'][:80]}"))
                continue
            n = 0
            for r in rows:
                rk = (str(r['branchcode']).strip(), str(r['docnumber']).split('.')[0],
                      _date(r['docdate']))
                ret = returns.get(rk)
                if ret is None:
                    continue          # return not mirrored (other party type / out of range)
                pdate = _date(r['r_docdate'])
                pno = str(r['r_docnumber']).split('.')[0]
                purchase = purchases.get((rk[0], pno, pdate))
                if purchase is None:  # fall back: same supplier, any branch
                    purchase = next((p for k, p in purchases.items()
                                     if k[1] == pno and k[2] == pdate and p.party_id == ret.party_id), None)
                ReturnLink.objects.update_or_create(
                    return_invoice=ret, purchase_branchcode=(purchase.branchcode if purchase else rk[0]),
                    purchase_docnumber=pno, purchase_docdate=pdate,
                    defaults={'purchase_invoice': purchase,
                              'amount': Decimal(str(r['amt'] or 0)).quantize(Decimal('0.001'))})
                n += 1
                linked += bool(purchase)
                unresolved += purchase is None
            total += n
            self.stdout.write(f'  {a}: {n} links')
            self.stdout.flush()
        self.stdout.write(self.style.SUCCESS(
            f'DONE {total} return→purchase links ({linked} resolved to a mirrored purchase, {unresolved} not)'))


def _date(v):
    if v is None:
        return None
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    return datetime.date.fromisoformat(str(v)[:10])
