"""Year-end close to retained earnings with the stock carry-forward (finance-gl Plan 3, Task 7). SOFTECH is mocked.

TestCase throughout, as in test_gl_close: a TransactionTestCase would flush the kept test DB.
"""
import datetime
from decimal import Decimal
from unittest import mock

from apps.audit.models import AuditLog
from apps.finance.gl import compare, softech_checks
from apps.finance.gl.balances import account_statement, trial_balance
from apps.finance.gl.close import CloseError, reopen_month
from apps.finance.gl.ledger import LedgerError, approve, reverse, save_draft
from apps.finance.gl.periods import month_period
from apps.finance.gl.statements import branch_pl, comparison, financial_position, trading_and_pl
from apps.finance.models import (ClosingStockSnapshot, FinancialPeriod, GLAccount, GLAccountGroup, GLComparisonLine,
                                 GLSoftechCheck, LedgerEntry)
from apps.tests.test_gl_close import CloseBase

D = datetime.date
Z = Decimal('0')
Y0, DEC = D(2026, 1, 1), D(2026, 12, 31)
Y1, JAN1 = D(2027, 1, 1), D(2027, 1, 31)
YEAR_KEY, STOCK_KEY = 'year_end:2026', 'year_end_stock:2027'
TRADING_PL = ('5100', '5301', '5302', '6011', '7000', '7100')


def _d(v):
    return Decimal(str(v))


