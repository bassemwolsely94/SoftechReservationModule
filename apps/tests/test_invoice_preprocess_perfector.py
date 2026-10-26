"""
Tests for the image/PDF perfector (apps.invoices.preprocess) and the self-hosted
VLM engine registration (apps.invoices.ocr / engines).
"""
from django.test import SimpleTestCase, override_settings

from apps.invoices import preprocess as pp


def _img(w=120, h=60, color=200):
    from PIL import Image
    return Image.new('L', (w, h), color)


class PerfectorTests(SimpleTestCase):

    def test_unsharp_returns_same_size_image(self):
        im = _img()
        out = pp.unsharp(im)
        self.assertEqual(out.size, im.size)

    def test_sauvola_returns_binary_image(self):
        from PIL import Image, ImageDraw
        im = Image.new('L', (80, 40), 210)        # faint background
        d = ImageDraw.Draw(im)
        d.text((5, 12), 'ABC', fill=90)           # darker 'ink'
        out = pp.binarize_sauvola(im)
        self.assertEqual(out.size, im.size)
        vals = set(out.convert('L').getdata())
        self.assertTrue(vals.issubset({0, 255}))  # strictly 0/255

    def test_sauvola_degrades_safely_on_tiny_image(self):
        out = pp.binarize_sauvola(_img(4, 4))
        self.assertIsNotNone(out)

    @override_settings(INVOICE_OCR_ENHANCE=True, INVOICE_OCR_EQUALIZE=False,
                       INVOICE_OCR_SHARPEN=False, INVOICE_OCR_BINARIZE=False)
    def test_enhance_base_only_is_grayscale(self):
        out = pp.enhance_for_ocr(_img())
        self.assertEqual(out.mode, 'L')

    @override_settings(INVOICE_OCR_BINARIZE=True)
    def test_enhance_binarize_flag_produces_binary(self):
        from PIL import Image, ImageDraw
        im = Image.new('L', (200, 80), 205)
        ImageDraw.Draw(im).text((8, 30), 'TEST 123', fill=70)
        out = pp.enhance_for_ocr(im, enable_deskew=False)
        vals = set(out.convert('L').getdata())
        self.assertTrue(vals.issubset({0, 255}))

    @override_settings(INVOICE_OCR_SHARPEN=True, INVOICE_OCR_BINARIZE=False,
                       INVOICE_OCR_EQUALIZE=False)
    def test_enhance_sharpen_flag_keeps_grayscale(self):
        out = pp.enhance_for_ocr(_img(1600, 400), enable_deskew=False)
        self.assertEqual(out.mode, 'L')


class VlmEngineTests(SimpleTestCase):

    def test_vlm_unavailable_without_url(self):
        from apps.invoices import ocr
        with override_settings(VLM_OCR_URL=''):
            self.assertFalse(ocr._vlm_available())
            self.assertIsNone(ocr._vlm_images(['p1.png']))

    @override_settings(VLM_OCR_URL='http://10.0.0.5:8000/v1/chat/completions',
                       VLM_OCR_MODEL='PaddleOCR-VL')
    def test_vlm_available_and_registered(self):
        from apps.invoices import ocr, engines
        self.assertTrue(ocr._vlm_available())
        spec = engines.get_engine('vlm')
        self.assertIsNotNone(spec)
        self.assertEqual(spec.kind, 'api')
        self.assertTrue(spec.available())

    @override_settings(VLM_OCR_URL='http://<gpu-box>:8000/v1/chat/completions')
    def test_vlm_placeholder_url_is_not_available(self):
        # the example placeholder must NOT count as available (else every call
        # DNS-fails and silently zeroes out a run)
        from apps.invoices import ocr
        self.assertFalse(ocr._vlm_available())

    @override_settings(VLM_OCR_URL='not-a-url')
    def test_vlm_malformed_url_is_not_available(self):
        from apps.invoices import ocr
        self.assertFalse(ocr._vlm_available())

    def test_pdf_default_dpi_from_settings(self):
        from apps.invoices import pdf
        with override_settings(INVOICE_PDF_DPI=300):
            self.assertEqual(pdf._default_dpi(), 300)
        with override_settings(INVOICE_PDF_DPI=150):
            self.assertEqual(pdf._default_dpi(), 150)


class JunkLineFilterTests(SimpleTestCase):
    """parse_structured drops over-extracted non-product rows (125-vs-81 fix)."""

    def _names(self, data):
        from apps.invoices import ocr
        _, lines = ocr.parse_structured(data)
        return [ln['manual_name'] for ln in lines]

    def test_numeric_only_name_dropped(self):
        names = self._names({'lines': [
            {'item_name': '3,571.000', 'public_price': 0},
            {'item_name': 'ايفيروسبان 100', 'public_price': 55, 'vendor_item_code': '643352'},
        ]})
        self.assertEqual(names, ['ايفيروسبان 100'])

    def test_totals_phrase_without_code_or_price_dropped(self):
        names = self._names({'lines': [
            {'item_name': 'إجمالي الفاتورة', 'public_price': 0, 'vendor_item_code': ''},
            {'item_name': 'عدد الأصناف', 'public_price': 0},
            {'item_name': 'باندول اكسترا', 'public_price': 30, 'vendor_item_code': '6594'},
        ]})
        self.assertEqual(names, ['باندول اكسترا'])

    def test_real_line_with_price_is_kept_even_if_name_has_keyword(self):
        # a priced product row must survive even if its name contains a stop-word
        names = self._names({'lines': [
            {'item_name': 'صافي بلاس 500', 'public_price': 42, 'vendor_item_code': '7001'},
        ]})
        self.assertEqual(names, ['صافي بلاس 500'])

    def test_line_with_code_but_no_price_is_kept(self):
        names = self._names({'lines': [
            {'item_name': 'دواء بكود بدون سعر', 'public_price': 0, 'vendor_item_code': '8899'},
        ]})
        self.assertEqual(len(names), 1)
