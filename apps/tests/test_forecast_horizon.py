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


class SeasonalityMethodTests(TestCase):
    """Batch 3: trend-free (centred moving average) index, per-branch blend, seasonal mode."""

    def test_moving_average_index_ignores_steady_growth(self):
        from apps.forecasting import references as R
        s = {}
        for i in range(48):                       # +3%/month growth, no season at all
            y, m = _shift_month(2021, 1, i)
            s[(y, m)] = 1000 * (1.03 ** i)
        idx = R._seasonality(s)
        self.assertTrue(all(abs(v - 1) < 0.01 for v in idx.values()), idx)

    def test_moving_average_index_recovers_a_december_peak_under_growth(self):
        from apps.forecasting import references as R
        s = {}
        for i in range(48):
            y, m = _shift_month(2021, 1, i)
            s[(y, m)] = 1000 * (1.02 ** i) * (1.3 if m == 12 else 1.0)
        idx = R._seasonality(s)
        self.assertGreater(idx[12], 1.2)
        self.assertLess(abs(idx[6] - idx[7]), 0.02)

    def test_short_history_is_neutral(self):
        from apps.forecasting import references as R
        s = {(2025, m): 100.0 * m for m in range(1, 13)}     # 12 months: no 13-month window
        self.assertEqual(set(R._seasonality(s).values()), {1.0})

    def test_branch_weight_grows_with_history(self):
        from apps.forecasting import references as R
        self.assertEqual(R.branch_weight(12), 0.0)            # new branch → chain pattern
        self.assertAlmostEqual(R.branch_weight(18), 0.5)
        self.assertEqual(R.branch_weight(36), 1.0)
        self.assertEqual(R.branch_weight(60), 1.0)
        blended = R.blend_branch_index({12: 1.4}, {12: 1.0}, 0.5)
        self.assertEqual(blended[12], 1.2)
        self.assertEqual(blended[1], 1.0)

    def test_seasonal_blend_deseasonalises_recent_months(self):
        from apps.forecasting.engine import project_blend
        season = {mo: Decimal('1') for mo in range(1, 13)}
        season[12] = Decimal('1.2'); season[11] = Decimal('0.8')
        # January: LM = December (÷1.2), PM = November (÷0.8), target index 1
        v = project_blend(Decimal('1200'), Decimal('800'), Decimal('1000'),
                          w_lm=Decimal('0.5'), w_pm=Decimal('0.3'), w_yoy=Decimal('0.2'),
                          bench=Decimal('0'), season=season, month=1)
        self.assertEqual(v, Decimal('500') + Decimal('300') + Decimal('200'))
        plain = project_blend(Decimal('1200'), Decimal('800'), Decimal('1000'),
                              w_lm=Decimal('0.5'), w_pm=Decimal('0.3'), w_yoy=Decimal('0.2'), bench=Decimal('0'))
        self.assertEqual(plain, Decimal('1040'))

    def _refs(self, code):
        idx = {str(mo): 1.0 for mo in range(1, 13)}
        idx['8'] = 1.5
        return {'seasonality': {'cash_delivery': {str(mo): 1.0 for mo in range(1, 13)}},
                'branch_seasonality': {'cash_delivery': {code: {'months': 40, 'weight': 1.0, 'index': idx}}}}

    def test_branch_mode_uses_the_branch_index(self):
        from apps.config.models import SystemSetting
        b = Branch.objects.create(softech_branch_id='985', code='985', name='SM', is_operational=True)
        member = {'key': '985', 'label': 'SM', 'branch': b, 'kwargs': {'branch_ids': [b.id]}}
        SystemSetting.objects.update_or_create(key='forecast_seasonality_mode', defaults={'value': 'branch', 'label': 'x'})
        with mock.patch('apps.forecasting.references.get', return_value=self._refs('985')):
            e = ForecastEngine()
            self.assertEqual(e._season_index(member, 'cash_delivery')[8], Decimal('1.5'))
        SystemSetting.objects.update_or_create(key='forecast_seasonality_mode', defaults={'value': 'none'})
        self.assertIsNone(ForecastEngine()._season_index(member, 'cash_delivery'))

    def test_apply_references_keeps_factor_index_neutral_in_seasonal_mode(self):
        from apps.config.models import SystemSetting
        from apps.forecasting import references as R
        SystemSetting.objects.update_or_create(key='forecast_seasonality_mode', defaults={'value': 'chain', 'label': 'x'})
        sc = ForecastScenario.objects.create(name='m', year=2026, month=12)
        refs = {'seasonality': {'cash_delivery': {'12': 1.3}}, 'growth_goal': {}, 'benchmark': {}, 'inflation_monthly': 0}
        with mock.patch.object(R, 'get', return_value=refs):
            R.apply_to_scenario(sc)
        self.assertEqual(sc.factors.get(metric='cash_delivery').seasonality_index, Decimal('1'))

    def test_backtest_reports_branch_level_variants(self):
        from apps.forecasting.backtest import BacktestService as B
        flat = {(y, m): 100.0 for y in (2023, 2024, 2025) for m in range(1, 13)}
        with mock.patch('apps.forecasting.references._series', return_value=flat), \
             mock.patch('apps.forecasting.references._branch_series', return_value={'X': dict(flat)}):
            res = B.horizon_accuracy(metrics=['cash_delivery'],
                                     factors={'cash_delivery': B._default_factor('cash_delivery')}, bench=0)
        for v in ('br_b', 'br_chain', 'br_branch'):
            self.assertEqual(res['cash_delivery'][v]['1']['wape'], 0.0)


