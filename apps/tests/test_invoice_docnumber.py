"""
Tests for apps/invoices/docnumber.py — recovering the PRINTED invoice number when
the boundary parser grabbed the 1-D barcode instead.

The consensus (best_number / number_from_barcode / plausible) is pure and gets the
bulk of the coverage. refine_doc_number is exercised with the two image helpers
monkeypatched, so the real benchmark failures (13–14 digit barcode numbers) are
reproduced without needing image fixtures.
"""
from django.test import SimpleTestCase

from apps.invoices import docnumber as dn


class PlausibleTests(SimpleTestCase):

    def test_printed_invoice_numbers_are_plausible(self):
        # real matched Ramco / PharmaOverseas numbers from the HQ benchmark
        for n in ('1826060943', '1826060938', '18260609255', '18260609076',
                  '8822632985'):
            self.assertTrue(dn.plausible(n), n)

    def test_barcode_length_is_not_plausible(self):
        # the 12–14 digit reads that wrongly became doc numbers (12 = a barcode
        # digit leaked into the printed-number read; 13–14 = the barcode itself)
        for n in ('182606087057', '182606077093', '13260608845574',
                  '1826060926554', '18260608355151', '9118260609251'):
            self.assertFalse(dn.plausible(n), n)

    def test_customer_and_short_codes_are_not_plausible(self):
        self.assertFalse(dn.plausible('00010059'))   # zero-padded customer code
        self.assertFalse(dn.plausible('1234'))       # too short
        self.assertFalse(dn.plausible(''))
        self.assertFalse(dn.plausible(None))

    def test_punctuation_is_ignored(self):
        self.assertTrue(dn.plausible('1826-060943'))


class BarcodeReductionTests(SimpleTestCase):

    def test_hint_contained_in_barcode_is_confirmed(self):
        # barcode 91 + 1826060925 + check(1); the printed number is embedded
        self.assertEqual(dn.number_from_barcode('9118260609251', hint='1826060925'),
                         '1826060925')

    def test_invoice_length_barcode_is_returned_as_is(self):
        self.assertEqual(dn.number_from_barcode('1826060943'), '1826060943')

    def test_bare_marker_wrapped_barcode_is_not_guessed(self):
        # no hint → stripping an unknown marker/check is ambiguous → refuse
        self.assertEqual(dn.number_from_barcode('9118260609251'), '')

    def test_non_matching_hint_falls_through(self):
        self.assertEqual(dn.number_from_barcode('9998888777766', hint='1826060925'), '')


class NumberInBarcodeTests(SimpleTestCase):
    """The longest plausible text PREFIX that the barcode validates — the primary
    recovery when a barcode check digit leaked into the whole-page read."""

    def test_trailing_leak_is_trimmed_to_barcode_validated_number(self):
        # real p2/p4 from the Ramco smoke test
        self.assertEqual(dn.number_in_barcode('182606087057', '9118260608704'),
                         '1826060870')
        self.assertEqual(dn.number_in_barcode('182606077093', '9118260607707'),
                         '1826060770')

    def test_prefers_longest_plausible_prefix(self):
        # 11-digit prefix present in the barcode → take it (longest wins)
        self.assertEqual(dn.number_in_barcode('18260609076', '91182606090763'),
                         '18260609076')
        # 11th digit is a leak (absent from the barcode) → fall back to 10 (real p1)
        self.assertEqual(dn.number_in_barcode('18260609255', '9118260609251'),
                         '1826060925')

    def test_no_barcode_match_returns_empty(self):
        self.assertEqual(dn.number_in_barcode('182608077093', '9998888777766'), '')

    def test_empty_inputs(self):
        self.assertEqual(dn.number_in_barcode('', '9118260608704'), '')
        self.assertEqual(dn.number_in_barcode('182606087057', ''), '')


