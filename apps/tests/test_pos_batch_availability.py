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


class FefoSplitTests(TestCase):
    """POS Speed Wave Task 6: the FEFO split rule is pure + server-side (CLAUDE.md §7). It never
    reserves anything: the shortfall is returned and the cashier reserves it explicitly."""
    def _b(self, *qtys):
        return _parse_rows([(f'2028-0{i+1}-01', q, f'B{i}') for i, q in enumerate(qtys)])

    def test_single_batch_covers(self):
        from apps.pos_orders.batch_availability import fefo_split
        r = fefo_split(self._b(5), 2)
        self.assertEqual([p['qty'] for p in r['picks']], [2.0])
        self.assertEqual(r['picks'][0]['batchno'], 'B0')
        self.assertEqual(r['picks'][0]['expiry'], '2028-01-01')
        self.assertEqual(r['picks'][0]['available'], 5.0)
        self.assertEqual(r['shortfall'], 0)

    def test_spans_batches_earliest_first(self):
        from apps.pos_orders.batch_availability import fefo_split
        r = fefo_split(self._b(2, 1, 3), 4)
        self.assertEqual([p['qty'] for p in r['picks']], [2.0, 1.0, 1.0])
        self.assertEqual([p['batchno'] for p in r['picks']], ['B0', 'B1', 'B2'])
        self.assertEqual(r['shortfall'], 0)

    def test_shortfall(self):
        from apps.pos_orders.batch_availability import fefo_split
        r = fefo_split(self._b(2), 5)
        self.assertEqual([p['qty'] for p in r['picks']], [2.0])
        self.assertEqual(r['shortfall'], 3.0)

    def test_fractional_strips(self):
        # Review Focus 3: strip quantities are 5-dp pack fractions — the split must not drift.
        from apps.pos_orders.batch_availability import fefo_split
        r = fefo_split(self._b(0.33333, 1), 0.66667)
        qtys = [p['qty'] for p in r['picks']]
        self.assertEqual(qtys, [0.33333, 0.33334])
        self.assertEqual(round(sum(qtys), 5), 0.66667)
        self.assertEqual(r['shortfall'], 0)

    def test_skips_empty_batches(self):
        from apps.pos_orders.batch_availability import fefo_split
        r = fefo_split(self._b(0, 2, -1, 3), 4)
        self.assertEqual([p['batchno'] for p in r['picks']], ['B1', 'B3'])
        self.assertEqual([p['qty'] for p in r['picks']], [2.0, 2.0])

    def test_zero_need(self):
        from apps.pos_orders.batch_availability import fefo_split
        self.assertEqual(fefo_split(self._b(2, 3), 0), {'picks': [], 'shortfall': 0})
        self.assertEqual(fefo_split(self._b(2, 3), -1), {'picks': [], 'shortfall': 0})

    def test_fefo_split_endpoint_no_softech(self):
        from unittest import mock
        from .factories import make_user
        _, _, client = make_user('fefo_split_user', role='salesperson')
        batches = [{'expiry': '2028-01-01', 'qty': 2, 'batchno': 'A'},
                   {'expiry': '2028-02-01', 'qty': 3, 'batchno': 'B'}]
        with mock.patch('apps.pos_orders.batch_availability.get_branch_connection',
                        side_effect=AssertionError('no SOFTECH during a split')):
            r = client.post('/api/pos-orders/fefo-split/', {'batches': batches, 'need': 6},
                            format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([p['qty'] for p in r.data['picks']], [2.0, 3.0])
        self.assertEqual(r.data['shortfall'], 1.0)

    def test_fefo_split_endpoint_rejects_bad_input(self):
        from .factories import make_user
        _, _, client = make_user('fefo_split_user2', role='salesperson')
        many = [{'expiry': '2028-01-01', 'qty': 1, 'batchno': str(i)} for i in range(51)]
        r = client.post('/api/pos-orders/fefo-split/', {'batches': many, 'need': 1}, format='json')
        self.assertEqual(r.status_code, 400)
        r = client.post('/api/pos-orders/fefo-split/', {'batches': many[:2], 'need': -1},
                        format='json')
        self.assertEqual(r.status_code, 400)
        for bad in ('abc', 'NaN', 'Infinity', None):
            r = client.post('/api/pos-orders/fefo-split/', {'batches': many[:2], 'need': bad},
                            format='json')
            self.assertEqual(r.status_code, 400, bad)

    def test_fefo_split_endpoint_requires_staff(self):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient
        u = get_user_model().objects.create_user('no_profile_fefo', password='x')
        c = APIClient()
        c.force_authenticate(u)
        r = c.post('/api/pos-orders/fefo-split/', {'batches': [], 'need': 1}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_fefo_split_refuses_role_without_pos_grant(self):
        from .factories import make_user
        _, _, viewer = make_user('fefo_viewer', role='viewer')
        r = viewer.post('/api/pos-orders/fefo-split/', {'batches': [], 'need': 1}, format='json')
        self.assertEqual(r.status_code, 403)
        _, _, seller = make_user('fefo_seller', role='salesperson')
        r = seller.post('/api/pos-orders/fefo-split/', {'batches': [], 'need': 1}, format='json')
        self.assertEqual(r.status_code, 200)

    def _split_status(self, name, role):
        from .factories import make_user
        _, _, c = make_user(name, role=role)
        return c.post('/api/pos-orders/fefo-split/', {'batches': [], 'need': 1}, format='json').status_code

    def test_fefo_split_seeded_explicit_denial_is_final(self):
        from apps.users.models import RoleModuleAccess
        RoleModuleAccess.objects.create(role='salesperson', module='pos', action='view', is_allowed=False)
        self.assertEqual(self._split_status('fefo_denied', 'salesperson'), 403)

    def test_fefo_split_seeded_grant_allows(self):
        from apps.users.models import RoleModuleAccess
        RoleModuleAccess.objects.create(role='salesperson', module='pos', action='view', is_allowed=True)
        self.assertEqual(self._split_status('fefo_granted', 'salesperson'), 200)

    def test_fefo_split_unseeded_push_role_uses_fallback(self):
        self.assertEqual(self._split_status('fefo_unseeded', 'salesperson'), 200)
        self.assertEqual(self._split_status('fefo_unseeded_v', 'viewer'), 403)
