"""
Round 2 / R2 — POS order money correctness (docs/security/2026-11-05-full-project-test-plan.md §7 R2).

Sources of every expected value (cited per table):
  [6d]  docs/architecture/SOFTECH_INDIRECT_POS_ORDER_WRITEBACK.md §6d "Computed-field formulas (CONFIRMED)":
          transprice        = round(itemsaleprice × (1 − custdiscp/100), 2)
          transprice_total  = transprice × transqty
          itemsalestax      = transprice_total − transprice_total/(1 + taxp/100)   (VAT is INSIDE the price)
          docvalue = Σ transprice_total;  docvalue2 = Σ newcostprice·qty;  docvalue3 = Σ itemsalestax
        Goldens: order 468730 (207.5 @14% → tax 25.4825, ex-VAT 182.0175; header 217.5 / VAT 26.71 /
        COGS 154.65) and contract order 451978 (315×(1−.06)=296.1, ×2 = 592.2; 79×(1−.17)=65.57).
        apps/pos_orders/pricing.py rounds half-up (2 dp money, 4 dp tax).
  [pts] apps/pos_orders/points.py (verified live 2026-08-19) / memory "SOFTECH POS Points Mechanism":
          personnewbal = Σ per line floor(line_net × rate[line] / 100); cash + delivery earn only;
          a discounted line earns no points (DISCOUNT ⊻ POINTS); a return is signed −1.
  [Q]   apps/pos_orders/writer.py strips_to_qty: Q = round(K / packqty, 5) half-up, verified on
        production stktrans 2/3→0.66667, 5/7→0.71429, 20/7→2.85714; loose units = round(frac(Q)×packqty).

Note on the plan's R2 wording: the plan table writes "gross × (1 − d1) × (1 − d2)" and "VAT = net × rate".
The SOFTECH POS line carries ONE effective discount (custdiscp — the doc above: pharmacy/additional/special
discounts land in custdiscp) and its VAT is the tax INSIDE the VAT-inclusive net. These tests follow the
confirmed SOFTECH formulas, which is what the writer must reproduce; the (1−d1)(1−d2) form is the
purchase-invoice cost formula (apps/invoices/softech_columns.py), not the POS sale line.
No SOFTECH contact: prepare_order runs with live=False (offline values), points use a fake reader.
"""
import math
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from unittest import mock

from django.test import SimpleTestCase, TestCase

from apps.pos_orders import pricing, writer
from apps.pos_orders import points as P
from apps.pos_orders.models import SoftechSalesOrder, SoftechSalesOrderLine

from .factories import make_branch

D = Decimal
C2 = D('0.01')


def _half_up(v, q=C2):
    return D(v).quantize(q, rounding=ROUND_HALF_UP)


# ── [6d] line table: (label, itemsaleprice, tax %, qty, custdiscp) → (transprice, total, itemsalestax) ──
LINES = [
    ('golden 468730 (14% VAT, no disc)', '207.5', '14', '1', '0',  '207.50', '207.50', '25.4825'),
    ('golden 451978 contract 6% ×2',     '315',   '0',  '2', '6',  '296.10', '592.20', '0.0000'),
    ('golden 451978 contract 17%',       '79',    '0',  '1', '17', '65.57',  '65.57',  '0.0000'),
    ('half-up at the cent (0.025→0.03)', '0.05',  '0',  '3', '50', '0.03',   '0.09',   '0.0000'),
    ('half-up 4dp VAT',                  '10',    '14', '1', '0',  '10.00',  '10.00',  '1.2281'),
    ('15% contract, 14% VAT, ×3',        '108',   '14', '3', '15', '91.80',  '275.40', '33.8211'),
    ('100% discount',                    '55.55', '0',  '2', '100', '0.00',  '0.00',   '0.0000'),
    ('pack fraction qty (2/3 strip)',    '90',    '0',  '0.66667', '0', '90.00', '60.00', '0.0000'),
]


