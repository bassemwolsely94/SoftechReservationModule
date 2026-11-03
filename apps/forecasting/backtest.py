"""
BacktestService  (doc 16, Phase 4)
==================================
Replays Model A vs Model B across historical months and scores accuracy so the
owner can pick the model that best reproduces the past ("find the best working model").

For each testable target month M (needs base=M-12, LM=M-1, PM=M-2, actual=M all in
KpiActualRollup), for each metric, at CHAIN level (Σ operational branches):
    forecast_a, forecast_b = ForecastEngine.compute_models(base, lm, pm, factors, knobs)
    actual                 = chain actual(M)
Accumulate errors → per (metric, model):
    MAPE = mean(|f-a|/a)·100            WAPE = 100·Σ|f-a| / Σa   (robust for aggregates)
    bias = mean((f-a)/a)·100 (+=over)   RMSE = sqrt(mean((f-a)^2))
Winner per metric = lowest WAPE.

Factors: from a ForecastScenario if given, else ForecastEngine.DEFAULT_FACTORS.

Horizon accuracy (2026-11-03) — `horizon_accuracy(...)`, stored on the run: Model B
forecast h = 1..3 months ahead (months between the last complete month and the target
projected by the same blend), chain level, three seasonality variants, each using ONLY
data available at the forecast date (point-in-time seasonality index):
    b          — no seasonality (what the engine projects with)
    b_season   — blend × S[target]  (Model B when reference seasonality is applied)
    b_deseason — (w_lm·LM/S[LM] + w_pm·PM/S[PM])·S[target] + w_yoy·base·(1+bench)
"""
from decimal import Decimal
from math import sqrt

from django.db import transaction
from django.db.models import Sum

from apps.forecasting.engine import ForecastEngine, _shift_month


