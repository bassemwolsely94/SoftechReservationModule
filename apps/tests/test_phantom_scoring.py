"""
Unit tests for apps.purchasing.phantom.score_item — the pure phantom-substitution
scorer (no DB / SOFTECH). Mirrors the values validated on real data 2026-09-14:
DAIVOBET/EPREX flag (>=50%); CH-ALPHA/CONTROLOC do not (<50%).
"""
from django.test import SimpleTestCase
from apps.purchasing import phantom
from apps.purchasing.phantom import score_item, reduced_order_qty


class PhantomScoreTests(SimpleTestCase):
    def test_high_phantom_flags_strong_and_low_order_pct(self):
        # DAIVOBET OINT 30GM: sold 218, buyback 205 → ~94% phantom
        r = score_item(sold_flag=218, contract_flag=218, sold_recent=50,
                       buyback_flag=205, buyback_recent=48)
        self.assertTrue(r['is_phantom'])
        self.assertEqual(r['tier'], 'strong')
        self.assertAlmostEqual(r['phantom_ratio'], 0.9404, places=3)
        self.assertLess(r['order_pct'], 0.10)                 # order ~5%
        self.assertEqual(r['genuine_need'], 13.0)             # 218 - 205
        self.assertAlmostEqual(r['contract_ratio'], 1.0, places=3)

    def test_watch_tier_high_volume_below_strong_threshold(self):
        # CH-ALPHA: sold 2232, buyback 950 → 43% (< 50%) BUT bb >> 100 units
        # → WATCH (monitored), not strong. Absolute phantom volume is large.
        r = score_item(2232, 2165, 500, 950, 200)
        self.assertEqual(r['tier'], 'watch')
        self.assertTrue(r['is_phantom'])
        self.assertAlmostEqual(r['phantom_ratio'], 0.4256, places=3)

    def test_low_ratio_low_volume_not_flagged(self):
        # 35% ratio but only 40 buyback units (< WATCH_MIN_BUYBACK=100) → not flagged
        r = score_item(sold_flag=200, contract_flag=100, sold_recent=50,
                       buyback_flag=70, buyback_recent=18)
        self.assertEqual(r['tier'], '')
        self.assertFalse(r['is_phantom'])

    def test_volume_floor_blocks_flag(self):
        # ratio 0.9 but only 10 sold (< MIN_SOLD=12) → not flagged
        r = score_item(10, 10, 5, 9, 4)
        self.assertGreaterEqual(r['phantom_ratio'], 0.5)
        self.assertFalse(r['is_phantom'])

    def test_buyback_floor_blocks_flag(self):
        # ratio high but buyback below MIN_BUYBACK=6 → not flagged
        r = score_item(sold_flag=14, contract_flag=14, sold_recent=6,
                       buyback_flag=5, buyback_recent=2)
        self.assertFalse(r['is_phantom'])

    def test_auto_heal_restores_order_pct_when_recent_ratio_drops(self):
        # 12-mo ratio still 90% (flag stays) but recent buy-backs stopped
        # (item back at distributors) → order_pct recovers via recency weight.
        r = score_item(sold_flag=100, contract_flag=90, sold_recent=40,
                       buyback_flag=90, buyback_recent=4)
        self.assertTrue(r['is_phantom'])                      # flag on 12-mo view
        self.assertGreater(r['order_pct'], 0.5)              # ordering restored

    def test_buyback_exceeds_sold_clamps(self):
        r = score_item(20, 20, 0, 30, 0)                      # ratio 1.5, no recent
        self.assertTrue(r['is_phantom'])
        self.assertEqual(r['order_pct'], 0.0)                 # clamped, order nothing
        self.assertEqual(r['genuine_need'], 0.0)             # max(0, 20-30)

    def test_no_sales_is_neutral(self):
        r = score_item(0, 0, 0, 0, 0)
        self.assertFalse(r['is_phantom'])
        self.assertEqual(r['order_pct'], 1.0)                 # nothing to suppress
        self.assertEqual(r['phantom_ratio'], 0.0)

    def test_recent_ratio_ignored_when_recent_volume_tiny(self):
        # sold_recent 2 (< MIN_RECENT_SOLD=3) → fall back to flag ratio for order_pct
        r = score_item(sold_flag=100, contract_flag=80, sold_recent=2,
                       buyback_flag=80, buyback_recent=2)
        self.assertTrue(r['is_phantom'])
        self.assertAlmostEqual(r['order_pct'], 0.20, places=2)  # 1 - 0.80 (flag ratio)

    # ── reduced_order_qty — DORMANT reduction logic (built, off by default) ──
    def test_reduction_dormant_by_default(self):
        self.assertEqual(reduced_order_qty(100, 0.1, apply=False), 100)   # no change

    def test_reduction_scales_by_order_pct_when_activated(self):
        self.assertAlmostEqual(reduced_order_qty(100, 0.06, apply=True, monthly_avg=0), 6.0)

    def test_reduction_keeps_one_week_safety_floor(self):
        # order 0% but monthly_avg 40 → weekly genuine 10 → never below 10
        self.assertAlmostEqual(reduced_order_qty(100, 0.0, apply=True, monthly_avg=40), 10.0)

    def test_reduction_noop_when_order_pct_full(self):
        self.assertEqual(reduced_order_qty(100, 1.0, apply=True, monthly_avg=40), 100)

    def test_reduction_noop_on_zero_required(self):
        self.assertEqual(reduced_order_qty(0, 0.1, apply=True), 0)