class LineFormulaTests(SimpleTestCase):
    def test_line_table(self):
        for label, isp, tax, qty, disc, tp, total, vat in LINES:
            with self.subTest(label):
                c = pricing.compute_line(item_sale_price=isp, sale_tax_pct=tax, qty=D(qty), cust_discp=disc)
                self.assertEqual(c['trans_price'], D(tp))
                self.assertEqual(c['trans_price_total'], D(total))
                self.assertEqual(c['item_sale_tax'], D(vat))
                # the same values, re-derived from the [6d] formulas in this test
                exp_tp = _half_up(D(isp) * (1 - D(disc) / 100))
                exp_total = _half_up(exp_tp * D(qty))
                self.assertEqual((exp_tp, exp_total), (D(tp), D(total)))
                if D(tax):
                    exp_vat = (exp_total - exp_total / (1 + D(tax) / 100)).quantize(D('0.0001'), ROUND_HALF_UP)
                    self.assertEqual(c['item_sale_tax'], exp_vat)
                self.assertEqual(c['line_gross'], _half_up(D(isp) * D(qty)))

    def test_golden_ex_vat_price(self):
        c = pricing.compute_line(item_sale_price='207.5', sale_tax_pct='14', qty=1, cust_discp=0)
        self.assertEqual(c['item_sale_price_tax'], D('182.0175'))      # [6d] golden 468730

    def test_header_is_the_sum_of_lines_golden_468730(self):
        lines = [pricing.compute_line(item_sale_price='207.5', sale_tax_pct='14', qty=1, cust_discp=0,
                                      new_cost_price='154.649'),
                 pricing.compute_line(item_sale_price='10', sale_tax_pct='14', qty=1, cust_discp=0)]
        h = pricing.compute_header(lines)
        self.assertEqual(h['doc_value'], D('217.50'))
        self.assertEqual(h['doc_value_tax'], D('26.71'))
        self.assertEqual(h['doc_value_cogs'], D('154.65'))
        self.assertEqual(h['doc_value'], sum((l['trans_price_total'] for l in lines), D('0')))

    def test_money_is_decimal_never_float(self):
        c = pricing.compute_line(item_sale_price=0.1, sale_tax_pct=14, qty=3, cust_discp=0)
        for k, v in c.items():
            self.assertIsInstance(v, Decimal, k)
        self.assertEqual(c['trans_price_total'], D('0.30'))            # not 0.30000000000000004


class OrderTotalTests(TestCase):
    """prepare_order (offline) stores line nets and a header that is exactly their sum [6d]."""

    def _order(self, rows, channel='cash'):
        br = make_branch()
        o = SoftechSalesOrder.objects.create(
            branch=br, softech_branchcode=br.softech_branch_id, store_code=br.softech_branch_id[:3],
            channel=channel, doc_kind='sale', customer_name='R2', seller_usercode='2050')
        for i, (isp, tax, qty, disc, cost) in enumerate(rows):
            SoftechSalesOrderLine.objects.create(
                order=o, item=None, softech_itemcode=f'R2{i}', item_name=f'L{i}', qty=D(qty),
                item_sale_price=D(isp), sale_tax_pct=D(tax), cust_discp=D(disc), new_cost_price=D(cost))
        return o

    def test_order_total_is_sum_of_line_nets(self):
        rows = [('207.5', '14', '1', '0', '154.649'), ('108', '14', '3', '15', '81.1306'),
                ('0.05', '0', '3', '50', '0'), ('90', '0', '0.66667', '0', '60')]
        o = self._order(rows)
        expected = sum((D(l[6]) for l in (LINES[0], LINES[5], LINES[3], LINES[7])), D('0'))  # 542.99
        writer.prepare_order(o, tenders=[{'pay_type': 'cash', 'amount': str(expected)}])
        o.refresh_from_db()
        nets = [l.trans_price_total for l in o.lines.order_by('id')]
        self.assertEqual(nets, [D('207.50'), D('275.40'), D('0.09'), D('60.00')])
        self.assertEqual(o.doc_value, sum(nets, D('0')))
        self.assertEqual(o.doc_value, expected)
        vat = sum((l.item_sale_tax for l in o.lines.all()), D('0'))
        self.assertEqual(o.doc_value_tax, _half_up(vat))                     # docvalue3 = Σ itemsalestax
        self.assertEqual(o.doc_value_gross, D('207.50') + D('324.00') + D('0.15') + D('60.00'))
        self.assertEqual(sum((p.amount for p in o.payments.all()), D('0')), o.doc_value)

    def test_tenders_must_equal_the_total(self):
        o = self._order([('108', '0', '1', '15', '0')])                       # net 91.80
        # writer.prepare_order allows a 1-cent tolerance (|tenders − due| > 0.01 is refused)
        for amount in ('91.78', '91.82', '0'):
            with self.subTest(amount), self.assertRaises(ValueError):
                writer.prepare_order(o, tenders=[{'pay_type': 'cash', 'amount': amount}])
        writer.prepare_order(o, tenders=[{'pay_type': 'cash', 'amount': '50'},
                                         {'pay_type': 'card', 'amount': '41.80'}])
        o.refresh_from_db()
        self.assertEqual(o.doc_value, D('91.80'))

    def test_contract_copay_split_sums_to_the_total(self):
        # writer._contract_copay_tenders: patient = round(pct% × base, 2) half-up, company = total − patient.
        o = self._order([('315', '0', '2', '6', '0')], channel='contract')   # net 592.20, gross 630
        with mock.patch.object(writer, 'read_contract_copay',
                               return_value={'patient_paypercent': 25, 'patient_paytype': '1'}):
            t = writer._contract_copay_tenders(o, D('592.20'), D('630.00'))
        self.assertEqual(t, [{'pay_type': 'cash', 'amount': '157.50'},        # 25% of gross 630
                             {'pay_type': 'credit', 'amount': '434.70'}])
        self.assertEqual(sum((D(x['amount']) for x in t), D('0')), D('592.20'))


