"""
Platform accounts are 100% آجل (doc 38, owner 2026-11-18).

A marketplace platform's SOFTECH account is classed «عميل دائم» (channel 'permanent'), whose sales normally
default to cash. On a platform account the writer must default to one credit tender, refuse a cash/card tender,
refund credit on a return, and the validator must flag a non-credit payment row. Other «عميل دائم» sales keep
their cash default. No SOFTECH contact (live=False).
"""
from decimal import Decimal

from django.test import TestCase

from apps.marketplace.models import MarketplaceChannel
from apps.pos_orders import writer
from apps.pos_orders.models import SoftechSalesOrder, SoftechSalesOrderLine, SoftechSalesOrderPayment
from apps.pos_orders.platform_accounts import CREDIT_ONLY_MSG, is_platform_account, is_platform_order
from apps.pos_orders.validators import validate_order
from rest_framework.exceptions import ValidationError

from .factories import make_branch


def _order(account, channel='permanent'):
    br = make_branch()
    o = SoftechSalesOrder.objects.create(
        branch=br, softech_branchcode=br.softech_branch_id, store_code=br.softech_branch_id[:3],
        channel=channel, doc_kind='sale', softech_pic='130HD9668', cust_branch_code=account,
        customer_name='TEST', seller_usercode='2050')
    SoftechSalesOrderLine.objects.create(order=o, item=None, softech_itemcode='107295', item_name='ITM1',
                                         qty=2, item_sale_price=50, sale_tax_pct=0, cust_discp=0,
                                         new_cost_price='40')
    return o


class PlatformCreditTests(TestCase):
    def setUp(self):
        MarketplaceChannel.objects.create(code='tlb', name='طلبات', softech_personcode='4292')

    def test_platform_account_lookup(self):
        self.assertTrue(is_platform_account(' 4292 '))
        self.assertFalse(is_platform_account('4846'))
        self.assertFalse(is_platform_account(''))
        self.assertFalse(is_platform_order(_order('4292', channel='cash')))   # anonymous channel: never

    def test_platform_sale_defaults_to_full_credit(self):
        o = _order('4292')
        writer.prepare_order(o)
        o.refresh_from_db()
        self.assertEqual(o.doc_value, Decimal('100.00'))
        self.assertEqual(o.doc_value_pay, Decimal('0.00'))          # nothing collected into the drawer
        self.assertEqual(list(o.payments.values_list('pay_type', 'amount')), [('credit', Decimal('100.00'))])

    def test_platform_sale_refuses_cash_tender(self):
        o = _order('4292')
        with self.assertRaisesMessage(ValueError, CREDIT_ONLY_MSG):
            writer.prepare_order(o, tenders=[{'pay_type': 'cash', 'amount': '100'}])
        with self.assertRaisesMessage(ValueError, CREDIT_ONLY_MSG):
            writer.prepare_order(o, tenders=[{'pay_type': 'credit', 'amount': '60'},
                                             {'pay_type': 'card', 'amount': '40'}])
        o.refresh_from_db()
        self.assertEqual(o.status, SoftechSalesOrder.STATUS_DRAFT)
        self.assertFalse(o.payments.exists())

    def test_platform_sale_accepts_explicit_credit(self):
        o = _order('4292')
        writer.prepare_order(o, tenders=[{'pay_type': 'credit', 'amount': '100'}])
        o.refresh_from_db()
        self.assertEqual(list(o.payments.values_list('pay_type', flat=True)), ['credit'])

    def test_other_permanent_customer_keeps_cash_default(self):
        o = _order('4846')
        writer.prepare_order(o)
        o.refresh_from_db()
        self.assertEqual(list(o.payments.values_list('pay_type', 'amount')), [('cash', Decimal('100.00'))])
        self.assertEqual(o.doc_value_pay, Decimal('100.00'))

    def test_validator_flags_cash_row_on_platform_account(self):
        o = _order('4292')
        SoftechSalesOrderPayment.objects.create(order=o, pay_type='cash', amount=Decimal('100'))
        with self.assertRaises(ValidationError) as cm:
            validate_order(o)
        self.assertEqual(cm.exception.detail['payments_detail'][0]['pay_type'], CREDIT_ONLY_MSG)

    def test_validator_allows_credit_row_on_platform_account(self):
        o = _order('4292')
        SoftechSalesOrderPayment.objects.create(order=o, pay_type='credit', amount=Decimal('100'))
        try:
            validate_order(o)
        except ValidationError as e:
            self.assertNotIn('payments_detail', e.detail)
