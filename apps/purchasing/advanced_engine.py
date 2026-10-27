"""
apps/purchasing/advanced_engine.py

ADVANCED (experimental) replenishment engine — a SEPARATE, parallel pathway.

It NEVER writes to ItemDemandMetrics or touches the production engine. It reads
the latest run's metrics + the PG SalesTransactionLine history read-only, and
computes an alternative recommendation per (item, branch) so it can be compared
side-by-side with the current one (via the "advanced analysis" export).

Phases (all derived from one 12-month monthly demand series + existing metrics):
  A  Demand cleansing (winsorize bulk months) + trend + seasonality → forecast demand
  B  Statistical safety stock = z(service level) × σ(demand) × √lead_time
  C  Lead-time reorder point (ROP) + order-up-to (S) + recommended order qty (JIT)
  D  Demand classification (ADI / CV² → smooth/erratic/intermittent/lumpy/slow) +
     Croston rate for intermittent + dead-stock / overstock flags

Everything is heuristic-but-sound and fully parameterised (AdvancedConfig), so it
can be tuned without code changes. Defaults are conservative.
"""
import datetime
import math
import statistics
from dataclasses import dataclass, field


# ── Tunables (parallel pathway — safe to change freely) ──────────────────────
@dataclass
class AdvancedConfig:
    history_months:     int   = 12       # window for series-based stats
    bulk_cap_factor:    float = 3.0      # a month above median×this is winsorised (bulk)
    trend_months:       int   = 6        # recent months for the trend slope
    trend_clamp:        float = 0.75     # cap trend adjustment to ±75%
    # Recency weighting of the base rate. The base rate anchors the forecast; a flat
    # mean lets stale, older months hold it back. With a half-life the weight of a
    # month halves every `base_rate_halflife_months` going back, so recent demand
    # dominates. Lower = more aggressive (tracks the latest months harder):
    #   0  → flat mean (every completed month equal — most stable, laggy)
    #   6  → mild recency bias
    #   3  → aggressive (default — recent quarter carries most of the weight; the
    #         winsorizer still caps one-off bulk, so it tracks trend, not spikes)
    #   2  → very aggressive (forecast ≈ the last couple of months; jumpier)
    base_rate_halflife_months: float = 3.0
    # Service level z-scores by ABC (higher = fewer stockouts, more stock)
    service_z:          dict  = field(default_factory=lambda: {
        'A': 1.88,   # ~97%
        'B': 1.64,   # ~95%
        'C': 1.28,   # ~90%
        'X': 1.04,   # ~85%
    })
    # Lead time (months) by ABC — expensive/A ordered more often (JIT)
    lead_time_months:   dict  = field(default_factory=lambda: {
        'A': 0.25, 'B': 0.5, 'C': 1.0, 'X': 1.0,
    })
    review_period_months: dict = field(default_factory=lambda: {
        'A': 0.25, 'B': 0.5, 'C': 1.0, 'X': 1.0,
    })
    # Minimum coverage FLOOR (months) by ABC — critical items keep a manual-style
    # cushion even under JIT. The floor raises BOTH the reorder trigger and the
    # order-up-to level, so coverage never falls below it. 0 = pure JIT (reorder
    # point only). Only applies to items with real demand — dead / no-demand /
    # order-on-demand items are NEVER force-stocked by the floor.
    #   A = 1.0mo (manual-style cushion) essentials, B = 0.5mo (~2 weeks),
    #   C / X = pure JIT.
    min_coverage_months: dict = field(default_factory=lambda: {
        'A': 1.0, 'B': 0.5, 'C': 0.0, 'X': 0.0,
    })
    # Optional per-item floor overrides {item_id: months} — beats the per-ABC
    # default for named critical SKUs (e.g. a life-critical chronic med). Empty by
    # default; populate from the caller / a DB list as needed.
    item_coverage_floor: dict = field(default_factory=dict)
    overstock_months:   float = 6.0      # coverage above this → overstock/dead-stock flag
    dead_no_sale_months: int  = 6        # no sales in N months + stock on hand → dead
    min_monthly_rate:   float = 0.02     # below this → treat as order-on-demand (no stock)

    # ── Partial current-month handling ───────────────────────────────────────
    # The newest calendar-month bucket is the CURRENT, still-running month, so its
    # qty is understated (only part of the month has happened). Left in, it drags
    # the trend slope and mean down and inflates the std. Modes:
    #   'drop'  — exclude the current partial month from all series statistics
    #             (rate / trend / std / ADI / CV²). Recency (months-since-sale) still
    #             honours a real sale in the partial month. Default; most robust.
    #   'scale' — extrapolate it to a full-month equivalent (qty / elapsed-fraction)
    #             and keep it, so a genuine in-month surge/drop still moves the trend.
    #   'keep'  — legacy behaviour (use the partial month as-is).
    partial_month_mode:          str   = 'drop'
    partial_month_complete_frac: float = 0.9   # ≥ this fraction elapsed ⇒ treat as complete
    partial_month_scale_min_frac: float = 0.33 # 'scale' mode: below this, drop instead of scale

    # ── Phase E: ROI-priority buy list under a cash budget ───────────────────
    cash_budget:        float = 0.0      # total purchase budget (EGP); 0 = unlimited
    default_margin_pct: float = 0.15     # fallback gross margin when cost/price missing
    # importance weight by ABC (A ranks higher when budget is tight)
    abc_weight:         dict  = field(default_factory=lambda: {
        'A': 1.5, 'B': 1.2, 'C': 1.0, 'X': 0.8,
    })
    # confidence multiplier by demand pattern (predictable demand = safer buy)
    class_confidence:   dict  = field(default_factory=lambda: {
        'smooth': 1.0, 'erratic': 0.85, 'intermittent': 0.7, 'lumpy': 0.55,
        'no_demand': 0.2,
    })


