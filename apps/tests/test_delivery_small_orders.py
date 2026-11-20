"""
C20 — delivery small-order and fee-less invoice report (apps/delivery/small_orders.py).

Rules under test: small (< 100 EGP of goods) and below the rider's pay (margin + fee < 10 EGP per
fee unit); a fee-less invoice is «unexplained» only without a fee-carrying invoice of the same
customer the same day or ±1 day; channel 90 sales only; branch scope; Excel formulas neutralised.
"""
import datetime as dt
import io
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.delivery import small_orders as SO
from apps.tests.factories import make_admin, make_branch, make_branch2, make_customer, make_item, make_user

URL = '/api/delivery/small-orders/'
N = [0]


def _inv(branch, day, lines, *, pic='01HD1', channel='90', doc='115', customer=None):
    """lines: [(item, qty, line_total, unit_cost)]"""
    from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
    N[0] += 1
    inv = PurchaseHistory.objects.create(
        customer=customer or make_customer(), softech_invoice_id=f'C20-{N[0]}', branch=branch, doc_code=doc,
        docnumber=str(1000 + N[0]), sales_channel=channel, softech_phcode=pic,
        invoice_date=timezone.make_aware(dt.datetime.combine(day, dt.time(14, 0))),
        total_amount=sum(Decimal(str(t)) for _, _, t, _ in lines))
    for item, qty, total, cost in lines:
        PurchaseHistoryLine.objects.create(purchase=inv, item=item, quantity=Decimal(str(qty)),
                                           unit_price=Decimal(str(total)) / Decimal(str(qty)),
                                           line_total=Decimal(str(total)), cost_at_sale=Decimal(str(cost)))
    return inv


D = dt.date(2026, 11, 10)


class RuleTests(SimpleTestCase):
    def test_classify(self):
        # 80 goods, cost 75, fee 13 on 1 unit → margin 18 ≥ rider 10, but small
        self.assertEqual(SO.classify(Decimal('80'), Decimal('75'), Decimal('13'), Decimal('1')),
                         (Decimal('18'), Decimal('10'), True, False))
        # 300 goods, cost 296, no fee → margin 4 < rider 10 (one ride at least)
        self.assertEqual(SO.classify(Decimal('300'), Decimal('296'), Decimal('0'), Decimal('0'))[3], True)
        # 2 fee units → rider 20
        self.assertEqual(SO.classify(Decimal('300'), Decimal('290'), Decimal('26'), Decimal('2'))[1], Decimal('20'))

    def test_companion_within_one_day(self):
        fee_days = {'pic:A': {D}}
        self.assertTrue(SO.has_companion('pic:A', D, fee_days))
        self.assertTrue(SO.has_companion('pic:A', D + dt.timedelta(days=1), fee_days))
        self.assertTrue(SO.has_companion('pic:A', D - dt.timedelta(days=1), fee_days))
        self.assertFalse(SO.has_companion('pic:A', D + dt.timedelta(days=2), fee_days))
        self.assertFalse(SO.has_companion('pic:B', D, fee_days))


