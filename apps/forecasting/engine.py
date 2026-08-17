"""
ForecastEngine  (doc 16, Phase 3)
=================================
Generates monthly branch targets from history using two owner-tunable models:

  Model A (goal):   forecast = base × (1 + growth_goal)
  Model B (blend):  forecast = [w_lm·LM + w_pm·PM + w_yoy·(base × (1+benchmark))]
                               × seasonality × (1 + inflation + promotion_lift)
  avg:              forecast = (A + B) / 2

  target = forecast ÷ incentive_threshold        (so hitting the threshold = the forecast)

Signals per branch × metric, for target period (Y, M):
  base = actual(Y-1, M)      same month last year (seasonal/YoY anchor)
  LM   = actual(M-1)         month immediately before the target month
  PM   = actual(M-2)         two months before

Actuals come from KpiActualRollup (fast) with a KpiResolver fallback when a month
has not been rolled up yet. Chain (branch=None) result = sum of branch forecasts.
"""
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

Q2 = Decimal('0.01')


def _shift_month(year, month, delta):
    idx = (year * 12 + (month - 1)) + delta
    return idx // 12, idx % 12 + 1


class ForecastEngine:
    # Metrics generated (mirror the KPI board set).
    METRICS = ['cash_delivery', 'credit', 'gross_profit', 'customer_count', 'beauty']

    # Validated v2 defaults: growth_goal + blend weights (w_lm, w_pm, w_yoy).
    DEFAULT_FACTORS = {
        'cash_delivery':  (Decimal('0.20'), Decimal('0.50'), Decimal('0.30'), Decimal('0.20')),
        'credit':         (Decimal('0.47'), Decimal('0.60'), Decimal('0.25'), Decimal('0.15')),
        'beauty':         (Decimal('0.30'), Decimal('0.40'), Decimal('0.20'), Decimal('0.40')),
        'gross_profit':   (Decimal('0.15'), Decimal('0.50'), Decimal('0.30'), Decimal('0.20')),
        'customer_count': (Decimal('0.10'), Decimal('0.50'), Decimal('0.30'), Decimal('0.20')),
    }

    def __init__(self):
        from apps.forecasting.kpi import KpiResolver
        self.resolver = KpiResolver()
        self._cache = {}   # (branch_id, year, month, metric) -> Decimal

    # ── shared model math (used by generate + backtest) ────────────────────────
    @staticmethod
    def compute_models(base, lm, pm, *, growth, w_lm, w_pm, w_yoy,
                       seasonality, bench, infl, promo):
        """Return (model_a, model_b) Decimals. Both are linear in base/lm/pm,
        so chain-level == Σ branch-level."""
        model_a = base * (Decimal('1') + growth)
        yoy_signal = base * (Decimal('1') + bench)
        blend = (w_lm * lm + w_pm * pm + w_yoy * yoy_signal)
        model_b = blend * seasonality * (Decimal('1') + infl + promo)
        return model_a, model_b

    # ── factor seeding ─────────────────────────────────────────────────────────
    @classmethod
    def ensure_factors(cls, scenario):
        """Create default ForecastFactor rows for any missing metric."""
        from apps.forecasting.models import ForecastFactor
        for metric in cls.METRICS:
            g, wl, wp, wy = cls.DEFAULT_FACTORS[metric]
            ForecastFactor.objects.get_or_create(
                scenario=scenario, metric=metric,
                defaults={'growth_goal': g, 'w_lm': wl, 'w_pm': wp, 'w_yoy': wy},
            )

    # ── scope members (branch / salesperson / category) ─────────────────────────
    # Cap non-branch scopes so an on-demand generate stays responsive.
    MEMBER_CAP = 60

    def _members(self, scenario):
        """Return [{branch, key, label, kwargs}] for the scenario's scope."""
        from apps.forecasting.models import ForecastScenario as S
        st = scenario.scope_type
        if st == S.SCOPE_SALESPERSON:
            return self._salesperson_members(scenario)
        if st == S.SCOPE_CATEGORY:
            return self._category_members(scenario)
        from apps.forecasting.kpi import analytics_branches
        out = []
        for b in analytics_branches().order_by('code', 'softech_branch_id'):
            out.append({'branch': b, 'key': b.code or b.softech_branch_id,
                        'label': getattr(b, 'name_ar', '') or b.name, 'kwargs': {'branch_ids': [b.id]}})
        return out

    def _recent_window(self, scenario):
        ly, lm = _shift_month(scenario.year, scenario.month, -1)
        py, pm = _shift_month(scenario.year, scenario.month, -3)
        s, _ = self.resolver.month_bounds(py, pm)
        _, e = self.resolver.month_bounds(ly, lm)
        return s, e

    def _salesperson_members(self, scenario):
        from apps.customers.models import PurchaseHistory
        from django.db.models import Sum
        s, e = self._recent_window(scenario)
        rows = (PurchaseHistory.objects.filter(
                    invoice_date__date__gte=s, invoice_date__date__lte=e, doc_code='115')
                .exclude(softech_user='')
                .values('softech_user').annotate(amt=Sum('total_amount'))
                .order_by('-amt')[:self.MEMBER_CAP])
        return [{'branch': None, 'key': r['softech_user'], 'label': f"مندوب {r['softech_user']}",
                 'kwargs': {'softech_user': r['softech_user']}} for r in rows]

    def _category_members(self, scenario):
        from apps.customers.models import PurchaseHistoryLine
        from django.db.models import Sum
        s, e = self._recent_window(scenario)
        rows = (PurchaseHistoryLine.objects.filter(
                    purchase__invoice_date__date__gte=s, purchase__invoice_date__date__lte=e,
                    purchase__doc_code='115', item__category__isnull=False)
                .values('item__category_id', 'item__category__name_ar', 'item__category__name')
                .annotate(amt=Sum('line_total')).order_by('-amt')[:self.MEMBER_CAP])
        return [{'branch': None, 'key': str(r['item__category_id']),
                 'label': r['item__category__name_ar'] or r['item__category__name'] or f"فئة {r['item__category_id']}",
                 'kwargs': {'category_id': r['item__category_id']}} for r in rows]

    # ── actuals lookup (rollup fast-path for a single branch, resolver otherwise) ─
    def _member_actual(self, member, year, month, metric) -> Decimal:
        kw = member['kwargs']
        bids = kw.get('branch_ids')
        # branch fast-path via KpiActualRollup
        if bids and len(bids) == 1 and not kw.get('softech_user') and not kw.get('category_id'):
            key = (bids[0], year, month, metric)
            if key in self._cache:
                return self._cache[key]
            from apps.forecasting.models import KpiActualRollup
            row = KpiActualRollup.objects.filter(
                branch_id=bids[0], year=year, month=month, metric=metric).first()
            if row is not None:
                self._cache[key] = Decimal(row.value)
                return self._cache[key]
        start, end = self.resolver.month_bounds(year, month)
        return self.resolver.resolve(metric, start=start, end=end, **kw)

    # ── generate ─────────────────────────────────────────────────────────────
    @transaction.atomic
    def generate(self, scenario) -> dict:
        """Compute ForecastResult rows for every scope member × metric + chain aggregate."""
        from apps.forecasting.models import ForecastFactor, ForecastResult

        self.ensure_factors(scenario)
        factors = {f.metric: f for f in ForecastFactor.objects.filter(scenario=scenario)}
        members = self._members(scenario)

        y, m = scenario.year, scenario.month
        by, bm  = _shift_month(y, m, -12)   # base: same month last year
        ly, lm  = _shift_month(y, m, -1)    # last month
        py, pm  = _shift_month(y, m, -2)    # prior month

        thr = scenario.incentive_threshold or Decimal('0.90')
        bench = scenario.benchmark_growth or Decimal('0')
        infl = scenario.inflation or Decimal('0')
        promo = scenario.promotion_lift or Decimal('0')

        ForecastResult.objects.filter(scenario=scenario).delete()

        chain = {metric: {'base': Decimal('0'), 'lm': Decimal('0'), 'pm': Decimal('0'),
                          'a': Decimal('0'), 'b': Decimal('0'),
                          'forecast': Decimal('0'), 'target': Decimal('0')}
                 for metric in self.METRICS}
        n = 0
        for metric in self.METRICS:
            f = factors[metric]
            for mem in members:
                base = self._member_actual(mem, by, bm, metric)
                lmv  = self._member_actual(mem, ly, lm, metric)
                pmv  = self._member_actual(mem, py, pm, metric)

                model_a, model_b = self.compute_models(
                    base, lmv, pmv,
                    growth=f.growth_goal, w_lm=f.w_lm, w_pm=f.w_pm, w_yoy=f.w_yoy,
                    seasonality=f.seasonality_index, bench=bench, infl=infl, promo=promo)

                forecast = self._pick(scenario.model, model_a, model_b)
                target = (forecast / thr) if thr else forecast

                ForecastResult.objects.create(
                    scenario=scenario, branch=mem['branch'],
                    scope_key=mem['key'], scope_label=mem['label'], metric=metric,
                    base_value=base.quantize(Q2, ROUND_HALF_UP),
                    lm_value=lmv.quantize(Q2, ROUND_HALF_UP),
                    pm_value=pmv.quantize(Q2, ROUND_HALF_UP),
                    model_a=model_a.quantize(Q2, ROUND_HALF_UP),
                    model_b=model_b.quantize(Q2, ROUND_HALF_UP),
                    forecast_value=forecast.quantize(Q2, ROUND_HALF_UP),
                    target_value=target.quantize(Q2, ROUND_HALF_UP),
                )
                n += 1
                c = chain[metric]
                c['base'] += base; c['lm'] += lmv; c['pm'] += pmv
                c['a'] += model_a; c['b'] += model_b
                c['forecast'] += forecast; c['target'] += target

            # member shares (of forecast)
            total_fc = chain[metric]['forecast'] or Decimal('1')
            for r in ForecastResult.objects.filter(scenario=scenario, metric=metric).exclude(scope_key='chain'):
                r.branch_share = (r.forecast_value / total_fc).quantize(Decimal('0.0001'), ROUND_HALF_UP)
                r.save(update_fields=['branch_share'])

        # chain aggregate rows (scope_key='chain')
        for metric, c in chain.items():
            ForecastResult.objects.create(
                scenario=scenario, branch=None, scope_key='chain', scope_label='الإجمالى', metric=metric,
                base_value=c['base'].quantize(Q2, ROUND_HALF_UP),
                lm_value=c['lm'].quantize(Q2, ROUND_HALF_UP),
                pm_value=c['pm'].quantize(Q2, ROUND_HALF_UP),
                model_a=c['a'].quantize(Q2, ROUND_HALF_UP),
                model_b=c['b'].quantize(Q2, ROUND_HALF_UP),
                forecast_value=c['forecast'].quantize(Q2, ROUND_HALF_UP),
                target_value=c['target'].quantize(Q2, ROUND_HALF_UP),
                branch_share=Decimal('1'),
            )

        scenario.status = scenario.STATUS_GENERATED
        scenario.generated_at = timezone.now()
        scenario.save(update_fields=['status', 'generated_at'])
        return {'results': n, 'members': len(members), 'metrics': len(self.METRICS)}

    def _pick(self, model, a, b):
        from apps.forecasting.models import ForecastScenario as S
        if model == S.MODEL_B:
            return b
        if model == S.MODEL_AVG:
            return (a + b) / Decimal('2')
        return a

    # ── commit → SalesTarget (scope-aware) ──────────────────────────────────────
    @transaction.atomic
    def commit(self, scenario, created_by=None) -> dict:
        """Upsert incentives.SalesTarget rows from per-member ForecastResults."""
        from calendar import monthrange
        from datetime import date
        from apps.forecasting.models import ForecastResult, ForecastScenario as S
        from apps.incentives.models import SalesTarget

        start = date(scenario.year, scenario.month, 1)
        end   = date(scenario.year, scenario.month, monthrange(scenario.year, scenario.month)[1])
        label_month = f'{scenario.year}-{scenario.month:02d}'
        label = f'{scenario.name} · {label_month}'

        n = 0
        results = (ForecastResult.objects.filter(scenario=scenario)
                   .exclude(scope_key='chain').select_related('branch'))
        for r in results:
            if r.target_value <= 0:
                continue
            # scope-specific lookup keys
            if scenario.scope_type == S.SCOPE_SALESPERSON:
                lookup = dict(scope_type=SalesTarget.SCOPE_SALESPERSON, softech_user=r.scope_key)
            elif scenario.scope_type == S.SCOPE_CATEGORY:
                lookup = dict(scope_type=SalesTarget.SCOPE_CATEGORY, category_id=int(r.scope_key))
            else:
                lookup = dict(scope_type=SalesTarget.SCOPE_BRANCH, branch=r.branch)
            SalesTarget.objects.update_or_create(
                metric=r.metric, period_start=start, period_end=end, **lookup,
                defaults={'target_value': r.target_value, 'label': label, 'created_by': created_by},
            )
            n += 1

        scenario.status = scenario.STATUS_COMMITTED
        scenario.committed_at = timezone.now()
        scenario.save(update_fields=['status', 'committed_at'])
        return {'targets_committed': n}
