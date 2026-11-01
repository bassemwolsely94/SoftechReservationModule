"""
Owner requests 2026-10-31 (invoice 225):
- the supplier invoice DATE is OCR'd like the number (PharmaOverseas prints it unlabelled in
  the header; the main OCR missed it) and a missing number/date is flagged before posting;
- SofTech-master VAT disagreements and a missing item↔supplier link are loud NOTICES that
  never block posting;
- «↩ رجوع للتعديل» takes a confirmed / failed / queued / stuck invoice back to review —
  and never reopens one that already reached SOFTECH.
"""
from datetime import date
from unittest import mock

from django.test import SimpleTestCase, TestCase

from apps.invoices.models import InvoiceLine, SupplierInvoice, VendorProfile
from apps.invoices.ocr import find_invoice_date
from .factories import make_admin, make_branch, make_item

TODAY = date(2026, 10, 31)


class FindInvoiceDateTests(SimpleTestCase):
    def test_unlabelled_header_date(self):
        self.assertEqual(find_invoice_date('رقم امر البيع 1019370308  2026-10-29', TODAY), '2026-10-29')

    def test_day_first_and_two_digit_year(self):
        self.assertEqual(find_invoice_date('التاريخ: 29/10/2026', TODAY), '2026-10-29')
        self.assertEqual(find_invoice_date('29-10-26', TODAY), '2026-10-29')

    def test_expiry_and_old_dates_ignored(self):
        self.assertEqual(find_invoice_date('ت. الصلاحية 07/07/2029', TODAY), '')
        self.assertEqual(find_invoice_date('order 2024-01-01', TODAY), '')

    def test_labelled_date_wins(self):
        self.assertEqual(find_invoice_date('2026-10-01 ... تاريخ الفاتورة 2026-10-29', TODAY), '2026-10-29')


class ReopenTests(TestCase):
    def setUp(self):
        self.user, self.profile, self.client = make_admin('reopener')
        self.br = make_branch()
        self.vendor = VendorProfile.objects.create(name='V', softech_personcode='565')
        self.item = make_item(softech_id='90792')

    def _inv(self, status, **kw):
        inv = SupplierInvoice.objects.create(branch=self.br, vendor=self.vendor, supplier_name='S',
                                             invoice_number='8823747321', status=status, **kw)
        InvoiceLine.objects.create(invoice=inv, item=self.item, manual_name='X', quantity=2,
                                   public_price=40, unit_price=32)
        return inv

    def _reopen(self, inv):
        return self.client.post(f'/api/invoices/invoices/{inv.pk}/reopen/')

    def test_confirmed_failed_queued_go_back_to_review(self):
        for st in ('confirmed', 'push_failed', 'queued'):
            inv = self._inv(st)
            r = self._reopen(inv)
            self.assertEqual(r.status_code, 200, (st, r.content))
            inv.refresh_from_db()
            self.assertEqual(inv.status, 'review')

    def test_posted_invoice_never_reopens(self):
        inv = self._inv('finalized', softech_docnumber=66177)
        self.assertEqual(self._reopen(inv).status_code, 400)
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'finalized')

    def test_stuck_pushing_recorded_as_posted_when_softech_has_it(self):
        inv = self._inv('pushing')
        with mock.patch('apps.invoices.writer.find_posted_document', return_value=66181):
            r = self._reopen(inv)
        self.assertEqual(r.json()['status'], 'finalized')
        inv.refresh_from_db()
        self.assertEqual((inv.status, int(inv.softech_docnumber)), ('finalized', 66181))

    def test_stuck_pushing_reopens_when_softech_has_nothing(self):
        inv = self._inv('pushing')
        with mock.patch('apps.invoices.writer.find_posted_document', return_value=None):
            self.assertEqual(self._reopen(inv).status_code, 200)
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'review')

    def test_stuck_pushing_refused_when_softech_unreachable(self):
        inv = self._inv('pushing')
        with mock.patch('apps.invoices.writer.find_posted_document', side_effect=OSError('down')):
            self.assertEqual(self._reopen(inv).status_code, 502)
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'pushing')


class HeaderAndNoticeValidationTests(TestCase):
    def setUp(self):
        self.br = make_branch()
        self.vendor = VendorProfile.objects.create(name='V', softech_personcode='565')
        self.item = make_item(softech_id='90792')

    def _codes(self, **kw):
        from apps.invoices import validations
        kw.setdefault('source_image', 'invoice_images/scan.png')      # a scanned supplier paper
        inv = SupplierInvoice.objects.create(branch=self.br, vendor=self.vendor, supplier_name='S',
                                             status='confirmed', **kw)
        InvoiceLine.objects.create(invoice=inv, item=self.item, manual_name='X', quantity=2,
                                   public_price=40, unit_price=32)
        v = validations.validate_invoice(inv, live=False)
        return [e['code'] for e in v['errors']], [w['code'] for w in v['warnings']], v['notices']

    def test_missing_number_blocks_missing_date_warns(self):
        errors, warnings, _ = self._codes()
        self.assertIn('invoice_number_missing', errors)
        self.assertIn('invoice_date_missing', warnings)

    def test_generated_documents_need_no_printed_number(self):
        errors, warnings, _ = self._codes(source_image='')      # e.g. gift-coupon stocking
        self.assertNotIn('invoice_number_missing', errors)
        self.assertNotIn('invoice_date_missing', warnings)

    def test_complete_header_clean(self):
        errors, warnings, notices = self._codes(invoice_number='8823747321', invoice_date=date(2026, 10, 29))
        self.assertNotIn('invoice_number_missing', errors)
        self.assertNotIn('invoice_date_missing', warnings)
        self.assertEqual(notices, [])
