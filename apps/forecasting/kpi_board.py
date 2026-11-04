"""
KPI board maths shared by ``KpiBoardView`` and the branch morning brief.

Pure extraction of what the board computed inline: BOARD_METRICS, the latest complete data day,
the month pacing (elapsed/total/fraction), the per-cell pace and % (vs the target pro-rated to
the latest complete day), and ``branch_mtd`` which gives one branch's month-to-date numbers.
The view and the brief both call these, so the two can never disagree.
"""
from calendar import monthrange
from datetime import date
from decimal import Decimal

from .models import KpiActualRollup

BOARD_METRICS = [
    KpiActualRollup.M_CASH_DELIVERY, KpiActualRollup.M_CREDIT,
    KpiActualRollup.M_GROSS_PROFIT, KpiActualRollup.M_CUSTOMERS,
    KpiActualRollup.M_BEAUTY,
]
# The metric the brief reports as «المبيعات»: the board's first column (the cash+delivery target).
SALES_METRIC = KpiActualRollup.M_CASH_DELIVERY


def latest_complete_date(year, month):
    """Last day of the month with COMPLETE sales data, for correct to-date pacing:
      • month fully over → its last day;  • future month → None;
      • in-progress → the latest synced sales day strictly before today (today is partial)."""
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


def month_pacing(year, month):
    """(m_start, m_end, data_through, total_days, elapsed_days, fraction)."""
    m_start = date(year, month, 1)
    m_end = date(year, month, monthrange(year, month)[1])
    data_through = latest_complete_date(year, month)
    total = (m_end - m_start).days + 1
    elapsed = ((data_through - m_start).days + 1) if data_through else 0
    frac = (elapsed / total) if total else 0
    return m_start, m_end, data_through, total, elapsed, frac


def pace(a, t, data_through, m_end, frac):
    if not t:
        return None
    if data_through is None:
        return 'pending'
    if data_through >= m_end:
        return 'met' if a >= t else 'missed'
    return 'ahead' if a >= (t * frac) else 'behind'


def make_cell(a, t, tid, data_through, m_end, frac):
    exp = (t * frac) if t else 0                       # target pro-rated to data_through
    return {
        'actual': round(a, 2),
        'target': (round(t, 2) if t else None),        # full-month target
        'target_todate': (round(exp, 2) if t else None),
        'pct': (round(a / exp * 100, 1) if exp else None),      # vs to-date (legacy %)
        'pct_full': (round(a / t * 100, 1) if t else None),     # progress vs full month
        'pace': pace(a, t, data_through, m_end, frac), 'target_id': tid,
    }


def month_targets(m_start, m_end, metrics, scope_types, branch_ids=None):
    """Editable targets overlapping the month, as dict rows ordered by id.

    The view and ``branch_mtd`` both read targets only through here and build their lookup by
    iterating in this order (last row wins), so overlapping targets resolve to the same row
    (the newest id) in both."""
    from apps.incentives.models import SalesTarget
    qs = SalesTarget.objects.filter(metric__in=metrics, period_start__lte=m_end,
                                    period_end__gte=m_start, scope_type__in=scope_types)
    if branch_ids is not None:
        qs = qs.filter(branch_id__in=list(branch_ids))
    return qs.order_by('id').values('id', 'scope_type', 'branch_id', 'metric', 'target_value')


def _dec(value):
    return None if value is None else Decimal(str(value))


def branch_mtd(branch_ids, year, month):
    """Month-to-date sales vs target per branch, exactly as the KPI board shows them.

    ``{branch_id: {'actual', 'target', 'pct', 'daily_needed', 'as_of'}}`` for the board's sales
    column (``SALES_METRIC``). ``target``/``pct`` are None without a target; ``pct`` is vs the
    target pro-rated to ``as_of`` (the latest complete data day); ``daily_needed`` is what each
    remaining day must sell to reach the full-month target (None when no target / month done).
    """
    from apps.incentives.models import SalesTarget
    ids = list(branch_ids)
    m_start, m_end, data_through, _total, _elapsed, frac = month_pacing(year, month)
    actual = {r['branch_id']: float(r['value']) for r in KpiActualRollup.objects.filter(
        year=year, month=month, metric=SALES_METRIC, branch_id__in=ids).values('branch_id', 'value')}
    target = {}
    for t in month_targets(m_start, m_end, [SALES_METRIC], [SalesTarget.SCOPE_BRANCH], ids):
        if t['branch_id']:
            target[t['branch_id']] = float(t['target_value'] or 0)
    out = {}
    for bid in ids:
        a, t = actual.get(bid, 0.0), target.get(bid, 0.0)
        c = make_cell(a, t, None, data_through, m_end, frac)
        daily = None
        if t and data_through is not None and data_through < m_end:
            remaining = (m_end - data_through).days
            daily = _dec(round(max(t - a, 0) / remaining, 2)) if remaining else None
        out[bid] = {'actual': _dec(c['actual']), 'target': _dec(c['target']),
                    'pct': _dec(c['pct']), 'daily_needed': daily, 'as_of': data_through}
    return out
