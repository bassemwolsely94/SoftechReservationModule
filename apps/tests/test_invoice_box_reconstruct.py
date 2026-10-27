"""
Regression tests for box→invoice reconstruction (apps/invoices/engines.py).

These lock in the fix for the PaddleOCR "0 matched" bug, whose two root causes were:
  1. the PharmaOverseas column template was not selected for a vendor named in
     English ("PHARMA OVER SEAS") because its keywords were run-together Arabic/
     English only; reconstruction then fell through to the generic path, and
  2. `_structured_by_bands` dropped every product row whose price cell the engine
     failed to read — fatal for PaddleOCR, which reads names well but misses ~half
     the numbers. A product is now proven by a dosage-form word in the name too.

Both fixes raise recall for EVERY box engine (Tesseract/easyOCR/PaddleOCR) and must
not admit header/customer/footer rows, so the drug-form gate is tested for precision.
"""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from apps.invoices import engines as eng


class DrugFormGateTests(SimpleTestCase):
    """`_has_drug_form`: distinctive form word OR digit-anchored dose unit, and
    nothing that a header/company/customer label would contain."""

    def test_distinctive_form_words(self):
        for s in ('ماكروفيوران كبسولة', 'باراسيتامول اقراص', 'فنتولين بخاخ',
                  'فولتارين لبوس', 'أوجمنتين شراب', 'فيوسيدين كريم'):
            self.assertTrue(eng._has_drug_form(s), s)

    def test_digit_anchored_dose_units(self):
        for s in ('ابيكسيدو 4 مجم', 'جليمباك ٥ مجم', 'محلول 10 مل', 'اتورستات 20مج'):
            self.assertTrue(eng._has_drug_form(s), s)

    def test_rejects_header_and_company_labels(self):
        # bare 'مل' is a substring of these — must NOT register as a drug.
        for s in ('شركة الامل الكبرى', 'عامل كامل شامل', 'اسم الحساب', 'المندوب',
                  'العنوان', 'نوع الأمر', 'دورة التوزيع', 'ل اصا', 'فاءي'):
            self.assertFalse(eng._has_drug_form(s), s)


class TemplateSelectionTests(SimpleTestCase):
    """The PharmaOverseas template must be picked for the real vendor name, which is
    stored in English with spaces ('PHARMA OVER SEAS')."""

    def _vendor(self, name):
        return SimpleNamespace(name=name, ocr_profile={})

    def test_pharmaoverseas_matched_by_english_name(self):
        bands, _ = eng._match_template([{'text': 'x', 'cx': 1, 'cy': 1}],
                                       self._vendor('PHARMA OVER SEAS'))
        self.assertTrue(bands)
        self.assertEqual(bands[-1]['field'], 'item_name')  # rightmost band in RTL

    def test_pharmaoverseas_matched_by_arabic_blob(self):
        boxes = [{'text': 'فارما اوفرسيز', 'cx': 1, 'cy': 1}]
        bands, _ = eng._match_template(boxes, None)
        self.assertTrue(bands)

    def test_unrelated_vendor_no_template(self):
        bands, _ = eng._match_template([{'text': 'شركة عامة', 'cx': 1, 'cy': 1}],
                                       self._vendor('SOME OTHER CO'))
        self.assertFalse(bands)

    def test_paddle_engine_uses_paddle_bands_when_present(self):
        # a template's bands_paddle variant is used ONLY for the paddle engine, so
        # paddle calibration never regresses Tesseract/easyOCR (which keep `bands`).
        tpl = {'keywords': ('acme',), 'multiline': False,
               'bands': [{'field': 'item_name', 'x0': 0.70, 'x1': 0.92}],
               'bands_paddle': [{'field': 'item_name', 'x0': 0.60, 'x1': 0.98}]}
        boxes = [{'text': 'acme co', 'cx': 1, 'cy': 1}]
        with mock.patch.dict(eng._BUILTIN_TEMPLATES, {'acme': tpl}, clear=True):
            default_bands, _ = eng._match_template(boxes, None, 'tesseract')
            paddle_bands, _ = eng._match_template(boxes, None, 'PaddleOCR/sidecar')
        self.assertEqual(default_bands[0]['x0'], 0.70)   # Tesseract keeps default
        self.assertEqual(paddle_bands[0]['x0'], 0.60)    # paddle gets the variant

    def test_vendor_profile_paddle_bands_override(self):
        v = SimpleNamespace(name='X', ocr_profile={
            'column_bands':        [{'field': 'item_name', 'x0': 0.70, 'x1': 0.92}],
            'column_bands_paddle': [{'field': 'item_name', 'x0': 0.55, 'x1': 0.97}]})
        d, _ = eng._match_template([{'text': 'x', 'cx': 1, 'cy': 1}], v, 'tesseract')
        p, _ = eng._match_template([{'text': 'x', 'cx': 1, 'cy': 1}], v, 'paddleocr')
        self.assertEqual(d[0]['x0'], 0.70)
        self.assertEqual(p[0]['x0'], 0.55)


