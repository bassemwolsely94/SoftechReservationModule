"""
Forecast reference values  (doc 16, Phase 8)
============================================
Grounded, refreshable engine inputs instead of hardcoded guesses:
  • seasonality   — per metric × month, CALCULATED from KpiActualRollup history
                    (ratio to a centred 12-month moving average, so growth is not read
                    as seasonality); per BRANCH too — a branch's own index weighted by its
                    history (full at 36 months), the chain index filling the rest, so a new
                    branch starts from the chain pattern until it has data of its own
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


def _branch_series(metric):
    """{branch code: {(y, m): value}} for operational retail branches (closed branches
    are not analytics branches, so they never shape the pattern). Zero months — before a
    branch opened — are dropped."""
    from apps.forecasting.models import KpiActualRollup as K
    from apps.forecasting.kpi import analytics_branches
    code = {b.id: (b.code or b.softech_branch_id) for b in analytics_branches()}
    out = defaultdict(dict)
    for r in K.objects.filter(branch_id__in=list(code), metric=metric).values('branch_id', 'year', 'month', 'value'):
        if r['value']:
            out[code[r['branch_id']]][(r['year'], r['month'])] = float(r['value'])
    return out


BRANCH_FULL_MONTHS = 36     # own index at full weight from 3 years of a branch's history
BRANCH_MIN_MONTHS = 13      # below one 13-month window the branch uses the chain index


def branch_weight(n_months):
    if n_months < BRANCH_MIN_MONTHS:
        return 0.0
    return round(min(n_months / BRANCH_FULL_MONTHS, 1.0), 4)


def blend_branch_index(own, chain, w):
    """w × own + (1−w) × chain per calendar month."""
    return {mo: round(w * own.get(mo, 1.0) + (1 - w) * chain.get(mo, 1.0), 4) for mo in range(1, 13)}


def _branch_seasonality(metric, chain_idx):
    out = {}
    for code, s in _branch_series(metric).items():
        s = _complete(s)
        w = branch_weight(len(s))
        own = _seasonality(s) if w else {}
        out[code] = {'months': len(s), 'weight': w,
                     'index': {str(mo): v for mo, v in blend_branch_index(own, chain_idx, w).items()}}
    return out


def _complete(s):
    """Exclude the current, still-partial month."""
    today = date.today()
    cutoff = (today.year, today.month)
    return {k: v for k, v in s.items() if k < cutoff}


def _seasonality(s):
    """Index per calendar month (1.00 = average). Ratio of each month to its centred
    12-month moving average (classical decomposition — the trend is divided out, so a
    growing metric does not show a fake "December high / January low"); averaged per
    calendar month and normalised to mean 1. A month never covered by a full 13-month
    window stays neutral (1.0) — mixing in the year-mean ratio back-tested worse.
    Back-tested 2026-11-03: credit 1-month-ahead WAPE 20.6% → 13.4% vs year-mean."""
    from apps.forecasting.engine import _shift_month
    ratios = defaultdict(list)
    for (y, mo), v in s.items():
        win = [_shift_month(y, mo, k) for k in range(-6, 7)]
        if not all(w in s for w in win):
            continue
        cma = (0.5 * s[win[0]] + sum(s[w] for w in win[1:-1]) + 0.5 * s[win[-1]]) / 12
        if cma:
            ratios[mo].append(v / cma)
    idx = {mo: (mean(ratios[mo]) if ratios[mo] else 1.0) for mo in range(1, 13)}
    k = mean(idx.values()) or 1.0
    return {mo: round(v / k, 4) for mo, v in idx.items()}


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
    branch_seasonality = {}
    history = {}
    for m in metrics:
        s = _complete(_series(m))
        if not s:
            continue
        if m == 'cash_delivery':      # the history window the screen reports
            ks = sorted(s)
            history = {'from': f'{ks[0][0]}-{ks[0][1]:02d}', 'to': f'{ks[-1][0]}-{ks[-1][1]:02d}',
                       'months': len(ks)}
        chain_idx = _seasonality(s)
        seasonality[m] = {str(mo): v for mo, v in chain_idx.items()}
        if m != 'call_count':
            branch_seasonality[m] = _branch_seasonality(m, chain_idx)
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
        'growth_goal': growth_goal, 'seasonality': seasonality, 'history': history,
        'branch_seasonality': branch_seasonality,
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


def refresh_history():
    """Recompute the history-derived parts (seasonality/YoY/benchmark/growth) keeping the
    owner's inflation + real-growth inputs. Called after a closed month's rollup is rebuilt.
    Values are only stored — applying them to a scenario stays a manual action."""
    prev = get()
    if prev is None:
        return None
    return compute(real_growth=float(prev.get('real_growth', 0.15)))


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
    from apps.forecasting.engine import seasonality_mode
    ForecastEngine.ensure_factors(scenario)
    seasonal_engine = seasonality_mode() != 'none'
    mo = str(scenario.month)
    applied = 0
    for f in scenario.factors.all():
        changed = False
        if f.metric in refs.get('growth_goal', {}):
            f.growth_goal = Decimal(str(refs['growth_goal'][f.metric])); changed = True
        if f.metric in refs.get('benchmark', {}):
            f.benchmark = Decimal(str(refs['benchmark'][f.metric])); changed = True
        seas = refs.get('seasonality', {}).get(f.metric, {})
        if seasonal_engine:
            # the engine applies (branch/chain) seasonality itself — a factor index on
            # top would count the season twice
            f.seasonality_index = Decimal('1'); changed = True
        elif mo in seas:
            f.seasonality_index = Decimal(str(seas[mo])); changed = True
        if changed:
            f.save(); applied += 1
    scenario.inflation = Decimal(str(refs.get('inflation_monthly', 0)))
    scenario.save(update_fields=['inflation'])
    return {'factors_updated': applied, 'inflation': float(scenario.inflation),
            'as_of': refs.get('as_of')}
