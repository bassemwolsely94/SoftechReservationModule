"""
Tests for the shared invoice→catalog matcher apps.invoices.pipeline.match_candidates.

This is the single matching implementation used by BOTH production build_lines and
the accuracy benchmark, so the 4-tier order is pinned here:
  Tier 0 itemssuppliers (SOFTECH code→item, authoritative)  → mocked (mirror)
  Tier 1 learned vendor_item_code (PG VendorItemMapping)
  Tier 2 learned normalized name (PG VendorItemMapping)
  Tier 3 fuzzy corpus (find_best_matches)                   → mocked
Tiers 0 and 3 are mocked so each tier is deterministic without SOFTECH or pg_trgm.
"""
from django.test import TestCase

from apps.catalog.models import Item
from apps.invoices import pipeline
from apps.invoices.models import VendorProfile, VendorItemMapping
from apps.shortage.matching import _normalize


class MatchCandidatesTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.it_supp = Item.objects.create(softech_id='100', name='ITEM VIA ITEMSSUPPLIERS')
        cls.it_code = Item.objects.create(softech_id='200', name='ITEM VIA VENDOR CODE')
        cls.it_name = Item.objects.create(softech_id='300', name='PANADOL EXTRA')
        cls.it_fuzz = Item.objects.create(softech_id='400', name='ITEM VIA FUZZY')
        cls.vendor = VendorProfile.objects.create(
            name='رامكو', softech_personcode='4321', is_main=True)
        VendorItemMapping.objects.create(
            vendor=cls.vendor, vendor_item_code='RC200', raw_name_normalized='zzz',
            item=cls.it_code)
        VendorItemMapping.objects.create(
            vendor=cls.vendor, raw_name_normalized=_normalize('بانادول اكسترا'),
            item=cls.it_name)

    # ── tier 0: SOFTECH itemssuppliers (mocked mirror) ──
    def test_tier0_itemssuppliers_code(self):
        import apps.catalog.supplier_links as sl
        orig = sl.resolve_codes
        sl.resolve_codes = lambda pc, codes: {'RSUP': '100'}
        try:
            res = pipeline.match_candidates(
                [{'vendor_item_code': 'RSUP', 'manual_name': 'whatever'}], self.vendor)
        finally:
            sl.resolve_codes = orig
        self.assertEqual(res[0]['item'], self.it_supp)
        self.assertEqual(res[0]['tier'], 'itemssuppliers')
        self.assertEqual(res[0]['score'], 1.0)

    # ── tier 1: learned vendor_item_code ──
    def test_tier1_vendor_code(self):
        res = self._match_no_mirror(
            [{'vendor_item_code': 'RC200', 'manual_name': 'anything'}])
        self.assertEqual(res[0]['item'], self.it_code)
        self.assertEqual(res[0]['tier'], 'vendor_code')

    # ── tier 2: learned normalized name ──
    def test_tier2_vendor_name(self):
        res = self._match_no_mirror(
            [{'vendor_item_code': '', 'manual_name': 'بانادول اكسترا'}])
        self.assertEqual(res[0]['item'], self.it_name)
        self.assertEqual(res[0]['tier'], 'vendor_name')

    # ── tier 3: fuzzy (mocked) ──
    def test_tier3_fuzzy(self):
        import apps.shortage.matching as sm
        orig = sm.find_best_matches
        sm.find_best_matches = lambda name, **kw: [{'item_id': self.it_fuzz.id, 'score': 0.77}]
        try:
            res = pipeline.match_candidates(
                [{'vendor_item_code': 'UNKNOWN', 'manual_name': 'مجهول'}],
                self._vendor_not_main())
        finally:
            sm.find_best_matches = orig
        self.assertEqual(res[0]['item'], self.it_fuzz)
        self.assertEqual(res[0]['tier'], 'fuzzy')
        self.assertAlmostEqual(res[0]['score'], 0.77)

    def test_no_match_returns_empty(self):
        import apps.shortage.matching as sm
        orig = sm.find_best_matches
        sm.find_best_matches = lambda name, **kw: []
        try:
            res = pipeline.match_candidates(
                [{'vendor_item_code': 'NOPE', 'manual_name': 'nope'}],
                self._vendor_not_main())
        finally:
            sm.find_best_matches = orig
        self.assertIsNone(res[0]['item'])
        self.assertEqual(res[0]['tier'], '')

    def test_code_beats_name_and_order_preserved(self):
        # code match must win over a (would-be) name match, and results align 1:1
        res = self._match_no_mirror([
            {'vendor_item_code': 'RC200', 'manual_name': 'بانادول اكسترا'},
            {'vendor_item_code': '', 'manual_name': 'بانادول اكسترا'},
        ])
        self.assertEqual(res[0]['item'], self.it_code)   # code wins
        self.assertEqual(res[0]['tier'], 'vendor_code')
        self.assertEqual(res[1]['item'], self.it_name)   # name tier
        self.assertEqual(res[1]['tier'], 'vendor_name')

    def test_vendor_none_skips_tier0_but_still_matches_global_code(self):
        VendorItemMapping.objects.create(
            vendor=None, vendor_item_code='GLOBAL9', raw_name_normalized='g9',
            item=self.it_code)
        res = pipeline.match_candidates(
            [{'vendor_item_code': 'GLOBAL9', 'manual_name': 'x'}], None)
        self.assertEqual(res[0]['item'], self.it_code)
        self.assertEqual(res[0]['tier'], 'vendor_code')

    # ── helpers ──
    def _vendor_not_main(self):
        # is_main False → Tier-0 batch recall (which would hit SOFTECH) is skipped
        self.vendor.is_main = False
        return self.vendor

    def _match_no_mirror(self, cands):
        """Match isolating tiers 1–3: is_main=False skips the Tier-0 batch recall
        entirely (so no SOFTECH/itemssuppliers call), vendor still scopes tiers 1–2."""
        self.vendor.is_main = False
        return pipeline.match_candidates(cands, self.vendor)


class BarcodeTierTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import ItemBarcode
        cls.it = Item.objects.create(softech_id='501', name='SCANNED ITEM', barcode='6224000111121')
        cls.it2 = Item.objects.create(softech_id='502', name='SECONDARY BC ITEM')
        ItemBarcode.objects.create(item=cls.it2, barcode='6224000222228', is_active=True)
        cls.vendor = VendorProfile.objects.create(name='رامكو', softech_personcode='30', is_main=False)

    def test_primary_barcode_exact_match(self):
        res = pipeline.match_candidates(
            [{'vendor_item_code': '6224000111121', 'manual_name': 'whatever'}], self.vendor)
        self.assertEqual(res[0]['item'], self.it)
        self.assertEqual(res[0]['tier'], 'barcode')
        self.assertEqual(res[0]['score'], 1.0)

    def test_secondary_barcode_match(self):
        res = pipeline.match_candidates(
            [{'vendor_item_code': '6224000222228', 'manual_name': 'x'}], self.vendor)
        self.assertEqual(res[0]['item'], self.it2)
        self.assertEqual(res[0]['tier'], 'barcode')

    def test_short_code_not_treated_as_barcode(self):
        # a 5-digit supplier SKU must NOT be looked up as a barcode
        self.assertFalse(pipeline._looks_like_barcode('12345'))
        res = pipeline.match_candidates(
            [{'vendor_item_code': '12345', 'manual_name': 'nothing here'}], self.vendor)
        self.assertNotEqual(res[0]['tier'], 'barcode')


class StrengthGuardTests(TestCase):

    def test_strength_conflict_same_unit_diff_magnitude(self):
        self.assertTrue(pipeline._strength_conflict('كونكور 5 مجم', 'كونكور 10 مجم'))
        self.assertTrue(pipeline._strength_conflict('Amlor 5mg', 'Amlor 10mg'))

    def test_no_conflict_same_strength_or_missing_or_diff_unit(self):
        self.assertFalse(pipeline._strength_conflict('Amlor 5mg', 'Amlor 5 mg'))
        self.assertFalse(pipeline._strength_conflict('Panadol', 'Panadol Extra'))   # no strengths
        self.assertFalse(pipeline._strength_conflict('X 500mg', 'X 0.5g'))          # diff unit → not flagged

    def test_fuzzy_prefers_non_conflicting_strength(self):
        it5 = Item.objects.create(softech_id='611', name='CONCOR 5MG')
        it10 = Item.objects.create(softech_id='612', name='CONCOR 10MG')
        v = VendorProfile.objects.create(name='V', softech_personcode='', is_main=False)
        import apps.shortage.matching as sm
        orig = sm.find_best_matches
        # top candidate is the WRONG strength (10mg), second is the right one (5mg)
        sm.find_best_matches = lambda name, **kw: [
            {'item_id': it10.id, 'score': 0.90, 'name': 'CONCOR 10MG'},
            {'item_id': it5.id, 'score': 0.88, 'name': 'CONCOR 5MG'}]
        try:
            res = pipeline.match_candidates(
                [{'vendor_item_code': '', 'manual_name': 'كونكور 5 مجم'}], v)
        finally:
            sm.find_best_matches = orig
        self.assertEqual(res[0]['item'], it5)        # picked the 5mg, not the 10mg
        self.assertEqual(res[0]['tier'], 'fuzzy')

    def test_fuzzy_all_conflict_flags_review(self):
        it10 = Item.objects.create(softech_id='613', name='DRUGX 10MG')
        v = VendorProfile.objects.create(name='V2', softech_personcode='', is_main=False)
        import apps.shortage.matching as sm
        orig = sm.find_best_matches
        sm.find_best_matches = lambda name, **kw: [{'item_id': it10.id, 'score': 0.9, 'name': 'DRUGX 10MG'}]
        try:
            res = pipeline.match_candidates(
                [{'vendor_item_code': '', 'manual_name': 'DRUGX 5mg'}], v)
        finally:
            sm.find_best_matches = orig
        self.assertEqual(res[0]['item'], it10)       # kept (best available)
        self.assertTrue(res[0]['match_review'])      # but flagged — wrong-dose risk