class SeasonalityModeApiTests(TestCase):
    def setUp(self):
        from apps.tests.factories import make_user
        _, _, self.client = make_user('sm_admin', role='admin', access_all=True)

    def test_switch_is_audited_and_validated(self):
        from apps.audit.models import AuditLog
        r = self.client.post('/api/forecasting/references/', {'seasonality_mode': 'branch'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['engine_seasonality_mode'], 'branch')
        self.assertTrue(AuditLog.objects.filter(action='forecast_seasonality_mode').exists())
        bad = self.client.post('/api/forecasting/references/', {'seasonality_mode': 'magic'}, format='json')
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.client.get('/api/forecasting/references/').json()['engine_seasonality_mode'], 'branch')


class ScenarioSeasonalityChoiceTests(TestCase):
    """Each scenario chooses its own seasonality (none / chain / branch)."""

    @classmethod
    def setUpTestData(cls):
        cls.b = Branch.objects.create(softech_branch_id='986', code='986', name='SC2', is_operational=True)
        for (y, m, v) in [(2025, 9, 1000), (2026, 8, 1200), (2026, 7, 1100)]:
            K.objects.create(branch=cls.b, year=y, month=m, metric='cash_delivery', value=Decimal(v))

    def setUp(self):
        from apps.tests.factories import make_user
        _, _, self.client = make_user('ss_admin', role='admin', access_all=True)

    def _refs(self):
        idx = {str(mo): 1.0 for mo in range(1, 13)}
        idx['9'] = 1.1; idx['8'] = 0.8
        return {'seasonality': {'cash_delivery': idx}, 'branch_seasonality': {}}

    def test_new_scenario_defaults_to_global_setting_and_can_override(self):
        from apps.config.models import SystemSetting
        SystemSetting.objects.update_or_create(key='forecast_seasonality_mode', defaults={'value': 'chain', 'label': 'x'})
        y, m = _shift_month(*current_ym(), 1)
        r = self.client.post('/api/forecasting/scenarios/', {'name': 'a', 'year': y, 'month': m}, format='json')
        self.assertEqual(r.json()['seasonality_mode'], 'chain')
        r = self.client.post('/api/forecasting/scenarios/', {'name': 'b', 'year': y, 'month': m,
                                                             'seasonality_mode': 'none'}, format='json')
        self.assertEqual(r.json()['seasonality_mode'], 'none')
        sid = r.json()['id']
        r = self.client.patch(f'/api/forecasting/scenarios/{sid}/', {'seasonality_mode': 'branch'}, format='json')
        self.assertEqual(r.json()['seasonality_mode'], 'branch')

    def _generate(self, mode):
        sc = ForecastScenario.objects.create(name=mode, year=2026, month=9, model='b',
                                             benchmark_growth=Decimal('0'), seasonality_mode=mode)
        ForecastEngine.ensure_factors(sc)
        sc.factors.filter(metric='cash_delivery').update(
            w_lm=Decimal('0.5'), w_pm=Decimal('0.3'), w_yoy=Decimal('0.2'), seasonality_index=Decimal('1'))
        with mock.patch('apps.forecasting.references.get', return_value=self._refs()):
            ForecastEngine().generate(sc)
        return ForecastResult.objects.get(scenario=sc, branch=self.b, metric='cash_delivery')

    def test_none_mode_uses_no_seasonality(self):
        r = self._generate('none')
        self.assertIsNone(r.season_index)
        self.assertEqual(r.model_b, Decimal('1130.00'))          # 600 + 330 + 200

    def test_chain_mode_deseasonalises_and_records_the_index(self):
        r = self._generate('chain')
        self.assertEqual(r.season_index, Decimal('1.1000'))
        # (0.5×1200/0.8 + 0.3×1100/1.0)×1.1 + 0.2×1000 = (750+330)×1.1 + 200
        self.assertEqual(r.model_b, Decimal('1388.00'))
