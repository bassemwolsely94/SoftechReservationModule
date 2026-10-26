"""
Tests for multi-invoice PDF boundary detection (apps/invoices/splitter.py).

Fixtures mirror the two REAL specimens examined on 2026-10-16:
  - Ramco 50-page PDF = many one-page invoices, doc number changes each page,
    each page carries its own "1 / 1" counter and totals block.
  - PharmaOverseas priced-receipt with tax sections WITHIN one page (must not
    cause a split) and English "Page 1 of 1".
Plus synthetic multi-page invoices to exercise the "x of y" continuation logic.
"""
from django.test import SimpleTestCase

from apps.invoices import splitter as sp
from apps.invoices.ocr import _parse_page_signals


def _p(page, doc_number=None, page_index=None, page_count=None,
       has_header=True, has_totals=True, doc_type='', date=''):
    return dict(page=page, doc_number=doc_number, page_index=page_index,
                page_count=page_count, has_header=has_header, has_totals=has_totals,
                doc_type=doc_type, date=date)


class RamcoStackTests(SimpleTestCase):
    """50-page PDF of distinct one-page invoices → 50 invoices, never 1 blob."""

    def test_two_distinct_one_page_invoices_split(self):
        probes = [
            _p(0, doc_number='1826060925', page_index=1, page_count=1, date='2026-10-13'),
            _p(1, doc_number='1826060870', page_index=1, page_count=1, date='2026-10-12'),
        ]
        self.assertEqual(sp.group_pages(probes), [[0], [1]])

    def test_ten_distinct_pages_give_ten_invoices(self):
        probes = [_p(i, doc_number=str(1826060000 + i), page_index=1, page_count=1)
                  for i in range(10)]
        self.assertEqual(len(sp.group_pages(probes)), 10)

    def test_counter_alone_splits_even_without_doc_number(self):
        # OCR missed the invoice number on every page, but each reads "1 / 1"
        probes = [_p(0, page_index=1, page_count=1), _p(1, page_index=1, page_count=1)]
        self.assertEqual(sp.group_pages(probes), [[0], [1]])

    def test_no_signal_falls_back_to_one_per_page(self):
        # worst case: no doc number, no counter, but each page is a full invoice
        # (header + totals) → safe one-invoice-per-page default (correct for Ramco)
        probes = [_p(0, doc_number=None, page_index=None, page_count=None),
                  _p(1, doc_number=None, page_index=None, page_count=None)]
        self.assertEqual(sp.group_pages(probes), [[0], [1]])


class MultiPageInvoiceTests(SimpleTestCase):
    """Genuine multi-page invoices must stay together (the directive's warning)."""

    def test_three_page_invoice_stays_one(self):
        probes = [
            _p(0, doc_number='5001', page_index=1, page_count=3, has_totals=False),
            _p(1, doc_number='5001', page_index=2, page_count=3, has_header=False, has_totals=False),
            _p(2, doc_number='5001', page_index=3, page_count=3, has_header=False, has_totals=True),
        ]
        self.assertEqual(sp.group_pages(probes), [[0, 1, 2]])

    def test_two_multipage_invoices_split_at_counter_reset(self):
        probes = [
            _p(0, doc_number='5001', page_index=1, page_count=2, has_totals=False),
            _p(1, doc_number='5001', page_index=2, page_count=2),
            _p(2, doc_number='5002', page_index=1, page_count=2, has_totals=False),
            _p(3, doc_number='5002', page_index=2, page_count=2),
        ]
        self.assertEqual(sp.group_pages(probes), [[0, 1], [2, 3]])

    def test_continuation_when_doc_number_missing_on_page_two(self):
        # page 2's header/number didn't read, but "2 of 2" continues page 1
        probes = [
            _p(0, doc_number='5001', page_index=1, page_count=2, has_totals=False),
            _p(1, doc_number=None, page_index=2, page_count=2, has_header=False),
        ]
        self.assertEqual(sp.group_pages(probes), [[0, 1]])

    def test_page_count_exhausted_forces_new_segment(self):
        # declared "1 of 1" then another page with no counter → must not absorb it
        probes = [
            _p(0, doc_number='5001', page_index=1, page_count=1),
            _p(1, doc_number=None, page_index=None, page_count=None),
        ]
        self.assertEqual(sp.group_pages(probes), [[0], [1]])


