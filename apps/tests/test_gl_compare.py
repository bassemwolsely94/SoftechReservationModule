"""Ledger vs SOFTECH comparison (finance-gl Plan 3, Task 4). SOFTECH is mocked; nothing real is read."""
import datetime
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from apps.branches.models import Branch
from apps.finance.gl import compare, softech_checks
from apps.finance.gl.ledger import LedgerError, approve, reverse, save_draft
from apps.finance.gl.periods import month_period
from apps.finance.models import (APInvoice, GLAccount, GLAccountGroup, GLComparisonLine, GLParty,
                                 GLSoftechCheck, Payment, ReconParty)
from apps.finance.recon_balances import ap_balance_as_of
from apps.users.models import StaffProfile

D = datetime.date
Z = Decimal('0')


def _d(v):
    return Decimal(str(v))


class CompareBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        u = User.objects.create_user(username='gl_cmp_u', password='x')
        cls.staff, _ = StaffProfile.objects.get_or_create(user=u)
        g = GLAccountGroup.objects.create(name='مجموعة اختبار', section='income', order=1)
        mk = lambda code, name, nature, typ: GLAccount.objects.create(
            code=code, name=name, group=g, nature=nature, account_type=typ)
        mk('9100', 'نقدية', 'debit', 'asset')
        mk('9101', 'مبيعات', 'credit', 'revenue')
        mk('9103', 'مخزون', 'debit', 'asset')
        mk('9104', 'موردون', 'credit', 'liability')
        cls.b1 = Branch.objects.create(softech_branch_id='961', name='B1')
        cls.b2 = Branch.objects.create(softech_branch_id='962', name='B2')
        cls.period = month_period(D(2026, 3, 1))
        mkc = lambda key, **kw: GLSoftechCheck.objects.create(key=key, label=key, **kw)
        cls.sales = mkc('t_sales', kind='movement', account_codes=['9101'], source='sales', sign='credit')
        cls.stock = mkc('t_stock', kind='balance', account_codes=['9103'], source='stock_at_cost',
                        sign='debit')
        cls.sup = mkc('t_sup', kind='balance', account_codes=['9104'], source='supplier_balance',
                      sign='credit', per_party=True, blocks_close=False)

    def post(self, amount, day, debit='9100', credit='9101', branch=None, party=''):
        bid = branch.id if branch else None
        e = save_draft(user=self.staff, entry_date=day, description='x', lines=[
            {'account_code': debit, 'debit': _d(amount), 'credit': Z, 'branch_id': bid},
            {'account_code': credit, 'debit': Z, 'credit': _d(amount), 'branch_id': bid,
             'party_code': party}])
        return approve(e.id, user=self.staff)

    def line(self, check, branch=None, party=''):
        return GLComparisonLine.objects.get(period=self.period, softech_check=check,
                                            branch=branch, party_code=party)


class MovementTests(CompareBase):
    def test_movement_check_by_branch(self):
        self.post(100, D(2026, 3, 5), branch=self.b1)
        self.post(50, D(2026, 3, 9), branch=self.b2)
        self.post(30, D(2026, 4, 2), branch=self.b2)   # next month: not in March
        with mock.patch.object(softech_checks, 'sales', return_value={('961', ''): _d(100), ('962', ''): _d(40)}):
            compare.compute(self.period, check_keys=['t_sales'])
        l1, l2 = self.line(self.sales, self.b1), self.line(self.sales, self.b2)
        self.assertEqual((l1.ledger_amount, l1.softech_amount, l1.difference), (_d(100), _d(100), Z))
        self.assertEqual((l2.ledger_amount, l2.softech_amount, l2.difference), (_d(50), _d(40), _d(10)))

    def test_unknown_softech_branch_lands_on_no_branch_line(self):
        with mock.patch.object(softech_checks, 'sales', return_value={('999', ''): _d(7)}):
            compare.compute(self.period, check_keys=['t_sales'])
        self.assertEqual(self.line(self.sales).difference, _d(-7))


