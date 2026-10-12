"""
Distributor «الوارد» lists — owner batch 2026-10-07 (EGY DRUG شريف/زيتون, Pharma Overseas,
AKHNATON): time-first WhatsApp headers, chat remarks kept as notes, stock notes attached to
the item above, quota / bonus tiers / promo packs / Arabic ٪ discount / availability signals,
distributor shorthand for forms, and one written line → one row per product (or the family).
"""
from django.test import SimpleTestCase, TestCase

from apps.supply import availability as av
from apps.supply.availability import parse_availability_line as P, split_variants


class TermsTests(SimpleTestCase):
    def test_quota_words_and_numbers(self):
        self.assertEqual(P('Closol spray كوته علبه').quota, 1.0)
        self.assertEqual(P('Nostamine drop كوته اثنيت').quota, 2.0)
        self.assertEqual(P('Ketostril t كوته تلاته').quota, 3.0)
        self.assertEqual(P('Euthyrox 100ml tكوته خمسه').quota, 5.0)
        p = P('جالفس ميت 50/1000 كوته 20')
        self.assertEqual((p.quota, p.name_part), (20.0, 'جالفس ميت 50/1000'))
        self.assertIn('half_quota', P('بالميكورت نصف كوته').signals)
        bare = P('اولفنت شراب كوته')
        self.assertIsNone(bare.quota)
        self.assertIn('quota', bare.signals)

    def test_bonus_tiers(self):
        p = P('محلول ملح 18+2......36+4.....106+14')
        self.assertEqual(p.bonus_tiers, [[18.0, 2.0], [36.0, 4.0], [106.0, 14.0]])
        self.assertEqual((p.bonus_buy, p.foc_qty, p.supplier_qty), (18.0, 2.0, None))
        self.assertEqual(p.name_part, 'محلول ملح')
        q = P('انتوبرال ٤٠ بونص 10+1')
        self.assertEqual((q.bonus_buy, q.foc_qty, q.name_part), (10.0, 1.0, 'انتوبرال 40'))

    def test_promo_pack_is_not_a_bonus(self):
        p = P('Limitless man 30t +7free كوته علبه')
        self.assertEqual((p.promo, p.foc_qty, p.quota), ('30+7 free', None, 1.0))
        self.assertEqual(p.name_part, 'Limitless man 30 tab')

    def test_price_and_arabic_percent_discount(self):
        self.assertEqual(P('Finjuve 1300ج').price, 1300.0)
        self.assertEqual(P('استربسلز برتقال سعر 230').price, 230.0)
        self.assertEqual(P('بيبيلاك 1.....2.....3  خصم اضافي ٢٪').discount_pct, 2.0)

    def test_signals(self):
        self.assertEqual(P('Trulicity بقاله فتره مكنش موجود').signals, ['back_in_stock'])
        self.assertEqual(P('Trulicity بقاله فتره مكنش موجود').name_part, 'Trulicity')
        self.assertIn('limited', P('كليكسان 20 & 40 كوته 30 كميات محدوده جدا').signals)
        self.assertIn('last_qty', P('دافالندى امبول اخر كميه').signals)
        self.assertIn('scarce_variant', P('Megamox 625 التركيز ده قليل').signals)
        self.assertEqual(P('Xatral xl🔥🔥').signals, ['hot'])

    def test_forms_shorthand_and_strengths(self):
        self.assertEqual(P('Lamictal 50ml t كوته تلاته').name_part, 'Lamictal 50 tab')
        self.assertEqual(P('Trental 400t').name_part, 'Trental 400 tab')
        self.assertEqual(P('تلفاست ش').name_part, 'تلفاست شراب')
        self.assertEqual(P('فيموستون 10-2').supplier_qty, None)        # a strength, not "2 available"
        self.assertEqual(P('Depovita amp').name_part, 'Depovita amp')  # the form stays (≠ lozenges)
        n = P('Novopen 4 قلم الأنسولين')
        self.assertEqual((n.supplier_qty, n.name_part), (None, 'Novopen 4 قلم الأنسولين'))

    def test_family_word(self):
        p = P('بيتاسيرك اقراص بتركيزاته')
        self.assertTrue(p.all_variants)
        self.assertEqual(p.name_part, 'بيتاسيرك اقراص')
        self.assertTrue(P('ابتاميل لبن كل الانواع').all_variants)
        self.assertTrue(P('اوتريفين بانواعه').all_variants)


