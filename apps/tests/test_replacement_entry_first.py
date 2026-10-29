"""
Doc 25 §20 — entry-first (owner 2026-10-26). Every بدل case is entered in the module first; the
matcher only verifies. After a branch's cut-over a virtual-supplier purchase with no case becomes a
tracked, claimable «شراء بدون حالة» record; a live case funds vouchers from its DECLARED receipts
only; anonymous receipts are never auto-confirmed; approvals follow the owner matrix (cash manager
> 1,500, rate lowered manager > 5 pp, backdate bands).
"""
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import override_settings
from django.utils import timezone

from apps.finance.recon_models import Allocation, APInvoice, Payment, ReconParty
from apps.replacement import legs as LG
from apps.replacement import reconstruct as R
from apps.replacement import workflow as W
from apps.replacement.models import (CaseException as X, EntitlementLedgerEntry as E, PostingOperation as Op,
                                     ReplacementCase as RC, ReplacementGrant, ReplacementItem)

from . import test_replacement_workflow as TW
from .test_replacement_workflow import PIC

D = Decimal
TODAY = timezone.localdate()
YESTERDAY = TODAY - timedelta(days=1)
CUTOVER = {'130': (TODAY - timedelta(days=20)).isoformat()}


def _at(day, h=9, mi=0):
    return datetime(day.year, day.month, day.day, h, mi, tzinfo=dt_tz.utc)


