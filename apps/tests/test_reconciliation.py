"""
apps/tests/test_reconciliation.py

Phase-C batch 1 — the canonical A/P–A/R reconciliation mirror models
(apps/finance/recon_models.py). Pure-model tests (no SOFTECH access):
  • party-agnostic creation (supplier + customer)
  • SOFTECH composite-key uniqueness (invoice 4-part, payment 2-part, allocation)
  • outstanding / settled / allocated computed properties
  • the ground-truth golden example: voucher 51703 ← 743.40 → invoice 12207
  • candidate + evidence + exception + run + audit event wiring

Ground truth: docs/architecture/23_SOFTECH_AP_RECONCILIATION.md
"""
from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.finance.models import (
    ReconParty, APInvoice, Payment, Allocation, ReconciliationRun,
    MatchCandidate, MatchEvidence, ReconException, ReconAuditEvent,
)


def _supplier(personcode='4471', name='مورد شركات 30'):
    return ReconParty.objects.create(
        party_type='supplier', softech_personcode=personcode, name=name,
    )


def _invoice(party, docnumber='12207', branchcode='130', doccode='10',
             docdate=date(2026, 8, 15), value='743.40', paid='0'):
    return APInvoice.objects.create(
        party=party, branchcode=branchcode, doccode=doccode, docnumber=docnumber,
        docdate=docdate, docnumber2='5213', doc_value=Decimal(value),
        doc_value_pay=Decimal(paid), party_type=party.party_type,
    )


def _payment(party, cheqsno=51703, branchcode='130', amount='743.40'):
    return Payment.objects.create(
        party=party, branchcode=branchcode, cheqsno=cheqsno, cheqno='451',
        ourcheqsno=31789, financial_doc_code='10', cheqtype='20',
        direction='out', party_type=party.party_type, voucher_date=date(2026, 9, 18),
        bankcode='40', amount=Decimal(amount), note='مورد 12207',
        person_new_bal=Decimal('-1598644.04'), bank_new_bal=Decimal('13272723.36'),
    )


class ReconPartyTests(TestCase):

    def test_create_supplier_and_customer(self):
        s = _supplier()
        c = ReconParty.objects.create(
            party_type='customer', softech_personcode='9001', name='عميل تجزئة',
        )
        self.assertEqual(s.party_type, 'supplier')
        self.assertEqual(c.party_type, 'customer')
        self.assertIn('4471', str(s))

    def test_personcode_unique(self):
        _supplier(personcode='4471')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                _supplier(personcode='4471', name='dup')


class APInvoiceTests(TestCase):

    def setUp(self):
        self.party = _supplier()

    def test_outstanding_and_settled(self):
        inv = _invoice(self.party, value='743.40', paid='0')
        self.assertEqual(inv.outstanding, Decimal('743.40'))
        self.assertFalse(inv.is_fully_settled)

        inv.doc_value_pay = Decimal('743.40')
        self.assertEqual(inv.outstanding, Decimal('0.00'))
        self.assertTrue(inv.is_fully_settled)

    def test_partial_payment_outstanding(self):
        inv = _invoice(self.party, value='1000', paid='400')
        self.assertEqual(inv.outstanding, Decimal('600.000'))
        self.assertFalse(inv.is_fully_settled)

    def test_four_part_key_unique(self):
        _invoice(self.party)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                _invoice(self.party)   # same branch/doccode/docnumber/docdate

    def test_same_docnumber_different_branch_allowed(self):
        _invoice(self.party, branchcode='130')
        # docnumbers are per-(branch,doctype) sequences → NOT globally unique
        other = _invoice(self.party, branchcode='140')
        self.assertEqual(APInvoice.objects.count(), 2)
        self.assertNotEqual(other.branchcode, '130')


