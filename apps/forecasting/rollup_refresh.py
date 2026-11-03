"""
KPI rollup catch-up refresh  (doc 16)
=====================================
KpiActualRollup is the monthly source for the KPI board, forecast scenarios, backtest
and references. It used to be rebuilt for the CURRENT month only (06:30 daily), so a
month froze the moment it ended: the last days' sales synced on the 1st–3rd never
reached its rollup (Oct-2026 stuck 5.9% short), and a sleeping machine skipped the day.

Now a month is rebuilt whenever its sales changed after its rollup was computed:

  stale(y, m) = no rollup rows for the month
             OR max(PurchaseHistory.last_synced in the month) > min(rollup computed_at)

checked for the current month + the LOOKBACK previous months. The fast sales lane
re-touches today/yesterday every few minutes, so the CURRENT month is additionally
throttled to once per CURRENT_MIN_AGE (a closed month rebuilds as soon as late sales land).
Deep history is rebuilt by backfill_sales_history itself. Idempotent upserts only;
local DB only (the call-center step reads SOFTECH/Issabel, SELECT only).
"""
import logging
import threading
from datetime import date, datetime, time, timedelta

logger = logging.getLogger(__name__)

LOOKBACK_MONTHS = 2                       # previous months re-checked besides the current one
CURRENT_MIN_AGE = timedelta(hours=2)      # current-month rebuild throttle

_lock = threading.Lock()


def _shift(year, month, delta):
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def candidate_months(today=None):
    today = today or date.today()
    return [_shift(today.year, today.month, -k) for k in range(LOOKBACK_MONTHS, -1, -1)]


def _month_range(year, month):
    """Aware datetimes [start, next-month-start) in the project timezone."""
    from django.utils import timezone
    ny, nm = _shift(year, month, 1)
    tz = timezone.get_current_timezone()
    return (timezone.make_aware(datetime.combine(date(year, month, 1), time.min), tz),
            timezone.make_aware(datetime.combine(date(ny, nm, 1), time.min), tz))


def month_status(year, month, now=None):
    """{year, month, computed_at, sales_synced_at, stale, current} for one month."""
    from django.db.models import Max, Min
    from django.utils import timezone
    from apps.customers.models import PurchaseHistory
    from apps.forecasting.models import KpiActualRollup
    now = now or timezone.now()
    today = timezone.localdate(now)
    start, end = _month_range(year, month)
    computed = (KpiActualRollup.objects.filter(year=year, month=month)
                .exclude(branch__softech_branch_id='CC')
                .aggregate(m=Min('computed_at'))['m'])
    synced = (PurchaseHistory.objects.filter(invoice_date__gte=start, invoice_date__lt=end)
              .aggregate(m=Max('last_synced'))['m'])
    current = (year, month) == (today.year, today.month)
    if computed is None:
        stale = synced is not None or current
    else:
        stale = bool(synced and synced > computed)
        if stale and current and now - computed < CURRENT_MIN_AGE:
            stale = False
    return {'year': year, 'month': month, 'computed_at': computed,
            'sales_synced_at': synced, 'stale': stale, 'current': current}


def stale_months(today=None, now=None):
    return [(s['year'], s['month']) for s in
            (month_status(y, m, now=now) for (y, m) in candidate_months(today))
            if s['stale']]


def rebuild(months):
    """Rebuild branch + call-center rollups for the given months (oldest first)."""
    from django.core.management import call_command
    done = []
    for (y, m) in sorted(months):
        call_command('build_kpi_rollups', year=y, month=m, verbosity=0)
        try:
            call_command('build_call_center_rollups', year=y, month=m, verbosity=0)
        except Exception as exc:
            logger.warning('[kpi-refresh] CC rollup %s-%02d skipped: %s', y, m, exc)
        done.append((y, m))
    return done


def refresh(force_current=False):
    """Rebuild every stale candidate month (plus the current month when forced, e.g. the
    on-screen button). Returns the rebuilt months, or None when a refresh is already running."""
    if not _lock.acquire(blocking=False):
        return None
    try:
        months = set(stale_months())
        if force_current:
            today = date.today()
            months.add((today.year, today.month))
        done = rebuild(months)
        today = date.today()
        if any((y, m) < (today.year, today.month) for (y, m) in done):
            # a closed month changed → seasonality / YoY references follow it
            try:
                from apps.forecasting import references
                references.refresh_history()
            except Exception as exc:
                logger.warning('[kpi-refresh] references refresh skipped: %s', exc)
        return done
    finally:
        _lock.release()


def scheduled_tick():
    """Every 30 min from the scheduler — rebuilds only what is stale (catch-up after sleep)."""
    done = refresh()
    if done:
        logger.info('[APScheduler] KPI rollups rebuilt for %s',
                    ', '.join(f'{y}-{m:02d}' for y, m in done))
    return done


def status():
    """For the forecast/KPI freshness strip."""
    return {'running': _lock.locked(),
            'months': [month_status(y, m) for (y, m) in candidate_months()]}