# ── Croston / classification thresholds (Syntetos–Boylan) ────────────────────
_ADI_CUT = 1.32
_CV2_CUT = 0.49


def _safe_mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0


def _recency_weighted_mean(ys, halflife):
    """
    Exponentially recency-weighted mean of ys (oldest→newest). The newest element
    has weight 1; each step back multiplies the weight by 0.5**(1/halflife), so the
    weight halves every `halflife` months. halflife<=0 → plain mean.
    """
    n = len(ys)
    if n == 0:
        return 0.0
    if not halflife or halflife <= 0:
        return sum(ys) / n
    decay = 0.5 ** (1.0 / halflife)
    # age 0 = newest (index n-1)
    weights = [decay ** ((n - 1) - i) for i in range(n)]
    wsum = sum(weights)
    return sum(y * w for y, w in zip(ys, weights)) / wsum if wsum else sum(ys) / n


def _slope(ys):
    """Least-squares slope of ys over index 0..n-1 (per-step change)."""
    n = len(ys)
    if n < 2:
        return 0.0
    xbar = (n - 1) / 2.0
    ybar = sum(ys) / n
    num = sum((i - xbar) * (ys[i] - ybar) for i in range(n))
    den = sum((i - xbar) ** 2 for i in range(n))
    return num / den if den else 0.0


def _classify(adi, cv2):
    if adi <= 0:
        return 'no_demand'
    if adi < _ADI_CUT and cv2 < _CV2_CUT:
        return 'smooth'
    if adi < _ADI_CUT and cv2 >= _CV2_CUT:
        return 'erratic'
    if adi >= _ADI_CUT and cv2 < _CV2_CUT:
        return 'intermittent'
    return 'lumpy'


