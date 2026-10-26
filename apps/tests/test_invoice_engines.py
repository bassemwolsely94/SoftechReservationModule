"""
Tests for the pluggable OCR engine layer (apps/invoices/engines.py) — the free
easyocr structured extractor's pure logic + engine resolution.
"""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, override_settings

from apps.invoices import engines as eng


class ResolveEngineTests(SimpleTestCase):

    def test_explicit_wins(self):
        self.assertEqual(eng.resolve_engine('easyocr'), 'easyocr')
        self.assertEqual(eng.resolve_engine('gemini'), 'gemini')

    @override_settings(INVOICE_OCR_ENGINE='easyocr')
    def test_setting_used(self):
        self.assertEqual(eng.resolve_engine(), 'easyocr')

    @override_settings(INVOICE_OCR_ENGINE='auto')
    def test_auto_prefers_gemini_when_key(self):
        # auto prefers an available API engine; gemini's availability = keys present
        with mock.patch('apps.invoices.ocr._gemini_keys', return_value=['k']):
            self.assertEqual(eng.resolve_engine(), 'gemini')

    @override_settings(INVOICE_OCR_ENGINE='auto')
    def test_auto_prefers_tesseract_free_without_key(self):
        with mock.patch('apps.invoices.ocr._gemini_keys', return_value=[]), \
             mock.patch('apps.invoices.ocr._mistral_available', return_value=False), \
             mock.patch('apps.invoices.ocr._vlm_available', return_value=False), \
             mock.patch('apps.invoices.engines._tesseract_available', return_value=True):
            self.assertEqual(eng.resolve_engine(), 'tesseract')

    @override_settings(INVOICE_OCR_ENGINE='auto')
    def test_auto_falls_to_easyocr_without_key_or_tesseract(self):
        with mock.patch('apps.invoices.ocr._gemini_keys', return_value=[]), \
             mock.patch('apps.invoices.ocr._mistral_available', return_value=False), \
             mock.patch('apps.invoices.ocr._vlm_available', return_value=False), \
             mock.patch('apps.invoices.engines._tesseract_available', return_value=False), \
             mock.patch('apps.invoices.engines._paddleocr_available', return_value=False), \
             mock.patch('apps.invoices.engines._easyocr_available', return_value=True):
            self.assertEqual(eng.resolve_engine(), 'easyocr')


class NumbersOkTests(SimpleTestCase):
    """The numeric-consistency escalation signal: a free result with present-but-
    garbled numbers must fail so `auto` escalates to a semantic engine."""

    def test_consistent_line_passes(self):
        data = {'lines': [{'item_name': 'دواء', 'public_price': 100, 'discount_pct': 20,
                           'pharmacist_price': 80, 'quantity': 5, 'line_total': 400}]}
        self.assertTrue(eng.numbers_ok(data))

    def test_garbled_numbers_fail(self):
        # net 1.82 vs public×disc (≈80) and total÷qty (≈80) → inconsistent
        data = {'lines': [
            {'item_name': 'a', 'public_price': 100, 'discount_pct': 20, 'pharmacist_price': 1.82,
             'quantity': 5, 'line_total': 400},
            {'item_name': 'b', 'public_price': 50, 'discount_pct': 10, 'pharmacist_price': 3.0,
             'quantity': 2, 'line_total': 90},
        ]}
        self.assertFalse(eng.numbers_ok(data))

    def test_no_checkable_lines_is_ok(self):
        # only names/quantities, no price cross-check available → don't over-escalate
        data = {'lines': [{'item_name': 'دواء', 'quantity': 3}]}
        self.assertTrue(eng.numbers_ok(data))

    def test_mixed_half_consistent_passes_at_threshold(self):
        data = {'lines': [
            {'item_name': 'a', 'public_price': 100, 'discount_pct': 20, 'pharmacist_price': 80,
             'quantity': 1, 'line_total': 80},                      # consistent
            {'item_name': 'b', 'public_price': 100, 'discount_pct': 20, 'pharmacist_price': 9,
             'quantity': 1, 'line_total': 80},                      # inconsistent
        ]}
        self.assertTrue(eng.numbers_ok(data, min_frac=0.5))
        self.assertFalse(eng.numbers_ok(data, min_frac=0.75))


