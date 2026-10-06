"""
apps/tests/test_reconciliation_autowrite.py

Owner auto-write policy (recon_actions.auto_approve / hold_reason, doc 23 §15):
everything matched is approved EXCEPT real discrepancies, which stay proposed with
a 'يحتاج مراجعة' reason for the deep-revision queue.
"""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase, override_settings

from apps.finance import recon_actions as A
from apps.finance.models import (
    ReconParty, APInvoice, Payment, Allocation, MatchCandidate, ReconException,
)

T0 = date(2026, 6, 1)


@override_settings(AP_RECONCILE_AUTO_APPROVE=True)
class AutoApproveTests(TestCase):

    def setUp(self):
        self.party = ReconParty.objects.create(party_type='supplier', softech_personcode='4471')
        self.n = 0

    def pair(self, inv_value, pay_amount, proposed, cls, strategy='pairwise', lag=5):
        self.n += 1
        inv = APInvoice.objects.create(party=self.party, branchcode='130', doccode='10',
                                       docnumber=str(1000 + self.n), docdate=T0,
                                       doc_value=D(inv_value), doc_value_pay=D('0'), party_type='supplier')
        pay = Payment.objects.create(party=self.party, branchcode='130', cheqsno=5000 + self.n,
                                     direction='out', party_type='supplier',
                                     voucher_date=T0 + timedelta(days=lag), amount=D(pay_amount),
                                     is_unallocated=True)
        return MatchCandidate.objects.create(party=self.party, invoice=inv, payment=pay,
                                             proposed_amount=D(proposed), confidence_class=cls,
                                             confidence_score=D('70'), strategy=strategy)

    def status(self, c):
        c.refresh_from_db()
        return c.status

    def _named(self, inv_value, pay_amount, cheqno=True, branch='130'):
        c = self.pair(inv_value, pay_amount, inv_value, 'high')
        Payment.objects.filter(pk=c.payment_id).update(
            cheqno=c.invoice.docnumber if cheqno else '', branchcode=branch)
        return c

    def test_slight_overage_on_the_named_invoice_is_approved(self):
        # owner case 170/12307: voucher 1,464.60 names invoice 1,461.60 (3 EGP = 0.2%) → approve
        c = self._named('1461.60', '1464.60')
        A.auto_approve()
        self.assertEqual(self.status(c), 'approved')
        self.assertEqual(Allocation.objects.get(candidate=c).amount, D('1461.60'))   # excess stays on the voucher

    def test_overage_stays_held_when_large_unnamed_or_cross_branch(self):
        big = self._named('1000', '1100')                          # 10% over
        unnamed = self._named('1461.60', '1464.60', cheqno=False)
        other_branch = self._named('1461.60', '1464.60', branch='140')
        A.auto_approve()
        for c in (big, unnamed, other_branch):
            self.assertEqual(self.status(c), 'proposed')

    def test_medium_approved_but_fifo_residual_held(self):
        med = self.pair('500', '400', '400', 'medium')                     # partial + ref
        inst = self.pair('900', '300', '300', 'medium', strategy='installments')
        fifo = self.pair('500', '800', '500', 'low', strategy='fifo_residual')
        res = A.auto_approve()
        self.assertEqual(res['approved'], 2)
        for c in (med, inst):
            self.assertEqual(self.status(c), 'approved')
        # leftover-money-oldest-first is 5.6% exact → always a human's call (2026-09-29)
        self.assertEqual(self.status(fifo), 'proposed')
        fifo.refresh_from_db()
        self.assertIn('توزيع المتبقي', fifo.decision_note)
        self.assertEqual(Allocation.objects.filter(origin='approved').count(), 2)

    def test_discrepancies_are_held_with_reason(self):
        cases = {
            'conflict': self.pair('500', '500', '500', 'conflict'),
            'weak': self.pair('500', '300', '300', 'low'),
            'over': self.pair('500', '900', '500', 'medium'),
            'tiny': self.pair('31262.40', '31.26', '31.26', 'medium'),
            'early': self.pair('500', '500', '500', 'medium', lag=-30),
            'late': self.pair('500', '500', '500', 'medium', lag=400),
        }
        res = A.auto_approve()
        self.assertEqual(res['approved'], 0)
        self.assertEqual(res['held'], len(cases))
        for c in cases.values():
            c.refresh_from_db()
            self.assertEqual(c.status, 'proposed')
            self.assertTrue(c.decision_note.startswith(A.HOLD_PREFIX))

    def test_flagged_voucher_is_held(self):
        c = self.pair('500', '500', '500', 'medium')
        ReconException.objects.create(party=self.party, payment=c.payment, severity='critical',
                                      exception_type=ReconException.TYPE_DUPLICATE_PAYMENT)
        A.auto_approve()
        self.assertEqual(self.status(c), 'proposed')

    def test_higher_confidence_gets_capacity_first(self):
        hi = self.pair('500', '500', '500', 'high')
        # a fifo proposal competing for the same invoice
        fifo = MatchCandidate.objects.create(
            party=self.party, invoice=hi.invoice,
            payment=Payment.objects.create(party=self.party, branchcode='130', cheqsno=9999,
                                           direction='out', party_type='supplier',
                                           voucher_date=T0 + timedelta(days=9), amount=D('500'),
                                           is_unallocated=True),
            proposed_amount=D('500'), confidence_class='low', strategy='fifo_residual')
        A.auto_approve()
        self.assertEqual(self.status(hi), 'approved')
        self.assertNotEqual(self.status(fifo), 'approved')


