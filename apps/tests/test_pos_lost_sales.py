"""
apps/tests/test_pos_lost_sales.py — POS-AUDIT lost-sales shaping (Wave 3).

Pure test of shape_lost_sales (no SOFTECH contact): raw pos_cancel aggregates → API dict,
with name resolution + value-at-risk. The live read needs Sybase and is exercised in the app.
"""
from django.test import TestCase
from apps.pos_orders.pos_cancel_read import shape_lost_sales


class LostSalesShapeTests(TestCase):
    def test_shapes_totals_items_and_cashiers(self):
        totals = (120, 40, '5123.50')          # events, priced_events, lost_value
        item_rows = [
            ('3476', 'PENTASA 500MG', 12, 5, '2200.00'),
            ('96690', 'ASPIRIN', 8, 2, '150.00'),
        ]
        cashier_rows = [('1752', 30, 10, '3000.00'), ('1776', 25, 8, '2123.50')]
        out = shape_lost_sales(
            totals, item_rows, cashier_rows,
            item_names={'3476': 'PENTASA 500MG SLOW DELAYED 100TAB'},   # fuller catalog name wins
            cashier_names={'1752': 'BASSEM'},
        )
        self.assertEqual(out['summary']['events'], 120)
        self.assertEqual(out['summary']['priced_events'], 40)
        self.assertEqual(out['summary']['lost_value'], 5123.50)
        self.assertEqual(out['summary']['distinct_cashiers'], 2)   # derived from cashier rows
        # catalog name overrides the truncated mitemname
        self.assertEqual(out['top_items'][0]['name'], 'PENTASA 500MG SLOW DELAYED 100TAB')
        self.assertEqual(out['top_items'][0]['lost_value'], 2200.0)
        self.assertEqual(out['top_items'][0]['priced_events'], 5)
        # mitemname fallback when no catalog match
        self.assertEqual(out['top_items'][1]['name'], 'ASPIRIN')
        # cashier name resolved where known, else usercode
        self.assertEqual(out['by_cashier'][0]['name'], 'BASSEM')
        self.assertEqual(out['by_cashier'][1]['name'], '1776')

    def test_handles_empty_and_nulls(self):
        out = shape_lost_sales(None, [], [])
        self.assertEqual(out['summary']['events'], 0)
        self.assertEqual(out['summary']['lost_value'], 0.0)
        self.assertEqual(out['top_items'], [])
        self.assertEqual(out['by_cashier'], [])

    def test_null_sum_becomes_zero(self):
        # ASE SUM over no rows returns NULL — must not blow up
        out = shape_lost_sales((0, 0, None), [('x', None, 1, 0, None)], [])
        self.assertEqual(out['summary']['lost_value'], 0.0)
        self.assertEqual(out['top_items'][0]['name'], 'x')      # no name, no mitemname → code
        self.assertEqual(out['top_items'][0]['lost_value'], 0.0)