class ReportTests(TestCase):
    def setUp(self):
        self.b = make_branch()
        self.fee = make_item(name='D.L.V.', softech_id='2')
        self.drug = make_item(name='دواء', softech_id='DR01')

    def build(self, start=D, end=D):
        from apps.customers.models import PurchaseHistory
        return SO.build(PurchaseHistory.objects.all(), start, end)

    def test_small_and_below_rider_flags(self):
        _inv(self.b, D, [(self.drug, 1, 80, 75), (self.fee, 1, 13, 0)], pic='S1')        # small only
        _inv(self.b, D, [(self.drug, 1, 300, 298), (self.fee, 1, 13, 0)], pic='S2')      # 15 ≥ 10: fine
        _inv(self.b, D, [(self.drug, 1, 500, 499), (self.fee, 2, 6, 0)], pic='S3')       # 7 < 20: below rider
        rep = self.build()
        flags = {r['pic']: (r['small'], r['below_rider']) for r in rep['orders']}
        self.assertEqual(flags, {'S1': (True, False), 'S3': (False, True)})
        self.assertEqual((rep['totals']['orders'], rep['totals']['small'], rep['totals']['below_rider']), (3, 1, 1))
        self.assertEqual(rep['by_branch'][0]['fees'], 32.0)

    def test_feeless_explained_by_a_companion_the_day_before(self):
        _inv(self.b, D - dt.timedelta(days=1), [(self.drug, 1, 400, 300), (self.fee, 1, 13, 0)], pic='C1')
        _inv(self.b, D, [(self.drug, 1, 400, 300)], pic='C1')                            # companion → explained
        _inv(self.b, D, [(self.drug, 1, 400, 300)], pic='C2')                            # nobody → unexplained
        rep = self.build()
        self.assertEqual([r['pic'] for r in rep['orders']], ['C2'])
        self.assertEqual((rep['totals']['feeless'], rep['totals']['feeless_unexplained']), (2, 1))
        self.assertEqual(rep['by_branch'][0]['feeless_goods'], 400.0)

    def test_only_channel_90_sales_in_the_window(self):
        _inv(self.b, D, [(self.drug, 1, 50, 10)], channel='91')                          # cash counter
        _inv(self.b, D, [(self.drug, 1, 50, 10)], doc='30')                              # a return
        _inv(self.b, D + dt.timedelta(days=1), [(self.drug, 1, 50, 10)])                 # outside the window
        self.assertEqual(self.build()['totals']['orders'], 0)

    def test_excel_neutralises_formulas_and_labels_branches(self):
        from openpyxl import load_workbook
        _inv(self.b, D, [(self.drug, 1, 50, 10)], customer=make_customer(name='=HYPERLINK("x")', phone='01000000099'))
        wb = load_workbook(io.BytesIO(SO.to_excel(self.build())))
        cells = [c for ws in wb.worksheets for row in ws.iter_rows() for c in row]
        self.assertEqual([c.coordinate for c in cells if c.data_type == 'f'], [])
        self.assertIn(f'{self.b.softech_branch_id} · {self.b.name_ar or self.b.name}',
                      [c.value for c in wb['حسب الفرع']['A']])


class ApiTests(TestCase):
    def setUp(self):
        from apps.tests.security.fixtures import seed_code_matrix
        from core.middleware import module_access
        seed_code_matrix()
        self.addCleanup(module_access.clear_cache)
        self.b1, self.b2 = make_branch(), make_branch2()
        self.drug = make_item(name='دواء', softech_id='DR02')
        _inv(self.b1, D, [(self.drug, 1, 50, 10)], pic='B1')
        _inv(self.b2, D, [(self.drug, 1, 50, 10)], pic='B2')

    def test_admin_sees_every_branch_and_excel(self):
        _, _, c = make_admin('c20_admin')
        r = c.get(URL, {'date_from': D.isoformat(), 'date_to': D.isoformat()})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(sorted(o['pic'] for o in r.json()['orders']), ['B1', 'B2'])
        x = c.get(URL, {'date_from': D.isoformat(), 'date_to': D.isoformat(), 'format': 'xlsx'})
        self.assertIn('spreadsheetml', x['Content-Type'])
        self.assertEqual(c.get(URL, {'date_from': 'x'}).status_code, 400)

    def test_pharmacist_sees_own_branch_only(self):
        _, _, c = make_user('c20_pharm', role='pharmacist', branch=self.b1)
        r = c.get(URL, {'date_from': D.isoformat(), 'date_to': D.isoformat()})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([o['pic'] for o in r.json()['orders']], ['B1'])
        r = c.get(URL, {'date_from': D.isoformat(), 'date_to': D.isoformat(), 'branch': self.b2.id})
        self.assertEqual(r.json()['orders'], [])                       # ?branch= never widens the scope

    def test_rider_refused(self):
        _, _, c = make_user('c20_rider', role='delivery', branch=self.b1)
        self.assertEqual(c.get(URL).status_code, 403)

    def test_anonymous_refused(self):
        from rest_framework.test import APIClient
        self.assertIn(APIClient().get(URL).status_code, (401, 403))