@override_settings(AP_RECONCILE_AUTO_APPROVE=True)
class ReceiptVoucherTests(TestCase):
    """cheqtype '10' = مقبوضات (money received FROM the supplier): never settles a
    purchase invoice — engine, allocator, policy and writer all refuse it."""

    def setUp(self):
        self.party = ReconParty.objects.create(party_type='supplier', softech_personcode='4471')
        self.inv = APInvoice.objects.create(party=self.party, branchcode='130', doccode='10',
                                            docnumber='7001', docdate=T0, doc_value=D('500'),
                                            doc_value_pay=D('0'), party_type='supplier')
        self.rec = Payment.objects.create(party=self.party, branchcode='130', cheqsno=8001,
                                          direction='out', party_type='supplier', cheqtype='10',
                                          voucher_date=T0 + timedelta(days=3), amount=D('500'),
                                          note='مقبوضات 7001', is_unallocated=True)

    def test_engine_and_allocator_never_propose_it(self):
        from apps.finance import recon_engine as E
        E.run_matching(party_type='supplier')
        self.assertFalse(MatchCandidate.objects.filter(payment=self.rec, invoice=self.inv).exists())

    def test_policy_holds_it(self):
        c = MatchCandidate.objects.create(party=self.party, invoice=self.inv, payment=self.rec,
                                          proposed_amount=D('500'), confidence_class='high')
        A.auto_approve()
        c.refresh_from_db()
        self.assertEqual(c.status, 'proposed')
        self.assertIn('مقبوضات', c.decision_note)

    def test_writer_refuses_it_but_reversal_still_possible(self):
        from apps.finance import recon_writer as W
        alloc = Allocation.objects.create(payment=self.rec, invoice=self.inv, amount=D('500'),
                                          origin=Allocation.ORIGIN_APPROVED)
        with self.assertRaises(W.ReconWriteError):
            W.push_allocation(alloc, dry_run=True)
        # a row written before the fix must still be plannable for reversal
        alloc.origin = Allocation.ORIGIN_WRITTEN
        alloc.save()
        self.assertIn('statements', W.build_plan(alloc))

    def test_receipt_may_settle_a_return(self):
        ret = APInvoice.objects.create(party=self.party, branchcode='130', doccode='120',
                                       docnumber='7002', docdate=T0, doc_value=D('500'),
                                       doc_value_pay=D('0'), party_type='supplier', is_return=True)
        from apps.finance import recon_writer as W
        alloc = Allocation.objects.create(payment=self.rec, invoice=ret, amount=D('500'),
                                          origin=Allocation.ORIGIN_APPROVED)
        self.assertTrue(W.push_allocation(alloc, dry_run=True)['dry_run'])


@override_settings(AP_RECONCILE_AUTO_APPROVE=True)
class CrossBranchPartialHoldTests(TestCase):

    def test_partial_from_another_branch_is_held(self):
        party = ReconParty.objects.create(party_type='supplier', softech_personcode='4471')
        inv = APInvoice.objects.create(party=party, branchcode='130', doccode='10', docnumber='9001',
                                       docdate=T0, doc_value=D('1000'), doc_value_pay=D('0'),
                                       party_type='supplier')
        pay = Payment.objects.create(party=party, branchcode='100', cheqsno=9101, direction='out',
                                     party_type='supplier', voucher_date=T0 + timedelta(days=5),
                                     amount=D('400'), is_unallocated=True)
        c = MatchCandidate.objects.create(party=party, invoice=inv, payment=pay, strategy='pairwise',
                                          proposed_amount=D('400'), confidence_class='medium')
        A.auto_approve()
        c.refresh_from_db()
        self.assertEqual(c.status, 'proposed')
        self.assertIn('فرع مختلف', c.decision_note)



class PauseSwitchTests(TestCase):

    @override_settings(AP_RECONCILE_AUTO_APPROVE=False)
    def test_paused_policy_approves_nothing(self):
        res = A.auto_approve()
        self.assertTrue(res.get('paused'))
        self.assertEqual(res['approved'], 0)


class WrittenReviewTests(TestCase):

    def test_written_row_breaking_a_rule_is_tagged_not_reversed(self):
        party = ReconParty.objects.create(party_type='supplier', softech_personcode='4471')
        inv = APInvoice.objects.create(party=party, branchcode='130', doccode='10', docnumber='9101',
                                       docdate=T0, doc_value=D('500'), doc_value_pay=D('0'), party_type='supplier')
        pay = Payment.objects.create(party=party, branchcode='130', cheqsno=9201, direction='out',
                                     party_type='supplier', voucher_date=T0 - timedelta(days=90),
                                     amount=D('500'), is_unallocated=False)
        c = MatchCandidate.objects.create(party=party, invoice=inv, payment=pay, proposed_amount=D('500'),
                                          confidence_class='high', status='written')
        Allocation.objects.create(payment=pay, invoice=inv, amount=D('500'), origin='written', candidate=c)
        res = A.flag_written_for_review()
        c.refresh_from_db()
        self.assertEqual(res['written_needing_review'], 1)
        self.assertTrue(c.decision_note.startswith(A.WRITTEN_REVIEW_PREFIX))
        self.assertEqual(c.status, 'written')                                  # untouched in SOFTECH
        self.assertTrue(Allocation.objects.filter(candidate=c, origin='written').exists())
