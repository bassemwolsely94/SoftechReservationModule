"""Tests for the PIC Analytics definition rules (doc 33 §4). Pure functions, no DB."""
from datetime import date

from django.test import SimpleTestCase

from apps.pic_analytics import rules

D = date


class PicRulesTests(SimpleTestCase):
    def test_months_bought_counts_distinct_months(self):
        v = [D(2026, 1, 5), D(2026, 1, 20), D(2026, 2, 1), D(2026, 6, 9), D(2026, 10, 28)]
        self.assertEqual(rules.months_bought(v, D(2026, 10, 31)), 4)

    def test_months_window_is_12_months(self):
        self.assertEqual(
            rules.months_bought([D(2025, 10, 30), D(2026, 10, 1)], D(2026, 10, 31)), 1
        )

    def test_longest_streak(self):
        v = [D(2026, 1, 1), D(2026, 2, 1), D(2026, 3, 1), D(2026, 6, 1), D(2026, 8, 1)]
        self.assertEqual(rules.longest_streak(v, D(2026, 10, 31)), 3)

    def test_cycle_and_bucket(self):
        self.assertEqual(rules.cycle_days([D(2026, 1, 1), D(2026, 2, 15), D(2026, 3, 1)]), 29.5)
        self.assertEqual(rules.cycle_bucket(29.5), 'm1')
        self.assertEqual(rules.cycle_bucket(45), 'm2')
        self.assertEqual(rules.cycle_bucket(400), 'y1plus')
        self.assertEqual(rules.cycle_bucket(None), '')

    def test_same_day_visits_are_one(self):
        self.assertIsNone(rules.cycle_days([D(2026, 1, 1), D(2026, 1, 1)]))

    def test_overdue(self):
        self.assertTrue(rules.is_overdue(D(2026, 8, 1), 30, D(2026, 10, 1), 1.5))
        self.assertFalse(rules.is_overdue(D(2026, 9, 10), 30, D(2026, 10, 1), 1.5))

    def test_new_needs_recent_creation(self):
        args = dict(
            period_start=D(2026, 10, 1),
            period_end=D(2026, 10, 31),
            first_visit_in_period=D(2026, 10, 5),
            prev_visit=None,
        )
        self.assertEqual(
            rules.classify_pic(first_purchase=D(2026, 10, 5), created_at=D(2026, 10, 5), **args),
            'new',
        )
        self.assertEqual(
            rules.classify_pic(first_purchase=D(2026, 10, 5), created_at=D(2019, 1, 1), **args),
            'returning',
        )
        self.assertEqual(
            rules.classify_pic(first_purchase=D(2026, 10, 5), created_at=D(2026, 9, 2), **args),
            'new',  # within 30 d
        )

    def test_unknown_creation_falls_back_to_first_purchase(self):
        self.assertEqual(
            rules.classify_pic(D(2026, 10, 5), None, None, D(2026, 10, 1), D(2026, 10, 31), D(2026, 10, 5)),
            'new',
        )

    def test_reactivated_after_365_days(self):
        self.assertEqual(
            rules.classify_pic(
                D(2024, 9, 1), D(2024, 9, 1), D(2025, 9, 30), D(2026, 10, 1), D(2026, 10, 31), D(2026, 10, 1)
            ),
            'reactivated',
        )
        self.assertEqual(
            rules.classify_pic(
                D(2024, 9, 1), D(2024, 9, 1), D(2025, 10, 2), D(2026, 10, 1), D(2026, 10, 31), D(2026, 10, 1)
            ),
            'returning',
        )

    def test_returned_only_purchase_still_new(self):
        # Review Focus 2 — visit days come from sale dates, returns ignored
        self.assertEqual(
            rules.classify_pic(D(2026, 10, 5), D(2026, 10, 5), None, D(2026, 10, 1), D(2026, 10, 31), D(2026, 10, 5)),
            'new',
        )

    def test_retention(self):
        self.assertEqual(rules.retention({'a', 'b', 'c', 'd'}, {'a', 'b', 'x'}), 0.5)
        self.assertIsNone(rules.retention(set(), {'a'}))
