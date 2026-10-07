"""
Doc 25 — parallel entry (owner 2026-10-07): staff post the purchase and the product sales NATIVELY in
SOFTECH and link the document numbers to the live case. Nothing is written to SOFTECH; the link is
verified against the mirrors (immediately, or after the next A/P sync) and the nightly reconstruction
attaches to the live case instead of building a duplicate.
"""
from datetime import date, datetime, timezone as dt_tz
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.finance.recon_models import Allocation, APInvoice, Payment, ReconParty
from apps.replacement import legs as LG
from apps.replacement import reconstruct as R
from apps.replacement.models import (CaseDocument as CD, CaseException as X, EntitlementLedgerEntry as E,
                                     PostingOperation as Op, ReplacementCase as RC)

from . import test_replacement_workflow as TW
from .test_replacement_workflow import PIC

D = Decimal
TODAY = date(2026, 10, 7)


def _utc(h, mi):
    return datetime(2026, 10, 7, h, mi, tzinfo=dt_tz.utc)


class NativeLinkTests(TW._Base):
    approved = TW.LegTests.approved

    def setUp(self):
        super().setUp()
        self.party = ReconParty.objects.create(party_type='supplier', softech_personcode='4471', name='مورد شركات 30')

    def ap_invoice(self, docnumber='12600', value='5618.90', party=None, docdate=TODAY):
        return APInvoice.objects.create(party=party or self.party, party_type='supplier', branchcode='130',
                                        doccode='10', docnumber=docnumber, docdate=docdate, doc_value=D(value))

    def v(self, c):
        return RC.objects.get(pk=c.pk).version

    def link(self, c, docnumber='12600', docdate=TODAY, user=None):
        return LG.link_native_purchase(c.pk, user=user or self.sup, version=self.v(c), branchcode='130',
                                       docnumber=docnumber, docdate=docdate)

    def op(self, c):
        return Op.objects.get(case=c, kind=Op.KIND_PURCHASE, idempotency_key=f'{c.pk}:purchase')

    # ── purchase ──────────────────────────────────────────────────────────────
    def test_link_before_mirror_waits_then_attaches_on_the_scheduled_check(self):
        c = self.link(self.approved())
        op = self.op(c)
        self.assertEqual((op.status, op.result['native']['docnumber']), (Op.ST_POSTED, '12600'))
        self.assertIn('المزامنة', op.error)
        self.assertEqual(c.status, RC.STATUS_EXECUTING)
        self.assertFalse(E.objects.filter(case=c).exists())               # nothing booked yet

        self.ap_invoice()                                                  # next A/P sync brings it
        out = LG.resolve_pending_native_links()
        self.assertEqual(out, {'pending': 1, 'attached': 1})
        c.refresh_from_db()
        op.refresh_from_db()
        self.assertEqual((op.status, op.error), (Op.ST_VERIFIED, ''))
        self.assertEqual(c.purchase_ref.docnumber, '12600')
        self.assertEqual(c.ledger.get(entry_type=E.TYPE_CREATED).amount, D('5618.90'))
        self.assertEqual(c.status, RC.STATUS_ENTITLEMENT_ACTIVE)
        self.assertEqual(c.origin, RC.ORIGIN_LIVE)
        self.assertEqual(LG.resolve_pending_native_links(), {'pending': 0, 'attached': 0})

    def test_link_when_mirror_has_it_attaches_now_and_nightly_never_duplicates(self):
        inv = self.ap_invoice()
        c = self.link(self.approved())
        self.assertEqual(self.op(c).status, Op.ST_VERIFIED)
        out = R.reconstruct_invoice(inv)
        self.assertEqual((out['created'], out['case'].pk), (False, c.pk))
        self.assertEqual(RC.objects.count(), 1)
        self.assertEqual(RC.objects.get(pk=c.pk).ledger.filter(entry_type=E.TYPE_CREATED).count(), 1)

    def test_amount_differing_from_approval_raises_mismatch(self):
        self.ap_invoice(value='5000.00')
        c = self.link(self.approved())
        self.assertTrue(X.objects.filter(case=c, exception_type='purchase_value_mismatch', severity='high').exists())
        self.assertEqual(RC.objects.get(pk=c.pk).ledger.get(entry_type=E.TYPE_CREATED).amount, D('5000.00'))  # SOFTECH truth

    def test_wrong_supplier_fails_and_books_nothing(self):
        other = ReconParty.objects.create(party_type='supplier', softech_personcode='4470', name='مورد 40')
        self.ap_invoice(party=other)
        c = self.link(self.approved())
        op = self.op(c)
        self.assertEqual(op.status, Op.ST_FAILED)
        self.assertIn('4470', op.error)
        self.assertTrue(X.objects.filter(case=c, exception_type='posting_failed').exists())
        self.assertIsNone(RC.objects.get(pk=c.pk).purchase_ref)
        c2 = self.link(c, docnumber='12601')                               # a corrected number replaces it
        self.assertEqual(self.op(c2).result['native']['docnumber'], '12601')

    def test_untouched_reconstructed_duplicate_is_retired_into_the_live_case(self):
        inv = self.ap_invoice()
        dup = R.reconstruct_invoice(inv)['case']                           # nightly ran before the link
        self.assertEqual(dup.origin, RC.ORIGIN_RECONSTRUCTED)
        c = self.link(self.approved())
        self.assertEqual(self.op(c).status, Op.ST_VERIFIED)
        dup.refresh_from_db()
        self.assertEqual((dup.status, dup.purchase_ref_id, dup.outstanding), (RC.STATUS_CANCELLED, None, D('0')))
        self.assertEqual(sum(e.amount for e in dup.ledger.all()), D('0'))   # reversed, history kept
        self.assertTrue(dup.ledger.filter(entry_type=E.TYPE_REVERSAL).exists())
        self.assertEqual(RC.objects.get(pk=c.pk).purchase_ref.docnumber, '12600')
        self.assertEqual(RC.objects.exclude(status=RC.STATUS_CANCELLED).count(), 1)

    def test_duplicate_someone_worked_on_is_never_retired(self):
        inv = self.ap_invoice()
        dup = R.reconstruct_invoice(inv)['case']
        CD.objects.filter(case=dup).update(origin='manual')
        c = self.link(self.approved())
        op = self.op(c)
        self.assertEqual(op.status, Op.ST_FAILED)
        self.assertIn(dup.number, op.error)
        dup.refresh_from_db()
        self.assertNotEqual(dup.status, RC.STATUS_CANCELLED)

    def test_same_native_purchase_cannot_be_linked_to_two_cases(self):
        self.link(self.approved())
        with self.assertRaises(ValidationError):
            self.link(self.approved())

    def test_relinking_the_same_number_is_idempotent(self):
        c = self.link(self.approved())
        self.link(c)
        self.assertEqual(Op.objects.filter(case=c, kind=Op.KIND_PURCHASE).count(), 1)

    def test_native_leg_is_never_sent_to_a_writer(self):
        c = self.link(self.approved())
        with self.assertRaises(ValidationError):
            LG.post(c.pk, self.op(c).op_id, user=self.sup, version=self.v(c))

    def test_platform_prepared_purchase_blocks_a_native_link(self):
        c = self.approved()
        LG.prepare_purchase(c.pk, user=self.sup, version=c.version)
        with self.assertRaises(ValidationError):
            self.link(c)

    def test_needs_an_approved_case(self):
        c = self.calc(self.new_case())
        with self.assertRaises(ValidationError):
            self.link(c)

    def test_reconstruction_run_resolves_pending_links_first(self):
        c = self.link(self.approved())
        self.ap_invoice()
        run = R.run(date_from=date(2026, 9, 1))
        self.assertEqual(run.counts['native_links'], {'pending': 1, 'attached': 1})
        self.assertEqual(RC.objects.count(), 1)
        self.assertEqual(RC.objects.get(pk=c.pk).purchase_ref.docnumber, '12600')

    # ── product sales ─────────────────────────────────────────────────────────
    def sale(self, docno, total, phcode=PIC, channel='1', tt=None):
        from apps.customers.models import Customer, PurchaseHistory
        cust, _ = Customer.objects.get_or_create(softech_pic=phcode or 'CASHCUST',
                                                 defaults={'name': 'عميل', 'phone': f'01{docno}'})
        return PurchaseHistory.objects.create(
            customer=cust, branch=self.branch, doc_code='115', total_amount=D(total), docnumber=str(docno),
            softech_invoice_id=f'130-115-{docno}-20261007', sales_channel=channel, softech_phcode=phcode,
            invoice_date=timezone.make_aware(datetime(2026, 10, 7)), trans_time=tt or _utc(9, 0),
            cust_branch_code='1500')

    def link_sale(self, c, docno, user=None):
        return LG.link_native_product_sale(c.pk, user=user or self.sup, version=self.v(c), branchcode='130',
                                           docnumber=str(docno), docdate=TODAY)

    def test_product_sale_link_is_owned_and_verified_by_the_cashier_voucher(self):
        inv = self.ap_invoice()
        c = self.link(self.approved())
        ph = self.sale(470001, '300.00', phcode='')                       # cashier left the PIC empty
        self.link_sale(c, 470001)
        op = Op.objects.get(case=c, kind=Op.KIND_PRODUCT_SALE)
        self.assertEqual((op.status, op.expected_value, op.result['native_receipt']), (Op.ST_POSTED, D('300.00'), ph.pk))
        self.assertIn(ph.pk, R._own_receipts(RC.objects.get(pk=c.pk)))
        self.assertEqual(LG.available(RC.objects.get(pk=c.pk))['reserved'], D('300.00'))

        pay = Payment.objects.create(party=self.party, party_type='supplier', branchcode='130', cheqsno='901',
                                     cheqtype='20', direction='out', voucher_date=TODAY, amount=D('300'),
                                     trans_time=_utc(9, 5), note='سداد جزء')
        Allocation.objects.create(payment=pay, invoice=inv, amount=D('300'), origin='softech')
        R.reconstruct_invoice(inv, tabdeel=R.tabdeel_pics())
        op.refresh_from_db()
        self.assertEqual(op.status, Op.ST_VERIFIED)
        self.assertEqual(op.result['voucher_linked'], '130/901')
        c.refresh_from_db()
        self.assertEqual(c.redeemed_products, D('300.00'))
        self.assertEqual(c.outstanding, D('5318.90'))

    def test_product_sale_on_another_patient_or_another_case_is_refused(self):
        c = self.link(self.approved())
        self.sale(470002, '200', phcode='999HD1')
        with self.assertRaises(ValidationError):
            self.link_sale(c, 470002)
        self.sale(470003, '200')
        self.link_sale(c, 470003)
        self.link_sale(c, 470003)                                          # same again → idempotent
        self.assertEqual(Op.objects.filter(case=c, kind=Op.KIND_PRODUCT_SALE).count(), 1)
        with self.assertRaises(ValidationError):
            self.link_sale(self.approved(), 470003)

    def test_contract_receipt_cannot_be_linked_as_products(self):
        c = self.link(self.approved())
        self.sale(470004, '900', channel='10')
        with self.assertRaises(ValidationError):
            self.link_sale(c, 470004)

    def test_cash_case_has_no_product_sales(self):
        c = self.link(self.approved(mode='cash'))
        self.sale(470005, '100')
        with self.assertRaises(ValidationError):
            self.link_sale(c, 470005)

    # ── API ───────────────────────────────────────────────────────────────────
    def test_api_endpoints(self):
        self.ap_invoice()
        c = self.approved()
        r = self.sup_api.post(f'/api/replacement/cases/{c.pk}/link-purchase/',
                              {'version': c.version, 'branchcode': '130', 'docnumber': '12600',
                               'docdate': '2026-10-07'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.sale(470006, '150')
        r = self.sup_api.post(f'/api/replacement/cases/{c.pk}/link-product-sale/',
                              {'version': RC.objects.get(pk=c.pk).version, 'branchcode': '130',
                               'docnumber': '470006', 'docdate': '2026-10-07'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.sup_api.post(f'/api/replacement/cases/{c.pk}/link-purchase/',
                                           {'version': 1, 'docdate': 'x'}, format='json').status_code, 400)