class YearEndBase(CloseBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # code -> (group, section, statement_line, requires_branch, requires_party)
        for code, (gname, section, line, branch, party) in {
            '2409': ('حقوق الملكيه', 'balance_sheet', 'retained', False, False),
            '2501': ('جارى الشركاء', 'balance_sheet', 'partners', False, True),
            '6011': ('المبيعات', 'trading', 'net_sales', True, False),
            '7000': ('المصروفات العموميه', 'pl', 'general_expenses', False, False),
            '7100': ('مصروفات بيع وتوزيع', 'pl', 'selling_expenses', False, True),
        }.items():
            group, _ = GLAccountGroup.objects.get_or_create(name=gname, defaults={'section': section, 'order': 50})
            GLAccount.objects.create(code=code, name=f'acc {code}', group=group, nature='debit', account_type='asset',
                                     statement_line=line, requires_branch=branch, requires_party=party)

    def setUp(self):
        super().setUp()
        self.stock[DEC] = {'961': _d(100), '962': _d(50)}

    def entry(self, day, *lines, branch=None):
        """lines: (code, signed amount: debit positive, line branch, party)."""
        draft = save_draft(user=self.staff, entry_date=day, description='x', branch=branch, lines=[
            {'account_code': code, 'debit': max(_d(a), Z), 'credit': max(-_d(a), Z),
             'branch_id': b.id if b else None, 'party_code': party}
            for code, a, b, party in lines])
        return approve(draft.pk, user=self.staff)

    def year(self):
        """b1 profit 800 with its stock, b2 loss 150 with its stock, b3 nets to zero, one partner balance."""
        self.entry(D(2026, 2, 10), ('1301', 400, self.b1, ''), ('6011', -400, self.b1, ''))
        self.entry(D(2026, 12, 10), ('1301', 600, self.b1, ''), ('6011', -600, self.b1, ''))
        self.post(300, D(2026, 3, 5), branch=self.b1)
        self.entry(D(2026, 6, 1), ('7000', 200, self.b2, ''), ('1301', -200, self.b2, ''))
        self.entry(D(2026, 7, 1), ('1301', 70, self.b3, ''), ('6011', -70, self.b3, ''))
        self.entry(D(2026, 7, 2), ('7000', 70, self.b3, ''), ('1301', -70, self.b3, ''))
        self.entry(D(2026, 8, 1), ('1301', 50, self.b1, ''), ('2501', -50, self.b1, 'P1'))

    def close_december(self):
        FinancialPeriod.objects.filter(pk=month_period(D(2026, 11, 1)).pk).update(status='closed')
        return self.close(DEC)

    def lines(self, key):
        """(code, branch id, party) -> debit − credit of the live entry under `key`."""
        return {(ln.account.code, ln.branch_id, ln.party_code): ln.debit - ln.credit
                for ln in self.live(key).lines.select_related('account')}



class YearEndTests(YearEndBase):
    def test_pl_accounts_zero_after_year_end(self):
        self.year()
        before = self.balances(DEC)
        self.assertEqual(before['6011'], _d(-1070))
        self.close_december()
        after = self.balances(DEC)
        for code in TRADING_PL:
            self.assertNotIn(code, after)
        self.assertEqual(after['1390'], _d(150))   # balance sheet: not cleared
        self.assertEqual(after['2341'], _d(-300))

    def test_entries_are_as_specified(self):
        self.year()
        period = self.close_december()
        self.assertEqual(period.status, 'closed')
        closing, stock = self.live(YEAR_KEY), self.live(STOCK_KEY)
        self.assertEqual((closing.entry_date, closing.book, closing.source_type), (DEC, 'closing', 'year_end'))
        self.assertEqual((stock.entry_date, stock.book, stock.source_type), (Y1, 'opening', 'year_end_stock'))
        self.assertTrue(closing.number.startswith('JV-2026-'))
        self.assertTrue(stock.number.startswith('JV-2027-'))
        self.assertEqual(closing.approved_by, self.staff)
        self.assertEqual(month_period(Y1).status, 'open')
        # December's closing stock stays, unreversed, and no monthly auto-reversal is posted
        self.assertEqual(self.live('closing_stock:2026-12').status, 'approved')
        self.assertFalse(LedgerEntry.objects.filter(source_key='closing_stock_rev:2026-12').exists())
        audit = AuditLog.objects.filter(action='gl_period_closed', object_id=str(period.pk)).latest('pk')
        self.assertEqual(audit.new_data['year_end_entry_id'], closing.pk)
        self.assertEqual(audit.new_data['year_end_stock_entry_id'], stock.pk)

    def test_2409_receives_net_result_per_branch(self):
        self.year()
        self.close_december()
        lines = self.lines(YEAR_KEY)
        self.assertEqual(lines[('2409', self.b1.id, '')], _d(-800))   # profit: credit
        self.assertEqual(lines[('2409', self.b2.id, '')], _d(150))    # loss: debit
        self.assertNotIn(('2409', self.b3.id, ''), lines)             # nets to zero: no line
        self.assertEqual(lines[('6011', self.b3.id, '')], _d(70))     # but its accounts are cleared
        self.assertEqual(lines[('7000', self.b3.id, '')], _d(-70))
        self.assertEqual(sum(lines.values()), Z)
        self.assertEqual(self.balance('2409', DEC), _d(-650))

    def test_partners_untouched(self):
        self.year()
        self.close_december()
        self.assertFalse(any(code == '2501' for code, _, _ in self.lines(YEAR_KEY)))
        self.assertEqual(self.balance('2501', DEC), _d(-50))
        self.assertEqual(account_statement('2501', Y1, JAN1, party_code='P1')['opening_balance'], _d(-50))

    def test_next_year_opening_stock_on_5301_and_1390_zero(self):
        self.year()
        self.close_december()
        self.assertEqual(self.lines(STOCK_KEY), {
            ('5301', self.b1.id, ''): _d(100), ('1390', self.b1.id, ''): _d(-100),
            ('5301', self.b2.id, ''): _d(50), ('1390', self.b2.id, ''): _d(-50)})
        self.assertEqual(self.balance('5301', Y1), _d(150))
        self.assertEqual(self.balance('1390', Y1), Z)
        self.assertEqual(self.balance('1390', DEC), _d(150))

    def test_next_year_trial_balance_opening_equals_closing_bs(self):
        self.year()
        self.close_december()
        closing = {r['code']: r['closing_debit'] - r['closing_credit'] for r in trial_balance(Y0, DEC)[:-1]}
        rows = trial_balance(Y1, JAN1)
        opening = {r['code']: r['opening_debit'] - r['opening_credit'] for r in rows[:-1]}
        self.assertEqual({c: v for c, v in closing.items() if v}, {c: v for c, v in opening.items() if v})
        self.assertEqual(opening['2409'], _d(-650))
        for code in TRADING_PL:
            self.assertEqual(opening.get(code, Z), Z)
        total = rows[-1]
        self.assertEqual(total['opening_debit'], total['opening_credit'])

    def test_reopen_december_reverses_year_end_entries(self):
        self.year()
        before_dec, before_jan = self.balances(DEC), self.balances(JAN1)
        self.close_december()
        closing, stock = self.live(YEAR_KEY), self.live(STOCK_KEY)
        months = reopen_month(month_period(DEC).pk, user=self.staff, reason='تصحيح')
        self.assertEqual([m.month for m in months], [12])
        self.assertEqual(self.balances(DEC), before_dec)
        self.assertEqual(self.balances(JAN1), before_jan)
        for entry, day in ((closing, DEC), (stock, Y1)):
            entry.refresh_from_db()
            self.assertEqual(entry.status, 'reversed')
            self.assertEqual(entry.reversals.get().entry_date, day)
        self.assertEqual(month_period(DEC).status, 'open')

    def test_reopen_january_after_it_closed_takes_nothing_of_the_year_end(self):
        self.year()
        self.close_december()
        self.stock[JAN1] = {'961': _d(120)}
        self.close(JAN1)
        reopen_month(month_period(JAN1).pk, user=self.staff, reason='تصحيح')
        self.assertEqual(self.live(YEAR_KEY).status, 'approved')
        self.assertEqual(self.live(STOCK_KEY).status, 'approved')

    def test_reopen_december_cascades_to_a_closed_january(self):
        self.year()
        before = self.balances(JAN1)
        self.close_december()
        self.stock[JAN1] = {'961': _d(120)}
        self.close(JAN1)
        months = reopen_month(month_period(DEC).pk, user=self.staff, reason='تصحيح')
        self.assertEqual([m.month for m in months], [12, 1])
        self.assertEqual(self.balances(JAN1), before)

    def test_close_again_after_reopen_gives_the_same_result(self):
        self.year()
        self.close_december()
        first = self.balances(Y1)
        first_lines = self.lines(YEAR_KEY)
        reopen_month(month_period(DEC).pk, user=self.staff, reason='تصحيح')
        self.close(DEC)
        self.assertEqual(self.balances(Y1), first)
        self.assertEqual(self.lines(YEAR_KEY), first_lines)
        self.assertEqual(LedgerEntry.objects.filter(source_type='year_end').count(), 2)

    def test_party_is_kept_and_a_zero_group_posts_no_line(self):
        self.entry(D(2026, 5, 1), ('7100', 40, self.b1, 'S1'), ('1301', -40, self.b1, ''))
        self.entry(D(2026, 5, 2), ('7100', 15, self.b1, 'S2'), ('1301', -15, self.b1, ''))
        self.entry(D(2026, 5, 3), ('7000', 5, self.b1, ''), ('1301', -5, self.b1, ''))
        self.entry(D(2026, 5, 4), ('1301', 5, self.b1, ''), ('7000', -5, self.b1, ''))
        self.stock[DEC] = {}
        self.close_december()
        self.assertEqual(self.lines(YEAR_KEY), {
            ('7100', self.b1.id, 'S1'): _d(-40), ('7100', self.b1.id, 'S2'): _d(-15), ('2409', self.b1.id, ''): _d(55)})

    def test_a_line_without_branch_is_cleared_on_the_entry_branch(self):
        self.entry(D(2026, 5, 1), ('7000', 40, None, ''), ('1301', -40, None, ''), branch=self.b2)
        self.stock[DEC] = {}
        self.close_december()
        self.assertEqual(self.lines(YEAR_KEY), {('7000', self.b2.id, ''): _d(-40), ('2409', self.b2.id, ''): _d(40)})
        self.assertEqual(trial_balance(Y0, DEC, branch_id=self.b2.id)[-1]['closing_debit'], _d(40))

    def test_an_unbranched_balance_is_cleared_unbranched(self):
        self.entry(Y0, ('5301', 900, None, ''), ('2400', -900, None, ''))
        self.stock[DEC] = {}
        self.close_december()
        self.assertEqual(self.lines(YEAR_KEY), {('5301', None, ''): _d(-900), ('2409', None, ''): _d(900)})
        self.assertEqual(self.balance('5301', DEC), Z)

    def test_a_branch_with_negative_stock_flips_the_carry_forward(self):
        self.stock[DEC] = {'961': _d(100), '962': _d(-30), '963': Z}
        self.close_december()
        self.assertEqual(self.lines(STOCK_KEY), {
            ('5301', self.b1.id, ''): _d(100), ('1390', self.b1.id, ''): _d(-100),
            ('5301', self.b2.id, ''): _d(-30), ('1390', self.b2.id, ''): _d(30)})
        self.assertEqual(self.balance('1390', Y1), Z)

    def test_an_empty_year_closes_without_entries(self):
        self.stock[DEC] = {}
        period = self.close_december()
        self.assertEqual(period.status, 'closed')
        self.assertFalse(LedgerEntry.objects.filter(source_type__in=('year_end', 'year_end_stock')).exists())

    def test_a_reversed_entry_counts_as_nothing(self):
        wrong = self.entry(D(2026, 5, 1), ('7000', 40, self.b1, ''), ('1301', -40, self.b1, ''))
        reverse(wrong.pk, user=self.staff, reason='خطأ')
        self.entry(D(2026, 5, 2), ('7000', 10, self.b1, ''), ('1301', -10, self.b1, ''))
        self.stock[DEC] = {}
        self.close_december()
        self.assertEqual(self.lines(YEAR_KEY), {('7000', self.b1.id, ''): _d(-10), ('2409', self.b1.id, ''): _d(10)})

    def test_an_account_that_cannot_be_posted_fails_the_close_and_leaves_nothing(self):
        self.year()
        GLAccount.objects.filter(code='7000').update(is_active=False)
        period = month_period(DEC)
        with self.assertRaises(CloseError) as cm:
            self.close_december()
        self.assertEqual(cm.exception.code, 'year_end_account')
        self.assertEqual(cm.exception.detail, {'account_code': '7000', 'code': 'inactive_account'})
        period.refresh_from_db()
        self.assertEqual(period.status, 'open')
        self.assertFalse(LedgerEntry.objects.filter(source_type__in=('closing_stock', 'year_end', 'year_end_stock'))
                         .exists())
        self.assertFalse(ClosingStockSnapshot.objects.filter(period=period).exists())
        audit = AuditLog.objects.filter(action='gl_period_close_failed', object_id=str(period.pk)).latest('pk')
        self.assertEqual(audit.extra['code'], 'year_end_account')
        self.assertEqual(audit.extra['detail']['account_code'], '7000')

    def test_year_end_entries_are_refused_by_the_journal(self):
        self.year()
        self.close_december()
        for key in (YEAR_KEY, STOCK_KEY):
            with self.assertRaises(LedgerError) as cm:
                reverse(self.live(key).pk, user=self.staff, reason='x')
            self.assertEqual(cm.exception.code, 'close_entry')

    def test_the_next_year_runs_on_the_carried_stock(self):
        self.year()
        self.close_december()
        self.post(30, D(2027, 1, 5), branch=self.b1)
        self.stock[JAN1] = {'961': _d(120), '962': _d(50)}
        self.close(JAN1)
        r = trading_and_pl(Y1, JAN1)
        self.assertEqual(r['opening_stock'], _d(150))
        self.assertEqual(r['closing_stock'], _d(170))
        self.assertEqual(r['cost_of_sales'], _d(10))
        self.assertEqual(self.balance('1390', D(2027, 2, 1)), Z)


class StatementsAfterYearEndTests(YearEndBase):
    """The closing entry moves the year's result to 2409; the statements of that year must still show the year."""

    def test_statements_of_the_closed_year_keep_their_figures(self):
        self.year()
        self.close_december()
        r = trading_and_pl(Y0, DEC)
        self.assertEqual(r['net_sales'], _d(1070))
        self.assertEqual(r['closing_stock'], _d(150))
        self.assertEqual(r['net_profit'], _d(650))
        self.assertEqual(r['stock_basis'], 'entries')
        self.assertEqual(trading_and_pl(D(2026, 12, 1), DEC)['net_sales'], _d(600))
        self.assertEqual(comparison([2026])[0]['values']['net_profit'], _d(650))
        columns = {c['branch_id']: c for c in branch_pl(Y0, DEC) if not c['is_total'] and not c['is_hq']}
        self.assertEqual(columns[self.b1.id]['net_profit'], _d(800))
        self.assertEqual(columns[self.b2.id]['net_profit'], _d(-150))

    def test_they_still_do_after_a_reopen(self):
        self.year()
        self.close_december()
        reopen_month(month_period(DEC).pk, user=self.staff, reason='تصحيح')
        self.assertEqual(trading_and_pl(Y0, DEC)['net_sales'], _d(1070))
        self.assertEqual(trading_and_pl(Y0, DEC)['net_profit'], _d(500))   # the closing stock went back too

    def test_position_at_year_end(self):
        self.year()
        self.close_december()
        r = financial_position(DEC)
        self.assertEqual(r['check'], Z)
        self.assertEqual(r['unclosed_pl'], Z)
        self.assertEqual(r['retained_balance'], _d(-650))
        self.assertEqual(r['profit_and_loss'], _d(650))
        self.assertEqual(r['inventory'], _d(150))

    def test_position_with_a_supplied_stock_balances_at_and_after_year_end(self):
        self.year()
        self.close_december()
        at_year_end = financial_position(DEC, closing_stock_from_entries=False, closing_stock=_d(200))
        self.assertEqual(at_year_end['check'], Z)
        self.assertEqual(at_year_end['inventory'], _d(200))
        self.assertEqual(at_year_end['profit_and_loss'], _d(700))
        after = financial_position(JAN1, closing_stock_from_entries=False, closing_stock=_d(200))
        self.assertEqual(after['check'], Z)

    def test_december_comparison_ignores_the_closing_entry(self):
        check = GLSoftechCheck.objects.create(key='t_sales', label='مبيعات', kind='movement', account_codes=['6011'],
                                              group_names=[], source='sales', sign='credit', blocks_close=False)
        self.year()
        self.softech['sales'] = {('961', ''): _d(600)}
        self.close_december()
        period = month_period(DEC)
        compare.compute(period)
        line = GLComparisonLine.objects.get(period=period, softech_check=check, branch=self.b1)
        self.assertEqual(line.ledger_amount, _d(600))
        self.assertEqual(line.difference, Z)
        with mock.patch.object(softech_checks, 'detail', return_value=[]):
            detail = compare.detail(line.pk)
        self.assertEqual(sum(r['credit'] - r['debit'] for r in detail['ledger']), _d(600))
        self.assertEqual(sum(d['ledger'] for d in detail['by_day']), _d(600))
