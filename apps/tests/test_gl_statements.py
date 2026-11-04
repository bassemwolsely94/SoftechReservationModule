"""Trading account, P&L, financial position, branch P&L and comparison (finance-gl Task 7)."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from apps.branches.models import Branch
from apps.finance.gl.ledger import approve, save_draft
from apps.finance.gl.statements import (
    branch_pl, comparison, financial_position, trading_and_pl,
)
from apps.finance.models import GLAccount, GLAccountGroup, LedgerEntry, LedgerLine
from apps.users.models import StaffProfile

D = datetime.date
Z = Decimal('0')
Y0, Y1 = D(2026, 1, 1), D(2026, 12, 31)


def _d(v):
    return Decimal(str(v))


# code -> (group name, section, statement_line)
ACCOUNTS = {
    '1201': ('اصول ثابته', 'balance_sheet', 'fixed_assets'),
    '1251': ('مجمع الإهلاك', 'balance_sheet', 'accumulated_depreciation'),
    '1301': ('النقديه بالصندوق', 'balance_sheet', 'cash'),
    '1306': ('النقديه بالبنوك', 'balance_sheet', 'cash'),
    '1307': ('النقديه بالبنوك', 'balance_sheet', 'cash'),
    '1341': ('المقبوضات التجاريه', 'balance_sheet', 'receivables'),
    '1351': ('المقبوضات غير التجاريه', 'balance_sheet', 'other_debtors'),
    '1353': ('المقبوضات غير التجاريه', 'balance_sheet', 'deposits'),
    '1390': ('بضاعة آخر المدة', 'balance_sheet', 'inventory'),
    '2341': ('المدفوعات التجاريه', 'balance_sheet', 'suppliers'),
    '2343': ('المدفوعات التجاريه', 'balance_sheet', 'notes_payable'),
    '2351': ('المدفوعات الغير تجاريه', 'balance_sheet', 'creditors'),
    '2400': ('حقوق الملكيه', 'balance_sheet', 'capital'),
    '2409': ('حقوق الملكيه', 'balance_sheet', 'retained'),
    '2501': ('جارى الشركاء', 'balance_sheet', 'partners'),
    '6001': ('المبيعات', 'trading', 'net_sales'),
    '6018': ('المبيعات', 'trading', 'net_sales'),
    '5100': ('تكلفة المبيعات', 'trading', 'net_purchases'),
    '5301': ('محزون أول المده', 'trading', 'opening_stock'),
    '5302': ('مخزون آخر المدة', 'trading', 'closing_stock'),
    '7001': ('ايرادات', 'pl', 'other_revenue'),
    '7101': ('ارباح و خسائر راسمالية', 'pl', 'capital_gains'),
    '8001': ('المصروفات العموميه', 'pl', 'general_expenses'),
    '8101': ('مصروفات بيع وتوزيع', 'pl', 'selling_expenses'),
    '8201': ('مصروفات التشغيل', 'pl', 'operating_expenses'),
    '8301': ('المصروفات التمويلية', 'pl', 'financing_expenses'),
    '8401': ('الاهلاكات', 'pl', 'depreciation'),
}


class StatementsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        u = User.objects.create_user(username='gl_stmt_u', password='x')
        cls.staff, _ = StaffProfile.objects.get_or_create(user=u)
        groups = {}
        for code, (gname, section, line) in ACCOUNTS.items():
            if gname not in groups:
                groups[gname] = GLAccountGroup.objects.create(name=gname, section=section,
                                                              order=len(groups))
            GLAccount.objects.create(code=code, name=f'acc {code}', group=groups[gname],
                                     nature='debit', account_type='asset', statement_line=line)
        cls.hq = Branch.objects.create(softech_branch_id='971', name='HQ', kind=Branch.KIND_HQ)
        cls.b1 = Branch.objects.create(softech_branch_id='972', name='B1')
        cls.b2 = Branch.objects.create(softech_branch_id='973', name='B2')
        cls.b3 = Branch.objects.create(softech_branch_id='974', name='B3')

    def _entry(self, day, lines):
        """lines: (code, signed amount [+debit / -credit], branch or None)."""
        e = save_draft(user=self.staff, entry_date=day, description='t', lines=[
            {'account_code': c, 'debit': _d(a) if a > 0 else Z, 'credit': _d(-a) if a < 0 else Z,
             'branch_id': b.id if b else None} for c, a, b in lines])
        return approve(e.id, user=self.staff)

    def _year(self, day=D(2026, 6, 30), branch=None):
        """A full year: opening stock 100, purchases 800, sales 1000 (returns 50), closing 150."""
        b = branch
        self._entry(D(2026, 1, 1), [('5301', 100, None), ('2400', -100, None)])
        self._entry(day, [('5100', 800, b), ('2341', -800, None)])
        self._entry(day, [('1301', 1000, b), ('6001', -1000, b)])
        self._entry(day, [('6018', 50, b), ('1301', -50, b)])
        self._entry(day, [('1301', 30, b), ('7001', -30, b)])
        self._entry(day, [('1301', 5, b), ('7101', -5, b)])
        self._entry(day, [('8001', 40, b), ('8101', 10, b), ('8201', 20, b), ('8301', 5, b),
                          ('8401', 15, b), ('1301', -90, b)])
        self._entry(Y1, [('1390', 150, None), ('5302', -150, None)])

    # ── trading + P&L ────────────────────────────────────────────────────────

    def test_gross_and_net_profit_formula(self):
        self._year()
        r = trading_and_pl(Y0, Y1)
        self.assertEqual(r['net_sales'], _d(950))
        self.assertEqual(r['opening_stock'], _d(100))
        self.assertEqual(r['net_purchases'], _d(800))
        self.assertEqual(r['closing_stock'], _d(150))
        self.assertEqual(r['cost_of_sales'], _d(750))
        self.assertEqual(r['gross_profit'], _d(200))  # 950 - (100 + 800 - 150)
        self.assertEqual(r['other_revenue'], _d(30))
        self.assertEqual(r['capital_gains'], _d(5))
        self.assertEqual(r['total_expenses'], _d(90))
        self.assertEqual(r['net_profit'], _d(145))  # 200 + 30 + 5 - 90
        self.assertEqual(r['gross_margin'], _d('0.210526'))
        self.assertEqual(r['net_margin'], _d('0.152632'))
        self.assertEqual(r['expense_ratio'], _d('0.078947'))  # (90 - 15) / 950
        self.assertEqual(r['monthly_avg_sales'], _d('79.17'))  # 950 / 12

    def test_closing_stock_read_from_5302(self):
        self._year()
        self._entry(D(2026, 12, 31), [('1390', 25, None), ('5302', -25, None)])
        r = trading_and_pl(Y0, Y1)
        self.assertEqual(r['closing_stock'], _d(175))
        self.assertEqual(r['gross_profit'], _d(225))
        # a range that excludes the year-end closing entry has no closing stock
        self.assertEqual(trading_and_pl(Y0, D(2026, 11, 30))['closing_stock'], Z)

    def test_monthly_average_uses_months_in_range(self):
        self._year(day=D(2026, 2, 10))
        r = trading_and_pl(D(2026, 1, 1), D(2026, 3, 31))
        self.assertEqual(r['months'], 3)
        self.assertEqual(r['monthly_avg_sales'], _d('316.67'))

    def test_branch_filter(self):
        self._year(branch=self.b1)
        self.assertEqual(trading_and_pl(Y0, Y1, branch_id=self.b1.id)['net_sales'], _d(950))
        self.assertEqual(trading_and_pl(Y0, Y1, branch_id=self.b2.id)['net_sales'], Z)

    def test_unclassified_trading_account_still_in_net_profit(self):
        self._year()
        g = GLAccountGroup.objects.get(name='ايرادات')
        GLAccount.objects.create(code='7999', name='x', group=g, nature='credit',
                                 account_type='revenue', statement_line='')
        self._entry(D(2026, 5, 1), [('1301', 7, None), ('7999', -7, None)])
        r = trading_and_pl(Y0, Y1)
        self.assertEqual(r['unclassified'], _d(-7))
        self.assertEqual(r['net_profit'], _d(152))

    # ── financial position ───────────────────────────────────────────────────

    def _position_book(self):
        self._entry(D(2026, 1, 1), [
            ('1201', 1000, None), ('1251', -300, None), ('1306', 200, None), ('1307', 50, None),
            ('1341', 400, None), ('1351', 60, None), ('1353', 10, None),
            ('2341', -500, None), ('2343', -200, None), ('2351', -70, None),
            ('2400', -800, None), ('2501', -150, None), ('2409', 300, None)])
        self._year()
        self._entry(D(2026, 8, 1), [('2341', 120, None), ('1307', -120, None)])  # bank -> credit 70

    def test_financial_position_balances(self):
        self._position_book()
        r = financial_position(Y1)
        self.assertEqual(r['fixed_assets'], _d(1000))
        self.assertEqual(r['accumulated_depreciation'], _d(300))
        self.assertEqual(r['net_fixed_assets'], _d(700))
        self.assertEqual(r['inventory'], _d(150))
        self.assertEqual(r['receivables'], _d(400))
        self.assertEqual(r['other_debtors'], _d(60))
        self.assertEqual(r['deposits'], _d(10))
        self.assertEqual(r['suppliers'], _d(1180))  # 500 + 800 - 120
        self.assertEqual(r['notes_payable'], _d(200))
        self.assertEqual(r['creditors'], _d(70))
        self.assertEqual(r['capital'], _d(900))  # 800 + 100 opening-stock contra
        self.assertEqual(r['partners'], _d(150))
        self.assertEqual(r['net_profit'], _d(145))
        self.assertEqual(r['profit_and_loss'], _d(-155))  # -(300) + 145
        self.assertEqual(r['working_capital'], r['total_current_assets'] - r['total_current_liabilities'])
        self.assertEqual(r['total_investment'], r['net_fixed_assets'] + r['working_capital'])
        self.assertEqual(r['total_equity'], r['capital'] + r['partners'] + r['profit_and_loss'])
        self.assertEqual(r['check'], Z)

    def test_credit_balance_bank_moves_to_overdraft(self):
        self._position_book()
        r = financial_position(Y1)
        # cash: 1301 = 1000-50+30+5-90 = 895; bank 1306 = 200 (debit); bank 1307 = 50-120 = -70
        self.assertEqual(r['cash'], _d(1095))
        self.assertEqual(r['overdraft'], _d(70))
        self.assertEqual(r['check'], Z)

    def test_closing_stock_not_from_entries(self):
        self._position_book()
        r = financial_position(Y1, closing_stock_from_entries=False, closing_stock=_d(150))
        self.assertEqual(r['inventory'], _d(150))
        self.assertEqual(r['check'], Z)

    # ── branch P&L ───────────────────────────────────────────────────────────

    def test_branch_pl_allocation_sums_to_consolidated(self):
        # sales 100 / 100 / 100 → 1/3 each; HQ general 100.00 → 33.33 ×3 = 99.99, +0.01 remainder
        for b, sale in ((self.b1, 100), (self.b2, 100), (self.b3, 101)):
            self._entry(D(2026, 3, 1), [('1301', sale, b), ('6001', -sale, b)])
        self._entry(D(2026, 3, 1), [('1301', -1, self.b3), ('6018', 1, self.b3)])  # b3 net 100
        self._entry(D(2026, 3, 1), [('1301', 10, None), ('6001', -10, None)])  # HQ sales (no branch)
        self._entry(D(2026, 3, 2), [('8001', 100, None), ('8401', 10, self.hq), ('1301', -110, None)])
        self._entry(D(2026, 3, 2), [('8201', 7, self.b1), ('1301', -7, self.b1)])
        self._entry(D(2026, 3, 5), [('1301', 50, self.b1), ('6001', -50, self.b1)])  # b1 now 150

        cols = branch_pl(Y0, Y1)
        total = next(c for c in cols if c['is_total'])
        hq = next(c for c in cols if c['is_hq'])
        branches = [c for c in cols if not c['is_total'] and not c['is_hq']]
        self.assertEqual({c['branch_id'] for c in branches}, {self.b1.id, self.b2.id, self.b3.id})

        consolidated = trading_and_pl(Y0, Y1)
        self.assertEqual(total['net_profit'], consolidated['net_profit'])
        self.assertEqual(total['after']['net_profit'], consolidated['net_profit'])
        self.assertEqual(sum(c['after']['net_profit'] for c in cols if not c['is_total']),
                         consolidated['net_profit'])
        # HQ before allocation
        self.assertEqual(hq['general_expenses'], _d(100))
        self.assertEqual(hq['depreciation'], _d(10))
        self.assertEqual(hq['net_sales'], _d(10))
        self.assertEqual(hq['after']['general_expenses'], Z)
        self.assertEqual(hq['allocation']['general_expenses'], _d(-100))
        # shares 150/350, 100/350, 100/350 of 100 → 42.86, 28.57, 28.57 = 100.00
        alloc = {c['branch_id']: c['allocation'] for c in branches}
        self.assertEqual(alloc[self.b1.id]['general_expenses'], _d('42.86'))
        self.assertEqual(alloc[self.b2.id]['general_expenses'], _d('28.57'))
        self.assertEqual(alloc[self.b3.id]['general_expenses'], _d('28.57'))
        # depreciation 10: 4.29 + 2.86 + 2.86 = 10.01 → remainder -0.01 on b1 (largest)
        self.assertEqual(alloc[self.b1.id]['depreciation'], _d('4.28'))
        self.assertEqual(sum(a['depreciation'] for a in alloc.values()), _d(10))
        b1 = next(c for c in branches if c['branch_id'] == self.b1.id)
        self.assertEqual(b1['operating_expenses'], _d(7))
        self.assertEqual(b1['after']['operating_expenses'], _d(7))
        self.assertEqual(total['allocation']['general_expenses'], Z)

    def test_branch_pl_posts_nothing(self):
        self._entry(D(2026, 3, 1), [('1301', 100, self.b1), ('6001', -100, self.b1)])
        self._entry(D(2026, 3, 2), [('8001', 30, None), ('1301', -30, None)])
        before = (LedgerEntry.objects.count(), LedgerLine.objects.count())
        branch_pl(Y0, Y1)
        self.assertEqual((LedgerEntry.objects.count(), LedgerLine.objects.count()), before)

    # ── comparison ───────────────────────────────────────────────────────────

    def test_comparison_one_row_per_year(self):
        self._year()
        self._entry(D(2027, 4, 1), [('1301', 200, None), ('6001', -200, None)])
        rows = comparison([2025, 2026, 2027])
        self.assertEqual([r['year'] for r in rows], [2025, 2026, 2027])
        self.assertTrue(rows[0]['empty'])
        self.assertEqual(rows[0]['values']['net_sales'], Z)
        self.assertFalse(rows[1]['empty'])
        self.assertEqual(rows[1]['values']['net_profit'], _d(145))
        self.assertEqual(rows[1]['pct_of_sales']['gross_profit'], _d('0.210526'))
        self.assertEqual(rows[2]['values']['net_sales'], _d(200))
        self.assertEqual(rows[2]['pct_of_sales']['net_sales'], _d(1))


class ReproduceWorkbookCommandTests(TestCase):
    """gl_reproduce_workbook on a tiny synthetic workbook (finance's sheet shapes)."""

    TB = [  # group, code, name, signed balance (+debit / -credit)
        ('النقديه بالصندوق', '1301', 'الخزينة', 1000),
        ('حقوق الملكيه', '2400', 'راس المال', -650),
        ('المبيعات', '6001', 'مبيعات', -1200),
        ('تكلفة المبيعات', '5100', 'مشتريات', 700),
        ('محزون أول المده', '5301', 'مخزون اول', 100),
        ('المصروفات العموميه', '8001', 'ايجار', 50),
    ]
    # closing stock 150 → cogs 650, gross 550, net 500; equity 650 + 500 = 1150 = cash + stock
    TRADING = {'رصيد اول المدة ': 100, 'صافى المشتريات ': 700, 'صافى المبيعات ': 1200,
               'رصيد اخر المدة ': 150, 'مجمل الربح ': 550, 'المصاريف العمومية ': 50,
               'مصاريف البيع والتوزيع ': 0, 'الاهلاكات ': 0, 'مصاريف التشغيل ': 0,
               'المصاريف التمويلية ': 0, 'ايرادات ': 0, 'ارباح  راسمالية بيع اصول ': 0,
               'صافى الارباح ': 500}
    POSITION = [('الاصول طويلة الاجل ', None), ('الاصول الثابتة ', 0),
                ('اجمالى الاصول الثابتة ', 0), ('الاصول المتداولة ', None),
                ('بضاعة اخر المدة ', 150), ('عملاء مدينون واورق قبض', 0),
                ('مدينون متنوعون ', 0), ('تامينات لدى الغير ', 0),
                ('نقدية بالبنوك والصندوق  ', 1000), ('اجمالى الاصول المتداولة ', 1150),
                ('الالتزامات المتداولة ', None), ('دائنون متنوعون ', 0),
                ('سحب على المكشوف ', 0), ('اوراق الدفع ', 0), ('الموردين ', 0),
                ('اجمالى الالتزامات ( الخصوم ) المتداولة ', 0), ('راس المال العامل ', 1150),
                ('اجمالى الاستثمار', 1150), ('حقوق الملكية ', None), ('راس المال ', 650),
                ('جارى  الشركاء ', 0), ('ح/ الارباح والخسائر ', 500),
                ('اجمالى حقوق الملكية ', 1150)]

    def _workbook(self, net_profit=500):
        import openpyxl
        import os
        import tempfile
        wb = openpyxl.Workbook()
        tb = wb.active
        tb.title = 'ميزان المراجعة 2025'
        tb.append(['Sub account name', 'رقم العملية', 'Trans. Name', 'Credit', 'Debt', 'Grand Total'])
        for g, code, name, bal in self.TB:
            tb.append([g, int(code), name, min(bal, 0) or None, max(bal, 0) or None, bal])
        tb.append(['Grand Total', None, None, None, None, 0])
        tr = wb.create_sheet('الختامية بسوفتيك')
        tr['A2'], tr['B2'], tr['E2'] = 'القيمة ', 'البيان ', 'متوسط  المبيعات الشهرى '
        tr['E3'] = 100
        row = 3
        for label, value in self.TRADING.items():
            if label == 'صافى الارباح ':
                value = net_profit
            tr.cell(row=row, column=2, value=label)
            tr.cell(row=row, column=1, value=value)
            row += 1
        tr['F3'], tr['F4'] = 'المتوسط الشهرى ', round(net_profit / 12, 4)
        tr.cell(row=row, column=1, value='المصاريف ')
        tr.cell(row=row + 1, column=1, value=50)
        tr.cell(row=row + 1, column=2, value='معدل الشهر ')
        tr.cell(row=row + 1, column=3, value=round(50 / 12, 4))
        for i, (label, v) in enumerate([
                ('نسبة مجمل الربح لصافى المبيعات ', 550 / 1200),
                ('نسبة صافى الربح لصافى المبيعات ', net_profit / 1200),
                ('نسبة صافى الربح لصافى المبيعات بدون اهلاكات ', net_profit / 1200),
                ('نسبة المصاريف لصافى المبيعات', 50 / 1200)], start=row + 3):
            tr.cell(row=i, column=1, value=label)
            tr.cell(row=i, column=3, value=v)
        bs = wb.create_sheet('الميزانية 31-12-2025')
        for col, h in enumerate(['الصافى كلى ', 'الصافى فرعى ', 'مجمع الاهلاك ', 'التكلفة ',
                                 'الصافى فرعى ', 'مجمع الاهلاك ', 'التكلفة ', 'البيان '], start=1):
            bs.cell(row=2, column=col, value=h)
        for i, (label, v) in enumerate(self.POSITION, start=4):
            bs.cell(row=i, column=8, value=label)
            if v is not None:
                bs.cell(row=i, column=1, value=v)
                if label == 'الاصول الثابتة ':
                    bs.cell(row=i, column=6, value=0)
                    bs.cell(row=i, column=7, value=0)
        fd, path = tempfile.mkstemp(suffix='.xlsx')
        os.close(fd)
        wb.save(path)
        self.addCleanup(os.remove, path)
        return path

    def _run(self, path):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command('gl_reproduce_workbook', path, '--year', '2025', '--closing-stock', '150',
                     stdout=out)
        return out.getvalue()

    def test_matching_workbook_passes_and_persists_nothing(self):
        before = (GLAccount.objects.count(), LedgerEntry.objects.count(), User.objects.count())
        out = self._run(self._workbook())
        self.assertIn('all figures match', out)
        self.assertEqual((GLAccount.objects.count(), LedgerEntry.objects.count(),
                          User.objects.count()), before)

    def test_difference_fails_and_persists_nothing(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            self._run(self._workbook(net_profit=499))
        self.assertEqual(LedgerEntry.objects.count(), 0)
        self.assertEqual(GLAccount.objects.count(), 0)
