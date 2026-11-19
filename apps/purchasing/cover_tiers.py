"""
apps/purchasing/cover_tiers.py — C25 / P-34 tiered cover under a cash budget (READ-ONLY report).

Owner decisions 2026-11-19 (override the spec's velocity bands, docs/product-review/06_SPEC_P-34):
  • Tiers by SALES VALUE (ABC), per branch: A = the items making the top 80% of the branch's
    monthly sales value, B = the next 15%, C = the rest (and every item with no sales value).
  • Cover targets: A 1.5 months, B 1.0, C 0.5 — SystemSettings, so they can change later.
  • No cash budget yet: the cash each tier needs to reach its target is compared with 75% / 100% /
    125% of LAST MONTH's purchase value (procurement.PurchaseLine doc 10 net of returns doc 120,
    real suppliers only, as the P-40 cash view). The budget funds A first, then B, then C.

No new rate calculation: rate, stock and in-transit come from the latest successful
DemandCalculationRun (ItemDemandMetrics.monthly_avg / current_stock / in_transit_qty). Sales value =
the run's monthly_value (rate × pack price). Cash = Item.cost_price. Need = the ISR rule's whole-pack
arithmetic (isr_softech.softech_need), whole target scaled (no 1-month safety floor).

PostgreSQL only — no SOFTECH call, nothing written anywhere. Deterministic Decimal throughout.
"""
from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal

from .isr_softech import softech_need

ZERO = Decimal('0')
CENT = Decimal('0.01')
TIERS = ('A', 'B', 'C')
TIER_AR = {'A': 'أ — أعلى 80% من المبيعات', 'B': 'ب — الـ15% التالية', 'C': 'ج — الباقي'}
BUDGET_LEVELS = (75, 100, 125)

# SystemSetting key → code default (Decimal string). Missing / invalid → default.
SETTING_DEFAULTS = {
    'cover_tier_a_months': '1.5',
    'cover_tier_b_months': '1.0',
    'cover_tier_c_months': '0.5',
    'cover_tier_a_cut_pct': '80',    # A = items up to this cumulative % of sales value
    'cover_tier_b_cut_pct': '95',    # B = up to this % (80 + the next 15)
}


def _dec(v, default=ZERO) -> Decimal:
    try:
        return Decimal(str(v)) if v is not None and str(v).strip() != '' else default
    except Exception:
        return default


def tier_settings() -> dict:
    """{'months': {A,B,C}, 'cut_a', 'cut_b'} from SystemSetting, defaults in code. Bad values fall back."""
    from apps.config.models import SystemSetting
    vals = {}
    for key, default in SETTING_DEFAULTS.items():
        d = Decimal(default)
        v = _dec(SystemSetting.get(key, default), d)
        vals[key] = v if v >= 0 else d
    cut_a = min(vals['cover_tier_a_cut_pct'], Decimal('100'))
    cut_b = min(max(vals['cover_tier_b_cut_pct'], cut_a), Decimal('100'))
    return {'months': {'A': vals['cover_tier_a_months'], 'B': vals['cover_tier_b_months'],
                       'C': vals['cover_tier_c_months']},
            'cut_a': cut_a, 'cut_b': cut_b}


def assign_tiers(rows, cut_a, cut_b) -> None:
    """Set row['tier'] in place by a Pareto on row['sales_value'] (one group = one branch).
    A row is A when the cumulative share BEFORE it is under cut_a % (so the item that crosses 80% is
    still A), B when under cut_b %, else C. Zero value is always C. Ties: item code, so the split is
    reproducible."""
    total = sum((r['sales_value'] for r in rows if r['sales_value'] > 0), ZERO)
    cum = ZERO
    for r in sorted(rows, key=lambda r: (-r['sales_value'], r['itemcode'])):
        if total <= 0 or r['sales_value'] <= 0:
            r['tier'] = 'C'
            continue
        share_before = cum * 100 / total
        r['tier'] = 'A' if share_before < cut_a else ('B' if share_before < cut_b else 'C')
        cum += r['sales_value']


