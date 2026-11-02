"""
apps/tests/test_newqty_check.py

P-30 step 0 (docs/product-review/06_SPEC_P-30_measured_availability.md): before anything is built on the stock
ledger's `newqty` ("stock after this line"), check what it means — read-only, PostgreSQL mirror only:
  1 store mix · 2 chain consistency (previous newqty ± transqty = this newqty), direction per doccode inferred
  3 end state (last newqty vs ItemStock) · 4 strips / negatives · 5 a 20-case sheet for a person to check in SOFTECH
Pass rule (proposed): ≥ 19 of 20 sheet cases match and checks 2–3 ≥ 95 %.
"""
import datetime as dt
import os
import tempfile
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.tests.factories import make_branch

D = Decimal


def _t(day, hour=10, minute=0):
    return timezone.make_aware(dt.datetime(2026, 10, day, hour, minute))


class Base(TestCase):

    def setUp(self):
        from apps.catalog.models import Item
        self.branch = make_branch('فرع 160', '160')
        self.items = {c: Item.objects.create(softech_id=c, name=f'صنف {c}') for c in ('A', 'B', 'C', 'S')}
        self.no = 0

    def line(self, item, day, doccode, transqty, newqty, store='160', bonus='0', minute=0):
        from apps.stock_audit.models import StockLedgerLine
        self.no += 1
        return StockLedgerLine.objects.create(
            branchcode='160', doccode=doccode, docnumber=self.no, docdate=dt.date(2026, 10, day),
            trans_time=_t(day, minute=minute), storecode=store, itemcode=item, item=self.items[item],
            transqty=D(transqty), newqty=D(newqty), bonusqty=D(bonus))

    def stock(self, item, qty, store='160'):
        from apps.catalog.models import ItemStock
        return ItemStock.objects.create(item=self.items[item], branch=self.branch, softech_store_code=store,
                                        quantity_on_hand=D(qty))


class ChecksTests(Base):

    def setUp(self):
        super().setUp()
        self.line('A', 1, '15', '10', '10')        # first line of the chain: not a pair
        self.line('A', 2, '115', '2', '8')         # out
        self.line('A', 3, '15', '5', '13')         # in
        self.line('A', 4, '115', '1', '13')        # break (should be 12)
        self.line('B', 2, '10', '4', '5', bonus='1')   # first
        self.line('B', 3, '10', '3', '9', bonus='1')   # in with bonus: 5 + 3 + 1
        self.line('C', 5, '115', '0.5', '-0.5')    # strip sale to below zero
        self.line('C', 6, '115', '1', '1', store='161')   # another store of the branch

    def test_store_mix(self):
        from apps.stock_audit.newqty_check import load_lines, store_mix
        m = store_mix(load_lines('160', dt.date(2026, 9, 1)), '160')
        self.assertEqual(m['stores'], {'160': 7, '161': 1})
        self.assertEqual(m['other_share_pct'], D('12.5'))

    def test_chain_direction_per_doccode_and_breaks(self):
        from apps.stock_audit.newqty_check import chain_check, load_lines
        c = chain_check(load_lines('160', dt.date(2026, 9, 1)))
        self.assertEqual((c['pairs'], c['consistent']), (4, 3))
        self.assertEqual(c['pct'], D('75.0'))
        self.assertEqual(c['by_doccode']['115'], {'out': 1, 'break': 1})
        self.assertEqual(c['by_doccode']['15'], {'in': 1})
        self.assertEqual(c['by_doccode']['10'], {'in_bonus': 1})
        self.assertEqual(c['breaks'][0]['itemcode'], 'A')

    def test_units_and_signs(self):
        from apps.stock_audit.newqty_check import load_lines, units_signs
        u = units_signs(load_lines('160', dt.date(2026, 9, 1)))
        self.assertEqual((u['lines'], u['fractional'], u['negative'], u['zero_or_less']), (8, 1, 1, 1))

    def test_end_state_against_item_stock(self):
        from apps.stock_audit.newqty_check import end_state, load_lines
        from apps.catalog.models import ItemStock
        self.stock('A', '13')                       # equal
        self.stock('B', '8')                        # differs from 9
        late = self.stock('C', '0')                 # synced before C's last line → not compared
        ItemStock.objects.filter(pk=late.pk).update(last_synced=_t(5, 9))
        e = end_state('160', load_lines('160', dt.date(2026, 9, 1)))
        self.assertEqual((e['compared'], e['equal'], e['pct']), (2, 1, D('50.0')))
        self.assertEqual(e['mismatches'][0]['itemcode'], 'B')


class SampleTests(Base):

    def setUp(self):
        super().setUp()
        for i in range(30):                         # 15 lines that reach zero, 15 that do not
            self.line('S', 1 + i % 28, '115', '1', '0' if i % 2 else str(i + 1), minute=i)

    def test_twenty_cases_half_at_zero_and_stable(self):
        from apps.stock_audit.newqty_check import load_lines, pick_samples
        lines = load_lines('160', dt.date(2026, 9, 1))
        s = pick_samples(lines, 20)
        self.assertEqual(len(s), 20)
        self.assertEqual(sum(1 for r in s if r['newqty'] <= 0), 10)
        self.assertEqual(s, pick_samples(lines, 20))

    def test_score_and_verdict(self):
        from apps.stock_audit.newqty_check import score_samples, verdict
        rows = [{'newqty': D(i), 'seen': D(i)} for i in range(19)] + [{'newqty': D('5'), 'seen': D('4')}]
        self.assertEqual(score_samples(rows), {'filled': 20, 'matches': 19})
        self.assertEqual(verdict(D('96'), D('95'), {'filled': 20, 'matches': 19})['result'], 'pass')
        self.assertEqual(verdict(D('96'), D('95'), {'filled': 20, 'matches': 18})['result'], 'fail')
        self.assertEqual(verdict(D('94.9'), D('99'), {'filled': 20, 'matches': 20})['result'], 'fail')
        self.assertEqual(verdict(D('99'), D('99'), None)['result'], 'awaiting_sheet')


class CommandTests(Base):

    def test_writes_a_report_and_scores_it_without_db_writes(self):
        import openpyxl
        from apps.stock_audit.models import StockLedgerLine
        for i in range(24):
            self.line('S', 1 + i, '115', '1', '0' if i % 2 else '3')
        before = StockLedgerLine.objects.count()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'newqty_160.xlsx')
            call_command('verify_ledger_newqty', branch='160', days=90, out=path, today='2026-10-31', verbosity=0)
            wb = openpyxl.load_workbook(path)
            self.assertIn('عينة للتحقق', wb.sheetnames)
            ws = wb['عينة للتحقق']
            head = [c.value for c in ws[1]]
            times = [ws.cell(row=r, column=head.index('الوقت') + 1).value for r in range(2, ws.max_row + 1)]
            self.assertTrue(all(x.hour == 10 for x in times))          # local time, as the item card shows it
            seen_col = head.index('الرصيد في كارت الصنف') + 1
            new_col = head.index('الرصيد بعد السطر (المرآة)') + 1
            for r in range(2, ws.max_row + 1):          # the specialist copies what SOFTECH shows
                ws.cell(row=r, column=seen_col, value=ws.cell(row=r, column=new_col).value)
            wb.save(path)
            from io import StringIO
            out = StringIO()
            call_command('verify_ledger_newqty', branch='160', days=90, score=path, today='2026-10-31', stdout=out)
            self.assertIn('20/20', out.getvalue())
        self.assertEqual(StockLedgerLine.objects.count(), before)