class PharmaOverseasTests(SimpleTestCase):

    def test_tax_sections_do_not_split_a_single_page(self):
        # the whole priced-receipt is one page; intra-page tax sections are a
        # line-parsing concern, so the splitter just sees one page = one invoice
        probes = [_p(0, doc_number='8822632985', page_index=1, page_count=1,
                     doc_type='اذن استلام مسعر')]
        self.assertEqual(sp.group_pages(probes), [[0]])

    def test_doc_type_preserved_in_summary(self):
        probes = [_p(0, doc_number='8822632985', page_index=1, page_count=1,
                     doc_type='اذن استلام مسعر', date='2026-10-13')]
        g = sp.group_pages(probes)
        s = sp.summarize(probes, g)
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]['doc_type'], 'اذن استلام مسعر')
        self.assertEqual(s[0]['page_numbers'], [1])
        self.assertEqual(s[0]['confidence'], 'high')


class PageSignalParserTests(SimpleTestCase):
    """Engine-agnostic signal parser (works on text from ANY OCR engine)."""

    def test_ramco_footer_counter_and_number(self):
        text = 'رامكو فارم لتجارة الأدوية\nفاتورة 1826060925\nصافي الفاتورة 3,571.000\n1 / 1'
        sig = _parse_page_signals(text)
        self.assertEqual(sig['page_index'], 1)
        self.assertEqual(sig['page_count'], 1)
        self.assertEqual(sig['doc_number'], '1826060925')
        self.assertTrue(sig['has_totals'])
        self.assertEqual(sig['doc_type'], 'فاتورة')

    def test_pharmaoverseas_english_counter_and_doctype(self):
        text = 'Page 1 of 1\nاذن استلام مسعر\n8822632985\nالإجمالي 2,286.300'
        sig = _parse_page_signals(text)
        self.assertEqual((sig['page_index'], sig['page_count']), (1, 1))
        self.assertEqual(sig['doc_type'], 'اذن استلام مسعر')
        self.assertEqual(sig['doc_number'], '8822632985')
        self.assertTrue(sig['has_totals'])

    def test_date_not_mistaken_for_page_counter(self):
        sig = _parse_page_signals('تاريخ 13/10/2026\nفاتورة 1826060870')
        self.assertIsNone(sig['page_index'])
        self.assertEqual(sig['doc_number'], '1826060870')

    def test_expiry_not_mistaken_for_counter(self):
        sig = _parse_page_signals('صلاحية 12/2028')
        self.assertIsNone(sig['page_index'])

    def test_multipage_counter(self):
        sig = _parse_page_signals('فاتورة 5001\n2 / 3')
        self.assertEqual((sig['page_index'], sig['page_count']), (2, 3))

    def test_no_signal(self):
        sig = _parse_page_signals('مجرد نص بدون أرقام مستند')
        self.assertFalse(sig['has_header'])
        self.assertIsNone(sig['page_index'])
        self.assertEqual(sig['doc_number'], '')

    def test_customer_code_never_used_as_doc_number(self):
        # كود العميل 00010059 is CONSTANT on every page → must not be the doc number
        # (else all those pages merge into one invoice). Prefer the فاتورة number.
        sig = _parse_page_signals('رامكو فاتورة 1826060925 كود 00010059 9118260609251')
        self.assertEqual(sig['doc_number'], '1826060925')

    def test_falls_back_to_barcode_not_customer_code(self):
        # no فاتورة label read → take the unique barcode, never the customer code
        sig = _parse_page_signals('شركة الرزيقي كود العميل 00010059 9118260609251')
        self.assertEqual(sig['doc_number'], '9118260609251')


class EdgeCaseTests(SimpleTestCase):

    def test_empty_bundle(self):
        self.assertEqual(sp.group_pages([]), [])

    def test_single_page(self):
        self.assertEqual(sp.group_pages([_p(0, doc_number='X1')]), [[0]])

    def test_low_confidence_flagged_when_no_anchor(self):
        probes = [_p(0, doc_number=None, page_index=None, page_count=None)]
        s = sp.summarize(probes, sp.group_pages(probes))
        self.assertEqual(s[0]['confidence'], 'low')

    def test_doc_number_punctuation_ignored_in_comparison(self):
        # "1826-060925" and "1826060925" are the same invoice
        probes = [
            _p(0, doc_number='1826-060925', page_index=1, page_count=2, has_totals=False),
            _p(1, doc_number='1826060925', page_index=2, page_count=2),
        ]
        self.assertEqual(sp.group_pages(probes), [[0, 1]])