class _FakeReader:
    """Stands in for DiscountAuthorityReader: channel rep, items.itemcode_alt3 and custdiscounts rates."""
    def __init__(self, alt3, rates, rep='CashCust'):
        self.alt3, self.rates, self.rep = alt3, rates, rep

    def customer_personcode(self, channel):
        return self.rep

    def item_alt3(self, itemcode):
        return self.alt3.get(itemcode)

    def contracted(self, personcode, alt3):
        r = self.rates.get(alt3)
        return None if r is None else (r, 1)

    def close(self):
        pass


# [pts] (label, [(itemcode, net)], {itemcode: alt3}, {alt3: rate%}, expected points)
POINTS = [
    ('per-line floor then sum (shape of the verified 853 basket: 15+28+88+90)',
     [('a', '150.00'), ('b', '280.50'), ('c', '880.99'), ('d', '900.00')],
     {'a': 'X', 'b': 'X', 'c': 'X', 'd': 'X'}, {'X': 10}, 15 + 28 + 88 + 90),
    ('floor per line, not of the sum', [('a', '19.99'), ('b', '19.99')], {'a': 'X', 'b': 'X'}, {'X': 5}, 0),
    ('mixed rates and an unrated item', [('a', '100'), ('b', '100'), ('c', '100')],
     {'a': 'H', 'b': 'L', 'c': None}, {'H': D('7.5'), 'L': 2}, 7 + 2),
    ('exact integer boundary', [('a', '40.00')], {'a': 'X'}, {'X': D('2.5')}, 1),
]


class PointsTests(SimpleTestCase):
    def test_points_table(self):
        for label, lines, alt3, rates, expected in POINTS:
            with self.subTest(label):
                total, breakdown = P.compute_points(_FakeReader(alt3, rates), 'cash',
                                                    [(c, D(n)) for c, n in lines])
                self.assertEqual(total, expected)
                # re-derived with Decimal: Σ floor(net × rate / 100)
                exact = sum(int((D(n) * D(str(rates.get(alt3.get(c)) or 0)) / 100)
                                .to_integral_value(rounding=ROUND_FLOOR)) for c, n in lines)
                self.assertEqual(total, exact)
                self.assertEqual(total, sum(b['points'] for b in breakdown))

    def test_only_cash_and_delivery_earn(self):
        r = _FakeReader({'a': 'X'}, {'X': 10})
        for channel, earns in (('cash', True), ('delivery', True), ('contract', False),
                               ('insurance', False), ('employee', False)):
            with self.subTest(channel):
                total, _ = P.compute_points(r, channel, [('a', D('100'))])
                self.assertEqual(total, 10 if earns else 0)

    def test_return_is_negative(self):
        total, _ = P.compute_points(_FakeReader({'a': 'X'}, {'X': 10}), 'cash', [('a', D('155'))], sign=-1)
        self.assertEqual(total, -15)


class OrderPointsTests(TestCase):
    def test_discounted_line_earns_no_points(self):
        br = make_branch()
        o = SoftechSalesOrder.objects.create(branch=br, softech_branchcode=br.softech_branch_id, store_code='1',
                                             channel='cash', seller_usercode='1')
        for code, disc, net in (('a', '0', '200.00'), ('b', '10', '180.00')):
            SoftechSalesOrderLine.objects.create(order=o, item=None, softech_itemcode=code, qty=1,
                                                 item_sale_price=D('200'), cust_discp=D(disc),
                                                 trans_price_total=D(net))
        fake = _FakeReader({'a': 'X', 'b': 'X'}, {'X': 10})
        with mock.patch('apps.pos_orders.discount_authority.DiscountAuthorityReader', return_value=fake):
            total, _ = P.order_points(o)
        self.assertEqual(total, 20)                                             # line b: 0 (discount ⊻ points)


# [Q] (K strips, packqty) → Q
STRIPS = [(2, 3, '0.66667'), (5, 7, '0.71429'), (20, 7, '2.85714'), (1, 3, '0.33333'), (1, 8, '0.12500'),
          (1, 64, '0.01563'),   # 0.015625 → half-up 0.01563 (half-even would give 0.01562)
          (3, 1, '3'), (0, 5, '0.00000'), (10, 10, '1.00000')]


class StripQuantityTests(SimpleTestCase):
    def test_strip_table(self):
        for k, n, q in STRIPS:
            with self.subTest(k=k, n=n):
                self.assertEqual(writer.strips_to_qty(k, n), D(q))
                if n > 1:
                    self.assertEqual(writer.strips_to_qty(k, n),
                                     (D(k) / D(n)).quantize(D('0.00001'), rounding=ROUND_HALF_UP))

    def test_loose_units_round_trip(self):
        # SOFTECH's pharmacydiscp = round(frac(Q) × packqty) must give back the strips sold.
        for n in range(2, 61):
            for k in range(0, 3 * n):
                q = writer.strips_to_qty(k, n)
                with self.subTest(k=k, n=n):
                    self.assertEqual(writer.loose_units_from_qty(q, n), k % n)
                    self.assertEqual(math.floor(q), k // n)
