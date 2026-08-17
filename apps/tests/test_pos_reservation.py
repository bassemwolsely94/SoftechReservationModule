"""
apps/tests/test_pos_reservation.py — حجز (doccode 80) header/line builders.
(Live write/probe needs SOFTECH; here we test the pure row builders + the gate.)
"""
from decimal import Decimal
from django.test import TestCase

from apps.pos_orders.models import SoftechSalesOrder, SoftechSalesOrderLine
from apps.pos_orders import reservation as R
from apps.pos_orders.writer import _Raw, WriterDisabled
from .factories import make_branch


def _order(**kw):
    br = make_branch()
    return SoftechSalesOrder.objects.create(
        branch=br, softech_branchcode=br.softech_branch_id, store_code='130',
        seller_usercode='1309', softech_pic='130HD14190', channel='cash',
        doc_value=Decimal('715.54'), **kw)


def _line(o):
    return SoftechSalesOrderLine.objects.create(
        order=o, softech_itemcode='123538', qty=Decimal('0.4'),
        item_sale_price=Decimal('1883'), cust_discp=Decimal('5'),
        trans_price=Decimal('1788.85'), trans_price_total=Decimal('715.54'))


class ReservationBuilderTests(TestCase):
    def test_header_links_sale_via_docnumber2(self):
        o = _order()
        h = R._hagz_header(o, docnumber=33999, sale_docnumber=452840, seller='1309', doc_value=715.54)
        self.assertEqual(h['doccode'], '80')
        self.assertEqual(h['docnumber'], 33999)
        self.assertEqual(h['docnumber2'], 452840)          # ← links to the sale
        self.assertEqual(h['cust_branch_code'], '-80')
        self.assertEqual(h['ptclassifcode'], '-1')
        self.assertEqual(h['origdoc'], '5')

    def test_line_is_stock_in_with_placeholder_expiry(self):
        o = _order(); ln = _line(o)
        row = R._hagz_line(o, ln, docnumber=33999, sale_docnumber=452840, seller='1309')
        self.assertEqual(row['doccode'], '80')
        self.assertEqual(row['transqty'], 0.4)
        self.assertEqual(row['newqty'], 0.4)               # ← stock injected = transqty
        self.assertEqual(row['r_doccode'], '115')
        self.assertEqual(row['r_docnumber'], 452840)       # ← references the sale
        self.assertEqual(row['item_partno'], 'Reservation')
        self.assertIsInstance(row['itemexpirydate'], _Raw)  # placeholder date literal
        self.assertIn('2012-12-11', row['itemexpirydate'].sql)

    def test_push_requires_gate_and_confirm(self):
        o = _order(); _line(o)
        # writer disabled by default in tests → must raise (no SOFTECH contacted)
        with self.assertRaises(WriterDisabled):
            R.push_reservation(o, sale_docnumber=452840, confirm=True)
