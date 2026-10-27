"""
apps/tests/test_reconciliation_returns.py

Returns logic (recon_returns + signed voucher capacity + netting, doc 23 §17):
a return is a CREDIT — netted inside a مدفوعات (voucher = Σ purchases − Σ returns)
or refunded by a مقبوضات. Paid-and-returned invoices with an open credit and open
returns are revision items; a purchase with an open return is payable only for
what was kept.
"""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase, override_settings

from apps.finance import recon_actions as A, recon_allocator as RA, recon_returns as RR
from apps.finance.models import (
    ReconParty, APInvoice, Payment, Allocation, MatchCandidate, ReconException, ReturnLink,
)

T0 = date(2026, 6, 1)


class Base(TestCase):

    def setUp(self):
        self.party = ReconParty.objects.create(party_type='supplier', softech_personcode='4471')

    def doc(self, no, value, days=0, ret=False, paid='0'):
        return APInvoice.objects.create(party=self.party, branchcode='130', doccode='120' if ret else '10',
                                        docnumber=str(no), docdate=T0 + timedelta(days=days),
                                        doc_value=D(value), doc_value_pay=D(paid), is_return=ret,
                                        party_type='supplier', source_hash='x')

    def pay(self, no, amount, days=10, cheqtype='20'):
        return Payment.objects.create(party=self.party, branchcode='130', cheqsno=no, cheqtype=cheqtype,
                                      direction='out', party_type='supplier',
                                      voucher_date=T0 + timedelta(days=days), amount=D(amount),
                                      is_unallocated=True)


class SignedCapacityTests(Base):

    def test_return_link_is_a_credit_on_a_payment_voucher(self):
        p1, p2 = self.doc(1, '1000'), self.doc(2, '500')
        r = self.doc(3, '200', ret=True)
        v = self.pay(10, '1300')                           # 1000 + 500 − 200
        for inv, amt in ((p1, '1000'), (p2, '500'), (r, '200')):
            Allocation.objects.create(payment=v, invoice=inv, amount=D(amt), origin=Allocation.ORIGIN_SOFTECH)
        self.assertEqual(v.allocated_amount, D('1300'))
        self.assertEqual(v.unallocated_amount, D('0'))

    def test_refund_receipt_settles_a_return(self):
        r = self.doc(3, '200', ret=True)
        rec = self.pay(11, '200', cheqtype='10')
        Allocation.objects.create(payment=rec, invoice=r, amount=D('200'), origin=Allocation.ORIGIN_SOFTECH)
        self.assertEqual(rec.unallocated_amount, D('0'))


class ReturnAnalysisTests(Base):

    def link(self, ret, purchase, amount):
        ReturnLink.objects.create(return_invoice=ret, purchase_invoice=purchase,
                                  purchase_branchcode=purchase.branchcode,
                                  purchase_docnumber=purchase.docnumber,
                                  purchase_docdate=purchase.docdate, amount=D(amount))

    def test_paid_after_return_with_open_credit_is_flagged(self):
        p = self.doc(1, '1000')
        r = self.doc(2, '300', days=2, ret=True)             # returned, credit never taken
        self.link(r, p, '300')
        Allocation.objects.create(payment=self.pay(10, '1000', days=5), invoice=p, amount=D('1000'),
                                  origin=Allocation.ORIGIN_SOFTECH)
        res = RR.analyse()
        self.assertEqual(res.get('paid_after_return'), 1)
        e = ReconException.objects.get(exception_type=ReconException.TYPE_PAID_RETURNED)
        self.assertIn('دُفعت بعد إرجاعها', e.detail)
        self.assertTrue(ReconException.objects.filter(exception_type=ReconException.TYPE_OPEN_RETURN,
                                                      invoice=r).exists())

    def test_netted_return_is_not_a_problem(self):
        p = self.doc(1, '1000')
        r = self.doc(2, '300', days=2, ret=True)
        self.link(r, p, '300')
        v = self.pay(10, '700', days=5)                      # SOFTECH netting: 1000 − 300
        Allocation.objects.create(payment=v, invoice=p, amount=D('1000'), origin=Allocation.ORIGIN_SOFTECH)
        Allocation.objects.create(payment=v, invoice=r, amount=D('300'), origin=Allocation.ORIGIN_SOFTECH)
        RR.analyse()
        self.assertFalse(ReconException.objects.filter(
            exception_type__in=[ReconException.TYPE_PAID_RETURNED, ReconException.TYPE_OPEN_RETURN],
            status='open').exists())

    def test_open_return_reduces_payable_capacity(self):
        p = self.doc(1, '1000')
        r = self.doc(2, '300', days=2, ret=True)
        self.link(r, p, '300')
        self.pay(10, '700', days=5)
        invoices, vouchers, returns = RA.open_state(self.party)
        cap = {i.id: i.residual for i in invoices}
        self.assertEqual(cap[p.id], D('700'))              # only what was kept is payable
        self.assertEqual([x.id for x in returns], [r.id])  # the credit is available for netting

    @override_settings(AP_RECONCILE_AUTO_APPROVE=True)
    def test_match_on_invoice_with_open_return_is_held(self):
        p = self.doc(1, '1000')
        r = self.doc(2, '300', days=2, ret=True)
        self.link(r, p, '300')
        c = MatchCandidate.objects.create(party=self.party, invoice=p, payment=self.pay(10, '700', days=5),
                                          proposed_amount=D('700'), confidence_class='high')
        A.auto_approve()
        c.refresh_from_db()
        self.assertEqual(c.status, 'proposed')
        self.assertIn('مرتجع لم يُخصم', c.decision_note)


class NettingStrategyTests(Base):

    def test_voucher_equals_purchases_minus_open_returns(self):
        invs = [RA.OpenInvoice(1, T0, D('1000')), RA.OpenInvoice(2, T0 + timedelta(days=1), D('500'))]
        rets = [RA.OpenInvoice(3, T0 + timedelta(days=2), D('200'))]
        v = RA.OpenVoucher(10, T0 + timedelta(days=10), D('1300'))
        props = RA.allocate(invs, [v], strategies=['net_returns'], returns=rets)
        got = {(p['invoice'].id, p['amount']) for p in props}
        self.assertEqual(got, {(1, D('1000')), (2, D('500')), (3, D('200'))})
        self.assertTrue(any(p.get('is_credit') for p in props))

    def test_no_open_returns_means_no_netting(self):
        invs = [RA.OpenInvoice(1, T0, D('1000'))]
        v = RA.OpenVoucher(10, T0 + timedelta(days=10), D('800'))
        self.assertEqual(RA.allocate(invs, [v], strategies=['net_returns'], returns=[]), [])

    @override_settings(AP_RECONCILE_AUTO_APPROVE=True)
    def test_netting_proposals_are_always_held(self):
        p = self.doc(1, '1000')
        c = MatchCandidate.objects.create(party=self.party, invoice=p, payment=self.pay(10, '800'),
                                          proposed_amount=D('800'), confidence_class='medium',
                                          strategy='net_returns')
        A.auto_approve()
        c.refresh_from_db()
        self.assertEqual(c.status, 'proposed')
