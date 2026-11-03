"""PIC Analytics definitions as pure, deterministic functions.

Contract: docs/architecture/33_PIC_ANALYTICS.md section 4. Every number on the screen and in the
Excel report is computed by these rules, never by an LLM. Dates are Cairo-local calendar dates.

- Visit: a PIC's distinct calendar days with a sale (same-day invoices are one visit).
- Months bought (A): distinct calendar months with a visit in the 12 months ending at `end`'s month.
- Longest streak (B): longest run of consecutive months with a visit in that same 12-month window.
- Buying cycle (C): mean gap in days between distinct visit days (None under 2 visits), bucketed.
- Overdue: days since last visit exceed factor x own cycle.
- New / returning / reactivated: first purchase in the period and recently created = new;
  otherwise reactivated if the previous visit was 365+ days before the period visit; else returning.
- Retention: share of the previous period's PICs that bought again this period.
"""
from datetime import date, timedelta


def _month_index(d: date) -> int:
    return d.year * 12 + d.month - 1


def _window_months(visit_days, end: date) -> set[int]:
    """Distinct month indexes with a visit inside the 12 calendar months ending with end's month."""
    last = _month_index(end)
    first = last - 11
    return {m for m in (_month_index(d) for d in visit_days) if first <= m <= last}


def months_bought(visit_days: list[date], end: date) -> int:
    """A: distinct months with a visit over the 12 calendar months ending at end's month (1-12)."""
    return len(_window_months(visit_days, end))


def longest_streak(visit_days: list[date], end: date) -> int:
    """B: longest run of consecutive months with a visit, inside the same 12-month window (0-12)."""
    months = sorted(_window_months(visit_days, end))
    best = run = 0
    prev = None
    for m in months:
        run = run + 1 if prev is not None and m == prev + 1 else 1
        best = max(best, run)
        prev = m
    return best


def cycle_days(visit_days: list[date]) -> float | None:
    """C: mean days between consecutive distinct visit days; None with fewer than 2 distinct days."""
    days = sorted(set(visit_days))
    if len(days) < 2:
        return None
    gaps = [(b - a).days for a, b in zip(days, days[1:])]
    return sum(gaps) / len(gaps)


def cycle_bucket(days: float | None) -> str:
    """C bucket with inclusive upper bounds: m1 <=31, m2 <=62, m3 <=93, m4_6 <=186, m7_12 <=365, else y1plus."""
    if days is None:
        return ''
    if days <= 31:
        return 'm1'
    if days <= 62:
        return 'm2'
    if days <= 93:
        return 'm3'
    if days <= 186:
        return 'm4_6'
    if days <= 365:
        return 'm7_12'
    return 'y1plus'


def is_overdue(last_visit: date, cycle: float | None, today: date, factor: float) -> bool:
    """Overdue: days since last visit exceed factor x the PIC's own buying cycle. No cycle, not overdue."""
    if cycle is None:
        return False
    return (today - last_visit).days > factor * cycle


def classify_pic(
    first_purchase: date,
    created_at: date | None,
    prev_visit: date | None,
    period_start: date,
    period_end: date,
    first_visit_in_period: date,
) -> str:
    """New / reactivated / returning for a PIC that bought in the period.

    new: first purchase in the period and created no earlier than period start - 30 days
         (created_at unknown falls back to first purchase only).
    reactivated: not new, and the previous visit was 365+ days before the first visit in the period.
    returning: everything else.
    """
    if period_start <= first_purchase <= period_end and (
        created_at is None or created_at >= period_start - timedelta(days=30)
    ):
        return 'new'
    if prev_visit is not None and (first_visit_in_period - prev_visit).days >= 365:
        return 'reactivated'
    return 'returning'


def retention(prev_pics: set, cur_pics: set) -> float | None:
    """Share of the previous period's PICs that bought again this period; None if there were none."""
    if not prev_pics:
        return None
    return len(prev_pics & cur_pics) / len(prev_pics)
