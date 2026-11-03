"""
apps/tests/test_forecast_horizon.py  (doc 16)

Forecast horizon: a scenario up to PLAN_HORIZON months ahead. Signal months that are not
complete are estimates — the running month blends its scaled MTD with the projection by
elapsed share, a future month is projected recursively with the seasonality-free Model B
blend — and flagged lm_projected/pm_projected. Plus the rolling plan API, the horizon
limit on new scenarios and the backtest's per-horizon accuracy.
"""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from apps.branches.models import Branch
from apps.forecasting.engine import ForecastEngine, _shift_month, current_ym, PLAN_HORIZON
from apps.forecasting.models import ForecastResult, ForecastScenario, KpiActualRollup as K


class ProjectedSignalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.b = Branch.objects.create(softech_branch_id='983', code='983', name='HZ', is_operational=True)
        for (y, m, v) in [(2025, 8, 800), (2025, 9, 850), (2026, 5, 900), (2026, 6, 1000), (2026, 7, 1100)]:
            K.objects.create(branch=cls.b, year=y, month=m, metric='cash_delivery', value=Decimal(v))

    def _member(self):
        return {'key': '983', 'label': 'HZ', 'branch': self.b, 'kwargs': {'branch_ids': [self.b.id]}}

    PF = {'w_lm': Decimal('0.5'), 'w_pm': Decimal('0.3'), 'w_yoy': Decimal('0.2'), 'bench': Decimal('0.3')}

    @mock.patch('apps.forecasting.engine.current_ym', return_value=(2026, 7))
    def test_future_month_is_projected_recursively(self, _):
        e = ForecastEngine()
        v, est = e._signal(self._member(), 2026, 8, 'cash_delivery', self.PF)
        # 0.5×1100 (running Jul, complete in data) + 0.3×1000 + 0.2×800×1.3 = 550+300+208
        self.assertTrue(est)
        self.assertEqual(v, Decimal('1058.0'))
        past, est_past = e._signal(self._member(), 2026, 6, 'cash_delivery', self.PF)
        self.assertEqual((past, est_past), (Decimal('1000'), False))

    @mock.patch('apps.forecasting.engine.current_ym', return_value=(2026, 7))
    def test_scenario_two_months_ahead_flags_estimates(self, _):
        sc = ForecastScenario.objects.create(name='hz', year=2026, month=9, model='b',
                                             benchmark_growth=Decimal('0.30'))
        ForecastEngine.ensure_factors(sc)
        sc.factors.filter(metric='cash_delivery').update(
            w_lm=Decimal('0.5'), w_pm=Decimal('0.3'), w_yoy=Decimal('0.2'), seasonality_index=Decimal('1'))
        ForecastEngine().generate(sc)
        r = ForecastResult.objects.get(scenario=sc, branch=self.b, metric='cash_delivery')
        self.assertEqual(r.lm_value, Decimal('1058.00'))      # Aug projected
        self.assertEqual(r.pm_value, Decimal('1100.00'))      # Jul = running month
        self.assertTrue(r.lm_projected and r.pm_projected)
        # 0.5×1058 + 0.3×1100 + 0.2×850×1.3 = 529+330+221
        self.assertEqual(r.model_b, Decimal('1080.00'))
        chain = ForecastResult.objects.get(scenario=sc, scope_key='chain', metric='cash_delivery')
        self.assertTrue(chain.lm_projected)

    def test_running_month_blends_mtd_with_projection_by_elapsed_share(self):
        e = ForecastEngine()
        with mock.patch.object(e, '_member_actual', return_value=Decimal('3000')), \
             mock.patch.object(e, '_project', return_value=Decimal('900')), \
             mock.patch.object(e, '_latest_complete_date', return_value=date(2026, 6, 10)):
            v = e._running_estimate(self._member(), 2026, 6, 'cash_delivery', self.PF)
        self.assertEqual(v.quantize(Decimal('0.01')), Decimal('1600.00'))   # ⅓×3000 + ⅔×900


class HorizonLimitAndPlanApiTests(TestCase):
    def setUp(self):
        from apps.tests.factories import make_user
        _, _, self.client = make_user('hz_admin', role='admin', access_all=True)

    def _create(self, ahead):
        y, m = _shift_month(*current_ym(), ahead)
        return self.client.post('/api/forecasting/scenarios/',
                                {'name': 'x', 'year': y, 'month': m, 'scope_type': 'branch', 'model': 'b'},
                                format='json')

    def test_scenario_within_horizon_is_accepted(self):
        self.assertEqual(self._create(PLAN_HORIZON).status_code, 201)

    def test_scenario_beyond_horizon_is_rejected(self):
        r = self._create(PLAN_HORIZON + 1)
        self.assertEqual(r.status_code, 400)
        self.assertIn('month', r.json())

    def test_plan_lists_running_month_plus_horizon(self):
        r = self.client.get('/api/forecasting/plan/?horizon=3')
        self.assertEqual(r.status_code, 200, r.content)
        months = r.json()['months']
        self.assertEqual(len(months), 4)
        self.assertTrue(months[0]['running'])
        self.assertEqual((months[0]['year'], months[0]['month']), current_ym())


class HorizonAccuracyTests(TestCase):
    def test_flat_history_projects_exactly_at_every_horizon(self):
        from apps.forecasting.backtest import BacktestService as B
        flat = {(y, m): 100.0 for y in (2024, 2025) for m in range(1, 13)}
        with mock.patch('apps.forecasting.references._series', return_value=flat):
            res = B.horizon_accuracy(metrics=['cash_delivery'],
                                     factors={'cash_delivery': B._default_factor('cash_delivery')},
                                     bench=0)
        b = res['cash_delivery']['b']
        self.assertEqual(sorted(b), ['1', '2', '3'])
        self.assertEqual(b['3']['wape'], 0.0)
        self.assertEqual(res['cash_delivery']['b_deseason']['1']['wape'], 0.0)


class BacktestSkipsRunningMonthTests(TestCase):
    def test_running_month_is_not_a_test_month(self):
        from apps.forecasting.backtest import BacktestService
        b = Branch.objects.create(softech_branch_id='984', code='984', name='BT2', is_operational=True)
        cur = current_ym()
        for k in range(0, 15):
            y, m = _shift_month(*cur, -k)
            K.objects.create(branch=b, year=y, month=m, metric='cash_delivery', value=Decimal('100'))
        months = BacktestService()._testable_months('cash_delivery')
        self.assertNotIn(cur, months)
        self.assertIn(_shift_month(*cur, -1), months)
