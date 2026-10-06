"""
foc_audit  (doc 18)
===================
Line-by-line audit of FREE-OF-CHARGE (بونص) goods so the narrative report's «بضائع مجانية»
figure can be reconciled and any inflation found.

HOW FOC IS CALCULATED
---------------------
SOFTECH books a bonus deal as a paid line + a separate 100%-discount (free) line for the same
item. The procurement engine (apps/procurement/engine.py) collapses them into ONE PurchaseLine:
  • raw_qty / raw_value / net_value  → the PAID units and their value (at cost).
  • bonus_qty                        → the FREE units received (the بونص).
  • cost_price                       → cost per unit.
  • is_foc = True                    ⟺ bonus_qty > 0.
The TRUE value of the free goods (at purchasing cost) is therefore:
      FOC value = Σ cost_price × bonus_qty          (NOT cost_price × raw_qty)
      FOC units = Σ bonus_qty
Valuing at raw_qty (the paid units) inflates it — that was the bug this audit was written for.
Retail view (what the free units would sell for) = Σ public_price × bonus_qty.

USAGE
  python manage.py foc_audit --branch 100 --start 2026-08-01 --end 2026-08-28
  python manage.py foc_audit --branch 100 --month 2026-08          # 1st→end of month
  python manage.py foc_audit --start 2026-08-01 --end 2026-08-28 --by supplier --top 20
"""
import calendar
from datetime import datetime, date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum, Count, F, ExpressionWrapper, DecimalField


def _f(n):
    return f'{float(n or 0):,.0f}'


class Command(BaseCommand):
    help = 'Audit free-of-charge (بونص) goods value/qty for a branch + period (reconcile «بضائع مجانية»)'

    def add_arguments(self, parser):
        parser.add_argument('--branch', default='100', help="SOFTECH branch code (default 100 = HQ); 'all' for chain")
        parser.add_argument('--start', help='YYYY-MM-DD')
        parser.add_argument('--end', help='YYYY-MM-DD')
        parser.add_argument('--month', help='YYYY-MM (whole month; overrides start/end)')
        parser.add_argument('--by', choices=['item', 'supplier'], default='item')
        parser.add_argument('--top', type=int, default=25)

    def handle(self, *a, **o):
        from apps.procurement.models import PurchaseLine, SupplierProfile
        from apps.catalog.models import Item
        if o.get('month'):
            y, m = map(int, o['month'].split('-'))
            start = date(y, m, 1); end = date(y, m, calendar.monthrange(y, m)[1])
        elif o.get('start') and o.get('end'):
            start = datetime.strptime(o['start'], '%Y-%m-%d').date()
            end = datetime.strptime(o['end'], '%Y-%m-%d').date()
        else:
            raise CommandError('Provide --month YYYY-MM or --start and --end')

        DF = DecimalField(max_digits=22, decimal_places=4)
        free_cost = ExpressionWrapper(F('cost_price') * F('bonus_qty'), output_field=DF)   # CORRECT
        paid_cost = ExpressionWrapper(F('cost_price') * F('raw_qty'), output_field=DF)      # OLD (wrong)
        free_ret = ExpressionWrapper(F('public_price') * F('bonus_qty'), output_field=DF)

        qs = PurchaseLine.objects.filter(doc_date__gte=start, doc_date__lte=end,
                                         is_return=False, is_foc=True, bonus_qty__gt=0)
        if o['branch'] != 'all':
            qs = qs.filter(branch_code=o['branch'])

        agg = qs.aggregate(n=Count('id'), free_v=Sum(free_cost), free_q=Sum('bonus_qty'),
                           paid_v=Sum(paid_cost), paid_q=Sum('raw_qty'), ret=Sum(free_ret))
        scope = 'ALL branches' if o['branch'] == 'all' else f'branch {o["branch"]}'
        w = self.stdout.write
        w(self.style.MIGRATE_HEADING(f'FOC audit — {scope} — {start} → {end}  ({agg["n"] or 0} bonus lines)'))
        w('')
        w(f'  ✅ CORRECT  FOC value (cost × FREE qty) : {_f(agg["free_v"]):>14} EGP   free units: {_f(agg["free_q"])}')
        w(f'     …at retail (public × FREE qty)       : {_f(agg["ret"]):>14} EGP')
        w(self.style.WARNING(
          f'  ❌ OLD/WRONG value (cost × PAID qty)     : {_f(agg["paid_v"]):>14} EGP   paid units: {_f(agg["paid_q"])}'))
        infl = (Decimal(str(agg['paid_v'] or 0)) / Decimal(str(agg['free_v'] or 1)))
        w(f'     inflation factor (old ÷ correct)     : {float(infl):>14.1f}×')
        w('')

        w(self.style.MIGRATE_HEADING(f'Top {o["top"]} by FOC value ({o["by"]}):'))
        if o['by'] == 'supplier':
            rows = qs.values('supplier_code').annotate(v=Sum(free_cost), q=Sum('bonus_qty')).order_by('-v')[:o['top']]
            names = dict(SupplierProfile.objects.filter(
                supplier_code__in=[r['supplier_code'] for r in rows]).values_list('supplier_code', 'supplier_name'))
            for r in rows:
                nm = names.get(r['supplier_code']) or r['supplier_code']
                w(f'  {str(nm)[:38]:<38}  free_value={_f(r["v"]):>12}  free_qty={_f(r["q"]):>8}')
        else:
            rows = qs.values('item_code').annotate(
                v=Sum(free_cost), fq=Sum('bonus_qty'), pq=Sum('raw_qty')).order_by('-v')[:o['top']]
            names = dict(Item.objects.filter(
                softech_id__in=[str(r['item_code']) for r in rows]).values_list('softech_id', 'name'))
            w(f'  {"item":<34} {"free_val":>10} {"free_qty":>9} {"paid_qty":>9}')
            for r in rows:
                nm = names.get(str(r['item_code'])) or r['item_code']
                w(f'  {str(nm)[:34]:<34} {_f(r["v"]):>10} {_f(r["fq"]):>9} {_f(r["pq"]):>9}')
