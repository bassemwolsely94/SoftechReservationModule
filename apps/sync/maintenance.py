"""
apps/sync/maintenance.py

Database retention + sync-run hygiene (P-56, docs/product-review/06_SPEC_P-56).
Everything here deletes or marks rows in OUR Postgres only — nothing touches SOFTECH.

  prune_engine_runs()   keep the per-item rows of the last 10 completed demand-engine runs
                        + the last completed run of each calendar month; delete the rest.
                        Run headers stay (history, FKs). Reviewed transfer recommendations
                        (approved / rejected / executed) are decisions and are never deleted.
  prune_audit_log()     only actions in DELETABLE_AUDIT_ACTIONS age out (365 days). Money,
                        SOFTECH writes, permissions and approvals are never deleted (Rule 8).
  prune_pbx_events()    raw AMI events older than 90 days.
  prune_notifications() read > 30 days, unread > 90 days (P-55 Part C); announcements excluded.
  prune_slow_requests() slow-request log older than 30 days.
  mark_stale_runs()     SyncRun rows 'running' for > 60 min → failed (process died).
  alert_failing_lanes() 3 failed runs in a row of one lane → one admin alert per lane per day
                        (P-55 Part B).
  run_daily_retention() all of the above as one logged SyncRun (lane 'retention'). Guarded by a
                        Postgres advisory lock (RETENTION_LOCK_KEY): returns None, creating no
                        run row, when another process is already running it.
  retention_catchup_due() / run_retention_catchup()
                        safety net for a missed daily slot: due when no success in the last
                        OVERDUE_HOURS, nothing is running, and the last failed attempt is older
                        than RETENTION_RETRY_HOURS. Logged as 'retention:catchup'.
"""
import datetime
import logging

from django.db.models import Max
from django.db.models.functions import TruncMonth
from django.utils import timezone

logger = logging.getLogger('elrezeiky.sync')

KEEP_LAST_RUNS = 10
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

RETENTION_LOCK_KEY = 7_301_102     # advisory lock: one retention run at a time
OVERDUE_HOURS = 26                 # no success for this long -> catch-up is due
RETENTION_RETRY_HOURS = 6          # wait this long after a failed attempt before retrying

MORNING_CHAIN_LOCK_KEY = 7_301_103  # advisory lock: one morning chain at a time (07:30 job or catch-up)
MORNING_CHAIN_SLOT = (7, 30)        # local time of the scheduled morning chain
SOFTECH_UP_MINUTES = 30             # a fast sync must have succeeded this recently before a catch-up


def _batched_delete(qs, batch=BATCH):
    """Delete in primary-key batches so no single statement holds a long lock."""
    total = 0
    while True:
        ids = list(qs.values_list('pk', flat=True)[:batch])
        if not ids:
            return total
        n, _ = qs.model.objects.filter(pk__in=ids).delete()
        total += n


def engine_runs_to_keep():
    """Ids of DemandCalculationRuns whose detail rows are kept."""
    from apps.purchasing.models import DemandCalculationRun
    completed = DemandCalculationRun.objects.filter(status__in=['success', 'partial'])
    keep = set(completed.order_by('-started_at').values_list('pk', flat=True)[:KEEP_LAST_RUNS])
    last_per_month = (completed.annotate(month=TruncMonth('started_at'))
                      .values('month').annotate(last=Max('started_at')).values_list('last', flat=True))
    keep |= set(completed.filter(started_at__in=list(last_per_month)).values_list('pk', flat=True))
    # never touch a run that is still being written
    keep |= set(DemandCalculationRun.objects.filter(status='running').values_list('pk', flat=True))
    return keep


def prune_engine_runs():
    from apps.purchasing.models import (ItemDemandAggregated, ItemDemandMetrics,
                                        TransferRecommendation)
    keep = engine_runs_to_keep()
    out = {
        'metrics': _batched_delete(ItemDemandMetrics.objects.exclude(run_id__in=keep)),
        'aggregated': _batched_delete(ItemDemandAggregated.objects.exclude(run_id__in=keep)),
        'transfer_recs': _batched_delete(
            TransferRecommendation.objects.filter(status='pending')
            .exclude(run__demand_run_id__in=keep)),
    }
    return out


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
    """Every 15 min: run the retention catch-up and the morning-chain catch-up if due, then
    raise the missed-run alert. Never raises; each step is isolated from the others."""
    try:
        run_retention_catchup()
    except Exception:
        logger.exception('[retention] catch-up failed')
    try:
        run_morning_chain_catchup()
    except Exception:
        logger.exception('[morning_chain] catch-up failed')
    try:
        alert_missed_runs()
    except Exception:
        logger.exception('[retention] missed-run alert failed')


def run_daily_retention():
    """One SyncRun (lane 'retention') with a SyncLog per table. A failing step is
    logged and the others still run. Returns None (no run row) when another
    process holds the retention lock."""
    from apps.vouchers.coupon_dashboard import pg_lock
    steps = [
        ('retention:engine_runs', lambda: sum(prune_engine_runs().values())),
        ('retention:notifications', prune_notifications),
        ('retention:pbx_events', prune_pbx_events),
        ('retention:audit_log', prune_audit_log),
        ('retention:slow_requests', prune_slow_requests),
        ('retention:screen_views', prune_screen_views),
    ]
    with pg_lock(RETENTION_LOCK_KEY) as got:
        if not got:
            logger.warning('[retention] another run holds the lock; skipping')
            return None
        return _run_retention_steps(steps)


def _run_retention_steps(steps):
    from apps.sync.models import SyncLog, SyncRun
    run = SyncRun.objects.create(status='running', lane='retention')
    errors, total = [], 0
    for name, fn in steps:
        try:
            n = fn()
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
    logger.info('[retention] deleted %s rows%s', total, f' ({len(errors)} step(s) failed)' if errors else '')
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


def morning_chain_catchup_due(now=None):
    """True when today's 07:30 morning chain was missed and SOFTECH is reachable again (owner
    decision 2026-11-11). Its steps swallow their own errors, so a run while SOFTECH is down
    would read as a success; requiring a recent successful fast sync avoids that. At most one
    run per day, and a failed attempt waits RETENTION_RETRY_HOURS."""
    from apps.sync.models import SyncRun
    now = now or timezone.now()
    local = timezone.localtime(now)
    slot = local.replace(hour=MORNING_CHAIN_SLOT[0], minute=MORNING_CHAIN_SLOT[1], second=0, microsecond=0)
    if local < slot:
        return False
    runs = SyncRun.objects.filter(lane='morning_chain')
    if runs.filter(status='running').exists():
        return False
    if runs.filter(status='success', started_at__gte=slot).exists():
        return False
    last = runs.order_by('-started_at').first()
    if (last and last.status == 'failed'
            and last.started_at > now - datetime.timedelta(hours=RETENTION_RETRY_HOURS)):
        return False
    fast = SyncRun.objects.filter(lane='fast').exclude(status='running').order_by('-started_at').first()
    return bool(fast and fast.status == 'success'
                and fast.started_at >= now - datetime.timedelta(minutes=SOFTECH_UP_MINUTES))


def run_morning_chain_catchup():
    """Run the morning chain now when today's slot was missed. Returns the SyncRun or None."""
    if not morning_chain_catchup_due():
        return None
    from apps.sync import tasks
    run = tasks._run_morning_chain()
    if run is None:
        return None
    from apps.sync.models import SyncLog
    SyncLog.objects.create(sync_run=run, table_name='chain:catchup', records_processed=1)
    return run
