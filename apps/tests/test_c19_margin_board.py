"""
apps/tests/test_c19_margin_board.py

C19 / P-35 (docs/full-project-audit/08 §C19): one VAT-aligned margin basis (apps/analytics/margin.py) and the
«💹 الهامش: قناة × فرع» board. Reporting only — no price, discount or total changes.
"""
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
from .factories import make_admin, make_customer, make_item, make_user

BOARD = '/api/analytics/margin-board/'
SALES = '/api/analytics/sales/'
D = Decimal


class HelperTests(SimpleTestCase):

    def test_vat_item(self):
        from apps.analytics.margin import margin_pct, profit_ex_vat, revenue_ex_vat
        self.assertEqual(revenue_ex_vat(114, 14), D('100'))
        self.assertEqual(profit_ex_vat(114, 14, 70, 1), D('30'))
        self.assertEqual(margin_pct(D('30'), D('100')), 30.0)

    def test_non_vat_item_is_unchanged(self):
        from apps.analytics.margin import profit_ex_vat, revenue_ex_vat
        self.assertEqual(revenue_ex_vat(100, 0), D('100'))
        self.assertEqual(revenue_ex_vat(100, None), D('100'))
        self.assertEqual(profit_ex_vat(100, 0, 70, 1), D('30'))

    def test_old_basis_overstates_taxed_margin(self):
        from apps.analytics.margin import margin_pct, profit_ex_vat, revenue_ex_vat
        old = margin_pct(D('114') - D('70'), D('114'))                       # 38.6 %
        new = margin_pct(profit_ex_vat(114, 14, 70, 1), revenue_ex_vat(114, 14))   # 30 %
        self.assertGreater(old, new)
        self.assertEqual(new, 30.0)

    def test_no_revenue(self):
        from apps.analytics.margin import margin_pct
        self.assertEqual(margin_pct(5, 0), 0.0)


class _Sales(TestCase):

    def setUp(self):
        from apps.branches.models import Branch
        mk = lambda code, kind: Branch.objects.create(softech_branch_id=code, code=code, name=f'B{code}',
                                                     name_ar=f'B{code}', kind=kind, is_active=True)
        self.b130 = mk('130', Branch.KIND_RETAIL)
        self.b140 = mk('140', Branch.KIND_RETAIL)
        self.closed = mk('180', Branch.KIND_CLOSED)
        self.cust = make_customer()
        self.taxed = make_item('TAXED', 'TX1')
        self.taxed.sale_tax_pct = D('14')
        self.taxed.save(update_fields=['sale_tax_pct'])
        self.plain = make_item('PLAIN', 'PL1')
        self.n = 0

    def sale(self, branch, item, qty, total, cost, doc='115', channel='90'):
        self.n += 1
        p = PurchaseHistory.objects.create(customer=self.cust, branch=branch, doc_code=doc, total_amount=D(total),
                                           softech_invoice_id=f'C19-{self.n}', invoice_date=timezone.now(),
                                           sales_channel=channel)
        PurchaseHistoryLine.objects.create(purchase=p, item=item, quantity=D(qty), unit_price=D(total) / D(qty),
                                           line_total=D(total), cost_at_sale=D(cost))
        return p


class BoardTests(_Sales):

    def setUp(self):
        super().setUp()
        self.sale(self.b130, self.taxed, 1, 114, 70)                    # ex-VAT 100, profit 30
        self.sale(self.b130, self.plain, 2, 100, 30)                    # 100, profit 40
        self.sale(self.b140, self.taxed, 2, 228, 70, channel='91')      # 200, profit 60
        self.sale(self.b140, self.taxed, 1, 114, 70, doc='30', channel='91')   # return: −100, −30
        self.sale(self.b130, self.taxed, 5, 999, 1, doc='80')           # reservation preview: never counted
        _u, _s, self.client_ = make_admin('c19_admin')

    def test_cells_on_the_aligned_basis(self):
        r = self.client_.get(BOARD)
        self.assertEqual(r.status_code, 200)
        rows = {x['channel_code']: x for x in r.data['rows']}
        c = rows['90']['cells']['130']
        self.assertEqual((c['revenue'], c['revenue_ex_vat'], c['cogs'], c['profit_ex_vat']), (214.0, 200.0, 130.0, 70.0))
        self.assertEqual(c['margin_ex_vat_pct'], 35.0)
        self.assertEqual(c['profit_incl_vat'], 84.0)                   # the old figure, shown beside it
        c = rows['91']['cells']['140']                                  # net of the return
        self.assertEqual((c['revenue_ex_vat'], c['profit_ex_vat']), (100.0, 30.0))
        self.assertEqual(r.data['basis'], 'ex_vat')

    def test_totals_equal_the_sales_screen(self):
        board = self.client_.get(BOARD).data['total']
        s = self.client_.get(SALES).data['summary']
        self.assertEqual(board['revenue_ex_vat'], s['revenue_ex_vat'])
        self.assertEqual(board['profit_ex_vat'], s['profit_ex_vat'])
        self.assertEqual(board['margin_ex_vat_pct'], s['margin_ex_vat_pct'])
        self.assertEqual((board['revenue_ex_vat'], board['profit_ex_vat']), (300.0, 100.0))

    def test_existing_profit_fields_unchanged(self):
        s = self.client_.get(SALES).data['summary']
        # the old line-level profit: (114−70)+(100−60)+(228−140) − (114−70) = 128
        self.assertEqual(s['total_profit'], 128.0)

    def test_closed_branch_folds_into_other_without_its_code(self):
        self.sale(self.closed, self.plain, 1, 50, 20)
        r = self.client_.get(BOARD).data
        keys = [c['key'] for c in r['columns']]
        self.assertNotIn('180', keys)
        self.assertEqual(keys[-1], '__other__')
        self.assertEqual(r['total']['revenue_ex_vat'], 350.0)          # still equals the sales screen
        self.assertEqual(r['total']['revenue_ex_vat'], self.client_.get(SALES).data['summary']['revenue_ex_vat'])

    def _seed(self):
        from apps.tests.security.fixtures import seed_code_matrix
        from core.middleware import module_access
        seed_code_matrix()
        module_access.clear_cache()
        self.addCleanup(module_access.clear_cache)

    def test_branch_user_sees_own_branch_only(self):
        self._seed()
        _u, _s, client = make_user('c19_pharm', role='pharmacist', branch=self.b130)
        r = client.get(BOARD)
        self.assertEqual(r.status_code, 200)
        self.assertEqual([c['key'] for c in r.data['columns']], ['130'])
        self.assertEqual(r.data['total']['profit_ex_vat'], 70.0)

    def test_delivery_fees_per_branch_in_view(self):
        fees = self.client_.get(BOARD).data['delivery_fees']
        self.assertEqual((fees.get('130'), fees.get('140')), (0.0, 0.0))
        self.assertNotIn('180', fees)

    def test_without_analytics_rights(self):
        self._seed()
        _u, _s, client = make_user('c19_delivery', role='delivery', branch=self.b130)
        self.assertEqual(client.get(BOARD).status_code, 403)

    def test_nothing_is_written(self):
        before = list(PurchaseHistoryLine.objects.order_by('pk').values_list('pk', 'line_total', 'cost_at_sale'))
        self.client_.get(BOARD)
        self.assertEqual(list(PurchaseHistoryLine.objects.order_by('pk').values_list('pk', 'line_total',
                                                                                       'cost_at_sale')), before)
