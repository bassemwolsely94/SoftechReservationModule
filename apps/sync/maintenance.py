"""
apps/sync/maintenance.py

Database retention + sync-run hygiene (P-56, docs/product-review/06_SPEC_P-56).
Everything here deletes or marks rows in OUR Postgres only — nothing touches SOFTECH.

  prune_engine_runs()   keep the per-item rows of the last 10 completed demand-engine runs
                        + the last completed run of each calendar month; delete the rest.
                        Run headers stay (history, FKs). Reviewed transfer recommendations
                        (approved / rejected / executed) are decisions and are never deleted.
                        Takes another keep set from the lifecycle rule `rate_runs`. Once that
                        rule is on, the daily step here does nothing and the rule does the
                        delete, so its circuit breaker stands in front of it.
  prune_audit_log()     only actions in DELETABLE_AUDIT_ACTIONS age out (365 days). Money,
                        SOFTECH writes, permissions and approvals are never deleted (Rule 8).
  prune_pbx_events()    raw AMI events older than 90 days.
  prune_notifications() read > 30 days, unread > 90 days (P-55 Part C); announcements excluded.
  prune_slow_requests() slow-request log older than 30 days.
  mark_stale_runs()     SyncRun rows 'running' for > 60 min → failed (process died).
  alert_failing_lanes() 3 failed runs in a row of one lane → one admin alert per lane per day
                        (P-55 Part B).
  run_daily_retention() all of the above, then a table-size snapshot (retention:table_sizes, rows written
                        are counted in its log line, nothing is deleted), the data lifecycle rules and the held-file purge
                        (apps/data_lifecycle/runner.py), as one logged SyncRun (lane 'retention').
                        Guarded by a Postgres advisory lock (RETENTION_LOCK_KEY): returns None,
                        creating no run row, when another process is already running it.
  retention_catchup_due() / run_retention_catchup()
                        safety net for a missed daily slot: due when no success in the last
                        OVERDUE_HOURS, nothing is running, and the last failed attempt is older
                        than RETENTION_RETRY_HOURS. Logged as 'retention:catchup'.
"""
import datetime
import logging

from django.db import connection, transaction
from django.db.models import Max
from django.db.models.functions import TruncMonth
from django.utils import timezone

logger = logging.getLogger('elrezeiky.sync')

KEEP_LAST_RUNS = 10
COMPLETED_RUN_STATUSES = ('success', 'partial')
BATCH = 10_000

STALE_RUN_MINUTES = 60

AUDIT_NOISE_DAYS = 365
# Explicit allow-list: only these actions may ever be deleted. Anything not listed
# (money, SOFTECH writes, permissions, approvals, new actions) is kept forever.
DELETABLE_AUDIT_ACTIONS = (
    'user_login',
    'user_login_failed',
    'sync_completed',
    'sync_failed',
)

PBX_EVENT_DAYS = 90
NOTIF_READ_DAYS = 30
NOTIF_UNREAD_DAYS = 90
SLOW_REQUEST_DAYS = 30

LOCK_TIMEOUT_SECONDS = 30          # a delete batch waiting longer than this for a row lock fails its step

RETENTION_LOCK_KEY = 7_301_102     # advisory lock: one retention run at a time
OVERDUE_HOURS = 26                 # no success for this long -> catch-up is due
RETENTION_RETRY_HOURS = 6          # wait this long after a failed attempt before retrying


def _batched_delete(qs, batch=BATCH):
    """Delete in primary-key batches so no single statement holds a long lock. Each batch is its own
    transaction with a lock timeout, so a row held by an idle-in-transaction session fails the step
    (the caller records it) instead of hanging the job."""
    total = 0
    while True:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT_SECONDS}s'")
            ids = list(qs.values_list('pk', flat=True)[:batch])
            if not ids:
                return total
            n, _ = qs.model.objects.filter(pk__in=ids).delete()
        total += n


def last_run_of_each_month(runs):
    """Ids of the last run of each calendar month in this queryset of runs."""
    last_per_month = (runs.annotate(month=TruncMonth('started_at'))
                      .values('month').annotate(last=Max('started_at')).values_list('last', flat=True))
    return set(runs.filter(started_at__in=list(last_per_month)).values_list('pk', flat=True))


