"""
relink_purchase_customers
=========================
Re-point every synced invoice (PurchaseHistory) at its real buyer — the invoice PIC
(softech_phcode → Customer.softech_pic), or, with no PIC, the placeholder of its SOFTECH
sales account — and store the account code (softech_personcode). Fixes the links made by
the old personcode → Customer.softech_id match (random people; 2026-10-28).

Reads stktrans (DISTINCT document → personcode, week by week) from SOFTECH — READ-ONLY.
Writes only PurchaseHistory.customer / softech_personcode (+ placeholder Customers on --apply).

Usage:
  python manage.py relink_purchase_customers                      # dry run, whole history
  python manage.py relink_purchase_customers --start 2026-01-01   # dry run from a date
  python manage.py relink_purchase_customers --apply              # write + SyncRun record

After --apply re-run: segment_customers, then the health / chronic engines.
"""
import datetime as dt
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

Q_DOC_ACCOUNTS = """
    SELECT DISTINCT branchcode, doccode, docnumber, docdate, personcode
    FROM SOFTECHDB9.dbo.stktrans
    WHERE docdate >= ? AND docdate < ?
      AND doccode IN ('115', '30')
      AND personcode IS NOT NULL AND personcode != ''
"""


def _inv_id(branchcode, doccode, docnumber, docdate):
    """Same key sync_sales builds: '{branch}-{doccode}-{int docnumber}-{YYYYMMDD}'."""
    d = docdate.date() if isinstance(docdate, dt.datetime) else docdate
    if isinstance(d, str):
        d = dt.date.fromisoformat(d[:10])
    return f'{str(branchcode).strip()}-{str(doccode).strip()}-{int(float(str(docnumber)))}-{d:%Y%m%d}'


class Command(BaseCommand):
    help = 'Re-link PurchaseHistory to the PIC customer / account placeholder (dry run unless --apply).'

    def add_arguments(self, parser):
        parser.add_argument('--start', help='First docdate YYYY-MM-DD (default: oldest invoice)')
        parser.add_argument('--end', help='Exclusive end docdate YYYY-MM-DD (default: tomorrow)')
        parser.add_argument('--chunk-days', type=int, default=7)
        parser.add_argument('--apply', action='store_true', help='Write the changes (default: dry run)')

    def handle(self, *args, **o):
        from config.sybase import get_sybase_connection
        from apps.customers.account_link import CustomerLinker
        from apps.customers.models import PurchaseHistory
        from apps.sync.models import SyncRun, SyncLog

        try:
            start = dt.date.fromisoformat(o['start']) if o.get('start') else None
            end = dt.date.fromisoformat(o['end']) if o.get('end') else timezone.localdate() + dt.timedelta(days=1)
        except ValueError:
            raise CommandError('Dates must be YYYY-MM-DD')
        if start is None:
            first = PurchaseHistory.objects.order_by('invoice_date').values_list('invoice_date', flat=True).first()
            if first is None:
                self.stdout.write('No invoices.')
                return
            start = timezone.localtime(first).date()
        apply = o['apply']

        conn = get_sybase_connection()
        linker = CustomerLinker(conn)
        pic_owner = {v: k for k, v in linker.by_pic.items()}
        run = SyncRun.objects.create(status='running') if apply else None
        stats = Counter()
        to_account = Counter()
        samples = []
        try:
            day = start
            while day < end:
                nxt = min(day + dt.timedelta(days=o['chunk_days']), end)
                cur = conn.cursor()
                cur.execute(Q_DOC_ACCOUNTS, [f'{day:%Y%m%d}', f'{nxt:%Y%m%d}'], timeout=300)
                account_of = {}
                for bc, dc, dn, dd, pc in cur.fetchall():
                    try:
                        account_of.setdefault(_inv_id(bc, dc, dn, dd), str(pc).strip())
                    except (TypeError, ValueError):
                        continue
                if apply:
                    linker.prepare(set(account_of.values()))
                changed = []
                keys = list(account_of)
                for i in range(0, len(keys), 2000):
                    for ph in (PurchaseHistory.objects.filter(softech_invoice_id__in=keys[i:i + 2000])
                               .only('id', 'softech_invoice_id', 'customer_id', 'softech_phcode',
                                     'softech_personcode', 'sales_channel')):
                        pc = account_of[ph.softech_invoice_id]
                        pic = (ph.softech_phcode or '').strip()
                        stats['invoices'] += 1
                        if pic and pic in linker.by_pic:
                            target, kind = linker.by_pic[pic], 'pic'
                        else:
                            target, kind = (linker.by_account.get(pc) if apply else None), 'account'
                        if kind == 'pic' and ph.customer_id == target and ph.softech_personcode == pc:
                            stats['already_correct'] += 1
                            continue
                        stats[f'to_{kind}'] += 1
                        if kind == 'account':
                            to_account[pc] += 1
                        if len(samples) < 12:
                            samples.append((ph.softech_invoice_id, ph.sales_channel,
                                            pic_owner.get(ph.customer_id, f'#{ph.customer_id}'),
                                            pic if kind == 'pic' else f'ACCT-{pc}'))
                        if apply and target:
                            ph.customer_id, ph.softech_personcode = target, pc
                            changed.append(ph)
                if changed:
                    PurchaseHistory.objects.bulk_update(changed, ['customer', 'softech_personcode'], batch_size=2000)
                    stats['written'] += len(changed)
                self.stdout.write(f'  {day} → {nxt}: docs {len(account_of):,} | running {dict(stats)}')
                day = nxt
            stats['not_in_softech_window'] = (PurchaseHistory.objects.filter(
                invoice_date__date__gte=start, invoice_date__date__lt=end).count() - stats['invoices'])
        except Exception as exc:
            if run:
                run.status, run.error_message = 'failed', str(exc)[:500]
            raise
        else:
            if run:
                run.status, run.records_synced = 'success', stats['written']
        finally:
            if run:
                run.completed_at = timezone.now()
                run.progress = {'job': 'relink_purchase_customers', 'start': str(start), 'end': str(end),
                                'stats': dict(stats), 'top_accounts': to_account.most_common(15)}
                run.save()
                SyncLog.objects.create(sync_run=run, table_name='purchase_relink',
                                       records_processed=stats['written'])
            conn.close()

        self.stdout.write(self.style.SUCCESS(f"{'APPLIED' if apply else 'DRY RUN'} {start} → {end}: {dict(stats)}"))
        self.stdout.write(f'Top accounts receiving no-PIC invoices: {to_account.most_common(10)}')
        for s in samples:
            self.stdout.write(f'  {s[0]} ch {s[1]}: {s[2]} → {s[3]}')