class HelperTests(SimpleTestCase):

    def test_arabic_ratio(self):
        self.assertGreater(eng._arabic_ratio('بنادول'), 0.9)
        self.assertEqual(eng._arabic_ratio('PANADOL'), 0.0)
        self.assertEqual(eng._arabic_ratio('123'), 0.0)

    def test_is_number(self):
        self.assertTrue(eng._is_number('237.00'))
        self.assertTrue(eng._is_number('1,938.750'))
        self.assertFalse(eng._is_number('بنادول'))
        self.assertFalse(eng._is_number(''))

    def test_as_int_qty(self):
        self.assertEqual(eng._as_int_qty('11'), 11.0)
        self.assertIsNone(eng._as_int_qty('237.00'))   # price, not qty
        self.assertIsNone(eng._as_int_qty('99999'))     # too big


class RowClassifyTests(SimpleTestCase):

    def test_item_row_detected(self):
        self.assertTrue(eng._row_is_item(['ميكسا 10 مجم 30 قرص', '11', '237.00']))

    def test_totals_row_rejected(self):
        self.assertFalse(eng._row_is_item(['صافي الفاتورة', '3571.000']))
        self.assertFalse(eng._row_is_item(['اجمالي كمية', '20.00']))

    def test_header_row_rejected(self):
        self.assertFalse(eng._row_is_item(['اسم الصنف', 'الكمية', 'سعر الجمهور']))

    def test_pure_number_row_rejected(self):
        self.assertFalse(eng._row_is_item(['3.00', '3.00', '0.000']))


class NoTemplateLineTests(SimpleTestCase):

    def test_name_and_qty_filled_prices_zero(self):
        ln = eng._line_from_cells_no_template(['ميكسا 10 مجم 30 قرص', '11', '237.00'])
        self.assertEqual(ln['item_name'], 'ميكسا 10 مجم 30 قرص')
        self.assertEqual(ln['quantity'], 11.0)
        self.assertEqual(ln['public_price'], 0)         # never invented
        self.assertLess(ln['confidence'], 0.5)          # flagged for review

    def test_no_arabic_name_returns_none(self):
        self.assertIsNone(eng._line_from_cells_no_template(['123', '45', '6']))


class TemplateLineTests(SimpleTestCase):

    def test_template_maps_columns(self):
        # visual left→right template (RTL doc): total, price, qty, name
        cols = ['ignore', 'public_price', 'quantity', 'item_name']
        ln = eng._line_from_cells_template(['1938.750', '237.00', '11', 'ميكسا 30 قرص'], cols)
        self.assertEqual(ln['item_name'], 'ميكسا 30 قرص')
        self.assertEqual(ln['quantity'], '11')
        self.assertEqual(ln['public_price'], '237.00')


class EasyocrStructuredTests(SimpleTestCase):

    def test_structured_from_mocked_boxes(self):
        # mock the easyocr reader → two product rows + one totals row
        fake = [
            ([[500, 90], [900, 90], [900, 120], [500, 120]], 'ميكسا 30 قرص', 0.9),
            ([[100, 90], [160, 90], [160, 120], [100, 120]], '11', 0.9),
            ([[500, 160], [900, 160], [900, 190], [500, 190]], 'كوباد 30 كبسولة', 0.9),
            ([[100, 160], [160, 160], [160, 190], [100, 190]], '2', 0.9),
            ([[300, 240], [700, 240], [700, 270], [300, 270]], 'صافي الفاتورة', 0.9),
        ]
        reader = SimpleNamespace(readtext=lambda *a, **k: fake)
        img = SimpleNamespace(convert=lambda m: SimpleNamespace())
        with mock.patch('apps.invoices.ocr._get_easyocr_reader', return_value=reader), \
             mock.patch('numpy.array', return_value='arr'):
            out = eng.easyocr_structured_image(img)
        self.assertIsNotNone(out)
        self.assertEqual(out['_engine'], 'easyOCR')
        names = [l['item_name'] for l in out['lines']]
        self.assertIn('ميكسا 30 قرص', names)
        self.assertNotIn('صافي الفاتورة', names)     # totals row excluded


