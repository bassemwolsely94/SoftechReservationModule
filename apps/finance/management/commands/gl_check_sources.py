"""python manage.py gl_check_sources --source <type|all> --from YYYY-MM-DD --to YYYY-MM-DD

Read-only check of the GL source readers: per source type x month x branch the document count and the
sum of amounts. For supplier_payments / customer_collections it also totals the same vouchers (by due
date, restricted to parties the A/P ``Payment`` mirror knows) and prints the difference to the mirror.
Only SELECTs are issued against SOFTECH (open_fetch refuses anything else); nothing is written anywhere.
"""
import collections
import importlib
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum
from django.db.models.functions import TruncMonth

from apps.finance.gl.sources import READERS
from apps.finance.queries import sybase_gl
from apps.finance.recon_models import Payment, ReconParty

for _m in ('sales', 'purchases', 'treasury', 'expenses'):
    importlib.import_module(f'apps.finance.gl.sources.{_m}')

MIRROR = {'supplier_payments': ('supplier', 'out', 'in'), 'customer_collections': ('customer', 'in', 'out')}


def _amount(doc):
    # 'value' ahead of 'net': a purchase's total is the whole invoice, its net is before VAT (P32)
    return doc.amounts.get('amount', doc.amounts.get('value', doc.amounts.get('net', doc.amounts.get('credit', Decimal(0)))))


class Command(BaseCommand):
    help = 'Read-only: counts and totals of each GL source reader per month x branch (+ A/P mirror diff).'

    def add_arguments(self, p):
        p.add_argument('--source', default='all')
        p.add_argument('--from', dest='d1', required=True)
        p.add_argument('--to', dest='d2', required=True)

    def handle(self, *a, **o):
        d1, d2 = date.fromisoformat(o['d1']), date.fromisoformat(o['d2'])
        types = sorted(READERS) if o['source'] == 'all' else [o['source']]
        for t in types:
            if t not in READERS:
                raise CommandError(f'unknown source {t}; choose from {", ".join(sorted(READERS))}')
        with sybase_gl.open_fetch() as fetch:
            for t in types:
                self.report(t, list(READERS[t](d1, d2, fetch)))

    def report(self, t, docs):
        self.stdout.write(f'== {t}: {len(docs)} docs')
        dup = [d.source_key for d in docs if d.kind == '__duplicate__']
        if dup:
            self.stdout.write(f'  !! {len(dup)} __duplicate__ keys: {", ".join(dup[:10])}')
        agg = collections.defaultdict(lambda: [0, Decimal(0)])
        for d in docs:
            if d.kind == '__duplicate__':
                continue
            sign = -1 if d.attrs.get('direction') == 'receipt' and t == 'supplier_payments' else 1
            slot = agg[(d.doc_date.strftime('%Y-%m'), d.branch_code)]
            slot[0] += 1
            slot[1] += _amount(d) * sign
        for (ym, br), (n, tot) in sorted(agg.items()):
            self.stdout.write(f'  {ym} branch {br:>4} docs {n:>6} sum {tot:>16,.2f}')
        if t in MIRROR:
            self.mirror_diff(t, docs)

    def mirror_diff(self, t, docs):
        ptype, plus, minus = MIRROR[t]
        known = set(ReconParty.objects.filter(party_type=ptype).values_list('softech_personcode', flat=True))
        mine = collections.defaultdict(Decimal)
        for d in docs:
            if d.personcode not in known or not d.attrs.get('due_date') or d.kind == '__duplicate__':
                continue
            sign = 1 if (d.attrs['direction'] == 'payment') == (plus == 'out') else -1
            mine[(d.attrs['due_date'][:7], d.branch_code)] += _amount(d) * sign
        theirs = collections.defaultdict(Decimal)
        qs = (Payment.objects.filter(party__party_type=ptype, voucher_date__gte=min((d.doc_date for d in docs), default=date.today()).replace(day=1))
              .annotate(m=TruncMonth('voucher_date')).values('m', 'branchcode', 'direction').annotate(s=Sum('amount')))
        for r in qs:
            theirs[(r['m'].strftime('%Y-%m'), r['branchcode'])] += r['s'] * (1 if r['direction'] == plus else -1)
        months = {k[0] for k in mine}
        self.stdout.write('  -- vs A/P Payment mirror (by due date, mirror-known parties)')
        for k in sorted(set(mine) | {k for k in theirs if k[0] in months}):
            diff = mine.get(k, Decimal(0)) - theirs.get(k, Decimal(0))
            self.stdout.write(f'  {k[0]} branch {k[1]:>4} gl {mine.get(k, Decimal(0)):>16,.2f} '
                              f'mirror {theirs.get(k, Decimal(0)):>16,.2f} diff {diff:>14,.2f}')
