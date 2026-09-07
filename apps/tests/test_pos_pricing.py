"""
apps/tests/test_pos_pricing.py

Locks in the empirically-validated SOFTECH pricing formulas (spec §6d) so a
refactor can never silently break the money math. Pure functions — no DB.
Reference data: real branch-130 orders 468740 (contract) and 468770 (cash).
"""
from decimal import Decimal
from django.test import SimpleTestCase

from apps.pos_orders import pricing


class LineComputationTests(SimpleTestCase):
    def test_contract_line_468740_item1(self):
        # item 108 @ 15% discount, tax 0 → transprice 91.80
        c = pricing.compute_line(item_sale_price=108, sale_tax_pct=0, qty=1,
                                 cust_discp=15, new_cost_price=81.1306)
        self.assertEqual(c['trans_price'], Decimal('91.80'))
        self.assertEqual(c['trans_price_total'], Decimal('91.80'))
        self.assertEqual(c['line_gross'], Decimal('108.00'))
        self.assertEqual(c['line_cogs'], Decimal('81.13'))

    def test_contract_line_468740_item2(self):
        c = pricing.compute_line(item_sale_price=216, sale_tax_pct=0, qty=1,
                                 cust_discp=15, new_cost_price=162.0824)
        self.assertEqual(c['trans_price'], Decimal('183.60'))
        self.assertEqual(c['trans_price_total'], Decimal('183.60'))

    def test_tax_inclusive_split_14pct(self):
        # 14% VAT-inclusive: tax portion of a 207.5 line = 207.5 - 207.5/1.14
        c = pricing.compute_line(item_sale_price=207.5, sale_tax_pct=14, qty=1,
                                 cust_discp=0, new_cost_price=0)
        self.assertEqual(c['trans_price_total'], Decimal('207.50'))
        self.assertEqual(c['item_sale_tax'], Decimal('25.4825'))
        self.assertEqual(c['item_sale_price_tax'], Decimal('182.0175'))

    def test_zero_tax_no_vat(self):
        c = pricing.compute_line(item_sale_price=100, sale_tax_pct=0, qty=2,
                                 cust_discp=0, new_cost_price=0)
        self.assertEqual(c['item_sale_tax'], Decimal('0.0000'))
        self.assertEqual(c['trans_price_total'], Decimal('200.00'))

    def test_quantity_multiplies_total(self):
        c = pricing.compute_line(item_sale_price=10, sale_tax_pct=0, qty=3,
                                 cust_discp=10, new_cost_price=4)
        self.assertEqual(c['trans_price'], Decimal('9.00'))
        self.assertEqual(c['trans_price_total'], Decimal('27.00'))
        self.assertEqual(c['line_cogs'], Decimal('12.00'))

    def test_rounding_half_up(self):
        # 33.33 * (1 - 0/100) * 1 ; check 2dp half-up on an odd value
        c = pricing.compute_line(item_sale_price='33.335', sale_tax_pct=0, qty=1,
                                 cust_discp=0, new_cost_price=0)
        self.assertEqual(c['trans_price'], Decimal('33.34'))


class HeaderComputationTests(SimpleTestCase):
    def test_header_aggregates_468740(self):
        l1 = pricing.compute_line(item_sale_price=108, sale_tax_pct=0, qty=1,
                                  cust_discp=15, new_cost_price=81.1306)
        l2 = pricing.compute_line(item_sale_price=216, sale_tax_pct=0, qty=1,
                                  cust_discp=15, new_cost_price=162.0824)
        h = pricing.compute_header([l1, l2])
        self.assertEqual(h['doc_value'], Decimal('275.40'))        # net
        self.assertEqual(h['doc_value_gross'], Decimal('324.00'))  # docvalue1 (pre-discount)
        self.assertEqual(h['doc_value_cogs'], Decimal('243.21'))   # docvalue2 (COGS)
        self.assertEqual(h['doc_value_tax'], Decimal('0.00'))      # docvalue3 (tax-exempt items)

    def test_header_empty(self):
        h = pricing.compute_header([])
        self.assertEqual(h['doc_value'], Decimal('0.00'))


class PaymentSplitTests(SimpleTestCase):
    def test_pure_cash_full_collected_no_patient_payment(self):
        # cash sale 4000 (order 468770): docvaluepay=4000, patientpayment=0
        pay, patient, norm = pricing.split_payment('cash', Decimal('4000.00'))
        self.assertEqual(pay, Decimal('4000.00'))
        self.assertEqual(patient, Decimal('0.00'))
        self.assertEqual(norm, [{'pay_type': 'cash', 'amount': Decimal('4000.00')}])

    def test_contract_mixed_split_468740(self):
        # 64.8 cash + 210.6 credit = 275.4 ; docvaluepay=64.8, patientpayment=64.8
        pay, patient, norm = pricing.split_payment(
            'contract', Decimal('275.40'),
            [{'pay_type': 'cash', 'amount': '64.80'}, {'pay_type': 'credit', 'amount': '210.60'}],
        )
        self.assertEqual(pay, Decimal('64.80'))      # only the non-credit portion is collected now
        self.assertEqual(patient, Decimal('64.80'))  # cash down-payment on a credit sale

    def test_contract_default_full_credit(self):
        pay, patient, norm = pricing.split_payment('contract', Decimal('500.00'))
        self.assertEqual(pay, Decimal('0.00'))       # nothing collected now
        self.assertEqual(norm, [{'pay_type': 'credit', 'amount': Decimal('500.00')}])

    def test_delivery_collected_in_full(self):
        pay, patient, norm = pricing.split_payment('delivery', Decimal('120.00'))
        self.assertEqual(pay, Decimal('120.00'))
        self.assertEqual(patient, Decimal('0.00'))