class TesseractBoxTests(SimpleTestCase):

    def test_boxes_from_tesseract_dict(self):
        data = {
            'text':   ['ميكسا', '11', '', 'صافي'],
            'conf':   ['90', '88', '-1', '80'],
            'left':   [500, 100, 0, 300], 'top': [90, 90, 0, 240],
            'width':  [120, 30, 0, 100],  'height': [28, 24, 0, 26],
            'block_num': [1, 1, 0, 2], 'par_num': [1, 1, 0, 1], 'line_num': [1, 1, 0, 1],
        }
        boxes = eng._boxes_from_tesseract(data)
        self.assertEqual(len(boxes), 3)                     # the empty/conf=-1 block is dropped
        texts = [b['text'] for b in boxes]
        self.assertIn('ميكسا', texts)
        self.assertNotIn('', texts)
        self.assertTrue(all('row_key' in b for b in boxes))

    def test_norm_ar_variants_rejected_as_totals(self):
        # صافى (ya variant) / إجمالى must still be caught as non-item rows
        self.assertFalse(eng._row_is_item(['صافى الفاتورة', '3571']))
        self.assertFalse(eng._row_is_item(['إجمالى كمية', '20']))

    def test_footer_misreads_rejected(self):
        # الدفع→الدقع, تعديل→تعجيل OCR variants must be filtered
        self.assertFalse(eng._row_is_item(['تعجيل الدقع', '53.05']))
        self.assertFalse(eng._row_is_item(['العروض والخصومات وفرت', '0']))


class QtySanityTests(SimpleTestCase):
    """Quantity cross-check: الكمية ≈ الإجمالي ÷ سعر الصيدلي catches gross misreads."""

    def test_corrects_gross_misread(self):
        ln = {'quantity': '50', 'pharmacist_price': '10', 'line_total': '20'}  # exp 2
        eng._qty_sanity(ln)
        self.assertEqual(ln['quantity'], '2')
        self.assertIn('مُصحّحة', ln['notes'])

    def test_fills_missing_qty(self):
        ln = {'quantity': '', 'pharmacist_price': '15.75', 'line_total': '31.50'}  # exp 2
        eng._qty_sanity(ln)
        self.assertEqual(ln['quantity'], '2')

    def test_keeps_consistent_qty(self):
        ln = {'quantity': '11', 'pharmacist_price': '176.25', 'line_total': '1938.75'}
        eng._qty_sanity(ln)
        self.assertEqual(ln['quantity'], '11')          # consistent → untouched
        self.assertNotIn('مُصحّحة', ln.get('notes', ''))

    def test_noop_when_total_missing(self):
        ln = {'quantity': '5', 'pharmacist_price': '10'}
        eng._qty_sanity(ln)
        self.assertEqual(ln['quantity'], '5')

    def test_noop_when_ratio_not_near_integer(self):
        ln = {'quantity': '99', 'pharmacist_price': '10', 'line_total': '25'}  # 2.5 → unsure
        eng._qty_sanity(ln)
        self.assertEqual(ln['quantity'], '99')          # not confident → leave for review


def _b(cx, cy, text, rk):
    return {'cx': cx, 'cy': cy, 'w': 60, 'h': 20, 'text': text, 'conf': 0.9, 'row_key': rk}


