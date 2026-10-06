"""
apps/tests/test_pos_quantity.py — SOFTECH-exact partial-pack (strip/units) quantity.

Locks the rule transqty = round(strips / packqty, 5) (round-half-up) and its inverse
loose_units = round(frac(transqty) × packqty). The golden values are REAL rows read from
production stktrans (branch 150), packqty 2/3/7 — see memory pos_strip_units_qty. This is the
server-side mirror of the frontend stripsToQty in usePosOrder.js; the two MUST stay identical.
"""
from decimal import Decimal

from django.test import SimpleTestCase

from apps.pos_orders.writer import strips_to_qty, loose_units_from_qty


class StripsToQtyTests(SimpleTestCase):
    # (strips K, packqty N) -> exact transqty string as stored in real stktrans
    GOLDEN = {
        (1, 3): '0.33333', (2, 3): '0.66667', (3, 3): '1.00000',
        (4, 3): '1.33333', (5, 3): '1.66667', (6, 3): '2.00000', (7, 3): '2.33333',
        (1, 7): '0.14286', (2, 7): '0.28571', (3, 7): '0.42857', (4, 7): '0.57143',
        (5, 7): '0.71429', (11, 7): '1.57143', (20, 7): '2.85714',
        (1, 2): '0.50000', (3, 2): '1.50000',
    }

    def test_matches_real_stktrans(self):
        for (k, n), expected in self.GOLDEN.items():
            self.assertEqual(str(strips_to_qty(k, n)), expected, msg=f'{k} strips / pack {n}')

    def test_two_thirds_rounds_up_not_truncated(self):
        # the case that proved the rule: 2/3 = 0.666666… must be 0.66667, NOT 0.66666
        self.assertEqual(str(strips_to_qty(2, 3)), '0.66667')
        self.assertEqual(str(strips_to_qty(5, 3)), '1.66667')

    def test_whole_unit_item_is_pass_through(self):
        # packqty <= 1 → strips are whole packs (no fraction)
        self.assertEqual(strips_to_qty(5, 1), Decimal(5))
        self.assertEqual(strips_to_qty(3, 0), Decimal(3))   # packqty 0 treated as 1

    def test_full_and_multi_packs_are_clean_integers(self):
        self.assertEqual(str(strips_to_qty(3, 3)), '1.00000')
        self.assertEqual(str(strips_to_qty(14, 7)), '2.00000')

    def test_zero_strips(self):
        self.assertEqual(strips_to_qty(0, 3), Decimal('0.00000'))


class LooseUnitsRoundTripTests(SimpleTestCase):
    """The frontend qty must reverse cleanly through the writer's pharmacydiscp decomposition,
    so SOFTECH's 'Items Quantities as Pkg+Unit' recovers the exact loose-strip count."""

    def test_loose_units_recovers_remainder(self):
        for (k, n) in [(1, 3), (2, 3), (4, 3), (5, 3), (7, 3),
                       (1, 7), (3, 7), (5, 7), (11, 7), (20, 7), (1, 2), (3, 2)]:
            q = strips_to_qty(k, n)
            self.assertEqual(loose_units_from_qty(q, n), k % n, msg=f'{k} strips / pack {n} → {q}')

    def test_real_stktrans_loose_column(self):
        # exact (transqty, packqty) -> pharmacydiscp rows observed in production
        for qty, n, expected_loose in [('0.33333', 3, 1), ('0.66667', 3, 2),
                                       ('0.14286', 7, 1), ('0.28571', 7, 2),
                                       ('0.42857', 7, 3), ('0.57143', 7, 4),
                                       ('0.71429', 7, 5), ('0.50000', 2, 1)]:
            self.assertEqual(loose_units_from_qty(Decimal(qty), n), expected_loose,
                             msg=f'{qty} × {n}')

    def test_whole_pack_has_no_loose_units(self):
        self.assertEqual(loose_units_from_qty(Decimal('1.00000'), 3), 0)
        self.assertEqual(loose_units_from_qty(Decimal('2.00000'), 7), 0)
