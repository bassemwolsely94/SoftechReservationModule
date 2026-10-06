"""
apps/tests/test_reconciliation_anomalies.py

Phase-C batch H — deeper anomaly scan (apps/finance/recon_anomalies.py):
duplicate invoices, over-allocation, statistical payment outliers. No SOFTECH.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.finance import recon_anomalies as H
from apps.finance.models import ReconParty, APInvoice, Payment, Allocation, ReconException


def _party(pc='4471'):
    return ReconParty.objects.create(party_type='supplier', softech_personcode=pc, name='مورد')


def _inv(party, docnumber, value, docnumber2='', is_return=False):
    return APInvoice.objects.create(
        party=party, branchcode='130', doccode='120' if is_return else '10',
        docnumber=docnumber, docdate=date(2026, 8, 15), docnumber2=docnumber2,
        doc_value=Decimal(value), doc_value_pay=Decimal('0'),
        is_return=is_return, party_type='supplier', source_hash='synced',
    )


def _pay(party, cheqsno, amount):
    return Payment.objects.create(
        party=party, branchcode='130', cheqsno=cheqsno, direction='out',
        party_type='supplier', voucher_date=date(2026, 9, 18), amount=Decimal(amount),
        note='', is_unallocated=True,
    )


class DuplicateInvoiceTests(TestCase):

    def test_same_supplier_docno_and_value_flags_duplicate(self):
        p = _party()
        _inv(p, '100', '500', docnumber2='SUP-9')
        _inv(p, '101', '500', docnumber2='SUP-9')   # same supplier doc-no + value
        n = H._duplicate_invoices(p)
        self.assertEqual(n, 1)
        self.assertTrue(ReconException.objects.filter(
            party=p, exception_type=ReconException.TYPE_DUPLICATE_INVOICE).exists())

    def test_different_value_not_duplicate(self):
        p = _party()
        _inv(p, '100', '500', docnumber2='SUP-9')
        _inv(p, '101', '600', docnumber2='SUP-9')   # same doc-no, different value
        self.assertEqual(H._duplicate_invoices(p), 0)

    def test_blank_docno_ignored(self):
        p = _party()
        _inv(p, '100', '500'); _inv(p, '101', '500')   # no docnumber2
        self.assertEqual(H._duplicate_invoices(p), 0)


class OverpaymentTests(TestCase):

    def test_over_allocation_flagged(self):
        p = _party()
        inv = _inv(p, '100', '500')
        pay = _pay(p, 1, '800')
        Allocation.objects.create(payment=pay, invoice=inv, amount=Decimal('800'),
                                  origin=Allocation.ORIGIN_SOFTECH)  # 800 > 500
        n = H._overpayments(p)
        self.assertEqual(n, 1)
        exc = ReconException.objects.get(party=p, exception_type=ReconException.TYPE_OVERPAYMENT)
        self.assertEqual(exc.severity, 'critical')


class OutlierTests(TestCase):

    def test_large_payment_outlier(self):
        p = _party()
        for i in range(12):
            _pay(p, i + 1, '1000')          # tight norm around 1000
        _pay(p, 99, '50000')                # extreme outlier
        n = H._payment_outliers(p)
        self.assertGreaterEqual(n, 1)
        self.assertTrue(ReconException.objects.filter(
            party=p, exception_type=ReconException.TYPE_ANOMALY,
            payment__cheqsno=99).exists())

    def test_small_population_no_flag(self):
        p = _party()
        for i in range(4):
            _pay(p, i + 1, '1000')
        _pay(p, 99, '50000')
        self.assertEqual(H._payment_outliers(p), 0)   # <8 payments → no norm


class MisallocationTests(TestCase):

    def _alloc(self, pay, inv, amount):
        return Allocation.objects.create(payment=pay, invoice=inv, amount=Decimal(amount),
                                         origin=Allocation.ORIGIN_SOFTECH)

    def test_swapped_pair_flagged(self):
        p = _party()
        a = _inv(p, '100', '500')          # note will name this one
        b = _inv(p, '200', '700')          # SOFTECH settled this one (wrong)
        pay = _pay(p, 1, '500')            # amount matches A exactly, not B
        pay.note = 'دفعة فاتورة رقم 100'; pay.save()
        self._alloc(pay, b, '500')
        n = H._misallocations(p)
        self.assertEqual(n, 1)
        exc = ReconException.objects.get(party=p, exception_type=ReconException.TYPE_MISALLOCATION)
        self.assertEqual(exc.invoice_id, a.id)      # flags the invoice the note NAMES
        self.assertEqual(exc.payment_id, pay.id)
        self.assertEqual(exc.severity, 'warning')   # money sits on the wrong invoice

    def test_note_names_settled_invoice_no_flag(self):
        p = _party()
        _inv(p, '100', '500')
        b = _inv(p, '200', '700')
        pay = _pay(p, 1, '700')
        pay.note = 'فاتورة 200'; pay.save()     # note DOES name the settled invoice
        self._alloc(pay, b, '700')
        self.assertEqual(H._misallocations(p), 0)

    def test_equal_value_crossed_pair_flagged_info(self):
        # the real shadow-mode case: two 100.00 vouchers 'ف 11552'/'ف 11548' whose
        # SOFTECH links are crossed — both flagged, info (no balance effect)
        p = _party()
        a = _inv(p, '11548', '100')
        b = _inv(p, '11552', '100')
        p1 = _pay(p, 55482, '100'); p1.note = 'ف 11552'; p1.save()
        p2 = _pay(p, 55481, '100'); p2.note = 'ف 11548'; p2.save()
        self._alloc(p1, a, '100')          # names 11552, settled 11548
        self._alloc(p2, b, '100')          # names 11548, settled 11552
        self.assertEqual(H._misallocations(p), 2)
        excs = ReconException.objects.filter(exception_type=ReconException.TYPE_MISALLOCATION)
        self.assertEqual({e.severity for e in excs}, {'info'})
        self.assertEqual({(e.payment_id, e.invoice_id) for e in excs},
                         {(p1.id, b.id), (p2.id, a.id)})
        self.assertEqual(H._misallocations(p), 0)   # idempotent re-scan

    def test_single_invoice_party_skipped(self):
        p = _party()
        b = _inv(p, '200', '700')
        pay = _pay(p, 1, '500')
        pay.note = 'فاتورة 100'; pay.save()
        self._alloc(pay, b, '500')
        self.assertEqual(H._misallocations(p), 0)


class MisallocationLifecycleTests(TestCase):
    """Owner case 170/53662: a flag must close once the mis-link is gone, and a link OUR
    writer made (even if re-labelled 'softech') is never SOFTECH's mis-allocation."""

    def _swapped(self):
        p = _party()
        named = _inv(p, '13073', '319.20')
        other = _inv(p, '12812', '319.20')
        pay = _pay(p, 53662, '319.20')
        Payment.objects.filter(pk=pay.pk).update(note='13073')
        a = Allocation.objects.create(payment=pay, invoice=other, amount=Decimal('319.20'),
                                      origin=Allocation.ORIGIN_SOFTECH)
        return p, a

    def test_flag_closes_when_the_mislink_is_gone(self):
        p, a = self._swapped()
        self.assertEqual(H._misallocations(p), 1)
        a.delete()                                          # reversed / re-paired
        H._misallocations(p)
        self.assertFalse(ReconException.objects.filter(
            party=p, exception_type=ReconException.TYPE_MISALLOCATION, status='open').exists())

    def test_our_own_link_is_not_a_softech_misallocation(self):
        from apps.finance.models import ReconAuditEvent
        p, a = self._swapped()
        ReconAuditEvent.objects.create(action='allocation_written', allocation=a)
        self.assertEqual(H._misallocations(p), 0)


class ScanTests(TestCase):

    def test_scan_idempotent(self):
        p = _party()
        _inv(p, '100', '500', docnumber2='SUP-9')
        _inv(p, '101', '500', docnumber2='SUP-9')
        H.scan(party_type='supplier')
        n1 = ReconException.objects.count()
        H.scan(party_type='supplier')   # re-run must not duplicate open exceptions
        self.assertEqual(ReconException.objects.count(), n1)

    def test_scan_scoped_by_personcode(self):
        a = _party('4471'); b = _party('5000')
        _inv(a, '1', '500', docnumber2='X'); _inv(a, '2', '500', docnumber2='X')
        _inv(b, '3', '700', docnumber2='Y'); _inv(b, '4', '700', docnumber2='Y')
        H.scan(personcode='4471')
        self.assertTrue(ReconException.objects.filter(party=a).exists())
        self.assertFalse(ReconException.objects.filter(party=b).exists())
