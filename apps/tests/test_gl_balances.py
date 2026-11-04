"""Trial balance and account statement (finance-gl Task 6)."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from apps.branches.models import Branch
from apps.finance.gl.balances import account_statement, trial_balance
from apps.finance.gl.ledger import approve, reverse, save_draft
from apps.finance.models import GLAccount, GLAccountGroup
from apps.users.models import StaffProfile

D = datetime.date
Z = Decimal('0')


def _d(v):
    return Decimal(str(v))


class BalancesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        u = User.objects.create_user(username='gl_bal_u', password='x')
        cls.staff, _ = StaffProfile.objects.get_or_create(user=u)
        cls.g_cash = GLAccountGroup.objects.create(name='نقدية', section='balance_sheet', order=1)
        cls.g_rev = GLAccountGroup.objects.create(name='ايرادات', section='income', order=2)
        cls.cash = GLAccount.objects.create(code='1101', name='الخزينة', group=cls.g_cash,
                                            nature='debit', account_type='asset')
        cls.bank = GLAccount.objects.create(code='1102', name='البنك', group=cls.g_cash,
                                            nature='debit', account_type='asset')
        cls.sales = GLAccount.objects.create(code='4101', name='المبيعات', group=cls.g_rev,
                                             nature='credit', account_type='revenue')
        cls.b1 = Branch.objects.create(softech_branch_id='961', name='B1')
        cls.b2 = Branch.objects.create(softech_branch_id='962', name='B2')

    def _post(self, amount, day, debit='1101', credit='4101', branch=None, party='', desc='x'):
        e = save_draft(user=self.staff, entry_date=day, description=desc, lines=[
            {'account_code': debit, 'debit': _d(amount), 'credit': Z,
             'branch_id': branch.id if branch else None, 'party_code': party},
            {'account_code': credit, 'debit': Z, 'credit': _d(amount),
             'branch_id': branch.id if branch else None},
        ])
        return approve(e.id, user=self.staff)

    def _row(self, rows, code):
        return next(r for r in rows if r['code'] == code)

    def test_drafts_excluded(self):
        save_draft(user=self.staff, entry_date=D(2026, 3, 1), description='d', lines=[
            {'account_code': '1101', 'debit': _d(50), 'credit': Z},
            {'account_code': '4101', 'debit': Z, 'credit': _d(50)}])
        rows = trial_balance(D(2026, 1, 1), D(2026, 12, 31))
        self.assertEqual([r for r in rows if r['code'] == '1101'], [])
        self.assertEqual(account_statement('1101', D(2026, 1, 1), D(2026, 12, 31))['lines'], [])

    def test_reversal_nets_to_zero(self):
        e = self._post(100, D(2026, 3, 1))
        reverse(e.id, user=self.staff, reason='r')
        rows = trial_balance(D(2026, 1, 1), D(2026, 12, 31))
        r = self._row(rows, '1101')
        self.assertEqual((r['period_debit'], r['period_credit']), (_d(100), _d(100)))
        self.assertEqual((r['closing_debit'], r['closing_credit']), (Z, Z))

    def test_opening_column_is_before_date_from(self):
        self._post(100, D(2026, 2, 10))
        self._post(40, D(2026, 4, 10))
        r = self._row(trial_balance(D(2026, 3, 1), D(2026, 12, 31)), '1101')
        self.assertEqual(r['opening_debit'], _d(100))
        self.assertEqual(r['opening_credit'], Z)
        self.assertEqual(r['period_debit'], _d(40))
        self.assertEqual(r['closing_debit'], _d(140))
        s = self._row(trial_balance(D(2026, 3, 1), D(2026, 12, 31)), '4101')
        self.assertEqual(s['opening_credit'], _d(100))
        self.assertEqual(s['closing_credit'], _d(140))
        self.assertEqual(s['closing_debit'], Z)

    def test_totals_balance(self):
        self._post(100, D(2026, 2, 10))
        self._post(30, D(2026, 4, 10), debit='1102')
        rows = trial_balance(D(2026, 3, 1), D(2026, 12, 31))
        total = rows[-1]
        self.assertTrue(total['is_total'])
        for side in ('opening', 'period', 'closing'):
            self.assertEqual(total[f'{side}_debit'], total[f'{side}_credit'])
        self.assertEqual(total['closing_debit'], _d(130))

    def test_branch_filter(self):
        self._post(100, D(2026, 3, 1), branch=self.b1)
        self._post(70, D(2026, 3, 2), branch=self.b2)
        self._post(5, D(2026, 3, 3))
        r1 = self._row(trial_balance(D(2026, 1, 1), D(2026, 12, 31), branch_id=self.b1.id), '1101')
        self.assertEqual(r1['period_debit'], _d(100))
        r2 = self._row(trial_balance(D(2026, 1, 1), D(2026, 12, 31), branch_id=self.b2.id), '1101')
        self.assertEqual(r2['period_debit'], _d(70))
        st = account_statement('1101', D(2026, 1, 1), D(2026, 12, 31), branch_id=self.b2.id)
        self.assertEqual(len(st['lines']), 1)

    def test_group_rollup(self):
        self._post(100, D(2026, 3, 1))
        self._post(30, D(2026, 3, 2), debit='1102')
        rows = trial_balance(D(2026, 1, 1), D(2026, 12, 31), by='group')
        self.assertEqual([r['name'] for r in rows[:-1]], ['نقدية', 'ايرادات'])
        self.assertEqual(rows[0]['period_debit'], _d(130))
        self.assertEqual(rows[1]['closing_credit'], _d(130))
        self.assertEqual(rows[-1]['closing_debit'], rows[-1]['closing_credit'])

    def test_running_balance(self):
        self._post(100, D(2026, 2, 1))
        self._post(30, D(2026, 3, 5), debit='4101', credit='1101')
        self._post(10, D(2026, 3, 6))
        st = account_statement('1101', D(2026, 3, 1), D(2026, 12, 31))
        self.assertEqual(st['opening_balance'], _d(100))
        self.assertEqual([ln['running_balance'] for ln in st['lines']], [_d(70), _d(80)])
        self.assertEqual(st['closing_balance'], _d(80))
        self.assertEqual(st['lines'][0]['credit'], _d(30))
        self.assertTrue(st['lines'][0]['number'])

    def test_statement_party_filter(self):
        self._post(100, D(2026, 3, 1), party='P1')
        self._post(20, D(2026, 3, 2), party='P2')
        st = account_statement('1101', D(2026, 1, 1), D(2026, 12, 31), party_code='P2')
        self.assertEqual(st['closing_balance'], _d(20))