@override_settings(REPLACEMENT_ENTRY_FIRST_FROM=CUTOVER)
class EntryFirstTests(TW._Base):
    approved = TW.LegTests.approved

    def setUp(self):
        super().setUp()
        self.party = ReconParty.objects.create(party_type='supplier', softech_personcode='4471', name='مورد شركات 30%')

    def ap_invoice(self, docnumber='12700', value='5618.90', docdate=YESTERDAY, branch='130', usercode='1776'):
        inv = APInvoice.objects.create(party=self.party, party_type='supplier', branchcode=branch, doccode='10',
                                       docnumber=docnumber, docdate=docdate, doc_value=D(value), usercode=usercode)
        return inv

    def v(self, c):
        return RC.objects.get(pk=c.pk).version

    # ── unclaimed records ─────────────────────────────────────────────────────
    def test_caseless_purchase_after_cutover_is_tracked_unclaimed(self):
        out = R.reconstruct_invoice(self.ap_invoice())
        c = out['case']
        self.assertTrue(out['created'])
        self.assertEqual((c.status, c.origin), (RC.STATUS_UNCLAIMED, RC.ORIGIN_RECONSTRUCTED))
        exc = X.objects.get(case=c, exception_type='caseless_purchase')
        self.assertEqual((exc.severity, exc.status, exc.evidence['usercode']), (X.SEV_HIGH, X.STATUS_OPEN, '1776'))
        self.assertEqual(c.ledger.get(entry_type=E.TYPE_CREATED).amount, D('5618.90'))   # money still tracked
        self.assertEqual(c.outstanding, c.native_outstanding)                              # I-1 holds
        again = R.reconstruct_invoice(APInvoice.objects.get(pk=c.purchase_invoice_id))      # nightly re-run
        self.assertEqual((again['created'], again['case'].status), (False, RC.STATUS_UNCLAIMED))

    def test_before_cutover_or_other_branch_stays_historical(self):
        old = R.reconstruct_invoice(self.ap_invoice(docnumber='12701', docdate=TODAY - timedelta(days=30)))['case']
        other = R.reconstruct_invoice(self.ap_invoice(docnumber='12702', branch='140'))['case']
        for c in (old, other):
            self.assertNotEqual(c.status, RC.STATUS_UNCLAIMED)
            self.assertFalse(X.objects.filter(case=c, exception_type='caseless_purchase').exists())

    # ── claim flow ────────────────────────────────────────────────────────────
    def claim(self, src, mode='products', items=None, user=None):
        return W.create_case(user=user or self.maker, branch=self.branch, source_type='insurance_rx',
                             settlement_mode=mode, softech_pic=PIC, contract_personcode='4479',
                             items=items if items is not None else [{'item_id': self.lokelma.pk, 'qty': 1}],
                             claim_of=src)

    def test_claim_links_purchase_on_approval_and_retires_the_unclaimed_record(self):
        src = R.reconstruct_invoice(self.ap_invoice())['case']
        X.objects.filter(case=src).update(status=X.STATUS_ACK)          # someone reviewed it — still claimable
        c = self.submit(self.calc(self.claim(src)))
        self.assertEqual(c.status, RC.STATUS_AWAITING_APPROVAL)
        self.assertTrue(any('بأثر رجعي' in r for r in c.approval_request.context_data['reasons']))
        c = W.decide(c.pk, user=self.sup, version=c.version, approve=True)

        c.refresh_from_db()
        op = Op.objects.get(case=c, idempotency_key=f'{c.pk}:purchase')
        self.assertEqual((op.status, op.result['claimed_from']), (Op.ST_VERIFIED, src.number))
        self.assertEqual(c.purchase_ref.docnumber, '12700')
        self.assertEqual(c.ledger.get(entry_type=E.TYPE_CREATED).amount, D('5618.90'))
        self.assertEqual(c.status, RC.STATUS_ENTITLEMENT_ACTIVE)
        self.assertEqual(X.objects.get(case=c, exception_type='backdated_entry').severity, X.SEV_INFO)
        src.refresh_from_db()
        self.assertEqual((src.status, src.purchase_ref_id), (RC.STATUS_CANCELLED, None))
        self.assertEqual(sum(e.amount for e in src.ledger.all()), D('0'))   # reversed, history kept
        # nightly: the purchase now belongs to the live case — no new unclaimed record
        out = R.reconstruct_invoice(APInvoice.objects.get(docnumber='12700'))
        self.assertEqual((out['created'], out['case'].pk), (False, c.pk))

    def test_claim_prefills_items_from_purchase_lines(self):
        src = R.reconstruct_invoice(self.ap_invoice())['case']
        ReplacementItem.objects.create(case=src, item=self.lokelma, itemcode='100186', item_name='LOKELMA 5MG',
                                       disposition=ReplacementItem.DISP_REPLACED, qty_replaced=D('1'),
                                       public_unit_price=D('8027'))
        c = self.claim(src, items=[])
        self.assertEqual(list(c.items.filter(disposition=ReplacementItem.DISP_REPLACED)
                              .values_list('itemcode', 'qty_replaced')), [('100186', D('1'))])

    def test_claim_guards(self):
        hist = R.reconstruct_invoice(self.ap_invoice(docnumber='12703', docdate=TODAY - timedelta(days=30)))['case']
        with self.assertRaises(ValidationError):                       # not an unclaimed record
            self.claim(hist)
        src = R.reconstruct_invoice(self.ap_invoice())['case']
        first = self.claim(src)
        with self.assertRaises(ValidationError):                       # already being claimed
            self.claim(src)
        W.cancel(first.pk, user=self.maker, version=self.v(first), reason='خطأ')
        self.assertIsNone(RC.objects.get(pk=first.pk).claim_of_id)
        self.claim(src)                                                # free again after cancel

    def test_claim_with_rule_on_another_supplier_cannot_be_submitted(self):
        src = R.reconstruct_invoice(self.ap_invoice())['case']          # 4471 (products)
        c = self.calc(self.claim(src, mode='cash'))                     # cash rule → 4470
        with self.assertRaises(ValidationError):
            self.submit(c)

    # ── live case verifies declared receipts only ──────────────────────────────
    def voucher(self, inv, amount, sno='950'):
        pay = Payment.objects.create(party=self.party, party_type='supplier', branchcode='130', cheqsno=sno,
                                     cheqtype='20', direction='out', voucher_date=inv.docdate, amount=D(amount),
                                     trans_time=_at(inv.docdate, 9, 5), note='سداد')
        Allocation.objects.create(payment=pay, invoice=inv, amount=D(amount), origin='softech')

    def sale(self, docno, total, day, phcode=PIC):
        from apps.customers.models import Customer, PurchaseHistory
        cust = Customer.objects.get(softech_pic=PIC)
        return PurchaseHistory.objects.create(
            customer=cust, branch=self.branch, doc_code='115', total_amount=D(total), docnumber=str(docno),
            softech_invoice_id=f'130-115-{docno}-{day:%Y%m%d}', sales_channel='1', softech_phcode=phcode,
            invoice_date=timezone.make_aware(datetime(day.year, day.month, day.day)), trans_time=_at(day, 9, 0),
            cust_branch_code='1500')

    def live_with_purchase(self, mode='products'):
        inv = self.ap_invoice(docdate=TODAY, value='5618.90' if mode == 'products' else '4816.20')
        if mode == 'cash':
            inv.party = ReconParty.objects.create(party_type='supplier', softech_personcode='4470', name='مورد 40')
            inv.save(update_fields=['party'])
            self.party = inv.party
        c = self.approved(mode=mode)
        LG.link_native_purchase(c.pk, user=self.sup, version=self.v(c), branchcode='130',
                                docnumber=inv.docnumber, docdate=inv.docdate)
        return RC.objects.get(pk=c.pk), inv

    def test_live_case_does_not_adopt_undeclared_patient_receipts(self):
        c, inv = self.live_with_purchase()
        self.sale(480001, '300.00', TODAY)                              # patient receipt, NOT declared
        self.voucher(inv, '300')
        R.reconstruct_invoice(inv, tabdeel=R.tabdeel_pics())
        c.refresh_from_db()
        self.assertEqual((c.redeemed_products, c.redeemed_unclassified), (D('0.00'), D('300.00')))
        self.assertEqual(X.objects.get(case=c, exception_type='undeclared_redemption').severity, X.SEV_WARNING)
        self.assertEqual(c.settlement_mode, RC.MODE_PRODUCTS)          # the operator's choice is kept

        LG.link_native_product_sale(c.pk, user=self.sup, version=self.v(c), branchcode='130',
                                    docnumber='480001', docdate=TODAY)  # declare it → verified
        R.reconstruct_invoice(inv, tabdeel=R.tabdeel_pics())
        c.refresh_from_db()
        self.assertEqual((c.redeemed_products, c.redeemed_unclassified), (D('300.00'), D('0.00')))
        self.assertFalse(X.objects.filter(case=c, exception_type='undeclared_redemption', status='open').exists())

    @override_settings(REPLACEMENT_APPROVAL_CASH_MANAGER_ABOVE=D('99999'))   # supervisor-only approval here
    def test_live_cash_case_voucher_is_cash(self):
        c, inv = self.live_with_purchase(mode='cash')
        self.voucher(inv, '1000')
        R.reconstruct_invoice(inv, tabdeel=R.tabdeel_pics())
        c.refresh_from_db()
        self.assertEqual((c.redeemed_cash, c.redeemed_unclassified), (D('1000.00'), D('0.00')))

    # ── redemption customer (Q5) ──────────────────────────────────────────────
    def test_anonymous_product_sale_is_refused(self):
        c, _ = self.live_with_purchase()
        self.sale(480002, '200', TODAY, phcode='')
        with self.assertRaises(ValidationError):
            LG.link_native_product_sale(c.pk, user=self.sup, version=self.v(c), branchcode='130',
                                        docnumber='480002', docdate=TODAY)

    def test_prepared_product_sale_needs_a_patient_code(self):
        c = W.create_case(user=self.maker, branch=self.branch, source_type='client_buyback',
                          settlement_mode='products', items=[{'item_id': self.small.pk, 'qty': 1}])
        c = self.submit(self.calc(c))
        if c.status != RC.STATUS_APPROVED:
            c = W.decide(c.pk, user=self.sup, version=c.version, approve=True)
        with self.assertRaises(ValidationError):
            LG.prepare_product_sale(c.pk, user=self.sup, version=self.v(c), channel='cash',
                                    items=[{'item_id': self.cream.pk, 'qty': 1}])

    # ── backdate on a typed native link ───────────────────────────────────────
    def test_native_purchase_older_than_the_case_is_flagged(self):
        inv = self.ap_invoice(docnumber='12704', docdate=TODAY - timedelta(days=10))
        c = self.approved()
        LG.link_native_purchase(c.pk, user=self.sup, version=self.v(c), branchcode='130',
                                docnumber=inv.docnumber, docdate=inv.docdate)
        self.assertEqual(X.objects.get(case=c, exception_type='backdated_entry').severity, X.SEV_HIGH)


