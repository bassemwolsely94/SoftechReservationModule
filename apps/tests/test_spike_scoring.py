"""
Unit tests for apps.purchasing.spike — the demand-spike (over-purchase) scorer.
Validated on real data 2026-09-15: Awadist 130001 ≈ 80×, Jutoxib 130892 ≈ 41×.
Pure functions, no DB.
"""
from django.test import SimpleTestCase
from apps.purchasing.spike import classify_spike, capped_gap


class ClassifySpikeTests(SimpleTestCase):
    def test_awadist_strong(self):
        # q90=53, q365=55 → recent 17.7/mo, prior 0.22/mo → ~80× STRONG
        r = classify_spike(51, 53, 55)
        self.assertEqual(r['tier'], 'strong')
        self.assertAlmostEqual(r['recent'], 17.667, places=2)
        self.assertGreater(r['ratio'], 50)

    def test_jutoxib_strong(self):
        r = classify_spike(34, 88, 95)          # recent 29.3, prior 0.78 → ~37×
        self.assertEqual(r['tier'], 'strong')
        self.assertGreater(r['ratio'], 30)

    def test_new_burst_no_history_is_strong(self):
        # all annual demand in the last quarter → prior≈0 → new burst → STRONG
        r = classify_spike(20, 60, 60)
        self.assertEqual(r['tier'], 'strong')
        self.assertEqual(r['ratio'], 999.0)
        self.assertAlmostEqual(r['prior'], 0.0, places=3)

    def test_watch_band(self):
        r = classify_spike(8, 24, 33)           # recent 8, prior 1 → 8× → WATCH
        self.assertEqual(r['tier'], 'watch')
        self.assertAlmostEqual(r['ratio'], 8.0, places=1)

    def test_below_watch_not_flagged(self):
        r = classify_spike(5, 15, 28.5)         # recent 5, prior 1.5 → 3.3× → ''
        self.assertEqual(r['tier'], '')

    def test_below_min_recent_not_flagged(self):
        r = classify_spike(3, 9, 9)             # recent 3 < 5 → never flagged
        self.assertEqual(r['tier'], '')

    def test_exact_thresholds(self):
        self.assertEqual(classify_spike(10, 30, 39)['tier'], 'strong')  # ratio 10 → strong
        self.assertEqual(classify_spike(6, 18, 27)['tier'], 'watch')    # ratio 6 → watch


class CappedGapTests(SimpleTestCase):
    def test_dormant_by_default(self):
        self.assertEqual(capped_gap(100, 44, apply=False), 100)

    def test_caps_to_one_month_recent(self):
        self.assertEqual(capped_gap(100, 44, apply=True), 44)          # min(100, 44×1)

    def test_no_change_when_gap_below_cap(self):
        self.assertEqual(capped_gap(20, 44, apply=True), 20)

    def test_noop_on_nonpositive_gap(self):
        self.assertEqual(capped_gap(-5, 44, apply=True), -5)
        self.assertEqual(capped_gap(0, 44, apply=True), 0)

    def test_cap_months_override(self):
        self.assertEqual(capped_gap(100, 44, apply=True, cap_months=2), 88)