def engine_runs_to_keep():
    """Ids of DemandCalculationRuns whose detail rows are kept."""
    from apps.purchasing.models import DemandCalculationRun
    completed = DemandCalculationRun.objects.filter(status__in=COMPLETED_RUN_STATUSES)
    keep = set(completed.order_by('-started_at').values_list('pk', flat=True)[:KEEP_LAST_RUNS])
    keep |= last_run_of_each_month(completed)
    # never touch a run that is still being written
    keep |= set(DemandCalculationRun.objects.filter(status='running').values_list('pk', flat=True))
    return keep


def engine_run_bound():
    """The highest DemandCalculationRun pk now. Read it BEFORE computing a keep set and pass it to
    engine_run_rows: a run created afterwards is in no keep set, so only the bound protects its rows."""
    from apps.purchasing.models import DemandCalculationRun
    return DemandCalculationRun.objects.aggregate(m=Max('pk'))['m'] or 0


def engine_run_rows(keep, max_run_id=None):
    """The detail rows of every run not in `keep` and not newer than `max_run_id`, by name.
    Pending recommendations only. None reads the bound now (callers that compute `keep` first should
    read it earlier, see engine_run_bound)."""
    from apps.purchasing.models import (ItemDemandAggregated, ItemDemandMetrics,
                                        TransferRecommendation)
    if max_run_id is None:
        max_run_id = engine_run_bound()
    return {
        'metrics': ItemDemandMetrics.objects.filter(run_id__lte=max_run_id).exclude(run_id__in=keep),
        'aggregated': ItemDemandAggregated.objects.filter(run_id__lte=max_run_id).exclude(run_id__in=keep),
        'transfer_recs': (TransferRecommendation.objects.filter(status='pending')
                          .filter(run__demand_run_id__lte=max_run_id)
                          .exclude(run__demand_run_id__in=keep)),
    }


def prune_engine_runs(keep=None, max_run_id=None):
    """`keep` is a set of run ids; None means engine_runs_to_keep(). `max_run_id` is the bound from
    engine_run_bound(), read before `keep` was computed; None reads it first here when `keep` is None."""
    if max_run_id is None:
        max_run_id = engine_run_bound()
    if keep is None:
        keep = engine_runs_to_keep()
    return {name: _batched_delete(rows) for name, rows in engine_run_rows(keep, max_run_id).items()}


def _prune_engine_runs_step():
    """The P-56 step. Once the lifecycle rule rate_runs is on, it does the delete behind its circuit
    breaker; deleting here first would go round the breaker and drop runs the rule keeps."""
    from apps.data_lifecycle.models import MODE_ON
    from apps.data_lifecycle.policy import get_mode
    if get_mode('rate_runs') == MODE_ON:
        return 0
    return sum(prune_engine_runs().values())


def prune_audit_log(days=AUDIT_NOISE_DAYS):
    from apps.audit.models import AuditLog
    cutoff = timezone.now() - datetime.timedelta(days=days)
    return _batched_delete(AuditLog.objects.filter(action__in=DELETABLE_AUDIT_ACTIONS,
                                                   created_at__lt=cutoff))


def prune_pbx_events(days=PBX_EVENT_DAYS):
    from apps.pbx.models import PBXEvent
    cutoff = timezone.now() - datetime.timedelta(days=days)
    return _batched_delete(PBXEvent.objects.filter(received_at__lt=cutoff))


def prune_notifications(read_days=NOTIF_READ_DAYS, unread_days=NOTIF_UNREAD_DAYS):
    """NotificationLog rows cascade with their notification."""
    from apps.notifications.models import Notification
    now = timezone.now()
    base = Notification.objects.exclude(notification_type='announcement')
    read = _batched_delete(base.filter(is_read=True, created_at__lt=now - datetime.timedelta(days=read_days)))
    unread = _batched_delete(base.filter(is_read=False, created_at__lt=now - datetime.timedelta(days=unread_days)))
    return read + unread


def prune_slow_requests(days=SLOW_REQUEST_DAYS):
    from apps.sync.models import SlowRequest
    cutoff = timezone.now() - datetime.timedelta(days=days)
    return _batched_delete(SlowRequest.objects.filter(at__lt=cutoff))


