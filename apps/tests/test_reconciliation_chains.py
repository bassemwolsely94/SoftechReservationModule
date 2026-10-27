"""
apps/tests/test_reconciliation_chains.py

Correction chains (apps/finance/recon_chains.py, doc 23 §17): a wrong مدفوعات
cancelled by a same-amount مقبوضات, optionally re-issued to the same or another
supplier. Cancelled payment + its reversal never settle anything.
"""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase

from apps.finance import recon_engine as E, recon_writer as W
from apps.finance.models import (
    ReconParty, APInvoice, Payment, Allocation, MatchCandidate, ReconException,
)
from apps.finance.recon_chains import detect_chains

T0 = date(2026, 8, 1)


class ChainTests(TestCase):

    def setUp(self):
        self.a = ReconParty.objects.create(party_type='supplier', softech_personcode='100', name='A')
        self.b = ReconParty.objects.create(party_type='supplier', softech_personcode='200', name='B')

    def pay(self, party, no, amount, days, cheqtype='20', note=''):
        return Payment.objects.create(party=party, branchcode='160', cheqsno=no, cheqtype=cheqtype,
                                      direction='out', party_type='supplier',
                                      voucher_date=T0 + timedelta(days=days), amount=D(amount),
                                      note=note, is_unallocated=True)

    def inv(self, party, no, value, days=-5):
        return APInvoice.objects.create(party=party, branchcode='160', doccode='10', docnumber=str(no),
                                        docdate=T0 + timedelta(days=days), doc_value=D(value),
                                        doc_value_pay=D('0'), party_type='supplier')

    def roles(self, *ps):
        out = []
        for p in ps:
            p.refresh_from_db()
            out.append(p.chain_role)
        return out

    def test_reversal_then_reissue_to_other_supplier(self):
        p1 = self.pay(self.a, 61496, '3095.08', 0)                   # wrong supplier
        r = self.pay(self.a, 61497, '3095.08', 0, cheqtype='10')      # cancelled
        p2 = self.pay(self.b, 61498, '3095.08', 0)                   # correct supplier
        res = detect_chains()
        self.assertEqual(self.roles(p1, r, p2), ['reversed', 'reversal', 'reissue'])
        self.assertEqual(res['reissue_other_supplier'], 1)
        self.assertIn('مورد آخر', p2.chain_note)
        self.assertTrue(ReconException.objects.filter(
            exception_type=ReconException.TYPE_SUPPLIER_MISMATCH, payment=p2).exists())

    def test_reversal_reissue_same_supplier(self):
        p1 = self.pay(self.a, 1, '500', 0)
        r = self.pay(self.a, 2, '500', 1, cheqtype='10')
        p2 = self.pay(self.a, 3, '500', 2)
        detect_chains()
        self.assertEqual(self.roles(p1, r, p2), ['reversed', 'reversal', 'reissue'])

    def test_receipt_without_prior_payment_is_refund(self):
        r = self.pay(self.a, 5, '750', 0, cheqtype='10', note='مرتجع مورد')
        detect_chains()
        self.assertEqual(self.roles(r), ['refund'])

    def test_payment_too_old_is_not_paired(self):
        p1 = self.pay(self.a, 1, '500', 0)
        r = self.pay(self.a, 2, '500', 30, cheqtype='10')
        detect_chains()
        self.assertEqual(self.roles(p1, r), ['', 'refund'])

    def test_idempotent(self):
        self.pay(self.a, 1, '500', 0); self.pay(self.a, 2, '500', 0, cheqtype='10')
        detect_chains()
        self.assertEqual(detect_chains()['changed'], 0)

    def test_cancelled_payment_never_matched(self):
        inv = self.inv(self.a, 7001, '500')
        p1 = self.pay(self.a, 1, '500', 0, note='7001')
        self.pay(self.a, 2, '500', 0, cheqtype='10')
        E.run_matching(party_type='supplier')          # runs detect_chains first
        self.assertFalse(MatchCandidate.objects.filter(payment=p1).exists())

    def test_reissued_payment_is_matched_normally(self):
        inv = self.inv(self.b, 8001, '900')
        self.pay(self.a, 1, '900', 0); self.pay(self.a, 2, '900', 0, cheqtype='10')
        p2 = self.pay(self.b, 3, '900', 0, note='8001')
        E.run_matching(party_type='supplier')
        self.assertTrue(MatchCandidate.objects.filter(payment=p2, invoice=inv).exists())

    def test_writer_refuses_cancelled_payment(self):
        inv = self.inv(self.a, 7001, '500')
        p1 = self.pay(self.a, 1, '500', 0)
        self.pay(self.a, 2, '500', 0, cheqtype='10')
        detect_chains()
        p1.refresh_from_db()
        alloc = Allocation.objects.create(payment=p1, invoice=inv, amount=D('500'),
                                          origin=Allocation.ORIGIN_APPROVED)
        with self.assertRaises(W.ReconWriteError):
            W.push_allocation(alloc, dry_run=True)

    def test_native_link_to_cancelled_payment_flagged(self):
        inv = self.inv(self.a, 7001, '500')
        p1 = self.pay(self.a, 1, '500', 0)
        Allocation.objects.create(payment=p1, invoice=inv, amount=D('500'), origin=Allocation.ORIGIN_SOFTECH)
        self.pay(self.a, 2, '500', 0, cheqtype='10')
        detect_chains()
        self.assertTrue(ReconException.objects.filter(
            exception_type=ReconException.TYPE_CANCELLED, payment=p1, invoice=inv).exists())