def compute_row(series, metric, seasonal_index, cfg: AdvancedConfig,
                lead_time_override=None, partial_frac: float = 1.0,
                item_floor_override=None) -> dict:
    """
    series: list of monthly net-qty (chronological, zero-filled), oldest→newest.
            The LAST bucket is the current calendar month.
    metric: an ItemDemandMetrics row (current_stock, in_transit_qty, monthly_avg,
            safety_stock, gap, abc_class, pack_price, cost_price, std_gross_margin_pct).
    seasonal_index: Decimal|float for the coverage window (1.0 if none).
    partial_frac: fraction of the current (last) month that has elapsed (0..1). Used
            to correct the understated partial month — see AdvancedConfig.partial_month_mode.
    Returns a dict of advanced fields.
    """
    abc = (metric.abc_class or 'X')
    cur_stock = float(metric.current_stock or 0)
    in_transit = float(getattr(metric, 'in_transit_qty', 0) or 0)
    position   = cur_stock + in_transit
    price      = float(metric.pack_price or 0)

    # ── Partial current-month correction ─────────────────────────────────────
    # `series` keeps the raw buckets (used for recency/months-since-sale so a real
    # sale in the running month still counts). `stat_series` is what every demand
    # statistic below is computed on, with the understated partial month handled.
    partial_frac = 1.0 if partial_frac is None else max(0.0, min(1.0, partial_frac))
    stat_series = list(series)
    partial_handled = 'none'
    if partial_frac < cfg.partial_month_complete_frac and len(series) >= 2:
        if cfg.partial_month_mode == 'drop':
            stat_series = series[:-1]
            partial_handled = 'dropped'
        elif cfg.partial_month_mode == 'scale':
            if partial_frac >= cfg.partial_month_scale_min_frac:
                stat_series = series[:-1] + [series[-1] / partial_frac]
                partial_handled = 'scaled'
            else:                       # too early in the month to extrapolate → drop
                stat_series = series[:-1]
                partial_handled = 'dropped'
        # 'keep' → stat_series stays == series (legacy)

    # ── Phase A: cleanse bulk months (winsorize) ─────────────────────────────
    nonzero = [q for q in stat_series if q > 0]
    med = statistics.median(nonzero) if nonzero else 0.0
    cap = med * cfg.bulk_cap_factor if med > 0 else float('inf')
    cleansed = [min(q, cap) for q in stat_series]
    bulk_units = round(sum(stat_series) - sum(cleansed), 2)

    # Base rate: recency-weighted mean of cleansed months so the latest demand
    # dominates (half-life tunable). Falls back to current monthly_avg when empty.
    recent = cleansed[-cfg.trend_months:] if len(cleansed) >= 1 else cleansed
    base_rate = (_recency_weighted_mean(cleansed, cfg.base_rate_halflife_months)
                 if cleansed else float(metric.monthly_avg or 0))
    if base_rate == 0:
        base_rate = float(metric.monthly_avg or 0)

    # ── Phase A: trend (slope over recent cleansed months) ───────────────────
    slope = _slope(recent) if len(recent) >= 2 else 0.0
    # translate slope (units/month) into a multiplicative factor vs base
    trend_factor = 1.0
    if base_rate > 0:
        trend_factor = 1.0 + max(-cfg.trend_clamp, min(cfg.trend_clamp, slope / base_rate))
    seas = float(seasonal_index or 1.0)

    forecast_demand = round(base_rate * trend_factor * seas, 3)

    # ── Phase D: classification (ADI / CV²) ──────────────────────────────────
    n = len(stat_series)
    n_nonzero = len(nonzero)
    adi = (n / n_nonzero) if n_nonzero else 0.0
    cv2 = 0.0
    if n_nonzero >= 2:
        m = _safe_mean(nonzero)
        sd = statistics.pstdev(nonzero)
        cv2 = (sd / m) ** 2 if m > 0 else 0.0
    demand_class = _classify(adi, cv2)

    # Croston rate for intermittent/lumpy (demand size / interval) — often lower
    # than the MA, preventing over-stock of sporadic items.
    croston_rate = None
    if demand_class in ('intermittent', 'lumpy') and n_nonzero:
        croston_rate = round(_safe_mean(nonzero) / adi, 3) if adi else None
    # The demand the policy actually uses:
    policy_demand = croston_rate if croston_rate is not None else forecast_demand
    if policy_demand is not None and policy_demand < cfg.min_monthly_rate:
        policy_demand = policy_demand  # keep, but flagged as order-on-demand below

    # ── Phase B: statistical safety stock ────────────────────────────────────
    demand_std = statistics.pstdev(cleansed) if len(cleansed) >= 2 else 0.0
    # Real per-supplier lead time (days→months) when known; else the ABC default.
    lt = lead_time_override if lead_time_override is not None else cfg.lead_time_months.get(abc, 1.0)
    lt_source = 'supplier' if lead_time_override is not None else 'abc_default'
    rp = cfg.review_period_months.get(abc, 1.0)
    z  = cfg.service_z.get(abc, 1.28)
    sigma_lt = demand_std * math.sqrt(max(lt, 0.0001))
    stat_safety = round(z * sigma_lt, 3)

    # ── Phase C: reorder point + order-up-to + recommended qty (JIT) ─────────
    demand_over_lt = policy_demand * lt
    rop_jit = round(demand_over_lt + stat_safety, 3)          # pure JIT reorder point
    order_up_to_jit = round(policy_demand * (lt + rp) + stat_safety, 3)

    # ── Minimum coverage floor (per-item override > per-ABC default) ──────────
    # A hard cushion for critical items: coverage never drops below this, whatever
    # the JIT reorder point says. Skipped for items with no real / order-on-demand
    # demand so it never forces stock onto dead SKUs.
    floor_months = (item_floor_override if item_floor_override is not None
                    else cfg.min_coverage_months.get(abc, 0.0)) or 0.0
    floorable = policy_demand and policy_demand >= cfg.min_monthly_rate and floor_months > 0
    floor_units = round(policy_demand * floor_months, 3) if floorable else 0.0

    # Floor raises BOTH the trigger and the target so a floored item reorders
    # before dropping under the cushion and refills at least back up to it.
    rop = max(rop_jit, floor_units)
    order_up_to = max(order_up_to_jit, floor_units)
    order_now = position <= rop
    # The floor is the binding reason for this buy when it lifted the trigger above
    # what pure JIT would have done and the item is at/under the cushion.
    floor_binding = bool(floorable and floor_units > rop_jit and position <= floor_units)
    pack_qty = int(getattr(metric.item, 'pack_qty', 1) or 1) if getattr(metric, 'item', None) else 1
    # Per-branch need rounded UP to WHOLE UNITS (HQ distributes loose units to
    # branches; each branch must get enough). Pack rounding happens later at the
    # PURCHASE level (network) in the supplier pivot — you buy full packs, not units.
    rec_qty_raw = max(0.0, order_up_to - position) if order_now else 0.0
    rec_qty = float(math.ceil(rec_qty_raw)) if rec_qty_raw > 0 else 0.0

    coverage_months = round(position / policy_demand, 2) if policy_demand > 0 else None

    # ── Phase D: dead-stock / overstock flags ────────────────────────────────
    months_since_sale = None
    for i in range(len(series) - 1, -1, -1):
        if series[i] > 0:
            months_since_sale = (len(series) - 1) - i
            break
    flags = []
    if coverage_months is not None and coverage_months > cfg.overstock_months:
        flags.append('overstock')
    if position > 0 and (months_since_sale is None or months_since_sale >= cfg.dead_no_sale_months):
        flags.append('dead_stock')
    if 0 < policy_demand < cfg.min_monthly_rate:
        flags.append('order_on_demand')
    if demand_class == 'lumpy':
        flags.append('lumpy')
    if floor_binding:
        flags.append('coverage_floor')

    # Capital at risk (cash stuck) for overstock/dead — for prioritising liquidation
    excess_units = 0.0
    if coverage_months is not None and coverage_months > cfg.overstock_months and policy_demand > 0:
        target = policy_demand * cfg.overstock_months
        excess_units = max(0.0, position - target)
    excess_value = round(excess_units * price, 2)

    # ── Phase E: purchase ROI + priority score ───────────────────────────────
    rec_value = round(rec_qty * price, 2)
    cost = float(getattr(metric.item, 'cost_price', 0) or 0) if getattr(metric, 'item', None) else 0.0
    margin_pct = (price - cost) / price if (price > 0 and 0 < cost < price) else cfg.default_margin_pct
    monthly_margin = round((policy_demand or 0) * price * margin_pct, 2)
    # urgency 0..1 — how far below the reorder point (fully depleted = 1)
    urgency = max(0.0, min(1.0, (rop - position) / rop)) if rop > 0 else (1.0 if order_now else 0.0)
    conf = cfg.class_confidence.get(demand_class, 0.7)
    aw = cfg.abc_weight.get(abc, 1.0)
    # ROI = monthly gross-margin captured per EGP of inventory invested.
    roi = round(monthly_margin / rec_value, 4) if rec_value > 0 else 0.0
    # priority blends ROI with urgency, demand confidence, and ABC importance.
    priority_score = round(roi * (0.5 + 0.5 * urgency) * conf * aw, 4) if order_now else 0.0

    return {
        # Phase A
        'cleansed_rate':   round(base_rate, 3),
        'bulk_units':      bulk_units,
        'partial_month_frac':    round(partial_frac, 2),
        'partial_month_handled': partial_handled,
        'trend_factor':    round(trend_factor, 3),
        'seasonal_index':  round(seas, 3),
        'forecast_demand': forecast_demand,
        # Phase D (classification — placed early as it drives the policy)
        'demand_class':    demand_class,
        'adi':             round(adi, 2),
        'cv2':             round(cv2, 2),
        'croston_rate':    croston_rate,
        'policy_demand':   round(policy_demand, 3) if policy_demand is not None else None,
        # Phase B
        'demand_std':      round(demand_std, 3),
        'service_z':       z,
        'stat_safety':     stat_safety,
        # Phase C
        'lead_time_months': round(lt, 3),
        'lead_time_source': lt_source,
        'rop':             round(rop, 3),          # effective (max of JIT rop and floor)
        'rop_jit':         rop_jit,                # pure JIT reorder point (pre-floor)
        'order_up_to':     round(order_up_to, 3),  # effective target
        'coverage_floor_months': round(floor_months, 3),
        'coverage_floor_units':  floor_units,
        'floor_binding':   floor_binding,
        'position':        round(position, 2),
        'order_now':       order_now,
        'rec_order_qty':   rec_qty,          # whole UNITS for this branch (distribution)
        'rec_order_raw':   round(rec_qty_raw, 2),
        'pack_qty':        pack_qty,
        'rec_order_value': rec_value,
        'adv_coverage_months': coverage_months,
        # Phase D flags
        'flags':           flags,
        'excess_value':    excess_value,
        # Phase E — ROI priority (funded/cum_cost filled by the ranking pass)
        'gross_margin_pct': round(margin_pct, 4),
        'monthly_margin':  monthly_margin,
        'urgency':         round(urgency, 3),
        'roi':             roi,
        'priority_score':  priority_score,
        'funded':          None,
        'cum_cost':        None,
        'rank':            None,
    }