def months_of_cover(stock, rate):
    """stock ÷ monthly rate; None when there is no rate."""
    rate = _dec(rate)
    if rate <= 0:
        return None
    return (max(_dec(stock), ZERO) / rate).quantize(CENT, ROUND_HALF_UP)


def line_need(rate, months, stock, transit) -> int:
    """Whole packs to reach rate × months, net of stock and in transit (ISR rule arithmetic)."""
    rate = _dec(rate)
    if rate <= 0:
        return 0
    return softech_need(rate * _dec(months), stock, transit)


def fit_budget(needs: dict, budget: Decimal) -> dict:
    """Fund the tiers in order A → B → C until the budget runs out. {tier: funded}, 'total', 'left'."""
    left = max(_dec(budget), ZERO)
    out = {}
    for t in TIERS:
        f = min(max(_dec(needs.get(t)), ZERO), left)
        out[t] = f
        left -= f
    out['total'] = sum((out[t] for t in TIERS), ZERO)
    out['left'] = left
    return out


def previous_month(today: dt.date):
    first = today.replace(day=1)
    end = first - dt.timedelta(days=1)
    return end.replace(day=1), end


def last_month_purchases(today: dt.date | None = None) -> dict:
    """Last calendar month's purchase value at real suppliers: doc 10 − doc 120 (net_value is signed)."""
    from django.db.models import Sum
    from apps.finance import supplier_terms as ST
    from apps.procurement.models import PurchaseLine
    today = today or dt.date.today()
    start, end = previous_month(today)
    value = (PurchaseLine.objects.filter(doccode__in=('10', '120'), doc_date__gte=start, doc_date__lte=end)
             .exclude(supplier_code__in=ST.internal_codes())
             .aggregate(s=Sum('net_value'))['s']) or ZERO
    return {'start': start, 'end': end, 'value': _dec(value).quantize(CENT, ROUND_HALF_UP),
            'month_label': f'{start:%Y-%m}'}


def latest_run():
    from .models import DemandCalculationRun
    return (DemandCalculationRun.objects.filter(status='success')
            .order_by('-finished_at', '-id').first())


def _metric_rows(run, branch_codes=None):
    """The run's retail-branch rows for orderable items (as isr_softech._items: stockable, not a
    planning-excluded medicine type, not return-only / stopped). branch_codes=None → every branch."""
    from apps.branches.models import Branch
    from apps.config.item_types import planning_excluded_codes
    from .models import ItemDemandMetrics
    branches = Branch.objects.retail()
    if branch_codes is not None:
        branches = branches.filter(softech_branch_id__in=list(branch_codes))
    qs = (ItemDemandMetrics.objects.filter(run=run, branch__in=branches, item__is_stockable=True)
          .exclude(item__medicine_type__in=planning_excluded_codes())
          .exclude(item__supplier_trans__in=['2', '3'])
          .values('item_id', 'item__softech_id', 'item__name', 'item__cost_price',
                  'branch__softech_branch_id', 'branch__name', 'branch__name_ar',
                  'monthly_avg', 'monthly_value', 'pack_price', 'current_stock', 'in_transit_qty'))
    return qs


