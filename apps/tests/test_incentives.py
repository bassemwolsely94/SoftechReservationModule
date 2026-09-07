"""
apps/tests/test_incentives.py

Unit tests for the incentive engine's pure calculation helpers (doc 12 priority
"start with … incentive engine"). These exercise the core money math in isolation
— slab lookup, tiered/target-based/percent/fixed dispatch — without touching the
SOFTECH (Sybase) ERP, so they run as fast SimpleTestCases with lightweight rule
stubs (the helpers only read attributes).
"""
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.incentives.engine import (
    _find_slab,
    _calc_tiered_incentive,
    _calc_target_based_incentive,
    _calc_incentive,
)


def _rule(**kw):
    base = dict(
        id=1, incentive_value=Decimal('0'), incentive_type='fixed_per_unit',
        slab_config=None, target_qty=None, target_tiers=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


class FindSlabTests(SimpleTestCase):
    SLABS = [
        {'min_qty': 0,  'max_qty': 9,    'rate': 0},
        {'min_qty': 10, 'max_qty': 49,   'rate': 5},
        {'min_qty': 50, 'max_qty': None, 'rate': 10},   # open-ended top slab
    ]

    def test_picks_correct_slab(self):
        self.assertEqual(_find_slab(self.SLABS, Decimal('5'))['rate'], 0)
        self.assertEqual(_find_slab(self.SLABS, Decimal('10'))['rate'], 5)
        self.assertEqual(_find_slab(self.SLABS, Decimal('49'))['rate'], 5)
        self.assertEqual(_find_slab(self.SLABS, Decimal('1000'))['rate'], 10)

    def test_no_match_returns_none(self):
        self.assertIsNone(_find_slab([{'min_qty': 100, 'max_qty': 200, 'rate': 1}], Decimal('5')))


class TieredIncentiveTests(SimpleTestCase):

    def test_percent_slab(self):
        rule = _rule(slab_config={'type': 'percent',
                                  'slabs': [{'min_qty': 10, 'max_qty': None, 'rate': 10}]})
        # period qty 12 ≥ 10 → 10% of 4×100 = 40
        self.assertEqual(
            _calc_tiered_incentive(rule, Decimal('4'), Decimal('100'), Decimal('12')),
            Decimal('40.0000'),
        )

    def test_fixed_per_unit_slab(self):
        rule = _rule(slab_config={'type': 'fixed',
                                  'slabs': [{'min_qty': 10, 'max_qty': None, 'rate': 3}]})
        self.assertEqual(
            _calc_tiered_incentive(rule, Decimal('4'), Decimal('100'), Decimal('12')),
            Decimal('12.0000'),   # 4 × 3
        )

    def test_below_first_slab_is_zero(self):
        rule = _rule(slab_config={'type': 'percent',
                                  'slabs': [{'min_qty': 10, 'max_qty': None, 'rate': 10}]})
        self.assertEqual(
            _calc_tiered_incentive(rule, Decimal('4'), Decimal('100'), Decimal('5')),
            Decimal('0'),
        )


class TargetBasedIncentiveTests(SimpleTestCase):
    TIERS = {'tiers': [
        {'min_pct': 0,   'max_pct': 79,   'rate': 0,  'type': 'fixed_per_unit'},
        {'min_pct': 80,  'max_pct': 99,   'rate': 5,  'type': 'fixed_per_unit'},
        {'min_pct': 100, 'max_pct': None, 'rate': 10, 'type': 'fixed_per_unit'},
    ]}

    def _rule(self):
        return _rule(incentive_type='target_based',
                     target_qty=Decimal('100'), target_tiers=self.TIERS)

    def test_full_achievement_tier(self):
        # 100/100 = 100% → rate 10 → 4 × 10 = 40
        self.assertEqual(
            _calc_target_based_incentive(self._rule(), Decimal('4'), Decimal('50'), Decimal('100')),
            Decimal('40.0000'),
        )

    def test_mid_achievement_tier(self):
        # 85/100 = 85% → rate 5 → 4 × 5 = 20
        self.assertEqual(
            _calc_target_based_incentive(self._rule(), Decimal('4'), Decimal('50'), Decimal('85')),
            Decimal('20.0000'),
        )

    def test_below_threshold_is_zero(self):
        # 50% → rate 0
        self.assertEqual(
            _calc_target_based_incentive(self._rule(), Decimal('4'), Decimal('50'), Decimal('50')),
            Decimal('0'),
        )

    def test_zero_target_is_zero(self):
        rule = _rule(incentive_type='target_based', target_qty=Decimal('0'), target_tiers=self.TIERS)
        self.assertEqual(
            _calc_target_based_incentive(rule, Decimal('4'), Decimal('50'), Decimal('100')),
            Decimal('0'),
        )


class CalcIncentiveDispatchTests(SimpleTestCase):

    def test_percent(self):
        rule = _rule(incentive_type='percent', incentive_value=Decimal('10'))
        self.assertEqual(
            _calc_incentive(rule, Decimal('2'), Decimal('100'), 'IT1', {}, Decimal('2'), 'D1', set()),
            Decimal('20.0000'),   # 2×100×10%
        )

    def test_fixed_per_unit(self):
        rule = _rule(incentive_type='fixed_per_unit', incentive_value=Decimal('3'))
        self.assertEqual(
            _calc_incentive(rule, Decimal('5'), Decimal('100'), 'IT1', {}, Decimal('5'), 'D1', set()),
            Decimal('15.0000'),   # 5×3
        )

    def test_fixed_per_transaction_counts_once_per_doc(self):
        rule = _rule(incentive_type='fixed_per_transaction', incentive_value=Decimal('7'))
        seen = set()
        first  = _calc_incentive(rule, Decimal('1'), Decimal('100'), 'IT1', {}, Decimal('1'), 'DOC1', seen)
        second = _calc_incentive(rule, Decimal('1'), Decimal('100'), 'IT2', {}, Decimal('1'), 'DOC1', seen)
        self.assertEqual(first,  Decimal('7.0000'))
        self.assertEqual(second, Decimal('0'))   # same document → not paid twice

    def test_item_override_wins(self):
        rule = _rule(id=9, incentive_type='fixed_per_unit', incentive_value=Decimal('3'))
        rule_item_map = {(9, 'IT1'): SimpleNamespace(incentive_override=Decimal('10'))}
        self.assertEqual(
            _calc_incentive(rule, Decimal('2'), Decimal('100'), 'IT1', rule_item_map, Decimal('2'), 'D1', set()),
            Decimal('20.0000'),   # 2 × 10 (override), not 2 × 3
        )