# ═══════════════════════════════════════════════════════════════════════════════
class OwnerApprovalMatrixTests(TW._Base):
    """Owner 2026-10-26. _Base keeps the value band at 2,000 / 6,000 so these isolate each control."""

    def route(self, case):
        return W.approval_route(RC.objects.get(pk=case.pk))

    def test_cash_supervisor_up_to_1500_manager_above(self):
        small = self.calc(self.new_case(item=self.small, mode='cash'))          # 1000 × 0.60 = 600
        self.assertEqual(self.route(small)[0], 'replacement_supervisor')
        big = self.calc(self.new_case(item=self.small, qty=3, mode='cash'))     # 1,800
        wf, reasons = self.route(big)
        self.assertEqual(wf, 'replacement_manager')
        self.assertTrue(any('1500' in r for r in reasons))

    def test_rate_lowered_supervisor_up_to_5pp_manager_above(self):
        ReplacementGrant.objects.create(staff=self.maker, max_override_pp=D('20'))
        c = self.calc(self.new_case(item=self.small), override_pct=D('26'), override_reason='عميل دائم')  # −4 pp
        self.assertEqual(self.route(c)[0], 'replacement_supervisor')
        c = self.calc(self.new_case(item=self.small), override_pct=D('24'), override_reason='عميل دائم')  # −6 pp
        self.assertEqual(self.route(c)[0], 'replacement_manager')

    @override_settings(REPLACEMENT_ENTRY_FIRST_FROM={'130': '2020-01-01'})
    def test_backdate_bands_on_claims(self):
        party = ReconParty.objects.create(party_type='supplier', softech_personcode='4471', name='مورد 30')

        def unclaimed(no, day):
            inv = APInvoice.objects.create(party=party, party_type='supplier', branchcode='130', doccode='10',
                                           docnumber=no, docdate=day, doc_value=D('700'))
            return R.reconstruct_invoice(inv)['case']

        def claim_route(src):
            c = W.create_case(user=self.maker, branch=self.branch, source_type='insurance_rx',
                              settlement_mode='products', softech_pic=PIC,
                              items=[{'item_id': self.small.pk, 'qty': 1}], claim_of=src)
            return self.route(self.calc(c))[0]

        today = timezone.localdate()
        yday = today - timedelta(days=1)
        self.assertEqual(claim_route(unclaimed('1', today)), None)                     # same day → auto (700 ≤ 2000)
        self.assertEqual(claim_route(unclaimed('2', yday)),                             # ≤ 3 days, same month
                         'replacement_supervisor' if yday.month == today.month else 'replacement_manager')
        self.assertEqual(claim_route(unclaimed('3', today - timedelta(days=40))), 'replacement_manager')