def prune_screen_views():
    """P-57 usage telemetry — 12 months. No-op until that model exists."""
    try:
        from apps.audit.models import ScreenView
    except ImportError:
        return 0
    cutoff = timezone.now() - datetime.timedelta(days=365)
    return _batched_delete(ScreenView.objects.filter(at__lt=cutoff))


def mark_stale_runs(minutes=STALE_RUN_MINUTES):
    from apps.sync.models import SyncRun
    now = timezone.now()
    return (SyncRun.objects
            .filter(status='running', started_at__lt=now - datetime.timedelta(minutes=minutes))
            .update(status='failed', completed_at=now,
                    error_message=f'stale — still "running" after {minutes} min; the process died'))


FAILURES_IN_A_ROW = 3

LANE_LABELS = {
    'fast': 'المخزون والمبيعات', 'slow': 'الأصناف والعملاء', 'full': 'المزامنة الكاملة',
    'items': 'الأصناف', 'retention': 'تنظيف قاعدة البيانات', 'morning_chain': 'مهام الصباح',
}


def alert_failing_lanes(in_a_row=FAILURES_IN_A_ROW):
    """One notification to admins for every lane whose last `in_a_row` finished runs all
    failed. Deduped per lane per day, so the heartbeat can call this every minute.
    Returns the lanes alerted."""
    from apps.sync.models import SyncRun
    lanes = (SyncRun.objects.exclude(lane='').exclude(status='running')
             .values_list('lane', flat=True).distinct())
    today = timezone.localdate().isoformat()
    alerted = []
    for lane in lanes:
        last = list(SyncRun.objects.filter(lane=lane).exclude(status='running')
                    .order_by('-started_at').values_list('status', 'error_message')[:in_a_row])
        if len(last) < in_a_row or any(st != 'failed' for st, _ in last):
            continue
        label = LANE_LABELS.get(lane, lane)
        body = (f'آخر {in_a_row} تشغيلات لمزامنة «{label}» فشلت. آخر خطأ: '
                f'{(last[0][1] or "—")[:300]} — راجع صفحة المزامنة.')
        _alert_admins(f'🔴 فشل متكرر في مزامنة «{label}»', body, f'sync_failure_{lane}_{today}')
        alerted.append(lane)
    return alerted


def _alert_admins(title, body, dedup_key):
    """Send one sync_failure notification to every active admin (deduped once per key)."""
    from apps.notifications.models import Notification
    from apps.users.models import StaffProfile
    for staff in StaffProfile.objects.filter(role='admin', is_active=True).select_related('branch'):
        Notification.send_to_user(staff, 'sync_failure', title, body,
                                  dedup_key=dedup_key, dedup_once=True, bypass_role_gate=True)


MISSED_RUN_LANES = ('retention', 'morning_chain')


def alert_missed_runs(now=None):
    """Admin alert for every daily lane with no success for OVERDUE_HOURS (or, when it
    never succeeded, whose first attempt is that old). Skips lanes with no rows or a run in
    progress. Deduped per lane per day. Returns the lanes alerted."""
    from apps.sync.models import SyncRun
    now = now or timezone.now()
    cutoff = now - datetime.timedelta(hours=OVERDUE_HOURS)
    today = timezone.localdate().isoformat()
    alerted = []
    for lane in MISSED_RUN_LANES:
        runs = SyncRun.objects.filter(lane=lane)
        if not runs.exists() or runs.filter(status='running').exists():
            continue
        ref = (runs.filter(status='success').aggregate(m=Max('started_at'))['m']
               or runs.order_by('started_at').values_list('started_at', flat=True).first())
        if ref >= cutoff:
            continue
        label = LANE_LABELS[lane]
        _alert_admins(f'🟠 لم تكتمل مهمة «{label}»',
                      f'لم تنجح مهمة «{label}» منذ أكثر من {OVERDUE_HOURS} ساعة. غالباً كان المجدول '
                      f'أو الجهاز متوقفاً، أو أن المهمة فشلت — راجع صفحة المزامنة.',
                      f'missed_run_{lane}_{today}')
        alerted.append(lane)
    return alerted