class BestNumberTests(SimpleTestCase):

    def test_clean_text_is_kept_no_regression(self):
        num, src, conf = dn.best_number(text_number='1826060943')
        self.assertEqual(num, '1826060943')
        self.assertEqual(src, 'text')
        self.assertGreaterEqual(conf, 0.7)

    def test_text_confirmed_by_barcode_is_boosted(self):
        num, src, conf = dn.best_number(text_number='1826060925',
                                        barcode='9118260609251')
        self.assertEqual(num, '1826060925')
        self.assertEqual(src, 'text+barcode')
        self.assertGreater(conf, 0.9)

    def test_barcode_anchored_prefix_beats_a_region_misread(self):
        # THE regression guard: text leaked a digit (182606077093); the region OCR
        # MISREAD it as 182608077. The barcode validates the true prefix 1826060770,
        # which must win over the plausible-but-wrong region read.
        num, src, conf = dn.best_number(text_number='182606077093',
                                        region_number='182608077',
                                        barcode='9118260607707')
        self.assertEqual(num, '1826060770')
        self.assertEqual(src, 'text+barcode')
        self.assertGreaterEqual(conf, 0.9)

    def test_barcode_length_text_is_recovered_by_region_when_no_barcode(self):
        # the core fix when the barcode does NOT decode (real p5): parser grabbed
        # the 14-digit read; the hi-DPI Arabic region read supplies the number.
        # Consistent with the text (1826060835 is a prefix of the 14-digit read).
        num, src, conf = dn.best_number(text_number='18260608355151',
                                        region_number='1826060835')
        self.assertEqual(num, '1826060835')
        self.assertEqual(src, 'region')
        self.assertGreaterEqual(conf, 0.8)

    def test_inconsistent_region_misread_is_rejected(self):
        # real regression guard: region OCR mangled 13260608845574 into the
        # unrelated 720060884 — it must NOT replace the original (which the SofTech
        # resolver can still try to truncate).
        num, src, conf = dn.best_number(text_number='13260608845574',
                                        region_number='720060884')
        self.assertNotEqual(num, '720060884')
        self.assertEqual(num, '13260608845574')   # original kept
        self.assertLessEqual(conf, 0.3)

    def test_region_confirmed_by_barcode_is_highest(self):
        num, src, conf = dn.best_number(text_number='13260608845574',
                                        region_number='1826060884',
                                        barcode='9118260608841')
        self.assertEqual(num, '1826060884')
        self.assertEqual(src, 'region+barcode')
        self.assertGreater(conf, 0.9)

    def test_invoice_length_barcode_used_when_text_and_region_fail(self):
        num, src, conf = dn.best_number(text_number='', region_number='',
                                        barcode='1826060943')
        self.assertEqual(num, '1826060943')
        self.assertEqual(src, 'barcode')

    def test_nothing_plausible_returns_best_effort_low_confidence(self):
        num, src, conf = dn.best_number(text_number='9118260609251')
        self.assertEqual(num, '9118260609251')   # never worse than before
        self.assertLessEqual(conf, 0.3)

    def test_empty_everything(self):
        self.assertEqual(dn.best_number(), ('', '', 0.2))


class ConsistencyTests(SimpleTestCase):

    def test_containment_is_consistent(self):
        self.assertTrue(dn.consistent('1826060835', '18260608355151'))  # p5 prefix

    def test_long_shared_run_is_consistent(self):
        # leading-digit misread in the text (1382…), region got 1826060919 — they
        # still share a ≥7 contiguous run, so the region read is trusted
        self.assertTrue(dn.consistent('1826060919', '1382606091964'))

    def test_unrelated_misread_is_inconsistent(self):
        self.assertFalse(dn.consistent('720060884', '13260608845574'))   # LCS 6
        self.assertFalse(dn.consistent('4826063905', '182606330555'))

    def test_empty_is_inconsistent(self):
        self.assertFalse(dn.consistent('', '1826060835'))


class RefineDocNumberTests(SimpleTestCase):
    """refine_doc_number with the image helpers stubbed — proves the trigger logic
    (only refine when implausible) and the candidate plumbing."""

    def _patch(self, region='', barcode=''):
        self._orig = (dn.region_number, dn.decode_barcode)
        dn.region_number = lambda img: region
        dn.decode_barcode = lambda img: barcode

    def tearDown(self):
        if hasattr(self, '_orig'):
            dn.region_number, dn.decode_barcode = self._orig

    def test_clean_text_skips_region_pass(self):
        called = {'region': False}
        self._orig = (dn.region_number, dn.decode_barcode)

        def boom(img):
            called['region'] = True
            return '9999999999'
        dn.region_number = boom
        dn.decode_barcode = lambda img: ''
        res = dn.refine_doc_number(object(), text_number='1826060943')
        self.assertEqual(res['number'], '1826060943')     # kept
        self.assertFalse(called['region'])                 # hi-DPI pass NOT paid for

    def test_barcode_length_text_triggers_region_recovery(self):
        # barcode does NOT decode → the hi-DPI Arabic region read recovers it (p5)
        self._patch(region='1826060835', barcode='')
        res = dn.refine_doc_number(object(), text_number='18260608355151')
        self.assertEqual(res['number'], '1826060835')
        self.assertEqual(res['source'], 'region')
        self.assertEqual(res['candidates']['text'], '18260608355151')

    def test_barcode_anchor_recovers_without_paying_for_region(self):
        # when the barcode validates a clean prefix, the costly region pass is skipped
        called = {'region': False}
        self._orig = (dn.region_number, dn.decode_barcode)

        def boom(img):
            called['region'] = True
            return '999999999'
        dn.region_number = boom
        dn.decode_barcode = lambda img: '9118260607707'
        res = dn.refine_doc_number(object(), text_number='182606077093')
        self.assertEqual(res['number'], '1826060770')
        self.assertEqual(res['source'], 'text+barcode')
        self.assertFalse(called['region'])

    def test_missing_number_recovered_from_region(self):
        self._patch(region='1826060938', barcode='')
        res = dn.refine_doc_number(object(), text_number='')
        self.assertEqual(res['number'], '1826060938')