class ScoreAndEscalationTests(SimpleTestCase):

    def test_score_extraction(self):
        good = {'lines': [
            {'item_name': 'بنادول', 'public_price': '25'},
            {'item_name': 'اوجمنتين', 'pharmacist_price': '40'}]}
        self.assertEqual(eng.score_extraction(good), 1.0)
        half = {'lines': [
            {'item_name': 'بنادول', 'public_price': '25'},
            {'item_name': 'لا سعر', 'public_price': ''}]}
        self.assertEqual(eng.score_extraction(half), 0.5)
        self.assertEqual(eng.score_extraction({'lines': []}), 0.0)
        self.assertEqual(eng.score_extraction(None), 0.0)

    def test_order_number_not_counted_as_price(self):
        # a line whose only "price" is an order/barcode number must not score
        d = {'lines': [{'item_name': 'صنف', 'public_price': '1018388184'}]}
        self.assertEqual(eng.score_extraction(d), 0.0)

    def test_auto_keeps_free_when_strong(self):
        from apps.invoices import ocr
        strong = {'lines': [{'item_name': 'بنادول', 'public_price': '25'}]}
        with mock.patch('apps.invoices.ocr._gemini_key', return_value='k'), \
             mock.patch('apps.invoices.engines.best_free_engine', return_value='tesseract'), \
             mock.patch('apps.invoices.engines.free_structured_images', return_value=strong), \
             mock.patch('apps.invoices.ocr._gemini_images') as gem:
            out = ocr.extract_structured_images(['p.png'], engine='auto')
        self.assertEqual(out, strong)
        gem.assert_not_called()                      # free was good → no Gemini spend

    def test_recall_ok(self):
        self.assertTrue(eng.recall_ok({'lines': [1, 2, 3], '_declared_count': 4}))   # 3/4≥0.7
        self.assertFalse(eng.recall_ok({'lines': [1, 2], '_declared_count': 10}))    # 2/10<0.7
        self.assertTrue(eng.recall_ok({'lines': [1]}))                                # no count → ok

    def test_auto_escalates_on_low_recall_even_if_precise(self):
        from apps.invoices import ocr
        # every emitted line is clean (score 1.0) but only 2 of 10 products captured
        weak = {'lines': [{'item_name': 'بنادول', 'public_price': '25'},
                          {'item_name': 'اوجمنتين', 'public_price': '40'}],
                '_declared_count': 10}
        gemo = {'lines': [{'item_name': 'x', 'public_price': '1'}], '_engine': 'gemini'}
        with mock.patch('apps.invoices.ocr._gemini_key', return_value='k'), \
             mock.patch('apps.invoices.engines.best_free_engine', return_value='tesseract'), \
             mock.patch('apps.invoices.engines.free_structured_images', return_value=weak), \
             mock.patch('apps.invoices.ocr._gemini_images', return_value=gemo) as gem:
            out = ocr.extract_structured_images(['p.png'], engine='auto')
        self.assertEqual(out, gemo)
        gem.assert_called_once()

    def test_confidence_ok(self):
        self.assertTrue(eng.confidence_ok({'_avg_confidence': 0.8}))
        self.assertFalse(eng.confidence_ok({'_avg_confidence': 0.3}))   # handwriting/blurry
        self.assertTrue(eng.confidence_ok({}))                          # no signal → ok

    def test_auto_escalates_on_handwriting_low_confidence(self):
        from apps.invoices import ocr
        # lines look clean (score 1.0, recall ok) but mean char confidence is low
        weak = {'lines': [{'item_name': 'بنادول', 'public_price': '25'}],
                '_avg_confidence': 0.30}
        gemo = {'lines': [{'item_name': 'x', 'public_price': '1'}], '_engine': 'gemini'}
        with mock.patch('apps.invoices.ocr._gemini_key', return_value='k'), \
             mock.patch('apps.invoices.engines.best_free_engine', return_value='tesseract'), \
             mock.patch('apps.invoices.engines.free_structured_images', return_value=weak), \
             mock.patch('apps.invoices.ocr._gemini_images', return_value=gemo) as gem:
            out = ocr.extract_structured_images(['p.png'], engine='auto')
        self.assertEqual(out, gemo)
        gem.assert_called_once()

    def test_auto_escalates_when_free_weak(self):
        from apps.invoices import ocr
        weak = {'lines': [{'item_name': 'صنف', 'public_price': ''}]}
        gemo = {'lines': [{'item_name': 'بنادول', 'public_price': '25'}], '_engine': 'gemini'}
        with mock.patch('apps.invoices.ocr._gemini_key', return_value='k'), \
             mock.patch('apps.invoices.engines.best_free_engine', return_value='tesseract'), \
             mock.patch('apps.invoices.engines.free_structured_images', return_value=weak), \
             mock.patch('apps.invoices.ocr._gemini_images', return_value=gemo) as gem:
            out = ocr.extract_structured_images(['p.png'], engine='auto')
        self.assertEqual(out, gemo)
        gem.assert_called_once()


