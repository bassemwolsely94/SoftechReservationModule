"""
Doc 25 §22 — B2: the patient's بدل balance in Customer 360 / the POS, and funding a POS order from it.
Figures come from legs.available (never a second balance); only live cases at the order's branch fund;
funding records the link and never touches the order; the cashier's voucher verifies it.
"""
from datetime import datetime, timezone as dt_tz
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.finance.recon_models import Allocation, APInvoice, Payment, ReconParty
from apps.replacement import legs as LG
from apps.replacement import reconstruct as R
from apps.replacement import redemption as RD
from apps.replacement.models import PostingOperation as Op, ReplacementCase as RC

from . import test_replacement_workflow as TW
from .factories import make_user
from .test_replacement_workflow import PIC

D = Decimal
TODAY = timezone.localdate()


class RedemptionTests(TW._Base):
    approved = TW.LegTests.approved

    def setUp(self):
        super().setUp()
        self.party = ReconParty.objects.create(party_type='supplier', softech_personcode='4471', name='مورد شركات 30%')
        self._n = 13000

    def live_case(self, item=None, mode='products'):
        """An approved live case whose purchase SOFTECH already has → balance active."""
        c = self.approved(item=item or self.small, mode=mode)
        self._n += 1
        party = self.party if mode != 'cash' else ReconParty.objects.get_or_create(
            party_type='supplier', softech_personcode='4470', defaults={'name': 'مورد شركات 40%'})[0]
        APInvoice.objects.create(party=party, party_type='supplier', branchcode='130', doccode='10',
                                 docnumber=str(self._n), docdate=TODAY, doc_value=c.entitlement)
        LG.link_native_purchase(c.pk, user=self.sup, version=RC.objects.get(pk=c.pk).version, branchcode='130',
                                docnumber=str(self._n), docdate=TODAY)
        c = RC.objects.get(pk=c.pk)
        self.assertEqual((c.status, c.outstanding), (RC.STATUS_ENTITLEMENT_ACTIVE, c.entitlement))
        return c

    def order(self, qty=1, channel='cash', pic=PIC, item=None):
        c = RC(branch=self.branch, softech_pic=pic, patient_name='محمد', customer=None, contract_personcode='')
        return LG._create_order(c, self.sup, channel=channel, lines=LG._order_lines([{'item': item or self.cream, 'qty': qty}]))

    # ── balance ───────────────────────────────────────────────────────────────
    def test_balance_is_the_live_available_and_staff_only(self):
        a = self.live_case()                                                    # 1000 × 0.70 = 700
        bal = RD.patient_balance(PIC, staff=self.sup, branch_id=self.branch.pk)
        self.assertEqual((bal['total_available'], [x['number'] for x in bal['cases']]), ('700.00', [a.number]))
        self.assertTrue(bal['cases'][0]['redeemable_here'])
        elsewhere = RD.patient_balance(PIC, staff=self.sup, branch_id=self.other.pk)
        self.assertEqual((elsewhere['total_available'], elsewhere['cases'][0]['redeemable_here']), ('0', False))
        _, sales, _ = make_user('sales9', role='salesperson', branch=self.branch)
        self.assertIsNone(RD.patient_balance(PIC, staff=sales))

    def test_pos_summary_carries_the_balance_only_for_allowed_staff(self):
        from apps.customers.models import Customer
        self.live_case()
        cust = Customer.objects.get(softech_pic=PIC)
        r = self.sup_api.get(f'/api/customers/{cust.pk}/pos-summary/', {'branch': self.branch.pk})
        self.assertEqual(r.data['replacement']['total_available'], '700.00')
        _, _, sales_api = make_user('sales8', role='salesperson', branch=self.branch)
        self.assertNotIn('replacement', sales_api.get(f'/api/customers/{cust.pk}/pos-summary/').data)

    # ── funding ───────────────────────────────────────────────────────────────
    def test_fund_oldest_first_across_cases_with_topup(self):
        a, b = self.live_case(), self.live_case()                                # 700 + 700
        o = self.order(qty=5)                                                   # 5 × 300 = 1,500 → top-up 100
        ops = RD.fund_order(o.pk, user=self.sup)
        self.assertEqual([(op.case_id, op.expected_value) for op in ops], [(a.pk, D('700.00')), (b.pk, D('700.00'))])
        self.assertEqual(ops[-1].result['customer_topup'], '100.00')
        self.assertTrue(all(op.result['from_pos'] for op in ops))
        self.assertEqual(LG.available(RC.objects.get(pk=a.pk))['available'], D('0'))
        o.refresh_from_db()
        self.assertEqual((o.status, o.channel), ('draft', 'cash'))              # the order itself is untouched
        self.assertEqual(RD.fund_order(o.pk, user=self.sup), ops)               # idempotent
        with self.assertRaises(ValidationError):                                 # the POS pushes it, not the case
            LG.post(a.pk, ops[0].op_id, user=self.sup, version=RC.objects.get(pk=a.pk).version)

    def test_named_case_and_topup_cap(self):
        a, b = self.live_case(), self.live_case()
        ops = RD.fund_order(self.order(qty=1).pk, user=self.sup, case_ids=[b.pk])
        self.assertEqual([(op.case_id, op.expected_value) for op in ops], [(b.pk, D('300.00'))])
        with self.assertRaises(ValidationError):                                 # 10 × 300 = 3,000 ≫ 1,100 + 50 %
            RD.fund_order(self.order(qty=10).pk, user=self.sup)

    def test_guards(self):
        a = self.live_case()
        for bad in (self.order(channel='contract'), self.order(pic='')):
            with self.assertRaises(ValidationError):
                RD.fund_order(bad.pk, user=self.sup)
        cash_case = self.live_case(mode='cash')                                 # cash entitlement never funds products
        with self.assertRaises(ValidationError):
            RD.fund_order(self.order().pk, user=self.sup, case_ids=[cash_case.pk])
        with self.assertRaises(PermissionDenied):                                # pharmacist may not post
            RD.fund_order(self.order().pk, user=self.maker)
        settled = self.order()
        settled.status = 'settled'
        settled.save(update_fields=['status'])
        with self.assertRaises(ValidationError):
            RD.fund_order(settled.pk, user=self.sup)
        self.assertEqual(LG.available(RC.objects.get(pk=a.pk))['available'], D('700.00'))

    def test_unfund_releases_until_settled(self):
        a = self.live_case()
        o = self.order()
        RD.fund_order(o.pk, user=self.sup)
        with self.assertRaises(ValidationError):
            RD.unfund_order(o.pk, user=self.sup, reason='')
        self.assertEqual(RD.unfund_order(o.pk, user=self.sup, reason='غيّر المنتجات'), 1)
        self.assertEqual(LG.available(RC.objects.get(pk=a.pk))['available'], D('700.00'))
        RD.fund_order(o.pk, user=self.sup)                                      # can be funded again
        o.softech_final_docnumber, o.status = D('470100'), 'settled'
        o.save(update_fields=['softech_final_docnumber', 'status'])
        with self.assertRaises(ValidationError):
            RD.unfund_order(o.pk, user=self.sup, reason='x')

    def test_settled_order_is_verified_by_the_cashier_voucher(self):
        from apps.customers.models import Customer, PurchaseHistory
        a = self.live_case()
        o = self.order()
        op = RD.fund_order(o.pk, user=self.sup)[0]
        o.softech_final_docnumber, o.status, o.softech_branchcode = D('470200'), 'settled', '130'
        o.save(update_fields=['softech_final_docnumber', 'status', 'softech_branchcode'])
        PurchaseHistory.objects.create(
            customer=Customer.objects.get(softech_pic=PIC), branch=self.branch, doc_code='115', total_amount=D('300'),
            docnumber='470200', softech_invoice_id=f'130-115-470200-{TODAY:%Y%m%d}', sales_channel='1',
            softech_phcode=PIC, invoice_date=timezone.make_aware(datetime(TODAY.year, TODAY.month, TODAY.day)),
            trans_time=datetime(TODAY.year, TODAY.month, TODAY.day, 9, 0, tzinfo=dt_tz.utc), cust_branch_code='1500')
        inv = APInvoice.objects.get(docnumber=a.purchase_ref.docnumber)
        pay = Payment.objects.create(party=self.party, party_type='supplier', branchcode='130', cheqsno='961',
                                     cheqtype='20', direction='out', voucher_date=TODAY, amount=D('300'),
                                     trans_time=datetime(TODAY.year, TODAY.month, TODAY.day, 9, 5, tzinfo=dt_tz.utc))
        Allocation.objects.create(payment=pay, invoice=inv, amount=D('300'), origin='softech')
        R.reconstruct_invoice(inv, tabdeel=R.tabdeel_pics())
        op.refresh_from_db()
        a.refresh_from_db()
        self.assertEqual((op.status, op.result['voucher_linked']), (Op.ST_VERIFIED, '130/961'))
        self.assertEqual((a.redeemed_products, a.outstanding), (D('300.00'), D('400.00')))

    # ── API ───────────────────────────────────────────────────────────────────
    def test_api_orders_fund_unfund_and_branch_scope(self):
        a = self.live_case()
        o = self.order()
        rows = self.sup_api.get('/api/replacement/cases/patient-orders/', {'pic': PIC, 'branch': self.branch.pk}).data['results']
        self.assertEqual([(r['id'], r['total'], r['funded_by']) for r in rows], [(o.pk, '300.00', [])])
        r = self.sup_api.post('/api/replacement/cases/fund-order/', {'order': o.pk, 'cases': [a.pk]}, format='json')
        self.assertEqual((r.status_code, r.data['funded'][0]['amount']), (200, '300.00'))
        _, _, other_api = make_user('sup140b', role='supervisor', branch=self.other)
        self.assertEqual(other_api.post('/api/replacement/cases/unfund-order/', {'order': o.pk, 'reason': 'x'},
                                        format='json').status_code, 404)
        r = self.sup_api.post('/api/replacement/cases/unfund-order/', {'order': o.pk, 'reason': 'x'}, format='json')
        self.assertEqual((r.status_code, r.data['released']), (200, 1))
        bal = self.sup_api.get('/api/replacement/cases/patient-balance/', {'pic': PIC, 'branch': self.branch.pk}).data
        self.assertEqual(bal['total_available'], '700.00')
