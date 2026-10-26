"""
Pre-save duplicate detection: our module (another SupplierInvoice, same vendor +
printed number) and the fast push guard. The SOFTECH side of check_duplicates is
not exercised here (no live Sybase); it is guarded and returns checked_softech
False offline.
"""
from django.test import TestCase, override_settings

from apps.tests.factories import make_branch, make_admin
from apps.invoices.models import SupplierInvoice, VendorProfile, InvoiceLine
from apps.invoices import writer


class ReconcileThreeWayTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        self.vendor = VendorProfile.objects.create(name='مورد', softech_personcode='12345')

    def _inv_with_lines(self, declared, line_prices):
        inv = SupplierInvoice.objects.create(branch=self.branch, vendor=self.vendor,
                                             doc_kind='purchase', invoice_number='555',
                                             declared_total=declared)
        for p in line_prices:
            InvoiceLine.objects.create(invoice=inv, manual_name='x', quantity=1, unit_price=p)
        return inv

    def test_recon_matches_ocr_no_flag(self):
        inv = self._inv_with_lines(100, [40, 60])        # Σ lines = 100 = declared
        r = writer.reconcile_three_way(inv)
        self.assertEqual(r['reconstructed_total'], 100.0)
        self.assertEqual(r['ocr_total'], 100.0)
        self.assertFalse(any(f['type'] == 'recon_vs_ocr' for f in r['flags']))

    def test_recon_vs_ocr_flagged(self):
        inv = self._inv_with_lines(100, [40, 20])        # Σ lines = 60 vs declared 100
        r = writer.reconcile_three_way(inv)
        f = [x for x in r['flags'] if x['type'] == 'recon_vs_ocr']
        self.assertTrue(f)
        self.assertEqual(f[0]['severity'], 'error')      # 40% diff > 10%
        self.assertIsNone(r['softech_total'])            # no live SOFTECH offline


class DuplicateCheckTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        self.vendor = VendorProfile.objects.create(name='مورد', softech_personcode='12345', is_main=True)

    def _inv(self, number='555', status='review'):
        return SupplierInvoice.objects.create(
            branch=self.branch, vendor=self.vendor, doc_kind='purchase',
            invoice_number=number, status=status)

    def test_detects_our_module_duplicate(self):
        self._inv(status='finalized')          # already posted here
        new = self._inv(status='confirmed')
        res = writer.check_duplicates(new)
        self.assertTrue(res['is_duplicate'])
        self.assertEqual(len(res['pg_duplicates']), 1)
        self.assertEqual(res['pg_duplicates'][0]['status'], 'finalized')

    def test_no_duplicate_for_unique_number(self):
        self._inv(number='111', status='finalized')
        new = self._inv(number='222', status='confirmed')
        res = writer.check_duplicates(new)
        self.assertFalse(res['is_duplicate'])

    def test_different_vendor_not_duplicate(self):
        other = VendorProfile.objects.create(name='آخر', softech_personcode='99999')
        a = SupplierInvoice.objects.create(branch=self.branch, vendor=other,
                                           invoice_number='555', status='finalized')
        new = self._inv(status='confirmed')
        res = writer.check_duplicates(new)
        self.assertFalse(res['is_duplicate'])


@override_settings(INVOICE_WRITER_ENABLED=False)
class PushDuplicateGuardTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        self.vendor = VendorProfile.objects.create(name='مورد', softech_personcode='12345', is_main=True)
        self.user, _, self.client = make_admin('dupadmin')

    def _inv(self, status='confirmed', number='777'):
        return SupplierInvoice.objects.create(
            branch=self.branch, vendor=self.vendor, doc_kind='purchase',
            invoice_number=number, status=status)

    def test_push_blocks_on_duplicate_without_force(self):
        self._inv(status='finalized')
        new = self._inv(status='confirmed')
        r = self.client.post(f'/api/invoices/invoices/{new.pk}/push/')
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.json().get('duplicate'))

    def test_push_allows_with_force(self):
        self._inv(status='finalized')
        new = self._inv(status='confirmed')
        r = self.client.post(f'/api/invoices/invoices/{new.pk}/push/', {'force': 'true'}, format='json')
        # writer gate is OFF → dry-run plan returned (not the 409 duplicate block)
        self.assertNotEqual(r.status_code, 409)


class CandidateScoringTests(TestCase):
    """The multi-factor SOFTECH duplicate scorer (_score_candidate) — pure, offline."""

    def test_exact_number_and_total_and_items_score_high(self):
        cand = {'docnumber2': '1826060925', 'docvalue': 3756.46,
                'docdate': '2026-10-08', '_item_codes': ['883', '7918', '3158']}
        score, factors = writer._score_candidate(
            cand, our_total=3756.46, our_codes={'883', '7918', '3158'},
            our_count=3, our_date=__import__('datetime').date(2026, 10, 8), our_dn2='1826060925')
        self.assertGreaterEqual(score, 0.9)
        self.assertTrue(any('مطابق تماماً' in f for f in factors))

    def test_different_invoice_still_matches_on_total_items_date(self):
        # OCR misread the number, but total + items + date still catch the duplicate.
        cand = {'docnumber2': '9999', 'docvalue': 3756.0,
                'docdate': '2026-10-09', '_item_codes': ['883', '7918', '3158']}
        score, _ = writer._score_candidate(
            cand, our_total=3756.46, our_codes={'883', '7918', '3158'},
            our_count=3, our_date=__import__('datetime').date(2026, 10, 8), our_dn2='1234')
        self.assertGreaterEqual(score, 0.5)

    def test_unrelated_doc_scores_low(self):
        cand = {'docnumber2': '7777', 'docvalue': 120.0,
                'docdate': '2026-01-01', '_item_codes': ['1', '2']}
        score, _ = writer._score_candidate(
            cand, our_total=3756.46, our_codes={'883', '7918', '3158'},
            our_count=3, our_date=__import__('datetime').date(2026, 10, 8), our_dn2='1826060925')
        self.assertLess(score, 0.3)
