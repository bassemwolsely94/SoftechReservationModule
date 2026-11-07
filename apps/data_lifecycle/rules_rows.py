"""
apps/data_lifecycle/rules_rows.py

What the row rules of register.py select. Imports nothing from register.py, which imports this.

Company-level by nature, no branch scoping; see models.py. No SOFTECH reads or writes.
"""
import datetime

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from apps.sync.maintenance import (
    COMPLETED_RUN_STATUSES, engine_run_rows, last_run_of_each_month, prune_engine_runs,
)

KEEP_RECENT_RUNS = 3
KEEP_MONTHLY_MONTHS = 24
OPEN_PUSH_HOLD_DAYS = 90      # a forgotten draft must not hold its run forever (design §5.2)
OPEN_PUSH_STATUSES = ('proposed', 'approved')

# What each reader of "the latest run" orders by, over status='success' as they all filter:
# rate_writer -finished_at,-id; spike_views -id; shortage and purchasing.views -started_at.
READER_LATEST_ORDERINGS = (('-finished_at', '-id'), ('-id',), ('-started_at',))


def tight_runs_to_keep(now=None):
    """Ids of DemandCalculationRuns whose detail rows the rate_runs rule keeps.

    The monthly window is the current calendar month plus the 24 before it, so a month is whole or gone.
    Other stored references were checked and hold nothing: CoverageTopUp and PivotSheetSnapshot have no open
    state and no reader of their run's rows; ShortageSnapshot and DeadStockSnapshot hang off the header.
    """
    from apps.purchasing.models import DemandCalculationRun, IsrPush, SalesRatePush
    now = now or timezone.now()
    runs = DemandCalculationRun.objects
    completed = runs.filter(status__in=COMPLETED_RUN_STATUSES)

    keep = set(completed.order_by('-started_at').values_list('pk', flat=True)[:KEEP_RECENT_RUNS])
    for ordering in READER_LATEST_ORDERINGS:
        keep.update(runs.filter(status='success').order_by(*ordering).values_list('pk', flat=True)[:1])

    month_start = timezone.localtime(now).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    keep |= last_run_of_each_month(completed.filter(started_at__gte=month_start - relativedelta(
        months=KEEP_MONTHLY_MONTHS)))

    keep |= set(runs.filter(status='running').values_list('pk', flat=True))

    hold_from = now - datetime.timedelta(days=OPEN_PUSH_HOLD_DAYS)
    for push_model in (IsrPush, SalesRatePush):
        keep |= set(push_model.objects
                    .filter(status__in=OPEN_PUSH_STATUSES, created_at__gte=hold_from, run__isnull=False)
                    .values_list('run_id', flat=True))
    return keep


def rate_runs_candidates():
    """The same querysets rate_runs_apply deletes, so a preview counts what a real run removes."""
    return list(engine_run_rows(tight_runs_to_keep()).values())


def rate_runs_apply():
    """prune_engine_runs stays the only code that deletes these rows. Returns the count removed."""
    return sum(prune_engine_runs(keep=tight_runs_to_keep()).values())