def load_monthly_series(item_ids, months: int):
    """
    One SQL → {(item_id, branch_id): [qty_oldest ... qty_newest]} zero-filled to
    `months` buckets ending this month. Read-only on PG.

    Returns (series_map, n, partial_frac) where partial_frac is the fraction of the
    current (newest) calendar month that has already elapsed — pass it to compute_row
    so the still-running month isn't mistaken for a low-demand month.
    """
    import calendar
    from django.db import connection
    today = datetime.date.today()
    # first day of the (months-1) months ago
    start = (today.replace(day=1) - datetime.timedelta(days=31 * (months - 1))).replace(day=1)

    rows = []
    with connection.cursor() as cur:
        cur.execute("""
            SELECT item_id, branch_id, date_trunc('month', doc_date)::date AS mon,
                   SUM(net_qty) AS qty
            FROM purchasing_salestransactionline
            WHERE item_id IS NOT NULL AND branch_id IS NOT NULL
              AND doc_date >= %s
            GROUP BY item_id, branch_id, date_trunc('month', doc_date)
        """, [start])
        rows = cur.fetchall()

    # month index
    month_keys = []
    m = start
    while m <= today.replace(day=1):
        month_keys.append(m)
        m = (m + datetime.timedelta(days=32)).replace(day=1)
    idx = {mk: i for i, mk in enumerate(month_keys)}
    n = len(month_keys)

    series = {}
    for item_id, branch_id, mon, qty in rows:
        key = (item_id, branch_id)
        if key not in series:
            series[key] = [0.0] * n
        if mon in idx:
            series[key][idx[mon]] = float(qty or 0)

    # Fraction of the current (newest) month elapsed — the last bucket is partial.
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    partial_frac = today.day / days_in_month
    return series, n, partial_frac


