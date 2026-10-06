"""
apps/tests/test_reconciliation_ingest.py

Phase-C batch 2 — the pure ingest core (apps/finance/recon_ingest.py), driven with
fabricated SOFTECH rows so NO Sybase connection is needed. Rows mirror the real
ground-truth document (voucher 51703 ← 743.40 → invoice 12207, supplier 4471) from
docs/architecture/23_SOFTECH_AP_RECONCILIATION.md.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.finance import recon_ingest
from apps.finance.models import ReconParty, APInvoice, Payment, Allocation


# ── fabricated SOFTECH rows (column names = real SOFTECH columns) ──────────────

def _inv_row(**kw):
    row = {
        'branchcode': '130', 'doccode': '10', 'docnumber': '12207.0',
        'docdate': '2026-08-15 14:39:35', 'docnumber2': '5213.0',
        'cust_branch_code': '4471', 'docvalue': '743.40', 'docvaluepay': '743.40',
        'fatcurrentstatus': '90', 'docpaydue': None, 'usercode': '1633',
    }
    row.update(kw)
    return row


def _vou_row(**kw):
    row = {
        'branchcode': '130', 'cheqsno': '51703', 'cheqno': '451', 'ourcheqsno': '31789',
        'financialdoccode': '10', 'cheqtype': '20', 'cheqdate': '2026-09-18 00:00:00',
        'bankcode': '40', 'personcode': '4471', 'cheqvalue': '743.40',
        'chequenote': 'مورد 12207', 'personnewbal': '-1598644.04',
        'banknewbal': '13272723.36', 'blockinv': '0', 'usercode': '1509',
        'ptcode': '20', '_party_name': 'مورد شركات 30',
    }
    row.update(kw)
    return row


def _alloc_row(**kw):
    row = {
        'cheqsno': '51703', 'cheqbranchcode': '130', 'branchcode': '130',
        'doccode': '10', 'docnumber': '12207.0', 'docdate': '2026-08-15 00:00:00',
        'docvaluepaid': '743.40', 'docvaluepaynow': '743.40',
    }
    row.update(kw)
    return row


class IngestGoldenTests(TestCase):

    def test_full_golden_ingest(self):
        stats = recon_ingest.ingest(
            invoices=[_inv_row()], vouchers=[_vou_row()], allocations=[_alloc_row()],
            party_type='supplier',
        )
        self.assertEqual(stats['invoices'], 1)
        self.assertEqual(stats['vouchers'], 1)
        self.assertEqual(stats['allocations'], 1)
        self.assertEqual(stats['unallocated_flagged'], 0)

        party = ReconParty.objects.get(softech_personcode='4471')
        self.assertEqual(party.party_type, 'supplier')

        inv = APInvoice.objects.get(branchcode='130', doccode='10', docnumber='12207')
        self.assertEqual(inv.doc_value, Decimal('743.400'))
        self.assertEqual(inv.doc_value_pay, Decimal('743.400'))
        self.assertTrue(inv.is_fully_settled)
        self.assertEqual(inv.docnumber2, '5213')          # trailing .0 stripped
        self.assertEqual(inv.docdate, date(2026, 8, 15))  # datetime → date

        pay = Payment.objects.get(branchcode='130', cheqsno=51703)
        self.assertEqual(pay.direction, 'out')            # supplier ⇒ money out
        self.assertEqual(pay.ourcheqsno, 31789)
        self.assertFalse(pay.is_unallocated)
        self.assertEqual(pay.note, 'مورد 12207')

        alloc = Allocation.objects.get(payment=pay, invoice=inv)
        self.assertEqual(alloc.amount, Decimal('743.400'))
        self.assertEqual(alloc.origin, Allocation.ORIGIN_SOFTECH)
        self.assertTrue(alloc.source_hash)

    def test_idempotent(self):
        args = dict(invoices=[_inv_row()], vouchers=[_vou_row()],
                    allocations=[_alloc_row()], party_type='supplier')
        recon_ingest.ingest(**args)
        hash1 = APInvoice.objects.get(docnumber='12207').source_hash
        recon_ingest.ingest(**args)   # re-run
        self.assertEqual(APInvoice.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(Allocation.objects.count(), 1)
        self.assertEqual(APInvoice.objects.get(docnumber='12207').source_hash, hash1)

    def test_source_hash_changes_on_drift(self):
        recon_ingest.ingest(invoices=[_inv_row()], party_type='supplier')
        h1 = APInvoice.objects.get(docnumber='12207').source_hash
        recon_ingest.ingest(invoices=[_inv_row(docvalue='999.00')], party_type='supplier')
        h2 = APInvoice.objects.get(docnumber='12207').source_hash
        self.assertNotEqual(h1, h2)   # value drift ⇒ different hash


class IngestProblemSetTests(TestCase):

    def test_unallocated_voucher_flagged(self):
        """A voucher with no chequestrans row = the historical problem."""
        stats = recon_ingest.ingest(
            vouchers=[_vou_row(cheqsno='60001')], allocations=[], party_type='supplier',
        )
        self.assertEqual(stats['unallocated_flagged'], 1)
        pay = Payment.objects.get(cheqsno=60001)
        self.assertTrue(pay.is_unallocated)
        self.assertEqual(pay.unallocated_amount, pay.amount)

    def test_allocation_clears_unallocated_flag_on_reingest(self):
        recon_ingest.ingest(vouchers=[_vou_row()], party_type='supplier')
        self.assertTrue(Payment.objects.get(cheqsno=51703).is_unallocated)
        # later run brings the allocation → flag flips off
        recon_ingest.ingest(vouchers=[_vou_row()], allocations=[_alloc_row()],
                            party_type='supplier')
        self.assertFalse(Payment.objects.get(cheqsno=51703).is_unallocated)

    def test_reingest_keeps_our_written_link_written(self):
        args = dict(invoices=[_inv_row()], vouchers=[_vou_row()],
                    allocations=[_alloc_row()], party_type='supplier')
        recon_ingest.ingest(**args)
        Allocation.objects.update(origin=Allocation.ORIGIN_WRITTEN)   # our writer put it there
        recon_ingest.ingest(**args)                                    # nightly re-read
        self.assertEqual(Allocation.objects.get().origin, Allocation.ORIGIN_WRITTEN)

    def test_allocation_to_out_of_window_invoice_creates_stub(self):
        # voucher + allocation ingested, but the invoice itself is NOT in this batch
        recon_ingest.ingest(vouchers=[_vou_row()], allocations=[_alloc_row()],
                            party_type='supplier')
        inv = APInvoice.objects.get(branchcode='130', doccode='10', docnumber='12207')
        self.assertEqual(inv.doc_value, Decimal('0'))     # stub — filled on later invoice ingest
        self.assertEqual(inv.party.softech_personcode, '4471')


class IngestClassificationTests(TestCase):

    def test_customer_sale_direction_in(self):
        stats = recon_ingest.ingest(
            invoices=[_inv_row(doccode='115', docnumber='7001')],
            vouchers=[_vou_row(cheqsno='7001', personcode='9001', ptcode='10')],
            party_type='customer',
        )
        self.assertEqual(stats['invoices'], 1)
        inv = APInvoice.objects.get(docnumber='7001')
        self.assertEqual(inv.party_type, 'customer')
        pay = Payment.objects.get(cheqsno=7001)
        self.assertEqual(pay.direction, 'in')             # customer ⇒ money in

    def test_return_doc_flagged(self):
        recon_ingest.ingest(invoices=[_inv_row(doccode='120', docnumber='9')],
                            party_type='supplier')
        self.assertTrue(APInvoice.objects.get(docnumber='9').is_return)

    def test_unknown_doccode_skipped(self):
        stats = recon_ingest.ingest(
            invoices=[_inv_row(doccode='999', docnumber='1')], party_type='supplier',
        )
        self.assertEqual(stats['invoices'], 0)
        self.assertEqual(stats['skipped'], 1)
        self.assertFalse(APInvoice.objects.filter(docnumber='1').exists())

    def test_ptcode_classifies_when_party_type_not_forced(self):
        # party_type=None → derive from ptcode ('20' ⇒ supplier/out)
        recon_ingest.ingest(vouchers=[_vou_row(cheqsno='8')], party_type=None)
        self.assertEqual(Payment.objects.get(cheqsno=8).party_type, 'supplier')


class CoercionTests(TestCase):

    def test_as_date_variants(self):
        self.assertEqual(recon_ingest._as_date('2026-08-15 14:39:35'), date(2026, 8, 15))
        self.assertEqual(recon_ingest._as_date('2026-08-15'), date(2026, 8, 15))
        self.assertIsNone(recon_ingest._as_date(None))
        self.assertIsNone(recon_ingest._as_date('NULL'))

    def test_dec_variants(self):
        self.assertEqual(recon_ingest._dec('743.40'), Decimal('743.40'))
        self.assertEqual(recon_ingest._dec(None), Decimal('0'))
        self.assertEqual(recon_ingest._dec('NULL'), Decimal('0'))
