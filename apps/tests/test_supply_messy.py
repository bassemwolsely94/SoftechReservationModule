"""
Phase-7 regression tests: messy real-world supplier messages (doc 24 §2/§4/§37/§38).

Every case here was a real failure of the first parser, found by probing it with the way
operators actually paste WhatsApp chats. Pure parsing — no database.
"""
from django.test import SimpleTestCase

from apps.supply.availability import (clean_line, detect_sender, parse_availability_line,
                                      split_availability_lines)


def P(line):
    return parse_availability_line(line)


class WhatsAppHeaderTests(SimpleTestCase):
    def test_android_copy_header_is_not_an_expiry_and_sender_does_not_leak(self):
        p = P('[20/09/2026, 10:15] Ibn Sina Sales: Recormon 4000 available 10')
        self.assertEqual(p.name_part, 'Recormon 4000')
        self.assertEqual(p.supplier_qty, 10.0)
        self.assertEqual(p.expiry, '')                     # the message date is NOT an expiry

    def test_export_header_format(self):
        p = P('20/09/2026, 10:16 - Ahmed Ibn Sina: كريون ٢٥٠٠٠ متاح ٢٠')
        self.assertEqual(p.name_part, 'كريون 25000')
        self.assertEqual(p.supplier_qty, 20.0)

    def test_arabic_locale_header_with_arabic_digits_and_am_marker(self):
        p = P('[٢٠/٩/٢٠٢٦ ١٠:١٧ ص] ابن سينا: سيلسبت ٥٠٠ عدد ٥')
        self.assertEqual(p.name_part, 'سيلسبت 500')
        self.assertEqual(p.supplier_qty, 5.0)

    def test_us_style_export_header(self):
        p = P('9/20/26, 10:15 PM - Sales: Xgeva 120mg 3')
        self.assertEqual(p.name_part, 'Xgeva 120mg')

    def test_sender_is_detected_as_supplier_hint(self):
        chat = ('[20/09/2026, 10:15] Ibn Sina Sales: Recormon 4000 10\n'
                '[20/09/2026, 10:16] Ibn Sina Sales: Kreon 25000 5\n'
                '[20/09/2026, 10:17] Me: شكرا')
        self.assertEqual(detect_sender(chat), 'Ibn Sina Sales')


class NoiseLineTests(SimpleTestCase):
    def test_non_product_lines_are_dropped(self):
        for line in ['السلام عليكم ورحمة الله', 'صباح الخير', 'متاح لدينا اليوم:',
                     '<Media omitted>', 'تم حذف هذه الرسالة', 'This message was deleted',
                     '20/09/2026, 10:14 - Messages and calls are end-to-end encrypted',
                     '✅✅', 'Thanks!']:
            self.assertIsNone(clean_line(line), line)
            self.assertTrue(P(line).noise, line)

    def test_split_counts_only_products(self):
        blob = ('السلام عليكم\nمتاح لدينا:\n• Xgeva 120mg x3\n<Media omitted>\n'
                'Voltaren 50 5، Brufen 400 3')
        self.assertEqual(split_availability_lines(blob),
                         ['Xgeva 120mg x3', 'Voltaren 50 5', 'Brufen 400 3'])

    def test_product_without_digits_is_kept(self):
        self.assertEqual(clean_line('Ozempic available'), 'Ozempic available')


class DecorationTests(SimpleTestCase):
    def test_bullets_numbering_and_emoji_do_not_leak_into_names(self):
        self.assertEqual(P('• Xgeva 120mg x3').name_part, 'Xgeva 120mg')
        self.assertEqual(P('1- Ozempic 1mg متاح').name_part, 'Ozempic 1mg')
        self.assertEqual(P('2) Nexium 40 mg 10 علب').name_part, 'Nexium 40 mg')
        self.assertEqual(P('✅ Zinnat 250 10+2').name_part, 'Zinnat 250')


class QuantityTests(SimpleTestCase):
    def test_single_bare_number_is_the_strength_not_the_quantity(self):
        p = P('Recormon 4000 available')
        self.assertEqual(p.name_part, 'Recormon 4000')     # strength kept for matching
        self.assertIsNone(p.supplier_qty)                   # unknown, not 4000

    def test_explicit_quantity_markers(self):
        self.assertEqual(P('Xgeva 120mg x3').supplier_qty, 3.0)
        self.assertEqual(P('Nexium 40 ×10').supplier_qty, 10.0)
        self.assertEqual(P('Augmentin 1g qty: 15').supplier_qty, 15.0)
        self.assertEqual(P('Nexium 40 mg 10 علب').supplier_qty, 10.0)
        self.assertEqual(P('Ozempic 1 mg 3 pens').supplier_qty, 3.0)
        self.assertEqual(P('Concor 5 - 20 box').supplier_qty, 20.0)

    def test_x_inside_a_name_is_not_a_quantity(self):
        p = P('Xgeva 120mg')
        self.assertEqual(p.name_part, 'Xgeva 120mg')
        self.assertIsNone(p.supplier_qty)

    def test_no_fabricated_quantity(self):
        self.assertIsNone(P('Xgeva 120mg vial').supplier_qty)


