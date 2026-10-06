"""
python manage.py measure_overstock                 # all branches: summary + top items
python manage.py measure_overstock --branch 150    # one branch
python manage.py measure_overstock --excel         # + media/reports/overstock_YYYY-MM-DD.xlsx
python manage.py measure_overstock --top 30

READ-ONLY. Measures stock sitting ABOVE the max-stock ceiling (stkbal.maxnowqty =
rate × coverage) on each branch's own server, valued at cost (catalog Item.cost_price),
plus stock on items with NO sales rate (money parked in items that don't move). Items
first stocked in the last NEW_DAYS days are marked "new" so launches aren't mistaken for
dead stock. Never writes to SOFTECH.
"""
import datetime
from collections import defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand

NEW_DAYS = 90          # stkbal.opendate within this many days → "new item"
TOL = 0.05             # 1dp tolerance


class Command(BaseCommand):
    help = 'READ-ONLY: stock above the max-stock ceiling + no-sales stock, valued at cost'

    def add_arguments(self, parser):
        parser.add_argument('--branch', action='append', default=None)
        parser.add_argument('--top', type=int, default=15)
        parser.add_argument('--excel', action='store_true')

    def handle(self, *a, **o):
        from apps.purchasing.rate_writer import _eligible_branches, resolve_store, _read_conn_for_target
        from apps.catalog.models import Item

        today = datetime.date.today()
        rows, summaries = [], []
        for b in _eligible_branches(o['branch']):            # never branch 100
            bc, st = b.softech_branch_id, resolve_store(b)
            try:
                conn = _read_conn_for_target(b, 'node')
                cur = conn.cursor()
                cur.execute("SELECT itemcode, nowqty, monthlyqty, maxnowqtymonths, maxnowqty, opendate "
                            "FROM stkbal WHERE branchcode=? AND storecode=? AND nowqty > 0", [bc, st])
                data = cur.fetchall()
                cur.close()
                conn.close()
            except Exception as exc:
                summaries.append({'branch': bc, 'error': str(exc)[:120]})
                continue
            for r in data:
                od = r[5]
                od = od.date() if hasattr(od, 'date') else od
                rows.append({
                    'branch': bc, 'itemcode': str(r[0]).strip(), 'stock': float(r[1] or 0),
                    'rate': float(r[2] or 0), 'coverage': float(r[3] or 0),
                    'max': float(r[4] or 0),
                    'age_days': (today - od).days if od else None,
                })

        catalog = {i.softech_id: (i.name or '', float(i.cost_price or 0)) for i in
                   Item.objects.filter(softech_id__in={r['itemcode'] for r in rows})
                   .only('softech_id', 'name', 'cost_price')}

        for r in rows:
            r['name'], r['cost'] = catalog.get(r['itemcode'], ('', 0.0))
            r['stock_value'] = r['stock'] * r['cost']
            r['months_of_stock'] = round(r['stock'] / r['rate'], 1) if r['rate'] > 0 else None
            r['is_new'] = r['age_days'] is not None and r['age_days'] <= NEW_DAYS
            # same excess if the ceiling were never below 1 pack (a slow item's max can be
            # 0.2 of a pack — you can't stock 0.2 of a pen, so 1 unit on the shelf is not
            # really overstock)
            r['excess_floor1'] = max(0.0, r['stock'] - max(r['max'], 1.0)) if r['max'] > 0 else 0.0
            if r['max'] > 0 and r['stock'] > r['max'] + TOL:
                r['category'] = 'above_ceiling'
                r['excess'] = r['stock'] - r['max']
            elif r['rate'] <= 0:
                r['category'] = 'no_sales_new' if r['is_new'] else 'no_sales'
                r['excess'] = r['stock']
            else:
                r['category'] = 'within'
                r['excess'] = 0.0
            r['excess_value'] = r['excess'] * r['cost']

        by = defaultdict(lambda: defaultdict(float))
        for r in rows:
            s = by[r['branch']]
            s['stock_value'] += r['stock_value']
            s['items_in_stock'] += 1
            s[f'{r["category"]}_items'] += 1
            s[f'{r["category"]}_value'] += r['excess_value']
            if r['category'] == 'above_ceiling':
                s['above_floor1_value'] += r['excess_floor1'] * r['cost']
                if r['excess_floor1'] > TOL:
                    s['above_floor1_items'] += 1
            if r['cost'] <= 0:
                s['zero_cost_items'] += 1
        for bc, s in by.items():
            summaries.append({'branch': bc, **s})

        self._print(summaries, rows, o['top'])
        if o['excel']:
            path = self._excel(summaries, rows, today)
            self.stdout.write(self.style.SUCCESS(f'\n  Excel: {path}'))

    # ── output ──────────────────────────────────────────────────────────────────
    @staticmethod
    def _egp(v):
        return f'{v:,.0f}'

    def _print(self, summaries, rows, top):
        self.stdout.write(self.style.MIGRATE_HEADING(
            '\n═══ overstock vs max-stock ceiling — branch servers, valued at cost (EGP) ═══'))
        self.stdout.write(f'  {"branch":<7}{"stock value":>14}{"above ceiling":>15}{"items":>7}'
                          f'{"no-sales (old)":>16}{"items":>7}{"no-sales (new)":>16}{"items":>7}{"no cost":>9}')
        tot = defaultdict(float)
        for s in sorted(summaries, key=lambda x: str(x['branch'])):
            if s.get('error'):
                self.stdout.write(self.style.WARNING(f'  {s["branch"]:<7} UNREACHABLE: {s["error"]}'))
                continue
            for k, v in s.items():
                if k != 'branch':
                    tot[k] += v
            self.stdout.write(
                f'  {s["branch"]:<7}{self._egp(s.get("stock_value", 0)):>14}'
                f'{self._egp(s.get("above_ceiling_value", 0)):>15}{int(s.get("above_ceiling_items", 0)):>7}'
                f'{self._egp(s.get("no_sales_value", 0)):>16}{int(s.get("no_sales_items", 0)):>7}'
                f'{self._egp(s.get("no_sales_new_value", 0)):>16}{int(s.get("no_sales_new_items", 0)):>7}'
                f'{int(s.get("zero_cost_items", 0)):>9}')
        self.stdout.write(
            f'  {"TOTAL":<7}{self._egp(tot["stock_value"]):>14}{self._egp(tot["above_ceiling_value"]):>15}'
            f'{int(tot["above_ceiling_items"]):>7}{self._egp(tot["no_sales_value"]):>16}'
            f'{int(tot["no_sales_items"]):>7}{self._egp(tot["no_sales_new_value"]):>16}'
            f'{int(tot["no_sales_new_items"]):>7}{int(tot["zero_cost_items"]):>9}')
        self.stdout.write(self.style.HTTP_INFO(
            '\n  above ceiling if the ceiling were never below 1 pack:'))
        for s in sorted(summaries, key=lambda x: str(x['branch'])):
            if not s.get('error'):
                self.stdout.write(f'    {s["branch"]:<7}{self._egp(s.get("above_floor1_value", 0)):>12} EGP'
                                  f'{int(s.get("above_floor1_items", 0)):>7} items')
        self.stdout.write(f'    {"TOTAL":<7}{self._egp(tot["above_floor1_value"]):>12} EGP'
                          f'{int(tot["above_floor1_items"]):>7} items')

        over = sorted((r for r in rows if r['category'] == 'above_ceiling'),
                      key=lambda r: -r['excess_value'])[:top]
        self.stdout.write(self.style.HTTP_INFO(f'\n  top {top} above ceiling (by excess value):'))
        for r in over:
            self.stdout.write(
                f'    br{r["branch"]} {r["itemcode"]:<8} {r["name"][:30]:<30} stock {r["stock"]:>8.1f}  '
                f'max {r["max"]:>7.1f}  excess {r["excess"]:>8.1f}  ≈{r["months_of_stock"]} mo  '
                f'{self._egp(r["excess_value"]):>9} EGP')
        dead = sorted((r for r in rows if r['category'] == 'no_sales'),
                      key=lambda r: -r['excess_value'])[:top]
        self.stdout.write(self.style.HTTP_INFO(f'\n  top {top} no-sales stock, older than {NEW_DAYS} days (by value):'))
        for r in dead:
            self.stdout.write(
                f'    br{r["branch"]} {r["itemcode"]:<8} {r["name"][:30]:<30} stock {r["stock"]:>8.1f}  '
                f'age {r["age_days"]}d  {self._egp(r["excess_value"]):>9} EGP')

    def _excel(self, summaries, rows, today):
        import os
        from openpyxl import Workbook
        from openpyxl.styles import Font
        out_dir = os.path.join(settings.MEDIA_ROOT, 'reports')
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f'overstock_{today:%Y-%m-%d}.xlsx')
        wb = Workbook()
        ws = wb.active
        ws.title = 'ملخص'
        ws.sheet_view.rightToLeft = True
        head = ['الفرع', 'قيمة المخزون', 'فوق الحد الأقصى (قيمة)', 'أصناف',
                'فوق الحد لو الحد ≥ عبوة (قيمة)', 'أصناف', 'بلا مبيعات قديم (قيمة)',
                'أصناف', 'بلا مبيعات جديد (قيمة)', 'أصناف', 'أصناف بلا تكلفة']
        ws.append(head)
        for s in sorted(summaries, key=lambda x: str(x['branch'])):
            if s.get('error'):
                ws.append([s['branch'], 'غير متاح'])
                continue
            ws.append([s['branch'], round(s.get('stock_value', 0)), round(s.get('above_ceiling_value', 0)),
                       int(s.get('above_ceiling_items', 0)), round(s.get('above_floor1_value', 0)),
                       int(s.get('above_floor1_items', 0)), round(s.get('no_sales_value', 0)),
                       int(s.get('no_sales_items', 0)), round(s.get('no_sales_new_value', 0)),
                       int(s.get('no_sales_new_items', 0)), int(s.get('zero_cost_items', 0))])
        ws2 = wb.create_sheet('الأصناف')
        ws2.sheet_view.rightToLeft = True
        labels = {'above_ceiling': 'فوق الحد الأقصى', 'no_sales': 'بلا مبيعات', 'no_sales_new': 'بلا مبيعات (جديد)'}
        ws2.append(['الفرع', 'الكود', 'الصنف', 'التصنيف', 'الرصيد', 'معدل الاستهلاك', 'التغطية (شهر)',
                    'الحد الأقصى', 'الزيادة', 'شهور مخزون', 'التكلفة', 'قيمة الزيادة', 'عمر الصنف (يوم)',
                    'الزيادة لو الحد ≥ عبوة', 'قيمتها'])
        for r in sorted((r for r in rows if r['category'] != 'within'), key=lambda r: -r['excess_value']):
            f1 = r['excess_floor1'] if r['category'] == 'above_ceiling' else None
            ws2.append([r['branch'], r['itemcode'], r['name'], labels[r['category']], round(r['stock'], 1),
                        r['rate'], r['coverage'], r['max'], round(r['excess'], 1), r['months_of_stock'],
                        r['cost'], round(r['excess_value']), r['age_days'],
                        round(f1, 1) if f1 is not None else None,
                        round(f1 * r['cost']) if f1 is not None else None])
        for w in (ws, ws2):
            for c in w[1]:
                c.font = Font(bold=True)
        wb.save(path)
        return path
