"""
Tests for document-robustness preprocessing (apps/invoices/preprocess.py):
blank-page detection and the review quality flags. Pure/PIL — no OCR engine.
"""
from unittest import mock

from django.test import SimpleTestCase
from PIL import Image, ImageDraw

from apps.invoices import preprocess as pp


class OrientationTests(SimpleTestCase):

    def test_rotates_when_osd_detects_sideways(self):
        img = Image.new('RGB', (800, 1100), 'white')          # portrait
        with mock.patch('apps.invoices.preprocess.detect_rotation', return_value=90):
            out, deg = pp.correct_orientation(img)
        self.assertEqual(deg, 90)
        self.assertEqual(out.size, (1100, 800))               # corrected → landscape dims

    def test_noop_when_upright(self):
        img = Image.new('RGB', (800, 1100), 'white')
        with mock.patch('apps.invoices.preprocess.detect_rotation', return_value=0):
            out, deg = pp.correct_orientation(img)
        self.assertEqual(deg, 0)
        self.assertEqual(out.size, (800, 1100))

    def test_ignores_bogus_angle(self):
        img = Image.new('RGB', (800, 1100), 'white')
        with mock.patch('apps.invoices.preprocess.detect_rotation', return_value=45):
            out, deg = pp.correct_orientation(img)
        self.assertEqual(deg, 0)                               # only 90/180/270 applied


class BlankPageTests(SimpleTestCase):

    def test_white_page_is_blank(self):
        img = Image.new('RGB', (800, 1100), 'white')
        self.assertTrue(pp.is_blank_page(img))

    def test_page_with_content_not_blank(self):
        img = Image.new('RGB', (800, 1100), 'white')
        d = ImageDraw.Draw(img)
        for y in range(50, 1050, 20):                 # lots of dark text lines
            d.rectangle([40, y, 760, y + 8], fill='black')
        self.assertFalse(pp.is_blank_page(img))

    def test_near_blank_with_speck_still_blank(self):
        img = Image.new('RGB', (800, 1100), 'white')
        ImageDraw.Draw(img).rectangle([10, 10, 14, 14], fill='black')  # a tiny speck
        self.assertTrue(pp.is_blank_page(img))


class EnhanceTests(SimpleTestCase):

    def test_upscales_small_and_grayscales(self):
        out = pp.enhance_for_ocr(Image.new('RGB', (400, 550), 'white'), enable_deskew=False)
        self.assertGreaterEqual(out.width, 1500)
        self.assertEqual(out.mode, 'L')

    def test_estimate_skew_detects_tilt(self):
        img = Image.new('L', (800, 600), 255)
        d = ImageDraw.Draw(img)
        for y in range(50, 560, 30):
            d.rectangle([40, y, 760, y + 6], fill=0)       # horizontal text rows
        tilted = img.rotate(-3, expand=False, fillcolor=255)
        self.assertAlmostEqual(abs(pp._estimate_skew(tilted)), 3, delta=1.0)

    def test_no_skew_on_straight(self):
        img = Image.new('L', (800, 600), 255)
        d = ImageDraw.Draw(img)
        for y in range(50, 560, 30):
            d.rectangle([40, y, 760, y + 6], fill=0)
        self.assertAlmostEqual(pp._estimate_skew(img), 0, delta=0.6)


class QualityFlagTests(SimpleTestCase):

    def test_no_lines_flag(self):
        q = pp.page_quality({'lines': []})
        self.assertIn('no_lines', q['flags'])

    def test_few_lines_flag(self):
        q = pp.page_quality({'lines': [{'item_name': 'x'}]})
        self.assertIn('few_lines', q['flags'])

    def test_low_recall_flag(self):
        q = pp.page_quality({'lines': [{'item_name': 'a'}, {'item_name': 'b'}],
                             '_declared_count': 10})
        self.assertIn('low_recall', q['flags'])

    def test_clean_invoice_no_flags(self):
        q = pp.page_quality({'lines': [{'item_name': 'a'}, {'item_name': 'b'}, {'item_name': 'c'}],
                             '_declared_count': 3})
        self.assertEqual(q['flags'], [])

    def test_low_confidence_from_boxes(self):
        boxes = [{'conf': 0.2}, {'conf': 0.3}, {'conf': 0.25}]
        q = pp.page_quality({'lines': [{'item_name': 'a'}, {'item_name': 'b'}]}, boxes=boxes)
        self.assertIn('low_confidence', q['flags'])
        self.assertAlmostEqual(q['avg_confidence'], 0.25, places=2)