class EconomicsTests(SimpleTestCase):
    def test_foc_keyword_before_number_wins_over_the_strength(self):
        p = P('Kreon 25000 بونص 2 مجانا')
        self.assertEqual(p.foc_qty, 2.0)                    # NOT 25000
        self.assertEqual(p.name_part, 'Kreon 25000')

    def test_price_with_currency_leaves_no_residue(self):
        p = P('Concor 5 - 20 box @ 45 LE')
        self.assertEqual((p.price, p.supplier_qty, p.name_part), (45.0, 20.0, 'Concor 5'))
        self.assertEqual(P('Panadol 500 20 بسعر 35 جنيه').price, 35.0)

    def test_discount_forms(self):
        p = P('Nexium 40 ×10 خصم 5%')
        self.assertEqual((p.discount_pct, p.supplier_qty, p.name_part), (5.0, 10.0, 'Nexium 40'))
        self.assertEqual(P('Concor 5 10 15%').discount_pct, 15.0)

    def test_expiry_forms_are_normalised(self):
        p = P('Lipitor 20mg 5 exp 2026-06')
        self.assertEqual((p.expiry, p.supplier_qty, p.name_part), ('06/2026', 5.0, 'Lipitor 20mg'))
        self.assertEqual(P('Lipitor 20mg 5 صلاحية 6/27').expiry, '06/2027')
        self.assertEqual(P('Lipitor 20mg 5 exp 06/2026').expiry, '06/2026')

    def test_supplier_item_code(self):
        p = P('Cellcept 500 كود 45871 5 علب')
        self.assertEqual((p.supplier_item_code, p.supplier_qty), ('45871', 5.0))


class GramIsNotAPriceTests(SimpleTestCase):
    def test_grams_stay_in_the_name(self):
        p = P('اوجمنتين ١ جم ٨ علب')
        self.assertEqual((p.name_part, p.price, p.supplier_qty), ('اوجمنتين 1 جم', None, 8.0))
        self.assertIsNone(P('Augmentin 1 جرام 5 علب').price)

    def test_pound_forms_are_prices(self):
        self.assertEqual(P('Concor 5 x10 45 ج.م').price, 45.0)
        self.assertEqual(P('Brufen 400 3 @ 25 ج').price, 25.0)
        self.assertEqual(P('Panadol 500 20 بسعر 35 جنيه').price, 35.0)


class MatchSafetyGuardTests(SimpleTestCase):
    """The real dangerous cases found on the live catalog (validate_supply_matching)."""

    def test_strength_conflicts_are_flagged(self):
        from apps.supply.ingest import review_flags
        self.assertIn('strength_mismatch',
                      review_flags('ريكورمون 4000', 'RECORMON 5000 I.U. 6SYRINGES (XX) (FRIDGE) ريكورمون'))
        self.assertIn('strength_mismatch',
                      review_flags('Concor Plus 5/12.5', 'CONCOR PLUS 10MG / 12.5MG 30TAB (3STRIPSX10)'))
        self.assertIn('strength_mismatch',
                      review_flags('اوجمنتين 1 جم', 'AUGMENTIN 457MG/5ML SYRUP 70ML اوجمنتين 457مجم شراب'))

    def test_matching_strength_and_thousands_separator_pass(self):
        from apps.supply.ingest import review_flags
        self.assertEqual(review_flags('KREON 25000', 'KREON 25000IU  100CAP (XX) (25,000IU)'), [])
        self.assertEqual(review_flags('Ozempic 0.5 mg', 'OZEMPIC 0.5MG 1PEN (XX) (FRIDGE)'), [])

    def test_dosage_form_conflict_is_flagged(self):
        from apps.supply.ingest import review_flags
        self.assertIn('form_mismatch',
                      review_flags('Nexium 40 mg tab', 'NEXIUM 40 MG POWDER FOR I.V. INF. VIAL XX'))

    def test_close_rival_of_a_different_brand_is_ambiguous(self):
        from apps.supply.ingest import review_flags
        self.assertIn('ambiguous', review_flags('Lipitur 40 mg', 'LIPINORM  40 MG 7TAB',
                                                runner_up_name='LIPITOR 40MG 14TAB', score=0.956,
                                                runner_up_score=0.95))
        # Same brand, other pack → not ambiguous (a pack choice, not a wrong product).
        self.assertNotIn('ambiguous', review_flags('Nexium 20mg', 'NEXIUM 20MG 28TAB',
                                                   runner_up_name='NEXIUM 20 MG 14 TAB',
                                                   score=1.0, runner_up_score=1.0))

    def test_harness_classification(self):
        from apps.supply.validation import classify
        self.assertEqual(classify(['1'], False, '1', 0.9), 'correct_confident')
        self.assertEqual(classify(['1'], False, '1', 0.9, guarded=True), 'correct_review')
        self.assertEqual(classify(['1'], False, '2', 0.9), 'wrong_confident')
        self.assertEqual(classify(['1'], False, '2', 0.9, guarded=True), 'wrong_flagged')
        self.assertEqual(classify(None, True, '2', 0.9), 'wrong_confident')
        self.assertEqual(classify(None, True, None, None), 'absent_ok')
