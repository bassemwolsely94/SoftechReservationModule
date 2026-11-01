"""
python manage.py probe_contract_receivables [--months 12] [--personcodes 4227,4288] [--out-dir logs] [--list-only]

P-41 step 0: a SELECT-only pass over every contract account (sales on channel 10 in the last year, from our sales
history) — or the given --personcodes. Per contract: sales and returns, receipts by type, value-weighted collection
days and max, how much of the sales SOFTECH's receipt links cover, receipts not linked («على الحساب»), the account
type and the SOFTECH balance. Prints a table and writes a CSV. Writes nothing to SOFTECH or to our database.
Run it off-hours: three queries per contract, each filtered to that contract's account.
--list-only prints the contract list without reading SOFTECH.
"""
import csv
import datetime as dt
import os

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.finance import receivables_probe as P


class Command(BaseCommand):
    help = 'P-41 step 0: read-only collection-days / link-coverage check across the contract accounts.'

    def add_arguments(self, parser):
        parser.add_argument('--months', type=int, default=12)
        parser.add_argument('--personcodes', default='', help='Comma-separated; default = contract accounts (channel 10).')
        parser.add_argument('--out-dir', default=os.path.join(str(settings.BASE_DIR), 'logs'))
        parser.add_argument('--list-only', action='store_true', help='Print the contracts; read nothing from SOFTECH.')

    def handle(self, *args, **o):
        codes = [c.strip() for c in o['personcodes'].split(',') if c.strip()] or P.contract_personcodes()
        self.stdout.write(f'{len(codes)} contract account(s): {", ".join(codes)}')
        if o['list_only'] or not codes:
            return
        today = dt.date.today()
        date_from = (today - dt.timedelta(days=round(o['months'] * 30.44))).isoformat()
        date_to = today.isoformat()
        balances = {}
        rows = P.get_party_balances(codes)
        if rows and '_error' not in rows[0]:
            balances = {str(r['personcode']).strip(): r for r in rows}
        out = []
        for pc in codes:
            s, err = P.probe(pc, date_from, date_to)
            b = balances.get(pc, {})
            base = {'personcode': pc, 'name': b.get('personname', ''), 'ptcode': b.get('ptcode', ''),
                    'ptclassifcode': b.get('ptclassifcode', ''), 'softech_balance': b.get('softech_balance', '')}
            if s is None:
                out.append({**base, 'error': err})
                self.stdout.write(self.style.WARNING(f'{pc}: {err}'))
                continue
            types = s['receipts_by_type']
            out.append({**base, 'invoices': s['invoice_count'], 'invoice_value': s['invoice_value'],
                        'returns': s['return_count'], 'return_value': s['return_value'],
                        'receipts_10': types.get('10', {}).get('count', 0),
                        'receipts_10_value': types.get('10', {}).get('value', 0),
                        'receipts_other': sum(v['count'] for k, v in types.items() if k != '10'),
                        'receipt_types': ','.join(sorted(types)),
                        'collection_days': s['collection_days'] if s['collection_days'] is not None else '',
                        'collection_days_max': s['collection_days_max'] if s['collection_days_max'] is not None else '',
                        'link_coverage_pct': s['allocation_coverage_pct'], 'on_account': s['on_account'],
                        'reliable': 'yes' if s['reliable'] else 'no', 'error': ''})
            self.stdout.write(f"{pc:>6} {base['name'][:28]:28} sales {s['invoice_count']:>5} "
                              f"{float(s['invoice_value']):>12,.0f}  days {s['collection_days'] or '—':>5} "
                              f"(max {s['collection_days_max'] or '—'})  links {s['allocation_coverage_pct']}%  "
                              f"on account {float(s['on_account']):,.0f}  {'reliable' if s['reliable'] else 'CHECK'}")
        os.makedirs(o['out_dir'], exist_ok=True)
        path = os.path.join(o['out_dir'], f'contract_receivables_probe_{today.isoformat()}.csv')
        fields = ['personcode', 'name', 'ptcode', 'ptclassifcode', 'softech_balance', 'invoices', 'invoice_value',
                  'returns', 'return_value', 'receipts_10', 'receipts_10_value', 'receipts_other', 'receipt_types',
                  'collection_days', 'collection_days_max', 'link_coverage_pct', 'on_account', 'reliable', 'error']
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in out:
                w.writerow({k: r.get(k, '') for k in fields})
        self.stdout.write(self.style.SUCCESS(f'Written {path} ({len(out)} contracts, {date_from} → {date_to}).'))
