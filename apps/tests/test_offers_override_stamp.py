"""
apps/tests/test_offers_override_stamp.py

The Ctrl+M / OFFERS manager-override stamp. Verified live (2026-08-30): SOFTECH
records a Ctrl+M-authorized discount as stktransm5.supp_main_code = <manager
usercode> (89 = OFFERS). Our writer must set that on an offer-discounted order so
the discount is pre-authorized at settlement. Pure header build — no SOFTECH.
"""
from decimal import Decimal
from django.test import TestCase, override_settings

from apps.pos_orders.models import SoftechSalesOrder, SoftechSalesOrderLine
from apps.pos_orders.writer import _header_row
from .factories import make_branch, make_item


def _order(branch):
    return SoftechSalesOrder.objects.create(
        branch=branch, softech_branchcode=branch.softech_branch_id, store_code='1',
        seller_usercode='1', softech_pic='PIC', channel='cash')


def _line(o, source, discp):
    it = make_item(name='X', softech_id='X1')
    return SoftechSalesOrderLine.objects.create(
        order=o, item=it, softech_itemcode='X1', qty=1, item_sale_price=100,
        cust_discp=Decimal(str(discp)), discount_source=source)


class OverrideStampTests(TestCase):
    def setUp(self):
        self.branch = make_branch()

    def test_offer_line_stamps_supp_main_code(self):
        o = _order(self.branch)
        _line(o, 'offer', 100)
        h = _header_row(o, docnumber=1, seller='1')
        self.assertEqual(h['supp_main_code'], '89')      # OFFERS override usercode

    def test_manual_line_no_stamp(self):
        o = _order(self.branch)
        _line(o, 'manual', 10)
        h = _header_row(o, docnumber=1, seller='1')
        self.assertEqual(h['supp_main_code'], '')        # native default

    def test_offer_line_zero_discount_no_stamp(self):
        o = _order(self.branch)
        _line(o, 'offer', 0)                              # offer-tagged but no discount
        h = _header_row(o, docnumber=1, seller='1')
        self.assertEqual(h['supp_main_code'], '')

    @override_settings(POS_OFFERS_OVERRIDE_USERCODE='77')
    def test_override_usercode_is_configurable(self):
        o = _order(self.branch)
        _line(o, 'offer', 100)
        h = _header_row(o, docnumber=1, seller='1')
        self.assertEqual(h['supp_main_code'], '77')