class BalanceTests(CompareBase):
    def test_balance_check_uses_period_end(self):
        self.post(500, D(2026, 2, 10), debit='9103', credit='9100', branch=self.b1)
        self.post(200, D(2026, 3, 20), debit='9103', credit='9100', branch=self.b1)
        self.post(100, D(2026, 4, 1), debit='9103', credit='9100', branch=self.b1)
        with mock.patch.object(softech_checks, 'stock_at_cost', return_value={('961', ''): _d(650)}):
            compare.compute(self.period, check_keys=['t_stock'])
        ln = self.line(self.stock, self.b1)
        self.assertEqual((ln.ledger_amount, ln.softech_amount, ln.difference), (_d(700), _d(650), _d(50)))


class SupplierTests(CompareBase):
    def setUp(self):
        self.rp = ReconParty.objects.create(party_type='supplier', softech_personcode='77001', name='s',
                                            opening_balance=_d(1000), opening_balance_date=D(2026, 1, 1))
        GLParty.objects.create(party_type='supplier', code='S1', name='s', softech_personcode='77001',
                               status='confirmed', recon_party=self.rp)
        self._n = 0

    def inv(self, day, value, ret=False):
        self._n += 1
        return APInvoice.objects.create(
            party=self.rp, branchcode='100', doccode='120' if ret else '10', docnumber=str(self._n),
            docdate=day, doc_value=_d(value), is_return=ret, party_type='supplier')

    def pay(self, day, amount):
        self._n += 1
        return Payment.objects.create(party=self.rp, branchcode='100', cheqsno=self._n, direction='out',
                                      party_type='supplier', voucher_date=day, amount=_d(amount))

    def test_supplier_check_per_party_uses_ap_balance_as_of(self):
        self.inv(D(2026, 3, 10), 500)
        self.inv(D(2026, 3, 12), 50, ret=True)
        self.pay(D(2026, 3, 20), 200)
        self.inv(D(2026, 4, 5), 999)   # after period end
        self.post(1200, D(2026, 3, 20), debit='9100', credit='9104', party='S1')
        compare.compute(self.period, check_keys=['t_sup'])
        ln = self.line(self.sup, None, 'S1')
        self.assertEqual((ln.ledger_amount, ln.softech_amount, ln.difference), (_d(1200), _d(1250), _d(-50)))

    def test_ap_balance_as_of_excludes_later_documents(self):
        self.inv(D(2026, 3, 10), 500)
        self.inv(D(2026, 4, 5), 300)
        self.pay(D(2026, 3, 20), 200)
        self.pay(D(2026, 4, 6), 100)
        self.assertEqual(ap_balance_as_of(self.rp, D(2026, 3, 31)), _d(1300))
        self.assertEqual(ap_balance_as_of(self.rp, D(2026, 4, 30)), _d(1500))
        self.assertIsNone(ap_balance_as_of(self.rp, D(2025, 12, 31)))

    def test_ap_balance_matches_reconciliation_equation(self):
        from apps.finance.recon_balances import reconciliation_equation
        self.inv(D(2026, 3, 10), 500)
        self.inv(D(2026, 3, 11), 40, ret=True)
        self.pay(D(2026, 3, 20), 200)
        self.assertEqual(ap_balance_as_of(self.rp, D(2026, 12, 31)),
                         reconciliation_equation(self.rp)['expected_closing'])

    def test_unconfirmed_party_has_no_softech_figure(self):
        GLParty.objects.filter(code='S1').update(status='proposed')
        self.assertEqual(softech_checks.supplier_balance(self.period), {})


class ExplainTests(CompareBase):
    def run_compute(self, softech):
        with mock.patch.object(softech_checks, 'sales', return_value={('961', ''): _d(softech)}):
            compare.compute(self.period, check_keys=['t_sales'])

    def test_recompute_keeps_explanation_and_flags_changed_difference(self):
        self.post(100, D(2026, 3, 5), branch=self.b1)
        self.run_compute(90)
        ln = self.line(self.sales, self.b1)
        self.assertTrue(ln.needs_explanation)
        compare.explain(ln.id, user=self.staff, text='فرق توقيت')
        ln = self.line(self.sales, self.b1)
        self.assertFalse(ln.needs_explanation)
        self.run_compute(90)                      # same difference: explanation holds
        self.assertFalse(self.line(self.sales, self.b1).needs_explanation)
        self.run_compute(80)                      # difference moved: re-opened, text kept
        ln = self.line(self.sales, self.b1)
        self.assertEqual(ln.explanation, 'فرق توقيت')
        self.assertTrue(ln.needs_explanation)

    def test_explain_requires_text(self):
        self.post(100, D(2026, 3, 5), branch=self.b1)
        self.run_compute(90)
        ln = self.line(self.sales, self.b1)
        for text in ('', '   ', None):
            with self.assertRaises(LedgerError):
                compare.explain(ln.id, user=self.staff, text=text)

    def test_compute_and_explain_are_audited(self):
        from apps.audit.models import AuditLog
        self.post(100, D(2026, 3, 5), branch=self.b1)
        self.run_compute(90)
        compare.explain(self.line(self.sales, self.b1).id, user=self.staff, text='سبب')
        actions = set(AuditLog.objects.values_list('action', flat=True))
        self.assertLessEqual({'gl_comparison_computed', 'gl_comparison_explained'}, actions)