def run_advanced(run, cfg: AdvancedConfig = None, metrics_qs=None):
    """
    Compute advanced rows for a DemandCalculationRun. Yields (metric, advanced_dict).
    Read-only. metrics_qs lets the caller pre-filter (e.g. one branch / ABC).
    """
    from apps.purchasing.models import ItemDemandMetrics, SupplierLeadTime
    from apps.forecasting.models import SeasonalityIndex

    cfg = cfg or AdvancedConfig()
    qs = metrics_qs if metrics_qs is not None else (
        ItemDemandMetrics.objects.filter(run=run).select_related('item', 'branch')
    )
    # Fetch one extra bucket so that after the partial current month is handled we
    # still have ~history_months of COMPLETE months for the statistics.
    fetch_months = cfg.history_months + 1
    series_map, _n, partial_frac = load_monthly_series(None, fetch_months)

    # Per-supplier lead time (days) → months, when populated. Falls back to the
    # per-ABC default inside compute_row when a supplier has no entry.
    lt_map = {
        sc: (days / 30.0)
        for sc, days in SupplierLeadTime.objects.values_list('supplier_code', 'lead_time_days')
        if days
    }

    # Seasonal index for next month (coverage window) — per ITEM (SeasonalityIndex
    # has no branch dimension). Empty until the forecast/seasonality job runs → 1.0.
    next_month = (datetime.date.today() + datetime.timedelta(days=30)).month
    seas_map = {}
    try:
        for s in SeasonalityIndex.objects.filter(month=next_month).values(
                'item_id', 'index_value'):
            seas_map[s['item_id']] = float(s['index_value'] or 1.0)
    except Exception:
        seas_map = {}

    for metric in qs.iterator():
        key = (metric.item_id, metric.branch_id)
        series = series_map.get(key, [0.0] * _n)
        seas = seas_map.get(metric.item_id, 1.0)
        lt_override = lt_map.get((metric.item.supplier_code or '').strip()) if metric.item else None
        floor_override = cfg.item_coverage_floor.get(metric.item_id) if cfg.item_coverage_floor else None
        yield metric, compute_row(series, metric, seas, cfg,
                                  lead_time_override=lt_override,
                                  partial_frac=partial_frac,
                                  item_floor_override=floor_override)