class BacktestService:
    def __init__(self):
        self._chain_cache = {}   # (year, month, metric) -> Decimal
        self._op_branch_ids = None

    def _operational_branch_ids(self):
        if self._op_branch_ids is None:
            from apps.branches.models import Branch
            self._op_branch_ids = list(
                Branch.objects.filter(is_operational=True).values_list('id', flat=True))
        return self._op_branch_ids

    def _chain_actual(self, year, month, metric) -> Decimal:
        """Σ KpiActualRollup over operational branches. None if the month has no rollup."""
        key = (year, month, metric)
        if key in self._chain_cache:
            return self._chain_cache[key]
        from apps.forecasting.models import KpiActualRollup
        qs = KpiActualRollup.objects.filter(
            year=year, month=month, metric=metric,
            branch_id__in=self._operational_branch_ids())
        if not qs.exists():
            self._chain_cache[key] = None
            return None
        val = Decimal(str(qs.aggregate(s=Sum('value'))['s'] or 0))
        self._chain_cache[key] = val
        return val

    def _testable_months(self, metric):
        """Months M with base(M-12), LM(M-1), PM(M-2) and actual(M) all present. The running
        month is never a test month — its actual is only a few days (scored it as a ~95% miss
        and pushed B's WAPE from ~6% to ~15%)."""
        from apps.forecasting.engine import current_ym
        from apps.forecasting.models import KpiActualRollup
        have = set(KpiActualRollup.objects.filter(metric=metric)
                   .values_list('year', 'month').distinct())
        cur = current_ym()
        out = []
        for (y, m) in sorted(have):
            if (y, m) >= cur:
                continue
            need = [(y, m), _shift_month(y, m, -1), _shift_month(y, m, -2), _shift_month(y, m, -12)]
            if all((ny, nm) in have for (ny, nm) in need):
                out.append((y, m))
        return out

    @transaction.atomic
    def run(self, *, months_back=12, scenario=None, benchmark_growth=None,
            incentive_threshold=None, inflation=None, promotion_lift=None,
            metrics=None, created_by=None):
        from apps.forecasting.models import (
            BacktestRun, BacktestResult, ForecastFactor, ForecastScenario)

        metrics = metrics or ForecastEngine.METRICS
        # knobs: scenario overrides explicit args override defaults
        bench = self._pick_knob(scenario, 'benchmark_growth', benchmark_growth, Decimal('0.30'))
        thr   = self._pick_knob(scenario, 'incentive_threshold', incentive_threshold, Decimal('0.90'))
        infl  = self._pick_knob(scenario, 'inflation', inflation, Decimal('0'))
        promo = self._pick_knob(scenario, 'promotion_lift', promotion_lift, Decimal('0'))

        # factors per metric
        scen_factors = {}
        if scenario:
            ForecastEngine.ensure_factors(scenario)
            scen_factors = {f.metric: {'growth_goal': f.growth_goal, 'w_lm': f.w_lm, 'w_pm': f.w_pm,
                                       'w_yoy': f.w_yoy, 'seasonality_index': f.seasonality_index}
                            for f in ForecastFactor.objects.filter(scenario=scenario)}

        # window bounds from union of testable months across metrics (bounded to months_back)
        all_months = sorted(set().union(*[set(self._testable_months(m)) for m in metrics]))
        if not all_months:
            raise ValueError('No testable months — backfill more history first')
        window = all_months[-months_back:] if months_back else all_months
        ws, we = window[0], window[-1]

        run = BacktestRun.objects.create(
            created_by=created_by,
            window_start_year=ws[0], window_start_month=ws[1],
            window_end_year=we[0], window_end_month=we[1], n_months=len(window),
            benchmark_growth=bench, incentive_threshold=thr,
            inflation=infl, promotion_lift=promo, scenario=scenario)

        for metric in metrics:
            factor = scen_factors.get(metric) or self._default_factor(metric)
            months = [mm for mm in self._testable_months(metric) if mm in set(window)]
            acc = {'a': _Acc(), 'b': _Acc()}
            for (y, m) in months:
                by, bm = _shift_month(y, m, -12)
                ly, lm = _shift_month(y, m, -1)
                py, pm = _shift_month(y, m, -2)
                base = self._chain_actual(by, bm, metric)
                lmv  = self._chain_actual(ly, lm, metric)
                pmv  = self._chain_actual(py, pm, metric)
                act  = self._chain_actual(y, m, metric)
                if act is None or act == 0 or base is None or lmv is None or pmv is None:
                    continue
                fa, fb = ForecastEngine.compute_models(
                    base, lmv, pmv,
                    growth=factor['growth_goal'], w_lm=factor['w_lm'],
                    w_pm=factor['w_pm'], w_yoy=factor['w_yoy'],
                    seasonality=factor['seasonality_index'],
                    bench=bench, infl=infl, promo=promo)
                acc['a'].add(float(fa), float(act))
                acc['b'].add(float(fb), float(act))

            # persist per-model, mark winner (lowest WAPE among models with points)
            scored = {}
            for model in ('a', 'b'):
                a = acc[model]
                if a.n == 0:
                    continue
                scored[model] = a.wape()
                BacktestResult.objects.create(
                    run=run, metric=metric, model=model, n_points=a.n,
                    mape=round(a.mape(), 2), wape=round(a.wape(), 2),
                    bias=round(a.bias(), 2), rmse=round(a.rmse(), 2),
                    factor_snapshot={k: float(v) for k, v in factor.items()})
            if scored:
                winner = min(scored, key=scored.get)
                BacktestResult.objects.filter(run=run, metric=metric, model=winner).update(is_winner=True)

        run.horizon_accuracy = self.horizon_accuracy(
            metrics=metrics, factors={m: (scen_factors.get(m) or self._default_factor(m)) for m in metrics},
            bench=bench, window=set(window))
        run.save(update_fields=['horizon_accuracy'])
        return run

    VARIANTS = ('b', 'b_season', 'b_deseason')
    HORIZONS = (1, 2, 3)

    @classmethod
    def horizon_accuracy(cls, *, metrics, factors, bench, window=None):
        """{metric: {variant: {h: {'wape', 'n'}}}} over the target months in `window`."""
        from apps.forecasting import references as R
        out = {}
        for metric in metrics:
            s = R._complete(R._series(metric))
            if not s:
                continue
            f = factors[metric]
            w_lm, w_pm, w_yoy = (float(f['w_lm']), float(f['w_pm']), float(f['w_yoy']))
            b = float(bench)
            res = {v: {} for v in cls.VARIANTS}
            for h in cls.HORIZONS:
                acc = {v: [0.0, 0.0, 0] for v in cls.VARIANTS}     # Σ|err|, Σactual, n
                for (y, m) in sorted(s):
                    if window is not None and (y, m) not in window:
                        continue
                    origin = _shift_month(y, m, -h)                 # last complete month
                    if _shift_month(y, m, -12) not in s:
                        continue
                    hist = {k: v for k, v in s.items() if k <= origin}
                    S = R._seasonality(hist)
                    for var in cls.VARIANTS:
                        fc = cls._recursive(s, origin, (y, m), var, S, w_lm, w_pm, w_yoy, b)
                        if fc is None:
                            continue
                        a = acc[var]
                        a[0] += abs(fc - s[(y, m)]); a[1] += s[(y, m)]; a[2] += 1
                for var, (err, act, n) in acc.items():
                    if n and act:
                        res[var][str(h)] = {'wape': round(100 * err / act, 2), 'n': n}
            out[metric] = res
        return out

    @staticmethod
    def _recursive(s, origin, target, var, S, w_lm, w_pm, w_yoy, bench):
        memo = {}

        def val(ym):
            if ym <= origin:
                return s.get(ym)
            if ym in memo:
                return memo[ym]
            lm, pm = val(_shift_month(*ym, -1)), val(_shift_month(*ym, -2))
            base = s.get(_shift_month(*ym, -12))
            if lm is None or pm is None or base is None:
                return None
            yoy = w_yoy * base * (1 + bench)
            st = S[ym[1]]
            if var == 'b':
                f = w_lm * lm + w_pm * pm + yoy
            elif var == 'b_season':
                f = (w_lm * lm + w_pm * pm + yoy) * st
            else:
                sl, sp = S[_shift_month(*ym, -1)[1]], S[_shift_month(*ym, -2)[1]]
                f = (w_lm * lm / sl + w_pm * pm / sp) * st + yoy
            memo[ym] = f
            return f
        return val(target)

    # ── helpers ────────────────────────────────────────────────────────────────
    @staticmethod
    def _pick_knob(scenario, attr, explicit, default):
        if explicit is not None:
            return Decimal(str(explicit))
        if scenario is not None:
            return getattr(scenario, attr)
        return default

    @staticmethod
    def _default_factor(metric):
        g, wl, wp, wy = ForecastEngine.DEFAULT_FACTORS[metric]
        return {'growth_goal': g, 'w_lm': wl, 'w_pm': wp, 'w_yoy': wy,
                'seasonality_index': Decimal('1')}


class _Acc:
    """Error accumulator for one (metric, model)."""
    def __init__(self):
        self.n = 0
        self.sum_ape = 0.0     # Σ |f-a|/a
        self.sum_spe = 0.0     # Σ (f-a)/a
        self.sum_abs = 0.0     # Σ |f-a|
        self.sum_act = 0.0     # Σ a
        self.sum_se = 0.0      # Σ (f-a)^2

    def add(self, f, a):
        self.n += 1
        err = f - a
        self.sum_ape += abs(err) / a
        self.sum_spe += err / a
        self.sum_abs += abs(err)
        self.sum_act += a
        self.sum_se += err * err

    def mape(self):
        return 100.0 * self.sum_ape / self.n if self.n else 0.0

    def bias(self):
        return 100.0 * self.sum_spe / self.n if self.n else 0.0

    def wape(self):
        return 100.0 * self.sum_abs / self.sum_act if self.sum_act else 0.0

    def rmse(self):
        return sqrt(self.sum_se / self.n) if self.n else 0.0