class StaleTests(CompareBase):
    def setUp(self):
        GLSoftechCheck.objects.exclude(key='t_sales').update(is_active=False)

    def test_is_stale_after_new_approval(self):
        self.assertTrue(compare.is_stale(self.period))       # no lines yet
        self.post(100, D(2026, 3, 5), branch=self.b1)
        with mock.patch.object(softech_checks, 'sales', return_value={('961', ''): _d(100)}):
            compare.compute(self.period, check_keys=['t_sales'])
        self.assertFalse(compare.is_stale(self.period))
        later = self.post(10, D(2026, 3, 6), branch=self.b1)
        self.assertTrue(compare.is_stale(self.period))
        with mock.patch.object(softech_checks, 'sales', return_value={('961', ''): _d(110)}):
            compare.compute(self.period, check_keys=['t_sales'])
        self.assertFalse(compare.is_stale(self.period))
        reverse(later.id, user=self.staff, reason='r')       # its reversal is newer than the lines
        self.assertTrue(compare.is_stale(self.period))


class StaleRulingTests(CompareBase):
    def setUp(self):
        GLSoftechCheck.objects.exclude(key__in=['t_sales', 't_stock']).update(is_active=False)

    def test_partial_compute_is_stale_and_all_zero_compute_is_fresh(self):
        with mock.patch.object(softech_checks, 'sales', return_value={}):
            compare.compute(self.period, check_keys=['t_sales'])
        self.assertTrue(compare.is_stale(self.period))      # t_stock never computed
        self.assertEqual(self.line(self.sales).difference, Z)   # zero/zero check still left its line
        with mock.patch.object(softech_checks, 'sales', return_value={}),                 mock.patch.object(softech_checks, 'stock_at_cost', return_value={}):
            compare.compute(self.period)
        self.assertFalse(compare.is_stale(self.period))
        self.assertEqual(GLComparisonLine.objects.filter(period=self.period).count(), 2)

    def test_earlier_dated_late_approval_stales_balance_checks_only(self):
        with mock.patch.object(softech_checks, 'sales', return_value={}),                 mock.patch.object(softech_checks, 'stock_at_cost', return_value={}):
            compare.compute(self.period)
            self.post(10, D(2026, 2, 3), debit='9103', credit='9100')
            self.assertTrue(compare.is_stale(self.period))
            compare.compute(self.period)
            GLSoftechCheck.objects.filter(key='t_stock').update(is_active=False)
            compare.compute(self.period)
            self.post(10, D(2026, 2, 4), debit='9103', credit='9100')
            self.assertFalse(compare.is_stale(self.period))   # movement-only: February is not its month

    def test_unknown_source_refused(self):
        with self.assertRaises(ValueError):
            softech_checks.figures('globals', self.period)
        with self.assertRaises(ValueError):
            softech_checks.detail('__import__', self.period, None)

    def test_expense_error_text_not_leaked(self):
        err = [{'_error': 'java.sql.SQLException: host 10.1.2.3 refused'}]
        with mock.patch('apps.finance.queries.sybase_accounting.get_dailyexpenses_by_branch_month',
                        return_value=err), self.assertLogs('elrezeiky.finance', 'ERROR'):
            with self.assertRaises(RuntimeError) as cm:
                softech_checks.expenses(self.period)
        self.assertNotIn('10.1.2.3', str(cm.exception))

    def test_reversal_pair_inside_month_nets_to_zero(self):
        e = self.post(100, D(2026, 3, 5), branch=self.b1)
        reverse(e.id, user=self.staff, reason='r')
        with mock.patch.object(softech_checks, 'sales', return_value={}),                 mock.patch.object(softech_checks, 'sales_detail', return_value=[]):
            compare.compute(self.period, check_keys=['t_sales'])
            self.assertEqual(GLComparisonLine.objects.filter(softech_check=self.sales).count(), 1)
            self.assertEqual(self.line(self.sales).ledger_amount, Z)
            # the branch-1 figures: both halves counted, netting to zero
            from apps.finance.gl.compare import _ledger_figures
            self.assertEqual(_ledger_figures(self.sales, self.period), {(self.b1.id, ''): Z})


