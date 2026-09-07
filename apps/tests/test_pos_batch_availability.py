"""
apps/tests/test_pos_batch_availability.py — batch row parsing + out-of-stock summary.
(The live read needs SOFTECH; here we test the pure helpers.)
"""
from django.test import TestCase

from apps.pos_orders.batch_availability import _parse_rows, summarize


class BatchAvailabilityTests(TestCase):
    def test_parse_orders_by_expiry_and_shapes(self):
        rows = [
            ('2028-02-01 22:00:00', 2.0, ' B1 '),
            ('2028-10-09 21:00:00', 1.0, None),
            ('2029-03-02 22:00:00', 3.0, ''),
        ]
        out = _parse_rows(rows)
        self.assertEqual([b['expiry'] for b in out], ['2028-02-01', '2028-10-09', '2029-03-02'])
        self.assertEqual([b['qty'] for b in out], [2.0, 1.0, 3.0])
        self.assertEqual(out[0]['batchno'], 'B1')      # trimmed
        self.assertEqual(out[1]['batchno'], '')        # None → ''

    def test_summary_in_stock(self):
        batches = _parse_rows([('2028-02-01', 2.0, ''), ('2029-03-02', 3.0, '')])
        s = summarize(batches)
        self.assertEqual(s['total'], 5.0)
        self.assertEqual(s['count'], 2)
        self.assertFalse(s['out_of_stock'])

    def test_summary_out_of_stock_triggers_reservation(self):
        s = summarize([])
        self.assertEqual(s['total'], 0)
        self.assertTrue(s['out_of_stock'])             # ⇒ reservation pathway
