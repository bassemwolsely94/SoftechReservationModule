"""Top-10 C05 / P-27 part B (owner 2026-11-19: «inside التوزيعة»): the dead-stock «move» lane is
wave 5 of the one distribution plan — only with SystemSetting dead_stock_in_distribution (default
False). Wave 0, the 100 EGP line threshold and the route documents apply as to every wave; an item
already moving to the same destination appears once. SOFTECH is never touched (pure plan_moves +
a patched build)."""
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from apps.purchasing import distribution_plan as DP
from apps.tests.factories import make_hq

NO_HOLD = lambda key: (None, '')
TH0 = {'min_line': 0, 'min_doc': 0}


def _sug(code, cat, src, targets, qty=2, age=100):
    return {'itemcode': code, 'item_name': code, 'category': cat, 'from_branch': src, 'qty_each': qty,
            'to_branches': [{'code': t, 'qty': qty} for t in targets], 'signals': [], 'reason': '',
            'from_position': {}, 'age_days': age}


def _plan(sugs, costs, *, flows=None, th=TH0):
    return DP.plan_moves(sugs, costs=costs, hq_stock={}, ceilings={}, flows=flows or {}, th=th, holder=NO_HOLD)


def _by(moves):
    return {(m['itemcode'], m['from_code'], m['to_code']): m for m in moves}


class LaneTests(TestCase):
    def setUp(self):
        make_hq('100', self)

    def test_dead_move_is_wave_5_and_planned(self):
        moves, docs = _plan([_sug('D', DP.DEAD_CAT, '130', ['160'], qty=4)], {'D': 100})
        m = _by(moves)[('D', '130', '160')]
        self.assertEqual((m['wave'], m['status'], m['value']), (5, 'planned', 400.0))
        self.assertTrue(docs)                                      # it lands in the route documents

    def test_same_destination_appears_once_with_the_tag(self):
        moves, _ = _plan([_sug('X', 'over_piled', '140', ['160']), _sug('X', DP.DEAD_CAT, '130', ['160'])],
                         {'X': 100})
        self.assertEqual([(m['from_code'], m['wave']) for m in moves if m['itemcode'] == 'X'], [('140', 2)])
        self.assertIn(DP.DEAD_CAT, moves[0]['reasons'])

    def test_a_source_already_drawn_is_not_drawn_twice(self):
        moves, _ = _plan([_sug('Y', 'over_piled', '130', ['150']), _sug('Y', DP.DEAD_CAT, '130', ['170'])],
                         {'Y': 100})
        self.assertEqual({(m['from_code'], m['to_code']) for m in moves}, {('130', '150')})

    def test_wave_0_cuts_what_is_already_coming(self):
        flows = {('Z', '160'): [{'source': 'transfer', 'label': 'تحويل TR-1', 'ref': 1, 'qty': 3}]}
        moves, _ = _plan([_sug('Z', DP.DEAD_CAT, '130', ['160'], qty=5)], {'Z': 100}, flows=flows)
        m = moves[0]
        self.assertEqual((m['status'], m['qty']), ('planned', 2))
        moves, _ = _plan([_sug('Z', DP.DEAD_CAT, '130', ['160'], qty=3)], {'Z': 100}, flows=flows)
        self.assertEqual(moves[0]['status'], 'conflict')

    def test_the_100_egp_line_threshold_applies(self):
        moves, _ = _plan([_sug('S', DP.DEAD_CAT, '130', ['160'], qty=1)], {'S': 50},
                         th={'min_line': 100.0, 'min_doc': 0})
        self.assertEqual(moves[0]['status'], 'below_line')


class SnapshotTests(TestCase):
    def setUp(self):
        make_hq('100', self)
        from apps.catalog.models import Item
        from apps.purchasing.models import DeadStockLine, DeadStockSnapshot, DemandCalculationRun
        self.run = DemandCalculationRun.objects.create(status='success')
        snap = DeadStockSnapshot.objects.create(run=self.run, as_of='2026-11-19')
        for code in ('M1', 'M2', 'M3', 'M4', 'M5', 'R1'):
            Item.objects.create(softech_id=code, name=f'صنف {code}', cost_price=Decimal('10'))

        def line(code, branch='130', lane='move', targets=None, flags=None):
            DeadStockLine.objects.create(snapshot=snap, item=Item.objects.get(softech_id=code), branch_code=branch,
                                         lane=lane, location='branches_only', qty=Decimal('5'), value=Decimal('50'),
                                         targets=[{'branch': '160', 'qty': 3}] if targets is None else targets,
                                         move_value=Decimal('300'), flags=flags or {})
        line('M1')
        line('M2', flags={'fridge': True})
        line('M3', flags={'below_threshold': True})
        line('M4', targets=[])
        line('M5', branch='100')                      # HQ-sourced: not this lane
        line('R1', lane='return')

    def test_only_movable_branch_lines_become_suggestions(self):
        s = DP.dead_stock_suggestions(self.run)
        self.assertEqual([(x['itemcode'], x['from_branch'], x['to_branches'], x['category']) for x in s],
                         [('M1', '130', [{'code': '160', 'qty': 3}], DP.DEAD_CAT)])

    def _build(self):
        with mock.patch('apps.purchasing.distribution.analyze', return_value=[]), \
                mock.patch('apps.purchasing.distribution._operational_branches', return_value=['130', '160']), \
                mock.patch.object(DP, 'committed_flows', return_value=({}, [])):
            return DP.build(live=False, run=self.run)

    def test_a_text_false_does_not_switch_it_on(self):
        from apps.config.models import SystemSetting
        SystemSetting.objects.update_or_create(key='dead_stock_in_distribution', defaults={
            'label': 'x', 'value': 'false', 'value_type': 'string'})
        self.assertFalse(DP.dead_stock_on())

    def test_switch_off_by_default_keeps_the_lane_out(self):
        plan = self._build()
        self.assertFalse(plan.inputs['dead_stock_lane'])
        self.assertFalse(plan.moves.filter(wave=5).exists())

    def test_switch_on_adds_wave_5(self):
        from apps.config.models import SystemSetting
        SystemSetting.objects.update_or_create(key='dead_stock_in_distribution', defaults={
            'label': 'dead stock in distribution', 'value': 'true', 'value_type': 'boolean'})
        plan = self._build()
        self.assertTrue(plan.inputs['dead_stock_lane'])
        self.assertEqual(list(plan.moves.filter(wave=5).values_list('itemcode', 'from_code', 'to_code', 'qty')),
                         [('M1', '130', '160', 3)])