# ═══════════════════════════════════════════════════════════════════════════════
@override_settings(REPLACEMENT_ENTRY_FIRST_FROM=CUTOVER)
class EntryFirstApiTests(TW._Base):
    def test_patient_lookup_by_mobile(self):
        from apps.customers.models import Customer
        Customer.objects.filter(softech_pic=PIC).update(phone='01001234567')
        r = self.sup_api.get('/api/replacement/cases/patient-sales/', {'pic': '01001234567'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data['pic'], [p['pic'] for p in r.data['patients']]), (PIC, [PIC]))
        Customer.objects.create(softech_pic='130HD99', name='ابن المريض', phone='01001234567')
        r = self.sup_api.get('/api/replacement/cases/patient-sales/', {'pic': '01001234567'})
        self.assertEqual((len(r.data['patients']), r.data['results']), (2, []))         # choose one

    def test_summary_adoption_and_claim_via_api(self):
        party = ReconParty.objects.create(party_type='supplier', softech_personcode='4471', name='مورد 30')
        inv = APInvoice.objects.create(party=party, party_type='supplier', branchcode='130', doccode='10',
                                       docnumber='12800', docdate=TODAY, doc_value=D('700'), usercode='1776')
        src = R.reconstruct_invoice(inv)['case']
        s = self.sup_api.get('/api/replacement/cases/summary/').data
        a = s['adoption'][0]
        self.assertEqual((a['branchcode'], a['entered_first'], a['unclaimed'], a['rate']), ('130', 0, 1, 0.0))
        self.assertEqual(a['unclaimed_by_user'][0]['usercode'], '1776')
        detail = self.sup_api.get(f'/api/replacement/cases/{src.pk}/').data
        self.assertTrue(detail['workflow']['claimable'])
        r = self.maker_api.post('/api/replacement/cases/', {
            'branch': self.branch.pk, 'source_type': 'insurance_rx', 'settlement_mode': 'products',
            'softech_pic': PIC, 'items': [{'item_id': self.small.pk, 'qty': 1}], 'claim_of': src.pk}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['workflow']['claim_of']['id'], src.pk)
        self.assertEqual(self.sup_api.get(f'/api/replacement/cases/{src.pk}/').data['workflow']['claimed_by']['id'],
                         r.data['id'])
