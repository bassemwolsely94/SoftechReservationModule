"""
Forecast reference values  (doc 16, Phase 8)
============================================
Grounded, refreshable engine inputs instead of hardcoded guesses:
  • seasonality   — per metric × month, CALCULATED from KpiActualRollup history
  • benchmark     — per-metric YoY anchor for Model B, grounded in historical YoY
                    (clamped to [FLOOR, CAP] so credit's +108% / customers' −18% are sane)
  • growth_goal   — the growth PLAN (Model A): (1+inflation)·(1+real_growth) for money
                    metrics, real_growth for counts — "cover inflating expenses + grow"
  • inflation     — Egypt CPI (EXTERNAL, entered by the owner; refreshed ~monthly)

Stored as one JSON blob in SystemSetting 'forecast_references' (as_of + source kept).
Owner applies them to a scenario MANUALLY (apply_to_scenario) — never auto-applied.
Recompute the history-derived parts any time with `compute_forecast_references`.
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal
from statistics import mean

SETTING_KEY = 'forecast_references'
MONEY_METRICS = {'cash_delivery', 'credit', 'gross_profit', 'beauty'}
COUNT_METRICS = {'customer_count', 'call_count'}
CORE_METRICS = ['cash_delivery', 'credit', 'gross_profit', 'customer_count', 'beauty']
BENCH_FLOOR = 0.0      # never anchor Model B to a decline
BENCH_CAP = 0.40       # cap runaway YoY (e.g. credit +108%) to a sane anchor


# ── history series ───────────────────────────────────────────────────────────
def _chain_series(metric):
    from apps.forecasting.models import KpiActualRollup as K
    from apps.forecasting.kpi import analytics_branches
    bids = list(analytics_branches().values_list('id', flat=True))
    agg = defaultdict(float)
    for r in K.objects.filter(branch_id__in=bids, metric=metric).values('year', 'month', 'value'):
        agg[(r['year'], r['month'])] += float(r['value'])
    return agg


def _cc_series(metric):
    from apps.forecasting.models import KpiActualRollup as K
    from apps.branches.models import Branch
    cc = Branch.objects.filter(softech_branch_id='CC').first()
    if not cc:
        return {}
    return {(r['year'], r['month']): float(r['value'])
            for r in K.objects.filter(branch=cc, metric=metric).values('year', 'month', 'value')}


def _series(metric):
    return _cc_series(metric) if metric == 'call_count' else _chain_series(metric)


def _complete(s):
    """Exclude the current, still-partial month."""
    today = date.today()
    cutoff = (today.year, today.month)
    return {k: v for k, v in s.items() if k < cutoff}


def _seasonality(s):
    """Index per calendar month (1.00 = average), each year normalised to its own mean."""
    years = defaultdict(dict)
    for (y, mo), v in s.items():
        years[y][mo] = v
    ratios = defaultdict(list)
    for y, md in years.items():
        if len(md) >= 6:
            ya = mean(md.values())
            if ya:
                for mo, v in md.items():
                    ratios[mo].append(v / ya)
    return {mo: (round(mean(ratios[mo]), 4) if ratios[mo] else 1.0) for mo in range(1, 13)}


def _recent_yoy(s):
    """Average of the latest available full year's YoY (this year vs last)."""
    today = date.today()
    yoys = []
    for mo in range(1, 13):
        cur, prev = s.get((today.year, mo)), s.get((today.year - 1, mo))
        if cur and prev:
            yoys.append(cur / prev - 1)
    if not yoys:   # fall back to the prior year pair
        for mo in range(1, 13):
            cur, prev = s.get((today.year - 1, mo)), s.get((today.year - 2, mo))
            if cur and prev:
                yoys.append(cur / prev - 1)
    return mean(yoys) if yoys else 0.0


# ── compute + store ────────────────────────────────────────────────────────────
def compute(real_growth=0.15, inflation_annual=None, inflation_source='', store=True):
    """Recompute the history-derived references; keep the externally-entered inflation
    unless a new value is passed. Returns the full reference dict."""
    prev = get() or {}
    infl_annual = float(inflation_annual) if inflation_annual is not None else float(prev.get('inflation_annual', 0.145))
    infl_source = inflation_source or prev.get('inflation_source', 'CAPMAS urban CPI')
    infl_monthly = round((1 + infl_annual) ** (1 / 12) - 1, 4)

    metrics = CORE_METRICS + ['call_count']
    seasonality, benchmark, growth_goal, hist_yoy = {}, {}, {}, {}
    for m in metrics:
        s = _complete(_series(m))
        if not s:
            continue
        seasonality[m] = {str(mo): v for mo, v in _seasonality(s).items()}
        yoy = round(_recent_yoy(s), 4)
        hist_yoy[m] = yoy
        benchmark[m] = round(min(max(yoy, BENCH_FLOOR), BENCH_CAP), 4)           # grounded + clamped
        if m in MONEY_METRICS:
            growth_goal[m] = round((1 + infl_annual) * (1 + real_growth) - 1, 4)  # cover inflation + real
        else:
            growth_goal[m] = round(real_growth, 4)                               # counts: real growth only

    refs = {
        'as_of': date.today().isoformat(),
        'inflation_annual': round(infl_annual, 4), 'inflation_monthly': infl_monthly,
        'inflation_source': infl_source, 'real_growth': round(float(real_growth), 4),
        'bench_floor': BENCH_FLOOR, 'bench_cap': BENCH_CAP,
        'historical_yoy': hist_yoy, 'benchmark': benchmark,
        'growth_goal': growth_goal, 'seasonality': seasonality,
    }
    if store:
        import json
        from apps.config.models import SystemSetting
        SystemSetting.objects.update_or_create(
            key=SETTING_KEY, defaults={'value': json.dumps(refs, ensure_ascii=False)})
    return refs


def get():
    import json
    from apps.config.models import SystemSetting
    raw = SystemSetting.get(SETTING_KEY, '')
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def set_inflation(inflation_annual, source=''):
    """Owner feeds the fresh external inflation; recompute monthly + keep history parts."""
    return compute(real_growth=float((get() or {}).get('real_growth', 0.15)),
                   inflation_annual=inflation_annual, inflation_source=source)


# ── manual application to a scenario ────────────────────────────────────────────
def apply_to_scenario(scenario):
    """Set the scenario's factors from the stored references (manual action).
    Per metric: growth_goal, benchmark, and the TARGET-MONTH seasonality. Plus the
    scenario-global monthly inflation. Returns a short summary."""
    from apps.forecasting.engine import ForecastEngine
    refs = get()
    if not refs:
        raise ValueError('لا توجد قيم مرجعية محسوبة بعد — شغّل compute_forecast_references')
    ForecastEngine.ensure_factors(scenario)
    mo = str(scenario.month)
    applied = 0
    for f in scenario.factors.all():
        changed = False
        if f.metric in refs.get('growth_goal', {}):
            f.growth_goal = Decimal(str(refs['growth_goal'][f.metric])); changed = True
        if f.metric in refs.get('benchmark', {}):
            f.benchmark = Decimal(str(refs['benchmark'][f.metric])); changed = True
        seas = refs.get('seasonality', {}).get(f.metric, {})
        if mo in seas:
            f.seasonality_index = Decimal(str(seas[mo])); changed = True
        if changed:
            f.save(); applied += 1
    scenario.inflation = Decimal(str(refs.get('inflation_monthly', 0)))
    scenario.save(update_fields=['inflation'])
    return {'factors_updated': applied, 'inflation': float(scenario.inflation),
            'as_of': refs.get('as_of')}
