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

Horizon (2026-11-03): a target up to PLAN_HORIZON months ahead. A signal month that is
not complete yet is an ESTIMATE (flagged lm_projected/pm_projected): the running month is
its MTD scaled to a full month; a future month is projected recursively with the
seasonality-free Model B blend  w_lm·LM + w_pm·PM + w_yoy·base·(1+benchmark)  — the
variant that back-tested best on our ~2 years of history (point-in-time seasonality
made 1–3-month-ahead WAPE worse for every metric but beauty; re-check after more
history is loaded — BacktestRun.horizon_accuracy reports both).
"""
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

Q2 = Decimal('0.01')

# ── "memorable" TARGET rounding (round UP to a clean step) ───────────────────
# Only TARGETS are rounded — forecast/base/LM/PM and all actuals stay exact.
# Steps inferred from the owner's target files (GCD of historical targets):
#   cash+delivery / credit / profit → 5,000 ; customers (PIC) → 50 ; beauty → 2,500.
# Owner-tunable per metric via SystemSetting 'kpi_round_step_<metric>'.
ROUND_STEP_DEFAULTS = {
    'cash_delivery': 5000, 'credit': 5000, 'gross_profit': 5000,
    'customer_count': 50, 'beauty': 2500, 'pic_count': 50,
}


def kpi_round_steps():
    """Return {metric: step} merging SystemSetting overrides over the defaults."""
    from apps.config.models import SystemSetting
    out = {}
    for m, d in ROUND_STEP_DEFAULTS.items():
        raw = SystemSetting.get(f'kpi_round_step_{m}', d)
        try:
            out[m] = int(float(raw))
        except (TypeError, ValueError):
            out[m] = d
    return out


def round_up_step(value, step):
    """Round a target UP to the nearest `step`. step≤1 → nearest whole number
    (ROUND_HALF_UP). Never applied to exact/actual values."""
    from decimal import ROUND_CEILING
    v = value if isinstance(value, Decimal) else Decimal(str(value))
    if step and step > 1:
        s = Decimal(step)
        return (v / s).to_integral_value(rounding=ROUND_CEILING) * s
    return v.to_integral_value(rounding=ROUND_HALF_UP)


def cash_profit_margin():
    """Owner rule: the معامل الربحية TARGET = this fraction of the cash-sales target
    (branches AND call center). Default 0.235 (≈23-24%). 0 disables the derivation and
    the engine keeps its independent profit forecast. SystemSetting 'kpi_cash_profit_margin'."""
    from apps.config.models import SystemSetting
    try:
        return Decimal(str(SystemSetting.get('kpi_cash_profit_margin', '0.235')))
    except (TypeError, ValueError, ArithmeticError):
        return Decimal('0.235')


def _shift_month(year, month, delta):
    idx = (year * 12 + (month - 1)) + delta
    return idx // 12, idx % 12 + 1


# Furthest target month a scenario / the rolling plan may forecast (months after the
# running one). Beyond ~6 the recursive projection is mostly its own echo.
PLAN_HORIZON = 6


def current_ym():
    from datetime import date
    t = date.today()
    return t.year, t.month


def project_blend(lm, pm, base, *, w_lm, w_pm, w_yoy, bench, season=None, month=None):
    """Model B blend for a month. season=None → seasonality-free (the default mode);
    with a {calendar month: index} the recent months are deseasonalised and the target
    month's index re-applied: (w_lm·LM/S[m-1] + w_pm·PM/S[m-2])·S[m] + w_yoy·base·(1+bench)
    (the same-month-last-year term already carries the target month's season)."""
    yoy = w_yoy * base * (Decimal('1') + bench)
    if not season:
        return w_lm * lm + w_pm * pm + yoy
    s_t = season[month]
    s_l = season[(month - 2) % 12 + 1]
    s_p = season[(month - 3) % 12 + 1]
    return (w_lm * lm / s_l + w_pm * pm / s_p) * s_t + yoy


SEASONALITY_MODES = ('none', 'chain', 'branch')


def seasonality_mode():
    """SystemSetting 'forecast_seasonality_mode': none (default) | chain | branch. Switched
    only when BacktestRun.horizon_accuracy shows the seasonal variant beating 'none'."""
    from apps.config.models import SystemSetting
    v = str(SystemSetting.get('forecast_seasonality_mode', 'none') or 'none').strip().lower()
    return v if v in SEASONALITY_MODES else 'none'


class ForecastEngine:
    # Metrics generated (mirror the KPI board set). call_count = Call-Center only;
    # branches have no call history so those rows are skipped (see generate()).
    METRICS = ['cash_delivery', 'credit', 'gross_profit', 'customer_count', 'beauty',
               'call_count', 'pic_count']
    # Generated for the Call-Center member only: branches have no rollup for these
    # (the board shows them in the CC block only), so a branch would hit the slow
    # live resolver and get a target nobody sees.
    CC_ONLY_METRICS = {'pic_count'}

    # Validated v2 defaults: growth_goal + blend weights (w_lm, w_pm, w_yoy).
    DEFAULT_FACTORS = {
        'cash_delivery':  (Decimal('0.20'), Decimal('0.50'), Decimal('0.30'), Decimal('0.20')),
        'credit':         (Decimal('0.47'), Decimal('0.60'), Decimal('0.25'), Decimal('0.15')),
        'beauty':         (Decimal('0.30'), Decimal('0.40'), Decimal('0.20'), Decimal('0.40')),
        'gross_profit':   (Decimal('0.15'), Decimal('0.50'), Decimal('0.30'), Decimal('0.20')),
        'customer_count': (Decimal('0.10'), Decimal('0.50'), Decimal('0.30'), Decimal('0.20')),
        'call_count':     (Decimal('0.10'), Decimal('0.50'), Decimal('0.30'), Decimal('0.20')),
        'pic_count':      (Decimal('0.10'), Decimal('0.50'), Decimal('0.30'), Decimal('0.20')),
    }

    def __init__(self):
        from apps.forecasting.kpi import KpiResolver
        self.resolver = KpiResolver()
        self._cache = {}   # (branch_id, year, month, metric) -> Decimal
        self._proj = {}    # (member key, year, month, metric) -> projected Decimal
        self._lcd = {}     # (year, month) -> latest complete date (MTD projection)
        self._season = {}  # (member key, metric) -> {month: Decimal} | None
        self._mode = seasonality_mode()
        self._refs = None

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
                        'label': getattr(b, 'name_ar', '') or b.name,
                        'kwargs': {'branch_ids': [b.id]}, 'in_chain': True})
        # Call Center overlay — forecast as its OWN member (sales/profit/beauty/orders +
        # call_count), but NOT summed into the chain (its sales are already in the branches).
        from apps.branches.models import Branch
        cc = Branch.objects.filter(softech_branch_id='CC').first()
        if cc:
            out.append({'branch': cc, 'key': 'CC', 'label': 'الكول سنتر',
                        'kwargs': {'branch_ids': [cc.id]}, 'in_chain': False})
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
        """Actual for a signal month, projected to a FULL month when that month is the
        current in-progress month (so a forecast run mid-month isn't understated by the
        partial MTD value)."""
        return self._project_full_month(self._member_actual_raw(member, year, month, metric),
                                         year, month)

    def _member_actual_raw(self, member, year, month, metric) -> Decimal:
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

    # ── signals: actual, running-month estimate, or projected future month ─────
    def _signal(self, member, year, month, metric, pf):
        """(value, is_estimate) for a signal month. pf = projection factors
        {'w_lm','w_pm','w_yoy','bench'} of the metric."""
        cur = current_ym()
        if (year, month) < cur:
            return self._member_actual(member, year, month, metric), False
        if (year, month) == cur:
            return self._running_estimate(member, year, month, metric, pf), True
        return self._project(member, year, month, metric, pf), True

    def _running_estimate(self, member, year, month, metric, pf):
        """Running month = elapsed-share × (MTD scaled to a full month) + rest × projected
        blend. Two days scaled ×15 is noise (and distinct-customer counts don't scale
        linearly), so the MTD only takes over as the month fills in."""
        from datetime import date
        from calendar import monthrange
        scaled = self._member_actual(member, year, month, metric)
        last = self._latest_complete_date(year, month)
        total = monthrange(year, month)[1]
        elapsed = (last - date(year, month, 1)).days + 1 if last else 0
        frac = Decimal(min(max(elapsed, 0), total)) / Decimal(total)
        if frac >= 1:
            return scaled
        return frac * scaled + (Decimal('1') - frac) * self._project(member, year, month, metric, pf)

    def _project(self, member, year, month, metric, pf):
        key = (member['key'], year, month, metric)
        if key not in self._proj:
            lm, _ = self._signal(member, *_shift_month(year, month, -1), metric, pf)
            pm, _ = self._signal(member, *_shift_month(year, month, -2), metric, pf)
            base, _ = self._signal(member, *_shift_month(year, month, -12), metric, pf)
            self._proj[key] = project_blend(lm, pm, base, **pf,
                                            season=self._season_index(member, metric), month=month)
        return self._proj[key]

    def _season_index(self, member, metric):
        """{calendar month: Decimal} for this member × metric in the active mode, or None.
        branch mode: the branch's own index (already blended toward the chain by its
        history); others (call center, salespeople, categories) use the chain index."""
        if self._mode == 'none':
            return None
        k = (member['key'], metric)
        if k not in self._season:
            if self._refs is None:
                from apps.forecasting import references as R
                self._refs = R.get() or {}
            idx = None
            if self._mode == 'branch' and member.get('branch') is not None:
                idx = (self._refs.get('branch_seasonality', {}).get(metric, {})
                       .get(str(member['key']), {}).get('index'))
            idx = idx or self._refs.get('seasonality', {}).get(metric)
            self._season[k] = ({int(mo): Decimal(str(v)) for mo, v in idx.items()}
                               if idx and len(idx) == 12 and all(float(v) > 0 for v in idx.values()) else None)
        return self._season[k]

    def _latest_complete_date(self, year, month):
        if (year, month) not in self._lcd:
            self._lcd[(year, month)] = self._latest_complete_date_q(year, month)
        return self._lcd[(year, month)]

    @staticmethod
    def _latest_complete_date_q(year, month):
        """Last day of the month with COMPLETE sales data (today excluded as partial)."""
        from datetime import date
        from calendar import monthrange
        from django.db.models import Max
        from apps.customers.models import PurchaseHistory
        today = date.today()
        mstart = date(year, month, 1)
        mend = date(year, month, monthrange(year, month)[1])
        if mend < today:
            return mend
        if mstart > today:
            return None
        return (PurchaseHistory.objects.filter(
            invoice_date__date__gte=mstart, invoice_date__date__lt=today)
            .aggregate(m=Max('invoice_date__date'))['m'])

    def _project_full_month(self, value, year, month) -> Decimal:
        """Scale a current-month MTD actual to a full-month run-rate estimate
        (value × total_days ÷ elapsed_complete_days). Complete months pass through."""
        from datetime import date
        from calendar import monthrange
        today = date.today()
        if (year, month) != (today.year, today.month) or not value:
            return value
        last = self._latest_complete_date(year, month)
        if not last:
            return value
        total = monthrange(year, month)[1]
        elapsed = (last - date(year, month, 1)).days + 1
        if elapsed <= 0 or elapsed >= total:
            return value
        return value * Decimal(total) / Decimal(elapsed)

    # ── generate ─────────────────────────────────────────────────────────────
    @transaction.atomic
    def generate(self, scenario) -> dict:
        """Compute ForecastResult rows for every scope member × metric + chain aggregate."""
        from apps.forecasting.models import ForecastFactor, ForecastResult

        self.ensure_factors(scenario)
        factors = {f.metric: f for f in ForecastFactor.objects.filter(scenario=scenario)}
        members = self._members(scenario)
        # the scenario decides whether (and which) seasonality is used
        self._mode = getattr(scenario, 'seasonality_mode', None) or seasonality_mode()
        self._season, self._proj = {}, {}

        y, m = scenario.year, scenario.month
        by, bm  = _shift_month(y, m, -12)   # base: same month last year
        ly, lm  = _shift_month(y, m, -1)    # last month
        py, pm  = _shift_month(y, m, -2)    # prior month

        thr = scenario.incentive_threshold or Decimal('0.90')
        bench = scenario.benchmark_growth or Decimal('0')
        infl = scenario.inflation or Decimal('0')
        promo = scenario.promotion_lift or Decimal('0')
        steps = kpi_round_steps()   # memorable target rounding per metric

        ForecastResult.objects.filter(scenario=scenario).delete()

        chain = {metric: {'base': Decimal('0'), 'lm': Decimal('0'), 'pm': Decimal('0'),
                          'a': Decimal('0'), 'b': Decimal('0'),
                          'forecast': Decimal('0'), 'target': Decimal('0')}
                 for metric in self.METRICS}
        n = 0
        for metric in self.METRICS:
            f = factors[metric]
            fbench = f.benchmark if f.benchmark is not None else bench   # per-metric YoY, else global
            pf = {'w_lm': f.w_lm, 'w_pm': f.w_pm, 'w_yoy': f.w_yoy, 'bench': fbench}
            for mem in members:
                if metric in self.CC_ONLY_METRICS and mem['key'] != 'CC':
                    continue
                base, _ = self._signal(mem, by, bm, metric, pf)
                lmv, lm_est = self._signal(mem, ly, lm, metric, pf)
                pmv, pm_est = self._signal(mem, py, pm, metric, pf)

                # Skip metrics a member has no history for (e.g. CC has no credit;
                # branches have no call_count) so there are no spurious zero targets.
                if not (base or lmv or pmv):
                    continue

                model_a, model_b = self.compute_models(
                    base, lmv, pmv,
                    growth=f.growth_goal, w_lm=f.w_lm, w_pm=f.w_pm, w_yoy=f.w_yoy,
                    seasonality=f.seasonality_index, bench=fbench, infl=infl, promo=promo)
                season = self._season_index(mem, metric)
                if season:
                    # seasonal mode: deseasonalised blend; the factor's index stays an
                    # owner multiplier on top (apply-references sets it to 1 in this mode)
                    model_b = (project_blend(lmv, pmv, base, **pf, season=season, month=m)
                               * f.seasonality_index * (Decimal('1') + infl + promo))

                forecast = self._pick(scenario.model, model_a, model_b)
                raw_target = (forecast / thr) if thr else forecast
                # round the TARGET up to a memorable step; forecast stays exact
                target = round_up_step(raw_target, steps.get(metric, 1))

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
                    lm_projected=lm_est, pm_projected=pm_est,
                    season_index=(season[m] if season else None),
                )
                n += 1
                # Chain aggregate: only members that are part of the chain (CC is an
                # overlay — its sales are already counted inside the branches).
                if mem.get('in_chain', True):
                    c = chain[metric]
                    c['base'] += base; c['lm'] += lmv; c['pm'] += pmv
                    c['a'] += model_a; c['b'] += model_b
                    c['forecast'] += forecast; c['target'] += target
                    c['lm_est'] = c.get('lm_est', False) or lm_est
                    c['pm_est'] = c.get('pm_est', False) or pm_est

            # member shares (of the chain forecast) — only for chain members; CC is an
            # overlay (not part of the chain) so it has no chain share.
            total_fc = chain[metric]['forecast']
            if total_fc:
                for r in ForecastResult.objects.filter(
                        scenario=scenario, metric=metric).exclude(scope_key__in=['chain', 'CC']):
                    r.branch_share = (r.forecast_value / total_fc).quantize(Decimal('0.0001'), ROUND_HALF_UP)
                    r.save(update_fields=['branch_share'])

        # chain aggregate rows (scope_key='chain') — skip metrics with no chain signal
        # (e.g. call_count, which only the non-chain CC member has).
        for metric, c in chain.items():
            if not c['forecast']:
                continue
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
                lm_projected=c.get('lm_est', False), pm_projected=c.get('pm_est', False),
            )

        # Owner rule: derive the معامل الربحية TARGET as a fixed margin of the
        # cash-sales (cash_delivery) target — same rate for branches, chain AND CC.
        # The independent profit forecast stays in forecast_value for reference.
        margin = cash_profit_margin()
        if margin and margin > 0:
            pstep = steps.get('gross_profit', 1)
            cash_tgt = {r.scope_key: r.target_value for r in ForecastResult.objects.filter(
                scenario=scenario, metric='cash_delivery')}
            for r in ForecastResult.objects.filter(scenario=scenario, metric='gross_profit'):
                ct = cash_tgt.get(r.scope_key)
                if ct:
                    r.target_value = round_up_step(margin * ct, pstep)
                    r.save(update_fields=['target_value'])

        scenario.status = scenario.STATUS_GENERATED
        scenario.generated_at = timezone.now()
        scenario.save(update_fields=['status', 'generated_at'])
        return {'results': n, 'members': len(members), 'metrics': len(self.METRICS)}

    # ── rolling plan (read-only outlook, nothing stored) ───────────────────────
    PLAN_METRICS = ['cash_delivery', 'credit', 'gross_profit', 'customer_count', 'beauty']

    def plan(self, horizon=PLAN_HORIZON):
        """Outlook for the running month + the next `horizon` months, per branch + chain:
        the running month = MTD scaled to a full month, later months = the projected
        seasonality-free Model B (default weights, reference benchmark). Same-month-last-
        year actuals alongside for YoY. Targets still come only from a committed scenario."""
        from apps.forecasting import references as R
        refs = R.get() or {}
        bench_ref = refs.get('benchmark', {})
        cy, cm = current_ym()
        months = [_shift_month(cy, cm, k) for k in range(0, horizon + 1)]
        members = [mm for mm in self._members_branch() if mm.get('in_chain', True)]
        out = {'months': [{'year': y, 'month': m, 'running': (y, m) == (cy, cm)} for y, m in months],
               'metrics': []}
        from apps.forecasting.models import KpiActualRollup
        for metric in self.PLAN_METRICS:
            _, wl, wp, wy = self.DEFAULT_FACTORS[metric]
            pf = {'w_lm': wl, 'w_pm': wp, 'w_yoy': wy,
                  'bench': Decimal(str(bench_ref.get(metric, 0)))}
            chain = [Decimal('0')] * len(months)
            last_year = [Decimal('0')] * len(months)
            rows = []
            for mem in members:
                vals = [self._signal(mem, y, m, metric, pf)[0] for (y, m) in months]
                ly = [self._member_actual(mem, *_shift_month(y, m, -12), metric) for (y, m) in months]
                if not any(vals):
                    continue
                for i, v in enumerate(vals):
                    chain[i] += v
                    last_year[i] += ly[i]
                rows.append({'key': mem['key'], 'label': mem['label'],
                             'values': [float(round(v)) for v in vals]})
            out['metrics'].append({
                'metric': metric, 'label': KpiActualRollup.METRIC_LABELS.get(metric, metric),
                'chain': [float(round(v)) for v in chain],
                'last_year': [float(round(v)) for v in last_year],
                'yoy': [(float(round((c / l - 1) * 100, 1)) if l else None) for c, l in zip(chain, last_year)],
                'benchmark': float(pf['bench']),
                'branches': rows,
            })
        return out

    def _members_branch(self):
        from apps.forecasting.models import ForecastScenario as S

        class _Branch:
            scope_type = S.SCOPE_BRANCH
        return self._members(_Branch)

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
        changes = {}          # descriptor → [old, new] for the audit trail
        created_n = 0
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
            existing = SalesTarget.objects.filter(
                metric=r.metric, period_start=start, period_end=end, **lookup).first()
            old_val = float(existing.target_value) if existing else None
            new_val = float(r.target_value)
            SalesTarget.objects.update_or_create(
                metric=r.metric, period_start=start, period_end=end, **lookup,
                defaults={'target_value': r.target_value, 'label': label, 'created_by': created_by},
            )
            if old_val is None:
                created_n += 1
            if old_val != new_val:        # only record genuine changes
                changes[f'{r.scope_key}·{r.metric}'] = [old_val, new_val]
            n += 1

        scenario.status = scenario.STATUS_COMMITTED
        scenario.committed_at = timezone.now()
        scenario.save(update_fields=['status', 'committed_at'])

        # Audit the approved/assigned targets (who/what/when/before→after).
        from apps.audit.models import AuditLog
        AuditLog.log('sales_target_committed', user=created_by, obj=scenario,
                     changes=changes or None,
                     extra={'period': label_month, 'scope': scenario.scope_type,
                            'model': scenario.model, 'committed': n, 'created': created_n,
                            'updated': len(changes) - created_n if len(changes) >= created_n else 0},
                     note=f'اعتماد {n} هدف من «{scenario.name}» ({label_month}) — {created_n} جديد / {len(changes)} تغيّر')
        return {'targets_committed': n}
