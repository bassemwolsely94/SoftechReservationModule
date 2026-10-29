"""
Doc 25 §24 — B4: reversal, never deletion. Reason + approval (band G) here, the supplier return posted
natively and verified by the daily check; live cases detect returns of their own contract / product
sales; an insurer rejection is recorded only.
"""
from datetime import date, datetime, timedelta, timezone as dt_tz
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.finance.recon_models import APInvoice, ReconParty, ReturnLink
from apps.replacement import legs as LG
from apps.replacement import reconstruct as R
from apps.replacement import reversal as REV
from apps.replacement.models import CaseException as X, ReplacementCase as RC, ReversalRequest as RR

from . import test_replacement_workflow as TW
from .test_replacement_workflow import PIC

D = Decimal
TODAY = timezone.localdate()


class ReversalTests(TW._Base):
    approved = TW.LegTests.approved

    def setUp(self):
        super().setUp()
        self.party = ReconParty.objects.create(party_type='supplier', softech_personcode='4471', name='مورد شركات 30%')
        self._n = 15000

    def v(self, c):
        return RC.objects.get(pk=c.pk).version

    def live_case(self):
        c = self.approved(item=self.small)                                 # products, 700
        self._n += 1
        inv = APInvoice.objects.create(party=self.party, party_type='supplier', branchcode='130', doccode='10',
                                       docnumber=str(self._n), docdate=TODAY, doc_value=c.entitlement)
        LG.link_native_purchase(c.pk, user=self.sup, version=self.v(c), branchcode='130',
                                docnumber=str(self._n), docdate=TODAY)
        return RC.objects.get(pk=c.pk), inv

    def supplier_return(self, inv, amount):
        self._n += 1
        ret = APInvoice.objects.create(party=self.party, party_type='supplier', branchcode='130', doccode='120',
                                       docnumber=str(self._n), docdate=TODAY, doc_value=D(amount), is_return=True)
        ReturnLink.objects.create(return_invoice=ret, purchase_invoice=inv, purchase_branchcode='130',
                                  purchase_docnumber=inv.docnumber, purchase_docdate=inv.docdate, amount=D(amount))
        R.reconstruct_invoice(inv, tabdeel=R.tabdeel_pics())

    def exc(self, c, t):
        return X.objects.filter(case=c, exception_type=t, status__in=['open', 'acknowledged'])

    def ask(self, c, **kw):
        return REV.request_reversal(c.pk, user=self.maker, version=self.v(c), **{'kind': 'wrong_rate',
                                                                                 'reason': 'النسبة 25 بدل 30', **kw})

    # ── request + approval ────────────────────────────────────────────────────
    def test_request_needs_reason_and_goes_to_the_supervisor(self):
        c, _ = self.live_case()
        with self.assertRaises(ValidationError):
            self.ask(c, reason='')
        self.ask(c)
        rr = c.reversals.get()
        self.assertEqual((rr.status, rr.amount, rr.balance_used), (RR.ST_AWAITING, D('700.00'), False))
        self.assertEqual(rr.approval_request.workflow.code, 'replacement_supervisor')
        with self.assertRaises(ValidationError):                            # one open request per case
            self.ask(c)
        with self.assertRaises(PermissionDenied):                           # maker ≠ checker
            REV.decide_reversal(c.pk, rr.pk, user=self.maker, version=self.v(c), approve=True)
        REV.decide_reversal(c.pk, rr.pk, user=self.sup, version=self.v(c), approve=True)
        rr.refresh_from_db()
        c.refresh_from_db()
        self.assertEqual((rr.status, c.status), (RR.ST_APPROVED, RC.STATUS_REVERSING))
        self.assertEqual(REV.instruction(c, rr)['amount'], '700.00')
        with self.assertRaises(ValidationError):                            # reversing → no new cash / products
            LG.prepare_product_sale(c.pk, user=self.sup, version=self.v(c), channel='cash',
                                    items=[{'item_id': self.cream.pk, 'qty': 1}])

    def test_used_balance_goes_to_the_manager_and_open_reservations_block(self):
        c, inv = self.live_case()
        op = LG.prepare_product_sale(c.pk, user=self.sup, version=self.v(c), channel='cash',
                                     items=[{'item_id': self.cream.pk, 'qty': 1}])     # reserves 300
        with self.assertRaises(ValidationError):
            self.ask(c)
        op.status = op.ST_CANCELLED
        op.save(update_fields=['status'])
        from apps.finance.recon_models import Allocation, Payment
        pay = Payment.objects.create(party=self.party, party_type='supplier', branchcode='130', cheqsno='990',
                                     cheqtype='20', direction='out', voucher_date=TODAY, amount=D('200'),
                                     trans_time=datetime(TODAY.year, TODAY.month, TODAY.day, 9, tzinfo=dt_tz.utc))
        Allocation.objects.create(payment=pay, invoice=inv, amount=D('200'), origin='softech')
        R.reconstruct_invoice(inv, tabdeel=R.tabdeel_pics())
        with self.assertRaises(ValidationError):                            # more than the 500 left
            self.ask(RC.objects.get(pk=c.pk), amount='600')
        self.ask(RC.objects.get(pk=c.pk))
        rr = c.reversals.get()
        self.assertEqual((rr.amount, rr.balance_used, rr.approval_request.workflow.code),
                         (D('500.00'), True, 'replacement_manager'))

    def test_reject_and_cancel_restore_the_case(self):
        c, _ = self.live_case()
        self.ask(c)
        rr = c.reversals.get()
        with self.assertRaises(ValidationError):
            REV.decide_reversal(c.pk, rr.pk, user=self.sup, version=self.v(c), approve=False)   # reason
        REV.decide_reversal(c.pk, rr.pk, user=self.sup, version=self.v(c), approve=False, note='النسبة صحيحة')
        self.assertEqual(RR.objects.get(pk=rr.pk).status, RR.ST_REJECTED)
        self.ask(RC.objects.get(pk=c.pk))
        rr2 = c.reversals.get(status=RR.ST_AWAITING)
        REV.decide_reversal(c.pk, rr2.pk, user=self.sup, version=self.v(c), approve=True)
        REV.cancel_reversal(c.pk, rr2.pk, user=self.maker, version=self.v(c), reason='المريض رجع في كلامه')
        c.refresh_from_db()
        self.assertEqual((RR.objects.get(pk=rr2.pk).status, c.status), (RR.ST_CANCELLED, RC.STATUS_ENTITLEMENT_ACTIVE))

    # ── daily check ───────────────────────────────────────────────────────────
    def test_native_return_executes_the_approved_request_and_reverses_the_case(self):
        c, inv = self.live_case()
        self.ask(c)
        rr = c.reversals.get()
        REV.decide_reversal(c.pk, rr.pk, user=self.sup, version=self.v(c), approve=True)
        self.supplier_return(inv, '700')
        rr.refresh_from_db()
        c.refresh_from_db()
        self.assertEqual((rr.status, c.status, c.outstanding), (RR.ST_EXECUTED, RC.STATUS_REVERSED, D('0.00')))
        self.assertFalse(self.exc(c, 'return_without_approval').exists())
        R.reconstruct_invoice(inv, tabdeel=R.tabdeel_pics())             # stable on re-run
        self.assertEqual(RC.objects.get(pk=c.pk).status, RC.STATUS_REVERSED)

    def test_return_without_approval_or_wrong_amount_is_high(self):
        c, inv = self.live_case()
        self.supplier_return(inv, '100')
        self.assertEqual(self.exc(c, 'return_without_approval').get().severity, X.SEV_HIGH)
        c2, inv2 = self.live_case()
        self.ask(c2)
        rr = c2.reversals.get()
        REV.decide_reversal(c2.pk, rr.pk, user=self.sup, version=self.v(c2), approve=True)
        self.supplier_return(inv2, '650')
        self.assertTrue(self.exc(c2, 'reversal_amount_mismatch').exists())
        self.assertEqual(RR.objects.get(pk=rr.pk).status, RR.ST_APPROVED)
        RR.objects.filter(pk=rr.pk).update(decided_at=timezone.now() - timedelta(days=5))
        R.reconstruct_invoice(inv2, tabdeel=R.tabdeel_pics())
        self.assertTrue(self.exc(c2, 'reversal_not_executed').exists())

    # ── detection of the case's own sales being returned ──────────────────────
    def sale(self, docno, total, day, *, doc='115', channel='10', item=None):
        from apps.customers.models import Customer, PurchaseHistory, PurchaseHistoryLine
        ph = PurchaseHistory.objects.create(
            customer=Customer.objects.get(softech_pic=PIC), branch=self.branch, doc_code=doc, total_amount=D(total),
            docnumber=str(docno), softech_invoice_id=f'130-{doc}-{docno}-{day:%Y%m%d}', sales_channel=channel,
            softech_phcode=PIC, invoice_date=timezone.make_aware(datetime(day.year, day.month, day.day, 12)),
            trans_time=datetime(day.year, day.month, day.day, 10, tzinfo=dt_tz.utc), cust_branch_code='4479')
        PurchaseHistoryLine.objects.create(purchase=ph, item=item or self.small, quantity=D('1'),
                                           unit_price=D(total), line_total=D(total))
        return ph

    def test_contract_cancelled_and_late_return_are_detected(self):
        c, inv = self.live_case()
        sale_day = date(TODAY.year, TODAY.month, 1)
        s = self.sale(480500, '1000', sale_day)
        LG.link_contract_sale(c.pk, user=self.sup, version=self.v(c), branchcode='130', docnumber='480500',
                              docdate=sale_day)
        self.assertEqual(REV.change_of_mind_until(sale_day), sale_day + timedelta(days=7))
        self.assertEqual(REV.change_of_mind_until(date(2026, 10, 28)), date(2026, 10, 31))      # month end wins
        self.sale(21600, '1000', sale_day + timedelta(days=10), doc='30')                        # full, after window
        R.reconstruct_invoice(inv, tabdeel=R.tabdeel_pics())
        self.assertEqual(self.exc(c, 'contract_cancelled').get().severity, X.SEV_HIGH)
        self.assertTrue(self.exc(c, 'late_contract_return').exists())
        wf = self.sup_api.get(f'/api/replacement/cases/{c.pk}/').data['workflow']
        self.assertEqual(wf['contract_return_until'], (sale_day + timedelta(days=7)).isoformat())
        self.assertEqual(s.docnumber, '480500')

    def test_returned_replacement_products_are_flagged(self):
        c, inv = self.live_case()
        self.sale(480600, '300', TODAY, channel='1', item=self.cream)
        LG.link_native_product_sale(c.pk, user=self.sup, version=self.v(c), branchcode='130',
                                    docnumber='480600', docdate=TODAY)
        self.sale(21700, '300', TODAY, doc='30', channel='1', item=self.cream)
        R.reconstruct_invoice(inv, tabdeel=R.tabdeel_pics())
        self.assertTrue(self.exc(c, 'product_sale_returned').exists())

    def test_insurer_rejection_is_recorded_and_survives_the_daily_check(self):
        c, inv = self.live_case()
        with self.assertRaises(PermissionDenied):                           # pharmacist has no «edit»
            REV.record_insurer_rejection(c.pk, user=self.maker, version=self.v(c), note='رفض')
        REV.record_insurer_rejection(c.pk, user=self.sup, version=self.v(c), note='رفض الموافقة 12/10')
        R.reconstruct_invoice(inv, tabdeel=R.tabdeel_pics())
        e = self.exc(c, 'insurer_rejected').get()
        self.assertEqual((e.status, e.severity), (X.STATUS_ACK, X.SEV_INFO))

    # ── API ───────────────────────────────────────────────────────────────────
    def test_api(self):
        c, _ = self.live_case()
        r = self.maker_api.post(f'/api/replacement/cases/{c.pk}/reversals/',
                                {'version': self.v(c), 'kind': 'duplicate', 'reason': 'مكررة'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        rv = r.data['workflow']['reversals'][0]
        self.assertFalse(rv['can_decide'])                                  # the requester cannot decide
        r = self.sup_api.post(f'/api/replacement/cases/{c.pk}/reversals/{rv["id"]}/approve/',
                              {'version': self.v(c)}, format='json')
        self.assertEqual((r.status_code, r.data['workflow']['reversals'][0]['status']), (200, 'approved'))
        self.assertEqual(r.data['workflow']['reversals'][0]['instruction']['amount'], '700.00')