def build_report(run=None, branch_codes=None, settings=None) -> dict:
    """Every line + the per-tier / per-branch summary. branch_codes = the codes in view (None = all).
    Tiers are computed per branch, so a branch's tiers never depend on which other branches are in view."""
    run = run or latest_run()
    st = settings or tier_settings()
    if run is None:
        return {'run': None, 'settings': st, 'lines': []}
    by_branch = {}
    for m in _metric_rows(run, branch_codes):
        rate = _dec(m['monthly_avg'])
        stock = _dec(m['current_stock'])
        if rate <= 0 and stock <= 0:
            continue                                    # nothing sold, nothing held: nothing to say
        value = _dec(m['monthly_value'])
        if value <= 0 and rate > 0:
            value = rate * _dec(m['pack_price'])
        code = str(m['branch__softech_branch_id']).strip()
        by_branch.setdefault(code, []).append({
            'item_id': m['item_id'], 'itemcode': str(m['item__softech_id'] or '').strip(),
            'name': m['item__name'] or '', 'branch_code': code,
            'branch_name': m['branch__name_ar'] or m['branch__name'] or code,
            'rate': rate, 'stock': stock, 'transit': _dec(m['in_transit_qty']),
            'cost': _dec(m['item__cost_price']), 'sales_value': value,
        })
    lines = []
    for code in sorted(by_branch):
        rows = by_branch[code]
        assign_tiers(rows, st['cut_a'], st['cut_b'])
        for r in rows:
            months = st['months'][r['tier']]
            target = r['rate'] * months
            need = line_need(r['rate'], months, r['stock'], r['transit'])
            cost = r['cost']
            r.update({
                'target_months': months,
                'cover_months': months_of_cover(r['stock'], r['rate']),
                'target_qty': target.quantize(CENT, ROUND_HALF_UP),
                'need_qty': need,
                'no_cost': cost <= 0,
                'stock_value': (max(r['stock'], ZERO) * cost).quantize(CENT, ROUND_HALF_UP),
                'monthly_cost': (r['rate'] * cost).quantize(CENT, ROUND_HALF_UP),
                'need_value': (Decimal(need) * cost).quantize(CENT, ROUND_HALF_UP),
                'excess_value': (max(r['stock'] - target, ZERO) * cost).quantize(CENT, ROUND_HALF_UP)
                if r['stock'] > 0 else ZERO,
                'at_zero': r['rate'] > 0 and r['stock'] <= 0,
            })
            lines.append(r)
    return {'run': run, 'settings': st, 'lines': lines}


def _blank():
    return {'lines': 0, 'sales_value': ZERO, 'stock_value': ZERO, 'monthly_cost': ZERO, 'need_value': ZERO,
            'excess_value': ZERO, 'lines_needing': 0, 'at_zero': 0, 'no_cost_needing': 0}


def _add(agg, l):
    agg['lines'] += 1
    for k in ('sales_value', 'stock_value', 'monthly_cost', 'need_value', 'excess_value'):
        agg[k] += l[k]
    if l['need_qty'] > 0:
        agg['lines_needing'] += 1
        if l['no_cost']:
            agg['no_cost_needing'] += 1
    if l['at_zero']:
        agg['at_zero'] += 1


def _finish(agg):
    mc = agg['monthly_cost']
    agg['cover_months'] = (agg['stock_value'] / mc).quantize(CENT, ROUND_HALF_UP) if mc > 0 else None
    return agg


def summarize(report, purchases=None) -> dict:
    """Per tier, per branch × tier and totals; the 75/100/125% budget fit when `purchases` is given.
    Cover per tier = stock value ÷ monthly cost of sales (both at cost), as the spec's measured table."""
    st = report['settings']
    tiers = {t: _blank() for t in TIERS}
    branches = {}
    total = _blank()
    for l in report['lines']:
        _add(tiers[l['tier']], l)
        _add(total, l)
        b = branches.setdefault(l['branch_code'], {'branch_code': l['branch_code'], 'branch_name': l['branch_name'],
                                                   'tiers': {t: _blank() for t in TIERS}, 'total': _blank()})
        _add(b['tiers'][l['tier']], l)
        _add(b['total'], l)
    for t in TIERS:
        _finish(tiers[t])
        tiers[t]['target_months'] = st['months'][t]
        tiers[t]['label'] = TIER_AR[t]
    _finish(total)
    for b in branches.values():
        for t in TIERS:
            _finish(b['tiers'][t])
        _finish(b['total'])
    out = {'tiers': tiers, 'total': total, 'branches': [branches[c] for c in sorted(branches)], 'budget': None}
    if purchases is not None:
        needs = {t: tiers[t]['need_value'] for t in TIERS}
        levels = []
        for pct in BUDGET_LEVELS:
            budget = (purchases['value'] * pct / 100).quantize(CENT, ROUND_HALF_UP)
            fit = fit_budget(needs, budget)
            levels.append({'pct': pct, 'budget': budget,
                           'funded': {t: fit[t] for t in TIERS}, 'funded_total': fit['total'],
                           'left': fit['left'], 'short': max(total['need_value'] - fit['total'], ZERO)})
        out['budget'] = {'purchases': purchases, 'levels': levels}
    return out
