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
  run_daily_retention() all of the above as one logged SyncRun (lane 'retention').
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
    from apps.notifications.models import Notification
    from apps.sync.models import SyncRun
    from apps.users.models import StaffProfile
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
        for staff in StaffProfile.objects.filter(role='admin', is_active=True).select_related('branch'):
            Notification.send_to_user(staff, 'sync_failure', f'🔴 فشل متكرر في مزامنة «{label}»', body,
                                      dedup_key=f'sync_failure_{lane}_{today}', dedup_once=True,
                                      bypass_role_gate=True)
        alerted.append(lane)
    return alerted


def run_daily_retention():
    """One SyncRun (lane 'retention') with a SyncLog per table. A failing step is
    logged and the others still run."""
    from apps.sync.models import SyncLog, SyncRun
    run = SyncRun.objects.create(status='running', lane='retention')
    steps = [
        ('retention:engine_runs', lambda: sum(prune_engine_runs().values())),
        ('retention:notifications', prune_notifications),
        ('retention:pbx_events', prune_pbx_events),
        ('retention:audit_log', prune_audit_log),
        ('retention:slow_requests', prune_slow_requests),
        ('retention:screen_views', prune_screen_views),
    ]
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