class HeaderDrivenTemplateTests(SimpleTestCase):
    """The per-distributor template system: self-calibrating header mapping +
    explicit column-band override. Deterministic synthetic boxes (no OCR)."""

    def _invoice_boxes(self):
        # RTL-ish layout: item name (right, high cx), qty (mid), public price (left)
        return [
            _b(500, 100, 'اسم الصنف', (1, 1, 1)), _b(300, 100, 'الكمية', (1, 1, 1)),
            _b(100, 100, 'سعر الجمهور', (1, 1, 1)),
            _b(500, 160, 'بنادول', (1, 1, 2)), _b(300, 160, '10', (1, 1, 2)),
            _b(100, 160, '25', (1, 1, 2)),
            _b(500, 220, 'اوجمنتين', (1, 1, 3)), _b(300, 220, '3', (1, 1, 3)),
            _b(100, 220, '40', (1, 1, 3)),
            _b(300, 300, 'اجمالي الفاتورة', (1, 1, 4)), _b(100, 300, '65', (1, 1, 4)),
        ]

    def test_header_columns_detected(self):
        rows = eng._group_text_rows(self._invoice_boxes())
        cols, idx = eng._detect_header_columns(rows)
        self.assertIsNotNone(cols)
        self.assertEqual(idx, 0)
        fields = {f for _, f in cols}
        self.assertEqual(fields, {'item_name', 'quantity', 'public_price'})

    def test_header_driven_maps_fields_and_skips_totals(self):
        out = eng._structured_header_driven(self._invoice_boxes(), engine='T')
        self.assertIsNotNone(out)
        self.assertEqual(out['_engine'], 'T/headers')
        lines = out['lines']
        self.assertEqual(len(lines), 2)                       # totals row excluded
        self.assertEqual(lines[0]['item_name'], 'بنادول')
        self.assertEqual(lines[0]['quantity'], '10')
        self.assertEqual(lines[0]['public_price'], '25')

    def test_band_template_maps_prices_and_filters_noise(self):
        # single-line vendor template (fractions of page width = 1000)
        from types import SimpleNamespace
        vendor = SimpleNamespace(name='V', ocr_profile={'column_bands': [
            {'field': 'public_price', 'x0': 0.10, 'x1': 0.25},
            {'field': 'quantity',     'x0': 0.45, 'x1': 0.60},
            {'field': 'item_name',    'x0': 0.75, 'x1': 0.95},
        ]})
        boxes = [
            _b(850, 100, 'بنادول', (1, 1, 1)), _b(500, 100, '10', (1, 1, 1)),
            _b(150, 100, '25', (1, 1, 1)),
            _b(850, 160, 'اوجمنتين', (1, 1, 2)), _b(150, 160, '40', (1, 1, 2)),
            # a customer/header row: name-band text but its "number" is an order no.
            _b(850, 40, 'الرزيقى', (1, 1, 0)), _b(150, 40, '1018388184', (1, 1, 0)),
        ]
        for b in boxes:
            b['h'] = 20
        out = eng._structured_from_boxes(boxes, vendor=vendor, engine='T', page_w=1000)
        self.assertIsNotNone(out)
        self.assertEqual(out['_engine'], 'T/template')
        names = [l['item_name'] for l in out['lines']]
        self.assertIn('بنادول', names)
        self.assertIn('اوجمنتين', names)
        self.assertNotIn('الرزيقى', names)            # order-number row filtered
        panadol = next(l for l in out['lines'] if l['item_name'] == 'بنادول')
        self.assertEqual(panadol['public_price'], '25')
        self.assertEqual(panadol['quantity'], '10')

    def test_field_voting_prefers_rapid_number(self):
        # price band has a garbled Tesseract '82' AND a RapidOCR '42.10' → rapid wins
        from types import SimpleNamespace
        vendor = SimpleNamespace(name='V', ocr_profile={'column_bands': [
            {'field': 'public_price', 'x0': 0.10, 'x1': 0.30},
            {'field': 'item_name', 'x0': 0.70, 'x1': 0.95}]})
        boxes = [
            {'cx': 850, 'cy': 100, 'w': 60, 'h': 20, 'text': 'بنادول', 'conf': 0.9, 'src': 't'},
            {'cx': 200, 'cy': 100, 'w': 40, 'h': 20, 'text': '82', 'conf': 0.5, 'src': 't'},
            {'cx': 205, 'cy': 100, 'w': 40, 'h': 20, 'text': '42.10', 'conf': 0.9, 'src': 'rapid'},
        ]
        out = eng._structured_from_boxes(boxes, vendor=vendor, engine='T', page_w=1000)
        self.assertEqual(out['lines'][0]['public_price'], '42.10')

    def test_column_bands_override(self):
        # headers deliberately garbled → rely on explicit per-vendor bands
        boxes = [
            _b(500, 160, 'بنادول', (1, 1, 2)), _b(300, 160, '10', (1, 1, 2)),
            _b(100, 160, '25', (1, 1, 2)),
        ]
        from types import SimpleNamespace
        vendor = SimpleNamespace(name='V', ocr_profile={'column_bands': [
            {'field': 'public_price', 'x0': 0.0, 'x1': 0.2},
            {'field': 'quantity',     'x0': 0.4, 'x1': 0.6},
            {'field': 'item_name',    'x0': 0.8, 'x1': 1.0},
        ]})
        out = eng._structured_header_driven(boxes, vendor=vendor, engine='T')
        self.assertIsNotNone(out)
        self.assertEqual(out['lines'][0]['item_name'], 'بنادول')
        self.assertEqual(out['lines'][0]['public_price'], '25')
