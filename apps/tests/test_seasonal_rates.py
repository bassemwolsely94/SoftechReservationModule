"""
Seasonality → pushed sales rates (owner decision 2026-11-10).

Steady-season items only, a day-weighted index over the next 30 days, capped ×0.7–×1.5,
behind an on/off switch on the rate-push screen. No SOFTECH connection: the SOFTECH reads
in build_plan are patched.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase

from apps.purchasing import rate_writer
from apps.purchasing import seasonality as S
from apps.purchasing.models import ItemSeasonality, SalesRatePush
from apps.tests.factories import make_admin, make_item


class WindowWeightsTests(SimpleTestCase):
    def test_whole_window_inside_one_month(self):
        self.assertEqual(S.window_weights(date(2026, 1, 1)), {1: 1.0})

    def test_window_split_across_months(self):
        w = S.window_weights(date(2026, 11, 21))          # 10 days of Nov, 20 of Dec
        self.assertAlmostEqual(w[11], 10 / 30)
        self.assertAlmostEqual(w[12], 20 / 30)
        self.assertAlmostEqual(sum(w.values()), 1.0)


class RateFactorTests(TestCase):
    def setUp(self):
        self.hot = make_item('COUGH SYRUP', softech_id='S1')
        self.cold = make_item('SUMMER SPRAY', softech_id='S2')
        self.wobbly = make_item('WOBBLY', softech_id='S3')
        self.half = make_item('HALF', softech_id='S4')
        ItemSeasonality.objects.create(item=self.hot, month=1, index=Decimal('2.400'), stable=True)
        ItemSeasonality.objects.create(item=self.cold, month=1, index=Decimal('0.400'), stable=True)
        ItemSeasonality.objects.create(item=self.wobbly, month=1, index=Decimal('1.300'), stable=False)
        # steady only in December: a Dec 16 → Jan 14 window counts January as ×1.00
        ItemSeasonality.objects.create(item=self.half, month=12, index=Decimal('1.300'), stable=True)
        ItemSeasonality.objects.create(item=self.half, month=1, index=Decimal('1.300'), stable=False)

    def test_capped_both_ways_and_unsteady_left_out(self):
        f = S.rate_factors(today=date(2026, 1, 1))
        self.assertEqual(f['S1'], S.FACTOR_MAX)            # 2.4 → capped 1.5
        self.assertEqual(f['S2'], S.FACTOR_MIN)            # 0.4 → capped 0.7
        self.assertNotIn('S3', f)                          # unsteady → rate unchanged
        self.assertNotIn('S4', f)                          # no steady month in window

    def test_unsteady_month_counts_as_one(self):
        f = S.rate_factors(today=date(2026, 12, 16))       # 16 days Dec (1.3) + 14 Jan (unsteady → 1.0)
        self.assertAlmostEqual(f['S4'], round(16 / 30 * 1.3 + 14 / 30 * 1.0, 3))

    def test_item_filter(self):
        f = S.rate_factors(['S2'], today=date(2026, 1, 1))
        self.assertEqual(set(f), {'S2'})


def _fake_branch():
    return SimpleNamespace(softech_branch_id='130', name='ElNozha', effective_db_host='h')


class BuildPlanSeasonalTests(SimpleTestCase):
    """build_plan(seasonal=True) multiplies the engine rate, keeps base + factor per line."""

    def _plan(self, seasonal, factors):
        want = {'130': {'A': (10.0, 'ITEM A'), 'B': (4.0, 'ITEM B')}}
        conn = mock.Mock()
        with mock.patch.object(rate_writer, '_latest_run', return_value=SimpleNamespace(id=1, pk=1, calc_date='2026-11-10')), \
             mock.patch.object(rate_writer, '_eligible_branches', return_value=[_fake_branch()]), \
             mock.patch.object(rate_writer, '_pivot_want', return_value=want), \
             mock.patch.object(rate_writer, 'resolve_store', return_value='130'), \
             mock.patch.object(rate_writer, '_read_conn_for_target', return_value=conn), \
             mock.patch.object(rate_writer, '_read_current_rates', return_value={'A': 1.0, 'B': 1.0}), \
             mock.patch.object(rate_writer, '_read_update_gate', return_value={'A': '1', 'B': '1'}), \
             mock.patch.object(S, 'rate_factors', return_value=factors) as rf:
            plan = rate_writer.build_plan(target='node', seasonal=seasonal)
        return plan, rf

    def test_off_is_unchanged_and_never_reads_factors(self):
        plan, rf = self._plan(False, {'A': 1.5})
        rf.assert_not_called()
        ch = {c['itemcode']: c for c in plan['branches'][0]['changes']}
        self.assertEqual(ch['A']['new'], 10.0)
        self.assertIsNone(ch['A']['factor'])
        self.assertIsNone(ch['A']['base'])
        self.assertFalse(plan['seasonal'])

    def test_on_multiplies_steady_items_only(self):
        plan, _ = self._plan(True, {'A': 1.25})
        ch = {c['itemcode']: c for c in plan['branches'][0]['changes']}
        self.assertEqual(ch['A']['new'], rate_writer._round(12.5))
        self.assertEqual(ch['A']['base'], 10.0)
        self.assertEqual(ch['A']['factor'], 1.25)
        self.assertEqual(ch['B']['new'], 4.0)              # no factor → pushed as the engine has it
        self.assertIsNone(ch['B']['factor'])
        self.assertTrue(plan['seasonal'])
        self.assertEqual(plan['seasonal_items'], 1)


class PersistSeasonalTests(TestCase):
    def test_persist_records_switch_base_and_factor(self):
        plan = {
            'run_id': None, 'calc_date': '2026-11-10', 'method': 'pivot', 'method_params': {},
            'target': 'node', 'seasonal': True,
            'branches': [{'branchcode': '130', 'name': 'ElNozha', 'store': '130', 'host': 'h',
                          'reachable': True, 'eligible_count': 1, 'skipped_count': 0,
                          'changes': [{'itemcode': 'A', 'item_name': 'ITEM A', 'old': 1.0, 'new': 12.5,
                                       'delta': 11.5, 'eligible': True, 'reason': '',
                                       'base': 10.0, 'factor': 1.25}]}],
            'totals': {'branches': 1, 'eligible': 1, 'skipped': 0, 'unreachable': 0}}
        push = rate_writer.persist_plan(plan)
        self.assertEqual(push.method_params, {'seasonal': True})
        line = push.lines.get(itemcode='A')
        self.assertEqual(float(line.base_rate), 10.0)
        self.assertEqual(float(line.season_factor), 1.25)

    def test_non_seasonal_plan_leaves_columns_empty(self):
        plan = {'run_id': None, 'calc_date': '2026-11-10', 'branches': [{
            'branchcode': '130', 'name': 'x', 'store': '130', 'host': 'h', 'reachable': True,
            'eligible_count': 1, 'skipped_count': 0,
            'changes': [{'itemcode': 'A', 'item_name': 'A', 'old': 0.0, 'new': 1.0, 'delta': 1.0,
                         'eligible': True, 'reason': ''}]}],
            'totals': {'branches': 1, 'eligible': 1, 'skipped': 0, 'unreachable': 0}}
        push = rate_writer.persist_plan(plan)
        self.assertEqual(push.method_params, {})
        line = push.lines.get(itemcode='A')
        self.assertIsNone(line.base_rate)
        self.assertIsNone(line.season_factor)


class ProposeViewSeasonalTests(TestCase):
    def setUp(self):
        _, _, self.client = make_admin('seasonal_rates_admin')

    def _propose(self, body):
        captured = {}

        def fake_push(**kw):
            captured.update(kw)
            p = SalesRatePush.objects.create(status=SalesRatePush.STATUS_PROPOSED,
                                             method_params={'seasonal': True} if kw['seasonal'] else {})
            return {'push_id': p.pk}

        with mock.patch.object(rate_writer, 'push', side_effect=fake_push):
            r = self.client.post('/api/purchasing/rates/propose/', body, format='json')
        return r, captured

    def test_switch_passed_through(self):
        r, kw = self._propose({'seasonal': True})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(kw['seasonal'])
        self.assertTrue(r.json()['method_params'].get('seasonal'))

    def test_default_off(self):
        r, kw = self._propose({})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertFalse(kw['seasonal'])

    def test_method_params_cannot_smuggle_the_switch(self):
        r, kw = self._propose({'method_params': {'seasonal': True}})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertFalse(kw['seasonal'])
        self.assertNotIn('seasonal', kw['method_params'])
