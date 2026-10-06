"""
Doc 25 Phase 0 — regressions found on the first real-data reconstruction run (2026-10-01):
  1. procurement.PurchaseLine rows synced before the 2026-06-25 date fix are dated one day early
  2. a supplier return closed by a voucher (cash back / netting) must NOT leave the case negative
  3. a genuinely OPEN return leaves a real negative balance (money owed back) — flagged HIGH
  4. several patients with the same chronic Rx → the voucher-day receipts name the patient
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.replacement import reconstruct as R
from apps.replacement.models import (CaseDocument as CD, CaseException as X,
                                     EntitlementLedgerEntry as E, ReplacementItem)

from .test_replacement import _local_midnight, _utc

D = Decimal


class RealDataRegressionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.branches.models import Branch
        from apps.catalog.models import Item
        from apps.customers.models import Customer
        from apps.finance.recon_models import ReconParty
        cls.branch = Branch.objects.create(softech_branch_id='160', name='B160')
        cls.item = Item.objects.create(softech_id='700001', name='CHRONIC X', is_active=True)
        cls.shampoo = Item.objects.create(softech_id='700002', name='SHAMPOO', is_active=True)
        cls.p30 = ReconParty.objects.create(party_type='supplier', softech_personcode='4471', name='مورد شركات 30')
        cls.p40 = ReconParty.objects.create(party_type='supplier', softech_personcode='4470', name='مورد شركات 40')
        cls.cust_a = Customer.objects.create(softech_pic='160HDA', name='مريض أ', phone='1')
        cls.cust_b = Customer.objects.create(softech_pic='160HDB', name='مريض ب', phone='2')

    def _inv(self, party, docno, d, value, doccode='10'):
        from apps.finance.recon_models import APInvoice
        return APInvoice.objects.create(party=party, party_type='supplier', branchcode='160', doccode=doccode,
                                        docnumber=str(docno), docdate=d, doc_value=D(value),
                                        is_return=doccode == '120')

    def _line(self, party, docno, d, value, public='1000'):
        from apps.procurement.models import PurchaseLine
        PurchaseLine.objects.create(branch_code='160', supplier_code=party.softech_personcode, doc_number=str(docno),
                                    doc_date=d, item_code=self.item.softech_id, doccode='10', raw_qty=D('1'),
                                    raw_value=D(value), unit_price=D(value), public_price=D(public),
                                    item=self.item, branch=self.branch)

    def _voucher(self, party, sno, d, amount, invoice, cheqtype='20', tt=None):
        from apps.finance.recon_models import Allocation, Payment
        p = Payment.objects.create(party=party, party_type='supplier', branchcode='160', cheqsno=sno,
                                   cheqtype=cheqtype, direction='out' if cheqtype == '20' else 'in',
                                   voucher_date=d, amount=D(amount), trans_time=tt)
        Allocation.objects.create(payment=p, invoice=invoice, amount=D(amount), origin='softech')
        return p

    def _sale(self, cust, docno, d, total, channel='10', item=None, tt=None):
        from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
        ph = PurchaseHistory.objects.create(
            customer=cust, branch=self.branch, doc_code='115', total_amount=D(total), docnumber=str(docno),
            softech_invoice_id=f'160-115-{docno}-{d:%Y%m%d}', invoice_date=_local_midnight(d),
            sales_channel=channel, softech_phcode=cust.softech_pic, cust_branch_code='4222', trans_time=tt)
        PurchaseHistoryLine.objects.create(purchase=ph, item=item or self.item, quantity=D('1'),
                                           unit_price=D(total), line_total=D(total), list_price=D('1000'))
        return ph

    def test_purchase_lines_with_legacy_minus_one_day_date_are_found(self):
        inv = self._inv(self.p30, 22952, date(2025, 8, 17), '700')
        self._line(self.p30, 22952, date(2025, 8, 16), '700')       # pre-fix mirror row: one day early
        c = R.reconstruct_invoice(inv)['case']
        self.assertFalse(c.exceptions.filter(exception_type='purchase_lines_missing').exists())
        self.assertEqual(c.items.filter(disposition=ReplacementItem.DISP_REPLACED).count(), 1)

    def test_return_settled_by_receipt_voucher_nets_to_zero(self):
        from apps.finance.recon_models import ReturnLink
        d = date(2025, 9, 1)
        inv = self._inv(self.p40, 500, d, '448.80')
        self._line(self.p40, 500, d, '448.80')
        self._voucher(self.p40, 63061, d, '448.80', inv)
        ret = self._inv(self.p40, 483, date(2025, 9, 3), '448.80', doccode='120')
        ReturnLink.objects.create(return_invoice=ret, purchase_invoice=inv, purchase_branchcode='160',
                                  purchase_docnumber='500', purchase_docdate=d, amount=D('448.80'))
        self._voucher(self.p40, 63066, date(2025, 9, 3), '448.80', ret, cheqtype='10')   # cash back
        c = R.reconstruct_invoice(inv)['case']
        self.assertEqual(c.outstanding, D('0.00'))
        self.assertEqual(c.native_outstanding, D('0.00'))
        self.assertFalse(c.exceptions.filter(exception_type='negative_entitlement').exists())
        self.assertTrue(c.ledger.filter(entry_type=E.TYPE_RETURN_SETTLED, amount=D('448.80')).exists())
        self.assertTrue(c.documents.filter(role=CD.ROLE_RETURN_SETTLEMENT).exists())
        self.assertEqual(c.reversed_by_return, D('0.00'))

    def test_open_return_leaves_negative_balance_and_flags_it(self):
        from apps.finance.recon_models import ReturnLink
        d = date(2025, 9, 1)
        inv = self._inv(self.p30, 501, d, '712')
        self._line(self.p30, 501, d, '712')
        self._voucher(self.p30, 63850, d, '712', inv)
        ret = self._inv(self.p30, 490, date(2025, 9, 2), '226', doccode='120')
        ReturnLink.objects.create(return_invoice=ret, purchase_invoice=inv, purchase_branchcode='160',
                                  purchase_docnumber='501', purchase_docdate=d, amount=D('226'))
        c = R.reconstruct_invoice(inv)['case']
        self.assertEqual(c.outstanding, D('-226.00'))
        self.assertEqual(c.native_outstanding, D('-226.00'))            # invariant I-1 still holds
        self.assertEqual(c.exceptions.get(exception_type='negative_entitlement').severity, X.SEV_HIGH)
        self.assertFalse(c.exceptions.filter(exception_type='ledger_native_mismatch').exists())

    def test_split_purchase_within_sold_qty_is_not_a_duplicate_but_overclaim_is(self):
        from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
        d = date(2025, 9, 20)
        ph = PurchaseHistory.objects.create(
            customer=self.cust_a, branch=self.branch, doc_code='115', total_amount=D('1800'), docnumber='9500',
            softech_invoice_id=f'160-115-9500-{d:%Y%m%d}', invoice_date=_local_midnight(d),
            sales_channel='10', softech_phcode=self.cust_a.softech_pic, cust_branch_code='4222')
        PurchaseHistoryLine.objects.create(purchase=ph, item=self.item, quantity=D('2'), unit_price=D('900'),
                                           line_total=D('1800'), list_price=D('1000'))
        cases = []
        for no in (601, 602, 603):                                  # 3 × qty 1 against a sale of qty 2
            inv = self._inv(self.p30, no, d, '700')
            self._line(self.p30, no, d, '700')
            cases.append(R.reconstruct_invoice(inv)['case'])
        flags = [c.exceptions.filter(exception_type='duplicate_purchase').exists() for c in cases]
        self.assertEqual(flags, [False, False, True])               # only the third exceeds what was sold
        self.assertTrue(all(c.softech_pic == '160HDA' for c in cases))
        # re-running the FIRST case after the others exist must not change its verdict (order-independent)
        c1 = R.reconstruct_invoice(cases[0].purchase_invoice)['case']
        self.assertFalse(c1.exceptions.filter(exception_type='duplicate_purchase', status='open').exists())

    def test_buying_back_more_than_one_sale_holds_is_a_warning_not_a_duplicate(self):
        d = date(2025, 9, 25)
        self._sale(self.cust_a, 9600, d, '900')                    # qty 1 sold
        inv = self._inv(self.p30, 610, d, '2800')
        from apps.procurement.models import PurchaseLine
        PurchaseLine.objects.create(branch_code='160', supplier_code='4471', doc_number='610', doc_date=d,
                                    item_code=self.item.softech_id, doccode='10', raw_qty=D('4'),
                                    raw_value=D('2800'), unit_price=D('700'), public_price=D('1000'),
                                    item=self.item, branch=self.branch)   # qty 4 bought back
        c = R.reconstruct_invoice(inv)['case']
        self.assertFalse(c.exceptions.filter(exception_type='duplicate_purchase').exists())
        self.assertEqual(c.exceptions.get(exception_type='qty_exceeds_sale').severity, X.SEV_WARNING)

    def test_cross_branch_link_written_by_our_ap_writer_is_high(self):
        from apps.finance.recon_models import Allocation, Payment
        d = date(2025, 9, 1)
        inv = self._inv(self.p30, 620, d, '500')
        self._line(self.p30, 620, d, '500')
        p = Payment.objects.create(party=self.p30, party_type='supplier', branchcode='140', cheqsno=70001,
                                   cheqtype='20', direction='out', voucher_date=d, amount=D('500'))
        Allocation.objects.create(payment=p, invoice=inv, amount=D('500'), origin='written')
        c = R.reconstruct_invoice(inv)['case']
        x = c.exceptions.get(exception_type='cross_branch_voucher')
        self.assertEqual(x.severity, X.SEV_HIGH)
        self.assertEqual(x.evidence['origin'], 'written')

    def test_reset_refused_after_any_human_decision(self):
        from apps.lineage.models import DocumentEdge
        from apps.replacement.models import ReplacementCase
        inv = self._inv(self.p30, 503, date(2025, 9, 1), '100')
        self._line(self.p30, 503, date(2025, 9, 1), '100')
        R.reconstruct_invoice(inv)
        self.assertEqual(R.reset_blockers(), [])
        counts = R.reset_reconstructed()
        self.assertEqual(counts['cases'], 1)
        self.assertEqual(ReplacementCase.objects.count(), 0)
        c = R.reconstruct_invoice(inv)['case']
        from .factories import make_user
        _, staff, _ = make_user('sup_reset', role='supervisor', access_all=True)
        DocumentEdge.objects.filter(to_ref=c.purchase_ref).update(decided_by=staff)
        c.exceptions.update(status=X.STATUS_RESOLVED) if c.exceptions.exists() else None
        v = self._voucher(self.p30, 64100, date(2025, 9, 2), '100', inv)
        c = R.reconstruct_invoice(inv)['case']
        DocumentEdge.objects.filter(from_ref__docnumber=str(v.cheqsno)).update(decided_by=staff)
        self.assertTrue(R.reset_blockers())
        with self.assertRaises(RuntimeError):
            R.reset_reconstructed()
        self.assertEqual(ReplacementCase.objects.count(), 1)

    def test_voucher_day_receipts_break_a_patient_tie(self):
        self._sale(self.cust_a, 9001, date(2025, 9, 8), '900')
        self._sale(self.cust_b, 9002, date(2025, 9, 8), '900')         # identical Rx, other patient
        inv = self._inv(self.p30, 502, date(2025, 9, 10), '700')
        self._line(self.p30, 502, date(2025, 9, 10), '700')
        self._voucher(self.p30, 64000, date(2025, 9, 12), '300', inv, tt=_utc(2025, 9, 12, 12, 0))
        self._sale(self.cust_b, 9100, date(2025, 9, 12), '300', channel='91', item=self.shampoo,
                   tt=_utc(2025, 9, 12, 11, 50))
        c = R.reconstruct_invoice(inv)['case']
        self.assertEqual(c.softech_pic, '160HDB')
        self.assertFalse(c.exceptions.filter(exception_type='ambiguous_patient').exists())
        self.assertEqual(c.redeemed_products, D('300.00'))
