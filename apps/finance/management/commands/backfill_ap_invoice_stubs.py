"""
python manage.py backfill_ap_invoice_stubs [--batch 40] [--limit N]

Fill the STUB invoices (source_hash = '') that the allocation ingest creates when a
SOFTECH chequestrans row points at an invoice outside the synced date range (mostly
2022). Stubs carry doc_value = 0, so their native allocations look like over-payments
and returns look worthless. Reads each header from SOFTECH stktransm by its 4-part
key (small OR-batches) and upserts it through the normal ingest path. Read-only on
SOFTECH; idempotent.
"""


from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Backfill zero-value stub invoices from SOFTECH stktransm'

    def add_arguments(self, parser):
        parser.add_argument('--batch', type=int, default=40)
        parser.add_argument('--limit', type=int, default=0)

    def handle(self, *args, **o):
        from apps.finance.models import APInvoice
        from apps.finance import recon_ingest as I
        from apps.finance.queries.sybase_reconciliation import DB, _rows

        stubs = list(APInvoice.objects.filter(source_hash='').select_related('party')
                     .order_by('docdate'))
        if o['limit']:
            stubs = stubs[:o['limit']]
        self.stdout.write(f'stub invoices: {len(stubs)}')
        filled = missing = 0
        for i in range(0, len(stubs), o['batch']):
            chunk = stubs[i:i + o['batch']]
            conds, params = [], []
            for s in chunk:
                # inline literals (the jConnect driver rejects datetime parameters);
                # every value comes from our own mirror and is digits-only
                br, dc = str(s.branchcode).strip(), str(s.doccode).strip()
                dn = int(str(s.docnumber).split('.')[0])
                if not (br.isdigit() and dc.isdigit()):
                    continue
                d = s.docdate
                conds.append(f"(sm.branchcode = '{br}' AND sm.doccode = '{dc}' AND sm.docnumber = {dn} "
                             f"AND sm.docdate = '{d.month}-{d.day}-{d.year} 0:0:0.000')")
            if not conds:
                continue
            sql = f"""
                SELECT sm.branchcode, sm.doccode, sm.docnumber, sm.docdate,
                       sm.docnumber2, sm.cust_branch_code, sm.docvalue, sm.docvaluepay,
                       sm.fatcurrentstatus, sm.docpaydue, sm.usercode,
                       sm.personnewbal, sm.trans_time, sm.comments
                FROM   {DB}.stktransm sm
                WHERE  {' OR '.join(conds)}
            """
            try:
                rows = _rows(sql, params, rowcount=len(chunk) * 2)
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f'  batch {i} failed: {str(exc)[:80]}'))
                continue
            if rows and '_error' in rows[0]:
                self.stdout.write(self.style.WARNING(f"  batch {i} error: {rows[0]['_error'][:80]}"))
                continue
            got = 0
            for r in rows:
                party = next((s.party for s in chunk
                              if s.branchcode == str(r.get('branchcode')).strip()
                              and str(s.docnumber).split('.')[0] == str(r.get('docnumber')).split('.')[0]), None)
                if I.upsert_invoice(r, party=party):
                    got += 1
            filled += got
            missing += len(chunk) - got
            if (i // o['batch']) % 10 == 0:
                self.stdout.write(f'  … {i + len(chunk)}/{len(stubs)} filled {filled}')
                self.stdout.flush()
        self.stdout.write(self.style.SUCCESS(f'DONE filled {filled}, not found {missing}'))
