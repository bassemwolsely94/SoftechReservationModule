"""
End-to-end orchestration test for multi-invoice bundle ingestion
(apps/invoices/ingest.process_bundle).

The PDF rendering and the Gemini probe/extract I/O are stubbed so the test is
deterministic and offline; what it verifies is the Phase-1 orchestration:
a bundle whose pages probe as TWO distinct invoices is fanned out into two
SupplierInvoice rows carrying the right source pages, and the split is recorded
on the batch for audit. Matching (pipeline.build_lines) is stubbed to a recorder
— its logic is covered elsewhere and is unchanged by this phase.
"""
from unittest import mock

from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.tests.factories import make_branch
from apps.invoices.models import InvoiceBatch, SupplierInvoice
from apps.invoices import ingest


class BundleIngestTests(TestCase):

    def setUp(self):
        self.branch = make_branch()

    def _batch(self):
        pdf = SimpleUploadedFile('bundle.pdf', b'%PDF-1.4 fake', content_type='application/pdf')
        return InvoiceBatch.objects.create(branch=self.branch, source_file=pdf)

    def test_two_invoice_bundle_fans_out(self):
        batch = self._batch()
        # two pages, two distinct one-page invoices (the Ramco pattern)
        by_path = {
            'p1.png': {'doc_number': '1826060925', 'page_index': 1, 'page_count': 1,
                       'has_header': True, 'has_totals': True, 'supplier_name': 'رامكو'},
            'p2.png': {'doc_number': '1826060870', 'page_index': 1, 'page_count': 1,
                       'has_header': True, 'has_totals': True, 'supplier_name': 'رامكو'},
        }
        struct = {'supplier_name': 'رامكو', 'lines': [
            {'item_name': 'PANADOL', 'quantity': 1, 'public_price': 10}]}

        with mock.patch('apps.invoices.pdf.render_pages', return_value=['p1.png', 'p2.png']), \
             mock.patch('apps.invoices.ingest._preprocess_pages', return_value=(set(), 0)), \
             mock.patch('apps.invoices.ingest._probe_one', side_effect=lambda p, h: dict(by_path[p])), \
             mock.patch('apps.invoices.ocr.extract_structured_images', return_value=struct), \
             mock.patch('apps.invoices.ocr.parse_structured',
                        return_value=({'supplier_name': 'رامكو'}, [])), \
             mock.patch('apps.invoices.pipeline.build_lines') as build:
            ingest.process_bundle(batch.pk)

        batch.refresh_from_db()
        self.assertEqual(batch.status, 'ready')
        self.assertEqual(batch.page_count, 2)
        self.assertEqual(batch.detected_count, 2)
        invoices = list(SupplierInvoice.objects.filter(batch=batch).order_by('id'))
        self.assertEqual(len(invoices), 2)
        self.assertEqual(invoices[0].source_pages, [1])
        self.assertEqual(invoices[1].source_pages, [2])
        self.assertEqual(invoices[0].invoice_number, '1826060925')
        self.assertEqual(build.call_count, 2)       # matching ran once per invoice

    def test_three_page_single_invoice_stays_one(self):
        batch = self._batch()
        by_path = {
            'p1.png': {'doc_number': '5001', 'page_index': 1, 'page_count': 3, 'has_totals': False},
            'p2.png': {'doc_number': '5001', 'page_index': 2, 'page_count': 3, 'has_header': False, 'has_totals': False},
            'p3.png': {'doc_number': '5001', 'page_index': 3, 'page_count': 3, 'has_header': False, 'has_totals': True},
        }
        with mock.patch('apps.invoices.pdf.render_pages', return_value=['p1.png', 'p2.png', 'p3.png']), \
             mock.patch('apps.invoices.ingest._preprocess_pages', return_value=(set(), 0)), \
             mock.patch('apps.invoices.ingest._probe_one', side_effect=lambda p, h: dict(by_path[p])), \
             mock.patch('apps.invoices.ocr.extract_structured_images', return_value=None), \
             mock.patch('apps.invoices.ocr.extract_text', return_value=''), \
             mock.patch('apps.invoices.ocr.parse_lines', return_value=[]), \
             mock.patch('apps.invoices.pipeline.build_lines'):
            ingest.process_bundle(batch.pk)

        batch.refresh_from_db()
        self.assertEqual(batch.detected_count, 1)
        inv = SupplierInvoice.objects.get(batch=batch)
        self.assertEqual(inv.source_pages, [1, 2, 3])

    def test_blank_page_skipped(self):
        batch = self._batch()
        by_path = {
            'p1.png': {'doc_number': '7001', 'page_index': 1, 'page_count': 1, 'has_totals': True},
            'p3.png': {'doc_number': '7002', 'page_index': 1, 'page_count': 1, 'has_totals': True},
        }
        with mock.patch('apps.invoices.pdf.render_pages', return_value=['p1.png', 'p2.png', 'p3.png']), \
             mock.patch('apps.invoices.ingest._preprocess_pages', return_value=({1}, 0)), \
             mock.patch('apps.invoices.ingest._probe_one', side_effect=lambda p, h: dict(by_path[p])), \
             mock.patch('apps.invoices.ocr.extract_structured_images', return_value=None), \
             mock.patch('apps.invoices.ocr.extract_text', return_value=''), \
             mock.patch('apps.invoices.ocr.parse_lines', return_value=[]), \
             mock.patch('apps.invoices.pipeline.build_lines'):
            ingest.process_bundle(batch.pk)
        batch.refresh_from_db()
        self.assertEqual(batch.detected_count, 2)              # blank page 2 skipped
        self.assertIn('blank_pages', batch.flags)

    def test_durability_command_reprocesses_pending(self):
        from django.core.management import call_command
        b = InvoiceBatch.objects.create(branch=self.branch, status='pending')
        with mock.patch('apps.invoices.ingest.process_bundle') as proc:
            call_command('process_pending_batches')
        proc.assert_called_once_with(b.pk)

    def test_no_renderer_fails_cleanly(self):
        batch = self._batch()
        with mock.patch('apps.invoices.pdf.render_pages', return_value=[]):
            ingest.process_bundle(batch.pk)
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'failed')
        self.assertIn('PyMuPDF', batch.error)
        self.assertEqual(SupplierInvoice.objects.filter(batch=batch).count(), 0)


class ImpossibleNumbersTests(TestCase):
    """A number OCR put in the wrong column (a real Pharma Overseas page read 1,000+ into
    «VAT %») is dropped and noted — it no longer crashes the line / the bundle."""

    def test_values_that_cannot_be_right_are_dropped_and_noted(self):
        from apps.branches.models import Branch
        from apps.invoices import pipeline
        from apps.invoices.models import SupplierInvoice
        br = Branch.objects.create(softech_branch_id='991', name='T')
        inv = SupplierInvoice.objects.create(branch=br, status='review')
        cands = [{'raw_text': 'دواء تجريبي', 'manual_name': 'دواء تجريبي', 'quantity': 2,
                  'public_price': 8822632985, 'discount_pct': 25, 'vat_pct': 1824.3, 'unit_price': 37.5}]
        with mock.patch('apps.shortage.matching.find_best_matches', return_value=[]):
            pipeline.build_lines(inv, cands)
        ln = inv.lines.get()
        self.assertEqual((float(ln.vat_pct), float(ln.public_price), float(ln.discount_pct)), (0.0, 0.0, 25.0))
        self.assertIn('vat_pct=1824.3', ln.notes)
        self.assertIn('public_price=8822632985', ln.notes)
