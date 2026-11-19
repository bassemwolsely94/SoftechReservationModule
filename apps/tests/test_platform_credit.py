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


class PlatformDraftsTests(TestCase):
    """«طلبات المنصات» on the cashier screen: the branch's open marketplace drafts, branch-locked;
    a platform sale needs no PIC and no patient data (native «عميل دائم» sales carry none)."""

    def setUp(self):
        from apps.marketplace.models import ChannelStore, ExternalOrder
        from .factories import make_branch2, make_user
        self.a = make_branch('فرع أ', 'B01')
        self.b = make_branch2('فرع ب', 'B02')
        _, _, self.seller = make_user('pd_seller', role='salesperson', branch=self.a)
        ch = MarketplaceChannel.objects.create(code='tlb2', name='طلبات', softech_personcode='4292')
        store = ChannelStore.objects.create(channel=ch, branch=self.a, external_store_id='S1', is_active=True)
        self.draft = SoftechSalesOrder.objects.create(
            branch=self.a, softech_branchcode='B01', store_code='B01', channel='permanent',
            cust_branch_code='4292', status=SoftechSalesOrder.STATUS_DRAFT, customer_name='طلبات — T1')
        SoftechSalesOrderLine.objects.create(order=self.draft, softech_itemcode='33677', item_name='PAD',
                                             qty=1, item_sale_price=Decimal('5.5'), sale_tax_pct=0, cust_discp=0)
        ExternalOrder.objects.create(channel=ch, store=store, branch=self.a, external_id='T1',
                                     status=ExternalOrder.STATUS_ACCEPTED, pos_order=self.draft)
        # an ordinary draft on the same branch is not a platform order
        SoftechSalesOrder.objects.create(branch=self.a, softech_branchcode='B01', store_code='B01',
                                         channel='cash', status=SoftechSalesOrder.STATUS_DRAFT)

    def test_lists_only_platform_drafts_of_the_branch(self):
        r = self.seller.get('/api/pos-orders/platform-drafts/', {'branch': self.a.pk})
        self.assertEqual(r.status_code, 200)
        rows = r.json()['results']
        self.assertEqual([(x['id'], x['platform'], x['platform_order']) for x in rows], [(self.draft.pk, 'طلبات', 'T1')])
        self.assertEqual(rows[0]['lines'][0]['itemcode'], '33677')

    def test_sent_draft_drops_off_the_list(self):
        SoftechSalesOrder.objects.filter(pk=self.draft.pk).update(status=SoftechSalesOrder.STATUS_PUSHED)
        r = self.seller.get('/api/pos-orders/platform-drafts/', {'branch': self.a.pk})
        self.assertEqual(r.json()['results'], [])

    def test_other_branch_refused(self):
        r = self.seller.get('/api/pos-orders/platform-drafts/', {'branch': self.b.pk})
        self.assertEqual(r.status_code, 403)

    def test_platform_sale_needs_no_pic_or_patient_data(self):
        o = self.draft
        writer.prepare_order(o)
        o.refresh_from_db()
        try:
            validate_order(o, for_push=True)
        except ValidationError as e:
            self.assertNotIn('softech_pic', e.detail)
            self.assertNotIn('claim', e.detail)

    def test_ordinary_permanent_sale_still_needs_pic(self):
        o = _order('4846')
        o.softech_pic = ''
        o.save()
        with self.assertRaises(ValidationError) as cm:
            validate_order(o)
        self.assertIn('softech_pic', cm.exception.detail)