class DetailTests(CompareBase):
    def test_detail_by_day_sums_to_line(self):
        self.post(100, D(2026, 3, 5), branch=self.b1)
        self.post(20, D(2026, 3, 5), branch=self.b1)
        self.post(30, D(2026, 3, 9), branch=self.b1)
        self.post(999, D(2026, 3, 9), branch=self.b2)         # other branch: not in this line
        rows = [{'date': D(2026, 3, 5), 'amount': _d(110)}, {'date': D(2026, 3, 11), 'amount': _d(25)}]
        with mock.patch.object(softech_checks, 'sales', return_value={('961', ''): _d(135)}), \
                mock.patch.object(softech_checks, 'sales_detail', return_value=rows) as sd:
            compare.compute(self.period, check_keys=['t_sales'])
            ln = self.line(self.sales, self.b1)
            out = compare.detail(ln.id)
        sd.assert_called_once_with(self.period, '961', '')
        self.assertEqual(sum((r['debit'] - r['credit']) * -1 for r in out['ledger']), ln.ledger_amount)
        self.assertEqual(sum(r['ledger'] for r in out['by_day']), ln.ledger_amount)
        self.assertEqual(sum(r['softech'] for r in out['by_day']), ln.softech_amount)
        self.assertEqual(sum(r['difference'] for r in out['by_day']), ln.difference)
        self.assertEqual([r['date'] for r in out['by_day']], [D(2026, 3, 5), D(2026, 3, 9), D(2026, 3, 11)])

    def test_balance_detail_opens_with_carried_balance(self):
        self.post(500, D(2026, 2, 10), debit='9103', credit='9100', branch=self.b1)
        self.post(200, D(2026, 3, 10), debit='9103', credit='9100', branch=self.b1)
        with mock.patch.object(softech_checks, 'stock_at_cost', return_value={('961', ''): _d(700)}),                 mock.patch.object(softech_checks, 'stock_at_cost_detail', return_value=[]):
            compare.compute(self.period, check_keys=['t_stock'])
            ln = self.line(self.stock, self.b1)
            out = compare.detail(ln.id)
        self.assertTrue(out['ledger'][0]['opening'])
        self.assertEqual(sum(r['debit'] - r['credit'] for r in out['ledger']), ln.ledger_amount)

    def test_balance_check_has_no_by_day(self):
        self.post(500, D(2026, 3, 10), debit='9103', credit='9100', branch=self.b1)
        with mock.patch.object(softech_checks, 'stock_at_cost', return_value={('961', ''): _d(500)}), \
                mock.patch.object(softech_checks, 'stock_at_cost_detail', return_value=[]):
            compare.compute(self.period, check_keys=['t_stock'])
            out = compare.detail(self.line(self.stock, self.b1).id)
        self.assertNotIn('by_day', out)
        self.assertEqual(len(out['ledger']), 1)   # no balance carried in: no opening row


class SeedTests(TestCase):
    def test_seed_checks_present(self):
        keys = {c.key: c for c in GLSoftechCheck.objects.filter(
            key__in=['sales', 'purchases', 'stock_at_cost', 'expenses', 'supplier_balance'])}
        self.assertEqual(set(keys), {'sales', 'purchases', 'stock_at_cost', 'expenses', 'supplier_balance'})
        self.assertTrue(keys['supplier_balance'].per_party)
        self.assertFalse(keys['supplier_balance'].blocks_close)
        self.assertFalse(keys['stock_at_cost'].blocks_close)
        self.assertEqual(keys['stock_at_cost'].account_codes, ['1390'])