class BandRowSurvivalTests(SimpleTestCase):
    """`_structured_by_bands`: a product row survives on a strong name even with no
    price (the engine missed the number); a non-product label row is still dropped."""

    def _vendor(self):
        return SimpleNamespace(name='PHARMA OVER SEAS', ocr_profile={})

    def _run(self, boxes):
        bands, multiline = eng._match_template(boxes, self._vendor())
        self.assertTrue(bands, 'template should match for this vendor')
        return eng._structured_by_bands(boxes, bands, multiline, self._vendor(),
                                        'TEST', page_w=1440)

    def test_name_only_product_row_survives(self):
        # item_name band is x 0.70–0.92 → cx 1008–1325 at page_w 1440. No price cell.
        boxes = [{'cx': 1200, 'cy': 300, 'w': 300, 'h': 40,
                  'text': 'ماكروفيوران كبسولة', 'conf': 0.9}]
        res = self._run(boxes)
        self.assertIsNotNone(res)
        names = [l['item_name'] for l in res['lines']]
        self.assertIn('ماكروفيوران كبسولة', names)

    def test_priced_row_without_form_word_still_survives(self):
        # old behaviour preserved: a name + a plausible price is a product even with
        # no form word (e.g. a cosmetic). pharmacist_price band 0.305–0.345 → cx≈439–497.
        boxes = [
            {'cx': 1200, 'cy': 300, 'w': 300, 'h': 40, 'text': 'سنتروم العائله', 'conf': 0.9},
            {'cx': 460, 'cy': 300, 'w': 60, 'h': 35, 'text': '58.6', 'conf': 0.9},
        ]
        res = self._run(boxes)
        self.assertIsNotNone(res)
        self.assertIn('سنتروم العائله', [l['item_name'] for l in res['lines']])

    def test_label_row_without_form_or_price_is_dropped(self):
        boxes = [{'cx': 1200, 'cy': 300, 'w': 300, 'h': 40,
                  'text': 'شركة الامل الكبرى', 'conf': 0.9}]
        res = self._run(boxes)
        names = [l['item_name'] for l in (res['lines'] if res else [])]
        self.assertNotIn('شركة الامل الكبرى', names)

    def test_name_only_row_flagged_for_price_review(self):
        boxes = [{'cx': 1200, 'cy': 300, 'w': 300, 'h': 40,
                  'text': 'فلازاكور قرص', 'conf': 0.9}]
        res = self._run(boxes)
        self.assertIsNotNone(res)
        ln = next(l for l in res['lines'] if l['item_name'] == 'فلازاكور قرص')
        self.assertLess(ln['confidence'], 0.65)      # lower confidence than a priced row
        self.assertIn('أدخلها يدويًا', ln['notes'])  # explicit "enter prices manually"
