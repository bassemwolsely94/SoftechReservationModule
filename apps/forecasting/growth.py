"""
GrowthService  (doc 16 metric-catalog Phase 2)
==============================================
Period-over-period comparison for any metric + scope. Supports:
  month  → MoM (previous month) · YoY (same month last year)
  quarter→ QoQ (previous quarter, rolling into prior year for Q1)
           · YoY / same-quarter-last-year (same quarter, previous year)

Returns {current, comparison, delta, pct} — reuses KpiResolver so numbers agree
with the board/targets.
"""
from calendar import monthrange
from datetime import date
from decimal import Decimal


def _month_bounds(year, month):
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def _quarter_bounds(year, q):
    m0 = (q - 1) * 3 + 1
    start = date(year, m0, 1)
    end = date(year, m0 + 2, monthrange(year, m0 + 2)[1])
    return start, end


def _shift_month(year, month, delta):
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def _shift_quarter(year, q, delta):
    idx = year * 4 + (q - 1) + delta
    return idx // 4, idx % 4 + 1


class GrowthService:
    COMPARISONS = {'mom', 'yoy', 'qoq', 'yoy_quarter'}

    def __init__(self):
        from apps.forecasting.kpi import KpiResolver
        self.resolver = KpiResolver()

    def compare(self, metric, *, year, period, period_type='month',
                comparison='yoy', **scope_kwargs):
        """
        period_type='month': period = 1..12 ; period_type='quarter': period = 1..4.
        scope_kwargs: branch_ids / softech_user / category_id (passed to resolver).
        """
        if period_type == 'quarter':
            cur_s, cur_e = _quarter_bounds(year, period)
            if comparison == 'qoq':
                cy, cp = _shift_quarter(year, period, -1)
            else:  # yoy / yoy_quarter — same quarter, previous year
                cy, cp = year - 1, period
            cmp_s, cmp_e = _quarter_bounds(cy, cp)
            cmp_label = f'{cy}-Q{cp}'
            cur_label = f'{year}-Q{period}'
        else:
            cur_s, cur_e = _month_bounds(year, period)
            if comparison == 'mom':
                cy, cp = _shift_month(year, period, -1)
            else:  # yoy — same month, previous year
                cy, cp = year - 1, period
            cmp_s, cmp_e = _month_bounds(cy, cp)
            cmp_label = f'{cy}-{cp:02d}'
            cur_label = f'{year}-{period:02d}'

        cur = self.resolver.resolve(metric, start=cur_s, end=cur_e, **scope_kwargs)
        cmp = self.resolver.resolve(metric, start=cmp_s, end=cmp_e, **scope_kwargs)
        delta = cur - cmp
        pct = (delta / cmp * 100) if cmp else None
        return {
            'metric': metric, 'comparison': comparison, 'period_type': period_type,
            'current_label': cur_label, 'current': float(cur),
            'comparison_label': cmp_label, 'comparison_value': float(cmp),
            'delta': float(delta),
            'pct': round(float(pct), 2) if pct is not None else None,
        }
