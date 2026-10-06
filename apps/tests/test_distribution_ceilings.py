"""
L3 «توزيعة» over_piled on SOFTECH ceilings (apps/purchasing/distribution.py).
Pure logic only — ceilings are passed in, no SOFTECH connection.
ceilings = {branch: {itemcode: (stock, ceiling)}}
"""
from django.test import SimpleTestCase

from apps.purchasing import distribution as d

OPS = {'100', '130', '140', '150', '160', '170'}


class PickSurplusTests(SimpleTestCase):
    def test_picks_branch_with_most_stock_above_its_ceiling(self):
        c = {'140': {'X': (20.0, 2.6)},      # 17.4 over
             '150': {'X': (10.0, 4.0)}}      # 6 over
        self.assertEqual(d._pick_surplus('X', c, OPS), ('140', 17.4))

    def test_at_or_just_above_ceiling_is_not_over_piled(self):
        c = {'140': {'X': (2.6, 2.6)}, '150': {'X': (4.03, 4.0)}}   # within 1dp tolerance
        self.assertEqual(d._pick_surplus('X', c, OPS), (None, 0.0))

    def test_hq_is_never_over_piled(self):
        c = {'100': {'X': (500.0, 1.0)}}
        self.assertEqual(d._pick_surplus('X', c, OPS), (None, 0.0))

    def test_branch_without_ceiling_is_ignored(self):
        # no ceiling = item doesn't sell there → that's no-sales stock, not over-piled
        self.assertEqual(d._pick_surplus('X', {'140': {}}, OPS), (None, 0.0))


class RoomTargetsTests(SimpleTestCase):
    def test_only_selling_branches_with_a_pack_of_room(self):
        c = {'130': {'X': (0.0, 5.0)},       # room 5
             '150': {'X': (4.5, 5.0)},       # room 0.5 → less than a pack
             '160': {'X': (9.0, 5.0)},       # already above
             '140': {'X': (20.0, 2.6)}}      # the source
        self.assertEqual(d._room_targets('X', c, OPS, source='140'), {'130': 5.0})

    def test_hq_is_never_a_target(self):
        c = {'100': {'X': (0.0, 50.0)}, '130': {'X': (1.0, 3.0)}}
        self.assertEqual(d._room_targets('X', c, OPS, source='140'), {'130': 2.0})


class AllocateTests(SimpleTestCase):
    def test_fills_roomiest_targets_up_to_excess(self):
        # 17.4 excess; rooms 10, 6, 4 → 10 + 6 + 1
        self.assertEqual(d._allocate(17.4, ['a', 'b', 'c'], {'a': 10, 'b': 6, 'c': 4}),
                         [('a', 10), ('b', 6), ('c', 1)])

    def test_never_more_than_room(self):
        self.assertEqual(d._allocate(50, ['a'], {'a': 3.7}), [('a', 3)])

    def test_whole_packs_only(self):
        # 0.6 excess (e.g. part of a pen) → nothing to move
        self.assertEqual(d._allocate(0.6, ['a'], {'a': 5}), [])


class SuggestionShapeTests(SimpleTestCase):
    def test_per_target_qty_and_total(self):
        s = d._sug('over_piled', 'X', 'Item', '140', ['130', '150'], 10, {}, 20, 3, 'r',
                   per_qty={'130': 10, '150': 6})
        self.assertEqual([t['qty'] for t in s['to_branches']], [10, 6])
        self.assertEqual(s['total_qty'], 16)

    def test_seeding_keeps_uniform_qty(self):
        s = d._sug('new_no_rate', 'X', 'Item', '100', ['130', '150'], 2, {}, 5, 0, 'r')
        self.assertEqual([t['qty'] for t in s['to_branches']], [2, 2])
        self.assertEqual(s['total_qty'], 4)