def retention_watch():
    """Every 15 min: run the retention catch-up if due, then raise the missed-run alert.
    Never raises; the morning chain is only alerted on, never run, from here."""
    try:
        run_retention_catchup()
    except Exception:
        logger.exception('[retention] catch-up failed')
    try:
        alert_missed_runs()
    except Exception:
        logger.exception('[retention] missed-run alert failed')


def _run_lifecycle_rules():
    # Imported here: the lifecycle app imports this module, and an import failure stays one failed step.
    from apps.data_lifecycle.runner import run_lifecycle_rules
    return run_lifecycle_rules()


def _snapshot_table_sizes():
    from apps.data_lifecycle.runner import snapshot_table_sizes
    return snapshot_table_sizes()


def _purge_held_files():
    from apps.data_lifecycle.runner import purge_held_files
    return purge_held_files()


def _take_data_health_snapshot():
    from apps.data_lifecycle.health import take_snapshot
    return 1 if take_snapshot() else 0


def run_daily_retention():
    """One SyncRun (lane 'retention') with a SyncLog per table. A failing step is
    logged and the others still run. Returns None (no run row) when another
    process holds the retention lock.

    RULE: the lock is a session lock on this thread's Django connection. No step, and nothing a step
    calls, may call close_old_connections() or connections.close_all(): that drops the lock silently
    and a second run could start."""
    from apps.vouchers.coupon_dashboard import pg_lock
    steps = [
        ('retention:engine_runs', _prune_engine_runs_step),
        ('retention:notifications', prune_notifications),
        ('retention:pbx_events', prune_pbx_events),
        ('retention:audit_log', prune_audit_log),
        ('retention:slow_requests', prune_slow_requests),
        ('retention:screen_views', prune_screen_views),
        ('retention:table_sizes', _snapshot_table_sizes),
        ('retention:lifecycle', _run_lifecycle_rules),
        ('retention:purge_held', _purge_held_files),
        ('retention:data_health', _take_data_health_snapshot),
    ]
    with pg_lock(RETENTION_LOCK_KEY) as got:
        if not got:
            logger.warning('[retention] another run holds the lock; skipping')
            return None
        return _run_retention_steps(steps)


# Steps whose count is rows written, not removed: kept on their SyncLog line, left out of the run's total.
NOT_REMOVAL_STEPS = frozenset({'retention:table_sizes'})


def _run_retention_steps(steps):
    from apps.sync.models import SyncLog, SyncRun
    run = SyncRun.objects.create(status='running', lane='retention')
    errors, total = [], 0
    for name, fn in steps:
        try:
            n = fn()
            if name not in NOT_REMOVAL_STEPS:
                total += n
            SyncLog.objects.create(sync_run=run, table_name=name, records_processed=n)
        except Exception as exc:
            logger.exception('[retention] %s failed', name)
            errors.append(f'{name}: {exc}')
    run.status = 'failed' if errors else 'success'
    run.error_message = '\n'.join(errors)
    run.records_synced = total
    run.completed_at = timezone.now()
    run.save()
    logger.info('[retention] removed %s%s', total, f' ({len(errors)} step(s) failed)' if errors else '')
    return run


def retention_catchup_due(now=None):
    """True when the daily retention slot was missed: nothing running, no success within
    OVERDUE_HOURS, and the latest attempt is not a failure younger than RETENTION_RETRY_HOURS."""
    from apps.sync.models import SyncRun
    now = now or timezone.now()
    runs = SyncRun.objects.filter(lane='retention')
    if runs.filter(status='running').exists():
        return False
    last_ok = runs.filter(status='success').order_by('-started_at').first()
    if last_ok and last_ok.started_at > now - datetime.timedelta(hours=OVERDUE_HOURS):
        return False
    last = runs.order_by('-started_at').first()
    if (last and last.status == 'failed'
            and last.started_at > now - datetime.timedelta(hours=RETENTION_RETRY_HOURS)):
        return False
    return True


def run_retention_catchup():
    """Run the daily retention now when it is overdue. Returns the SyncRun or None."""
    if not retention_catchup_due():
        return None
    run = run_daily_retention()
    if run is None:
        return None
    from apps.sync.models import SyncLog
    SyncLog.objects.create(sync_run=run, table_name='retention:catchup', records_processed=1)
    return run
