"""
apps/data_lifecycle/rules_rows.py

What the row rules of register.py select. Imports nothing from register.py, which imports this.

Company-level by nature, no branch scoping; see models.py. No SOFTECH reads or writes.
"""
import datetime
import re

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from apps.sync.maintenance import (
    COMPLETED_RUN_STATUSES, engine_run_bound, engine_run_rows, last_run_of_each_month, prune_engine_runs,
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
    bound = engine_run_bound()      # before the keep set: a run created after it is never a candidate
    return list(engine_run_rows(tight_runs_to_keep(), bound).values())


CLOSED_TRANSIT_STATUSES = ('received', 'cancelled', 'force_closed')
OPEN_TRANSIT_STATUSES = ('in_transit', 'erp_mismatch', 'expired_pending')

# The text sync_in_transit.py writes. The level of a note is the label in (...) after the prefix, `local` when
# there is none; the level of an event is the word after `level=`. Mismatch notes (`🔔 تباين`) and
# `erp_mismatch:` events start differently and never match.
AUTO_NOTE_PREFIX = '🔔 تنبيه تلقائي'
AUTO_EVENT_PREFIX = 'level='
_NOTE_LEVEL = re.compile(r'^\s*\(([^)]*)\)')
_EVENT_LEVEL = re.compile(r'^level=([^,\s]*)')


def _transit_cutoff(key, now=None):
    from .policy import keep_days    # policy imports register, which imports this module
    return (now or timezone.now()) - datetime.timedelta(days=keep_days(key))


def _note_level(body):
    match = _NOTE_LEVEL.match(body[len(AUTO_NOTE_PREFIX):])
    return match.group(1) if match else 'local'


def _event_level(event):
    action, detail = event
    return 'synced' if action == 'synced' else _EVENT_LEVEL.match(detail).group(1)


def _all_but_latest(model, rows, level_of):
    """Pks of rows (pk, transfer_id, created_at, ...) except the latest per (transfer, level)."""
    latest = {}
    for row in rows:
        key = (row[1], level_of(row[3:]))
        if key not in latest or (row[2], row[0]) > (latest[key][2], latest[key][0]):
            latest[key] = row
    keep = {row[0] for row in latest.values()}
    return model.objects.filter(pk__in=[row[0] for row in rows if row[0] not in keep])


def transit_alert_notes_candidates(now=None):
    from apps.transits.models import InTransitNote
    auto = InTransitNote.objects.filter(note_type='alert', body__startswith=AUTO_NOTE_PREFIX)
    closed = auto.filter(transfer__transit_status__in=CLOSED_TRANSIT_STATUSES,
                         transfer__updated_at__lt=_transit_cutoff('transit_alert_notes', now))
    rows = list(auto.filter(transfer__transit_status__in=OPEN_TRANSIT_STATUSES)
                .values_list('pk', 'transfer_id', 'created_at', 'body'))
    return [closed, _all_but_latest(InTransitNote, rows, lambda tail: _note_level(tail[0]))]


def transit_audit_events_candidates(now=None):
    from django.db.models import Q
    from apps.transits.models import InTransitAuditEvent
    auto = InTransitAuditEvent.objects.filter(
        Q(action='alert_sent', detail__startswith=AUTO_EVENT_PREFIX) | Q(action='synced'))
    closed = auto.filter(transfer__transit_status__in=CLOSED_TRANSIT_STATUSES,
                         transfer__updated_at__lt=_transit_cutoff('transit_audit_events', now))
    rows = list(auto.filter(transfer__transit_status__in=OPEN_TRANSIT_STATUSES)
                .values_list('pk', 'transfer_id', 'created_at', 'action', 'detail'))
    return [closed, _all_but_latest(InTransitAuditEvent, rows, _event_level)]


def rate_runs_apply():
    """prune_engine_runs stays the only code that deletes these rows. Returns the count removed."""
    bound = engine_run_bound()      # before the keep set, see rate_runs_candidates
    return sum(prune_engine_runs(keep=tight_runs_to_keep(), max_run_id=bound).values())
