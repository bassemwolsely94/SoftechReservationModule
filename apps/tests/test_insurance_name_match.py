"""Tests for the motalba patient-name autocomplete matcher (apps.insurance.name_match)."""
from django.test import SimpleTestCase

from apps.insurance.name_match import (
    normalize_ar, score_match, rank_candidates, suggest_name_improvement,
)


class NormalizeTests(SimpleTestCase):
    def test_folds_hamza_and_tashkeel(self):
        self.assertEqual(normalize_ar('أَحْمَد'), 'احمد')
        self.assertEqual(normalize_ar('إبراهيم'), 'ابراهيم')
        self.assertEqual(normalize_ar('يحيى'), 'يحيي')
        self.assertEqual(normalize_ar('فاطمة'), 'فاطمه')

    def test_collapses_whitespace(self):
        self.assertEqual(normalize_ar('  محمد   علي  '), 'محمد علي')


class ScoreMatchTests(SimpleTestCase):
    def test_ordered_prefix_hamza_tolerant(self):
        # user types without hamza; stored has hamza — must still match tier 3
        self.assertEqual(score_match('احمد محمد', 'أحمد محمد علي حسن')[0], 3)

    def test_partial_last_token(self):
        self.assertEqual(score_match('احمد مح', 'أحمد محمد علي حسن')[0], 3)

    def test_wrong_order_does_not_prefix_match(self):
        # «أحمد محمد» must NOT prefix-match «محمد أحمد ...» (repeated-token guard)
        sc = score_match('أحمد محمد', 'محمد أحمد علي حسن')
        self.assertTrue(sc is None or sc[0] < 3)

    def test_no_match(self):
        self.assertIsNone(score_match('خالد', 'محمد علي حسن'))

    def test_middle_token_subsequence_is_tier2(self):
        sc = score_match('محمد علي', 'أحمد محمد سعد علي')
        self.assertIsNotNone(sc)
        self.assertEqual(sc[0], 2)


class RankTests(SimpleTestCase):
    def test_exact_spelling_preserved_and_ranked(self):
        rows = [
            {'name': 'أحمد محمد علي حسن', 'count': 3, 'last_date': None},
            {'name': 'محمد أحمد سعيد',     'count': 9, 'last_date': None},
            {'name': 'خالد سمير',          'count': 1, 'last_date': None},
        ]
        res = rank_candidates('احمد محمد', rows, limit=5)
        self.assertTrue(res)
        # exact stored spelling (with hamza) is returned, not a normalized form
        self.assertEqual(res[0]['name'], 'أحمد محمد علي حسن')
        self.assertNotIn('خالد سمير', [r['name'] for r in res])


class SuggestImprovementTests(SimpleTestCase):
    def test_unambiguous_completion(self):
        rows = [
            {'name': 'أحمد محمد علي حسن', 'count': 5},
            {'name': 'أحمد محمد علي حسن', 'count': 0},
        ]
        imp = suggest_name_improvement('أحمد محمد علي', rows)
        self.assertEqual(imp['type'], 'complete')
        self.assertEqual(imp['suggestion'], 'أحمد محمد علي حسن')

    def test_ambiguous_completion_is_withheld(self):
        rows = [
            {'name': 'محمد علي حسن سعد', 'count': 3},
            {'name': 'محمد علي احمد فؤاد', 'count': 4},
        ]
        imp = suggest_name_improvement('محمد علي', rows)
        self.assertEqual(imp['type'], 'ambiguous')
        self.assertIsNone(imp['suggestion'])
        self.assertEqual(len(imp['options']), 2)

    def test_spelling_fix_when_variant_more_common(self):
        rows = [
            {'name': 'محمد علي ابراهيم', 'count': 9},   # ي
            {'name': 'محمد على ابراهيم', 'count': 1},   # ى (current)
        ]
        imp = suggest_name_improvement('محمد على ابراهيم', rows)
        self.assertEqual(imp['type'], 'spelling')
        self.assertEqual(imp['suggestion'], 'محمد علي ابراهيم')

    def test_no_suggestion_when_already_best(self):
        rows = [{'name': 'محمد علي ابراهيم', 'count': 9}]
        self.assertIsNone(suggest_name_improvement('محمد علي ابراهيم', rows))