class PaymentAllocationTests(TestCase):

    def setUp(self):
        self.party   = _supplier()
        self.invoice = _invoice(self.party)
        self.payment = _payment(self.party)

    def test_payment_key_unique(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                _payment(self.party, cheqsno=51703, branchcode='130')

    def test_same_cheqsno_other_branch_allowed(self):
        # cheqsno is only unique within a branch (verified: 51703 exists in 130/150/160/170)
        p = _payment(self.party, cheqsno=51703, branchcode='150')
        self.assertEqual(p.branchcode, '150')

    def test_golden_allocation(self):
        """Voucher 51703 fully settles invoice 12207 for 743.40 (the real row)."""
        alloc = Allocation.objects.create(
            payment=self.payment, invoice=self.invoice,
            amount=Decimal('743.40'), cumulative_paid=Decimal('743.40'),
            origin=Allocation.ORIGIN_SOFTECH,
        )
        self.assertEqual(alloc.amount, Decimal('743.40'))
        self.assertEqual(self.payment.allocated_amount, Decimal('743.40'))
        self.assertEqual(self.payment.unallocated_amount, Decimal('0.00'))

    def test_allocation_unique_per_payment_invoice(self):
        Allocation.objects.create(payment=self.payment, invoice=self.invoice,
                                  amount=Decimal('743.40'))
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Allocation.objects.create(payment=self.payment, invoice=self.invoice,
                                          amount=Decimal('1'))

    def test_one_payment_covers_many_invoices(self):
        inv2 = _invoice(self.party, docnumber='12208', value='256.60')
        big  = _payment(self.party, cheqsno=99999, amount='1000')
        Allocation.objects.create(payment=big, invoice=self.invoice, amount=Decimal('743.40'))
        Allocation.objects.create(payment=big, invoice=inv2,        amount=Decimal('256.60'))
        self.assertEqual(big.allocated_amount, Decimal('1000.00'))
        self.assertEqual(big.unallocated_amount, Decimal('0.00'))

    def test_many_payments_one_invoice(self):
        inv = _invoice(self.party, docnumber='30000', value='1000')
        p1  = _payment(self.party, cheqsno=1001, amount='600')
        p2  = _payment(self.party, cheqsno=1002, amount='400')
        Allocation.objects.create(payment=p1, invoice=inv, amount=Decimal('600'))
        Allocation.objects.create(payment=p2, invoice=inv, amount=Decimal('400'))
        total = sum(a.amount for a in inv.allocations.all())
        self.assertEqual(total, Decimal('1000'))


class MatchCandidateTests(TestCase):

    def setUp(self):
        self.party   = _supplier()
        self.invoice = _invoice(self.party)
        self.payment = _payment(self.party)
        self.run     = ReconciliationRun.objects.create(
            mode=ReconciliationRun.MODE_READONLY, party_type='supplier',
        )

    def test_candidate_with_evidence(self):
        cand = MatchCandidate.objects.create(
            run=self.run, party=self.party, invoice=self.invoice, payment=self.payment,
            proposed_amount=Decimal('743.40'), confidence_score=Decimal('96.00'),
            confidence_class=MatchCandidate.CONF_HIGH,
        )
        MatchEvidence.objects.create(candidate=cand, signal='party',
                                     outcome='exact', weight=Decimal('40'),
                                     contribution=Decimal('40'), detail='نفس المورد 4471')
        MatchEvidence.objects.create(candidate=cand, signal='amount',
                                     outcome='exact', weight=Decimal('30'),
                                     contribution=Decimal('30'), detail='743.40 = 743.40')
        MatchEvidence.objects.create(candidate=cand, signal='note',
                                     outcome='exact', weight=Decimal('20'),
                                     contribution=Decimal('20'), detail='"مورد 12207" في الملاحظات')
        self.assertEqual(cand.evidence.count(), 3)
        self.assertEqual(cand.confidence_class, 'high')
        # evidence ordered by contribution desc
        self.assertEqual(cand.evidence.first().signal, 'party')

    def test_candidate_unique_per_run(self):
        MatchCandidate.objects.create(
            run=self.run, party=self.party, invoice=self.invoice, payment=self.payment,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchCandidate.objects.create(
                    run=self.run, party=self.party, invoice=self.invoice, payment=self.payment,
                )


class ExceptionAndAuditTests(TestCase):

    def setUp(self):
        self.party   = _supplier()
        self.payment = _payment(self.party)

    def test_paid_no_link_exception(self):
        exc = ReconException.objects.create(
            party=self.party, payment=self.payment,
            exception_type=ReconException.TYPE_PAID_NO_LINK,
            severity='warning', detail='سند 51703 بلا تخصيص في chequestrans',
        )
        self.assertEqual(exc.status, 'open')
        self.assertIn('مسدد بلا ربط', str(exc))

    def test_audit_event_records_before_after(self):
        ev = ReconAuditEvent.objects.create(
            action='candidate_proposed', party=self.party,
            rules_version='v1',
            before_state={'allocated': '0'},
            after_state={'proposed': '743.40', 'confidence': 96},
            detail='engine proposal',
        )
        self.assertEqual(ev.after_state['confidence'], 96)
        self.assertEqual(ev.rules_version, 'v1')


class UnallocatedPaymentTests(TestCase):
    """The historical problem set: a payment voucher with no allocation."""

    def test_flag_unallocated(self):
        party = _supplier()
        p = _payment(party)
        p.is_unallocated = True
        p.save(update_fields=['is_unallocated'])
        self.assertTrue(Payment.objects.filter(is_unallocated=True, party=party).exists())
        self.assertEqual(p.unallocated_amount, p.amount)