def run_advanced_ranked(run, cfg: AdvancedConfig = None, metrics_qs=None):
    """
    Phase E — materialise advanced rows, rank the BUY candidates (order_now &
    rec_order_qty > 0) by priority_score, and greedily allocate cfg.cash_budget
    top-down. Fills funded / cum_cost / rank on each candidate.

    Returns (rows, summary):
      rows    = [(metric, advanced_dict), ...] in the original queryset order
      summary = budget/need/funded/deferred totals
    """
    cfg = cfg or AdvancedConfig()
    rows = list(run_advanced(run, cfg, metrics_qs=metrics_qs))

    cands = [(m, a) for (m, a) in rows if a['order_now'] and a['rec_order_qty'] > 0]
    cands.sort(key=lambda x: x[1]['priority_score'], reverse=True)

    budget = cfg.cash_budget or 0.0
    cum = total_need = funded_cost = 0.0
    funded_n = 0
    for rank, (m, a) in enumerate(cands, 1):
        cost = a['rec_order_value']
        total_need += cost
        a['rank'] = rank
        if budget <= 0 or cum + cost <= budget:      # 0 budget = unlimited
            a['funded'] = True
            cum += cost
            a['cum_cost'] = round(cum, 2)
            funded_cost += cost
            funded_n += 1
        else:
            a['funded'] = False                       # skip (a cheaper high-rank item may still fit)

    summary = {
        'candidates':     len(cands),
        'total_need':     round(total_need, 2),
        'budget':         budget,
        'funded_count':   funded_n,
        'funded_cost':    round(funded_cost, 2),
        'deferred_count': len(cands) - funded_n,
        'deferred_cost':  round(total_need - funded_cost, 2),
    }
    return rows, summary
