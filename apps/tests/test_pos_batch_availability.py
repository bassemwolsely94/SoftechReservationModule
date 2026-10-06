"""
apps/tests/test_pos_batch_availability.py — batch row parsing + out-of-stock summary.
(The live read needs SOFTECH; here we test the pure helpers.)
"""
from django.test import TestCase

from apps.pos_orders.batch_availability import _parse_rows, summarize, _is_stockable, batch_action


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

    def test_is_stockable_from_itemtrans(self):
        # SOFTECH items.itemtrans: '0' = non-stockable (service) → plain line, NEVER a reservation
        self.assertFalse(_is_stockable('0'))
        self.assertFalse(_is_stockable(' 0 '))         # trimmed
        self.assertTrue(_is_stockable('1'))
        self.assertTrue(_is_stockable('3'))
        self.assertTrue(_is_stockable(None))           # unknown → assume stockable (safe default)


class BatchMatrixTests(TestCase):
    """CASE 1-5 batch matrix — the authoritative POS decision (backend owns the rule)."""
    def _b(self, *qtys):
        return _parse_rows([(f'2028-0{i+1}-01', q, f'B{i}') for i, q in enumerate(qtys)])

    def test_case3_no_batch_stock_reserves(self):
        # No batch rows → reservation, whether or not batch is mandatory.
        self.assertEqual(batch_action([], batch_required=True)['action'], 'reserve')
        self.assertEqual(batch_action(self._b(0), batch_required=False)['action'], 'reserve')

    def test_case2_mandatory_single_batch_auto_selects(self):
        # Owner-confirmed: mandatory-batch item with exactly one available batch → auto-select it.
        v = batch_action(self._b(5), batch_required=True)
        self.assertEqual(v['action'], 'auto_select')
        self.assertEqual(v['batch']['qty'], 5.0)
        self.assertEqual(v['batch']['batchno'], 'B0')

    def test_case1_mandatory_multiple_batches_must_select(self):
        v = batch_action(self._b(2, 3), batch_required=True)
        self.assertEqual(v['action'], 'must_select')
        self.assertIsNone(v['batch'])

    def test_case4_5_optional_when_not_required(self):
        # Not mandatory + stock exists → optional FEFO helper (single OR multiple batches).
        self.assertEqual(batch_action(self._b(5), batch_required=False)['action'], 'optional')
        self.assertEqual(batch_action(self._b(2, 3), batch_required=False)['action'], 'optional')

    def test_non_stockable_is_plain(self):
        # Service/fee item: plain line even if it looks batch-required — never reserve/select.
        v = batch_action(self._b(5), batch_required=True, stockable=False)
        self.assertEqual(v['action'], 'plain')
