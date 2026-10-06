"""
Fast, DB-free unit tests for the purchasing demand-fill export helpers
(apps/purchasing/views.py): scale_demand_gap (Option B — 80% of the 1-month
order, safety floor kept) + round_pack + the total-vs-branch rounding contract.
"""
import unittest

from apps.purchasing.views import scale_demand_gap, round_pack


class ScaleDemandGapTests(unittest.TestCase):
    def test_none_returns_frozen_unchanged(self):
        # No override → the frozen 1-month gap is returned verbatim (the revert).
        self.assertEqual(scale_demand_gap(40.0, 10.0, None), 40.0)
        self.assertEqual(scale_demand_gap(-3.0, 99.0, None), -3.0)

    def test_cov_1_is_exact_identity(self):
        # coverage 1.0 reproduces the frozen gap exactly (target = gap + stock).
        for gap, stock in [(40, 10), (2, 0), (-5, 20), (0, 7), (123.45, 6.7)]:
            self.assertAlmostEqual(scale_demand_gap(gap, stock, 1.0), gap, places=9)

    def test_cov_0_8_fast_mover(self):
        # gap 40 @ stock 10 → target 50 → 0.8×50 − 10 = 30
        self.assertAlmostEqual(scale_demand_gap(40.0, 10.0, 0.8), 30.0, places=9)

    def test_cov_0_8_slow_mover_keeps_floor(self):
        # slow item: 1-month target = 2 (floor), stock 0 → 0.8×2 − 0 = 1.6 (not 0)
        self.assertAlmostEqual(scale_demand_gap(2.0, 0.0, 0.8), 1.6, places=9)

    def test_cov_above_one_scales_up(self):
        # gap 40 @ stock 10 → target 50 → 1.2×50 − 10 = 50
        self.assertAlmostEqual(scale_demand_gap(40.0, 10.0, 1.2), 50.0, places=9)

    def test_overstock_signal_preserved_negative(self):
        # target 15 @ stock 20 → 0.8×15 − 20 = -8 (still surplus)
        self.assertAlmostEqual(scale_demand_gap(-5.0, 20.0, 0.8), -8.0, places=9)


class RegimeSwitchTests(unittest.TestCase):
    """coverage>1 with floor+rate = keep-floor-scale-throughput (no slow-mover
    inflation); <1 always scales the whole target; =1 exact; >1 without floor/rate
    falls back to proportional scaling."""

    def test_identity_at_one_even_with_floor(self):
        self.assertAlmostEqual(
            scale_demand_gap(40.0, 10.0, 1.0, safety_stock=50.0, monthly_avg=50.0), 40.0, places=9)

    def test_above_one_fast_mover_keep_floor(self):
        # target = max(50, 50×1.5=75) − 10 = 65
        self.assertAlmostEqual(
            scale_demand_gap(40.0, 10.0, 1.5, safety_stock=50.0, monthly_avg=50.0), 65.0, places=9)

    def test_above_one_slow_mover_not_inflated(self):
        # floor 2 dominates 0.5×1.5=0.75 → stays 2 (NOT 3 that whole-scaling would give)
        self.assertAlmostEqual(
            scale_demand_gap(2.0, 0.0, 1.5, safety_stock=2.0, monthly_avg=0.5), 2.0, places=9)

    def test_below_one_ignores_floor_scales_whole(self):
        # even with floor known, <1 scales the whole target so the cut bites
        self.assertAlmostEqual(
            scale_demand_gap(2.0, 0.0, 0.8, safety_stock=2.0, monthly_avg=0.5), 1.6, places=9)

    def test_above_one_without_floor_falls_back_to_whole_scale(self):
        # aggregated network row (no floor/rate) → proportional: 1.5×2 = 3
        self.assertAlmostEqual(scale_demand_gap(2.0, 0.0, 1.5), 3.0, places=9)


class RoundPackTests(unittest.TestCase):
    def test_none_is_passthrough(self):
        self.assertEqual(round_pack(1.6, 'none'), 1.6)
        self.assertIsNone(round_pack(None, 'nearest'))

    def test_nearest_half_up(self):
        self.assertEqual(round_pack(1.6, 'nearest'), 2.0)
        self.assertEqual(round_pack(1.4, 'nearest'), 1.0)
        self.assertEqual(round_pack(2.5, 'nearest'), 3.0)     # half-up
        self.assertEqual(round_pack(-2.4, 'nearest'), -2.0)
        self.assertEqual(round_pack(-2.5, 'nearest'), -3.0)   # half-up away from zero

    def test_up_rounds_away_from_zero(self):
        self.assertEqual(round_pack(1.1, 'up'), 2.0)
        self.assertEqual(round_pack(2.0, 'up'), 2.0)
        self.assertEqual(round_pack(-1.1, 'up'), -2.0)


class TotalVsBranchRoundingTests(unittest.TestCase):
    """The documented contract: round-once-on-total ≤ sum-of-per-branch-rounded,
    because per-branch round-ups stack (over-buy)."""
    GAPS = [16.61, 8.0, -17.75, 5.53, 3.45, -2.39]

    def test_total_mode_rounds_once(self):
        total = round_pack(sum(self.GAPS), 'nearest')      # round(13.45) = 13
        self.assertEqual(total, 13.0)

    def test_branch_mode_sums_rounded(self):
        branch = sum(round_pack(g, 'nearest') for g in self.GAPS)  # 17+8-18+6+3-2 = 14
        self.assertEqual(branch, 14.0)

    def test_branch_not_below_total(self):
        total  = round_pack(sum(self.GAPS), 'nearest')
        branch = sum(round_pack(g, 'nearest') for g in self.GAPS)
        self.assertGreaterEqual(branch, total)


if __name__ == '__main__':
    unittest.main()
