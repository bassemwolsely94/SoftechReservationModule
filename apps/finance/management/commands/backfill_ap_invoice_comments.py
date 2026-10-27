"""
python manage.py backfill_ap_invoice_comments [--from 2017-01-01] [--to today]

Fill APInvoice.comments (stktransm.comments — الملاحظات) for invoices already in
the mirror. Scans SOFTECH quarter by quarter for purchase/return documents that
HAVE a note (AT ISOLATION 0 — dirty read, never queues behind other sessions' locks)
and updates the matching mirror rows. Read-only on SOFTECH; idempotent.
"""
import datetime

from django.core.management.base import BaseCommand


def _quarters(d0, d1):
    cur = datetime.date(d0.year, ((d0.month - 1) // 3) * 3 + 1, 1)
    while cur <= d1:
        nm = cur.month + 3
        nxt = datetime.date(cur.year + (nm > 12), (nm - 1) % 12 + 1, 1)
        yield cur, nxt
        cur = nxt


def _date(v):
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    return datetime.date.fromisoformat(str(v)[:10])


class Command(BaseCommand):
    help = 'Backfill invoice notes (stktransm.comments) into the reconciliation mirror'

    def add_arguments(self, parser):
        parser.add_argument('--from', dest='date_from', default='2017-01-01')
        parser.add_argument('--to', dest='date_to', default='')

    def handle(self, *args, **o):
        from apps.finance.models import APInvoice
        from apps.finance.queries.sybase_reconciliation import DB, _rows
        d0 = datetime.date.fromisoformat(o['date_from'])
        d1 = datetime.date.fromisoformat(o['date_to']) if o['date_to'] else datetime.date.today()
        keys = {(i.branchcode, i.doccode, str(i.docnumber).split('.')[0], i.docdate): i.id
                for i in APInvoice.objects.only('id', 'branchcode', 'doccode', 'docnumber', 'docdate')}
        total = 0
        for a, b in _quarters(d0, d1):
            sql = f"""
                SELECT branchcode, doccode, docnumber, docdate, comments
                FROM   {DB}.stktransm
                WHERE  doccode IN ('10', '120') AND comments IS NOT NULL AND comments <> ''
                  AND  docdate >= '{a.month}-{a.day}-{a.year}' AND docdate < '{b.month}-{b.day}-{b.year}'
                AT ISOLATION 0
            """
            try:
                rows = _rows(sql, [], rowcount=200_000)
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f'  {a}: failed {str(exc)[:80]}'))
                continue
            if rows and '_error' in rows[0]:
                self.stdout.write(self.style.WARNING(f"  {a}: {rows[0]['_error'][:80]}"))
                continue
            upd = []
            for r in rows:
                k = (str(r['branchcode']).strip(), str(r['doccode']).strip(),
                     str(r['docnumber']).split('.')[0], _date(r['docdate']))
                iid = keys.get(k)
                if iid:
                    upd.append(APInvoice(id=iid, comments=str(r['comments'] or '').strip()[:2000]))
            APInvoice.objects.bulk_update(upd, ['comments'], batch_size=2000)
            total += len(upd)
            if upd:
                self.stdout.write(f'  {a}: {len(upd)} notes')
                self.stdout.flush()
        self.stdout.write(self.style.SUCCESS(f'DONE {total} invoice notes filled'))