class VariantSplitTests(SimpleTestCase):
    def test_strengths(self):
        self.assertEqual(split_variants('كليكسان 20 & 40 & 60 & 80'),
                         ['كليكسان 20', 'كليكسان 40', 'كليكسان 60', 'كليكسان 80'])
        self.assertEqual(split_variants('نوفونورم 0.5 & 1 & 2 اقراص'),
                         ['نوفونورم 0.5 اقراص', 'نوفونورم 1 اقراص', 'نوفونورم 2 اقراص'])
        self.assertEqual(split_variants('بليتال 100....50'), ['بليتال 100', 'بليتال 50'])
        self.assertEqual(split_variants('Genuphil sach 10&30'), ['Genuphil sach 10', 'Genuphil sach 30'])
        self.assertEqual(split_variants(P('سيالس ٢و٤').name_part), ['سيالس 2', 'سيالس 4'])

    def test_word_variants(self):
        self.assertEqual(split_variants('بانادول اكيوت..ادفانس...اكسترا... شراب اطفال'),
                         ['بانادول اكيوت', 'بانادول ادفانس', 'بانادول اكسترا', 'بانادول شراب اطفال'])
        self.assertEqual(split_variants('فولتارين لبوس واقراص وامبول وجيل'),
                         ['فولتارين لبوس', 'فولتارين اقراص', 'فولتارين امبول', 'فولتارين جيل'])
        self.assertEqual(split_variants('تارج...كو تارج... كو ديوفان'), ['تارج', 'كو تارج', 'كو ديوفان'])
        self.assertEqual(split_variants('ميلجا & ميلجا ادفانس اقراص'), ['ميلجا', 'ميلجا ادفانس اقراص'])
        self.assertEqual(split_variants('Concor 5'), ['Concor 5'])


class ReadListTests(SimpleTestCase):
    SAMPLE = '\n'.join([
        'Ketostril', 'اخر 30علبه', '',
        '[12:44 pm, 07/10/2026] Sarah Masria Far3 Sherif: Duotrav drop',
        'وارد ايفا اخناتون 🌤️', 'فتحه شهر جديد', 'دي ديب نقط',
        'ده كل الوارد', 'فاضل فقط 100 علبه',
        'ليفاجول كبسول كوته كميه محدوده جدا',
    ])

    def test_entries_and_remarks(self):
        entries, remarks = av.read_list(self.SAMPLE)
        names = [e['parsed'].name_part for e in entries]
        self.assertEqual(names, ['Ketostril', 'Duotrav drop', 'دي ديب نقط', 'ليفاجول كبسول'])
        keto = entries[0]['parsed']
        self.assertEqual((keto.supplier_qty, keto.signals), (30.0, ['last_qty']))   # note → item above
        self.assertIn('ده كل الوارد', remarks)
        self.assertIn('فاضل فقط 100 علبه', remarks)        # after a remark → not attached to an item
        self.assertIn('وارد ايفا اخناتون', remarks)
        self.assertEqual(av.detect_sender(self.SAMPLE), 'Sarah Masria Far3 Sherif')


class IngestGroupsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        mk = lambda sid, name: Item.objects.create(softech_id=sid, name=name, is_active=True)
        cls.c20 = mk('730020', 'CLEXANE 20MG/0.2ML 2 PREFILLED SYRINGE')
        cls.c40 = mk('730040', 'CLEXANE 40MG/0.4ML 2 PREFILLED SYRINGE')
        cls.o1 = mk('730101', 'OTRIVIN 0.1% ADULT NASAL DROPS 10ML')
        cls.o2 = mk('730102', 'OTRIVIN 0.05% PAED NASAL DROPS 10ML')
        cls.o3 = mk('730103', 'OTRIVIN ADVANCE NASAL SPRAY 10ML')

    def _batch(self):
        from apps.supply.models import AvailabilityBatch
        return AvailabilityBatch.objects.create(supplier_name='PO')

    def test_variant_line_becomes_one_group_with_terms(self):
        b = self._batch()
        heads = av.ingest_batch(b, 'Clexane 20 & 40 كوته 30 كميات محدوده\nده كل الوارد')
        self.assertEqual(len(heads), 1)
        rows = list(b.lines.order_by('id'))
        self.assertEqual(len(rows), 2)
        self.assertEqual([r.split_from_id for r in rows], [None, heads[0].pk])
        self.assertEqual({r.item_id for r in rows}, {self.c20.id, self.c40.id})
        for r in rows:
            self.assertEqual((float(r.quota), r.signals), (30.0, ['limited']))
        self.assertEqual(av._learn_name(rows[0]), 'Clexane 20 & 40')   # remembered as written
        b.refresh_from_db()
        self.assertIn('ده كل الوارد', b.notes)

    def test_family_line_proposes_the_family_for_review(self):
        b = self._batch()
        head = av.ingest_batch(b, 'Otrivin بانواعه')[0]
        rows = list(b.lines.order_by('id'))
        self.assertEqual({r.item_id for r in rows}, {self.o1.id, self.o2.id, self.o3.id})
        self.assertTrue(all('family' in (r.match_reason.get('review_flags') or []) for r in rows))
        self.assertEqual(av._learn_name(head), 'Otrivin كل الانواع')
        # not "obvious": the bulk confirm leaves a family for a person
        self.assertEqual(av.confirm_matches(b), [])

    def test_sourcing_uses_the_bonus_buy_quantity(self):
        from decimal import Decimal
        from apps.supply.engine.sourcing import supplier_options
        from apps.supply.models import AvailabilityLine
        b = self._batch()
        ln = AvailabilityLine.objects.create(batch=b, raw_text='x', item=self.c20, price=Decimal('100'),
                                             bonus_buy=Decimal('10'), foc_qty=Decimal('1'))
        opt = supplier_options(self.c20.id, 10, availability_lines=[ln])['options'][0]
        self.assertAlmostEqual(opt['effective_cost'], round(100 * 10 / 11, 4))


class WrittenFormTests(SimpleTestCase):
    """The written form / strength breaks a near-tie; glued catalog forms are understood."""

    def test_glued_catalog_forms_raise_the_form_flag(self):
        from apps.supply.ingest import review_flags, forms_of
        self.assertEqual(forms_of('MELACRYST 3 MG 20FILM ORAL FILM TAB'), ['film', 'tablet'])
        self.assertIn('form_mismatch', review_flags('بانادول شراب اطفال', 'PANADOL 24TAB (XX)'))
        self.assertIn('form_mismatch', review_flags('لانتوس كارتلج', 'LANTUS SOLOSTAR 5PENS (XX)'))
        self.assertNotIn('form_mismatch', review_flags('ميلاكريست 3 فيلم', 'MELACRYST 3 MG 20FILM ORAL FILM TAB'))

    def test_close_candidate_with_the_written_form_wins(self):
        from apps.supply.ingest import _prefer_written
        m = [{'item_name': 'DEPOVIT PLUS 30 LOZENGES', 'score': 0.81},
             {'item_name': 'DEPOVIT - B12 1000MCG 5AMP 1ML', 'score': 0.77}]
        self.assertEqual(_prefer_written('Depovita amp', m)[0]['item_name'], 'DEPOVIT - B12 1000MCG 5AMP 1ML')
        # never jumps to another product because the form fits
        m2 = [{'item_name': 'LIMITLESS POWER MAX F/MALES 30CAP1JAR', 'score': 0.88},
              {'item_name': 'LIMITLESS WOMAN MAX 30 TAB', 'score': 0.86}]
        self.assertEqual(_prefer_written('Limitless power max tab', m2)[0]['item_name'], m2[0]['item_name'])
        # a remembered match is never moved
        m3 = [dict(m[0], learned=True), m[1]]
        self.assertEqual(_prefer_written('Depovita amp', m3)[0]['item_name'], m[0]['item_name'])
