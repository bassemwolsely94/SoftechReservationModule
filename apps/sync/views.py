import logging

from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework import status
from .models import SyncRun, SyncLog

logger = logging.getLogger('elrezeiky.sync')


class SyncLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = SyncLog
        fields = ['table_name', 'records_processed', 'created_at']


class SyncRunSerializer(serializers.ModelSerializer):
    logs = SyncLogSerializer(many=True, read_only=True)
    duration_seconds = serializers.IntegerField(read_only=True)

    class Meta:
        model = SyncRun
        fields = ['id', 'status', 'started_at', 'completed_at',
                  'records_synced', 'error_message', 'duration_seconds', 'logs']


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def sync_status(request):
    last = SyncRun.objects.first()
    return Response(SyncRunSerializer(last).data if last else {'status': 'no_sync_yet'})


@api_view(['POST'])
@permission_classes([IsAdminUser])
def trigger_sync(request):
    """
    Kick off a manual full sync WITHOUT blocking the request.

    run_full_sync pulls everything (items ~40s + customers ~100s + sales) and used
    to run inline here — a 3–4 minute blocking POST. It now runs in a background
    daemon thread and this endpoint returns 202 immediately; the SyncPage already
    polls /sync/status/ and /sync/logs/, so the run surfaces there as it does for
    the scheduled lanes.
    """
    import threading
    from datetime import timedelta
    from django.db import connections
    from django.utils import timezone
    from apps.sync.tasks import run_full_sync

    full = bool(request.data.get('full', False))

    # Don't pile a second full run on top of one already in flight. The scheduled
    # fast/slow lanes also create 'running' rows but finish in seconds/minutes; a
    # row older than 15 min is treated as stale (crashed process) and ignored.
    cutoff = timezone.now() - timedelta(minutes=15)
    inflight = SyncRun.objects.filter(status='running', started_at__gte=cutoff).first()
    if inflight:
        return Response(
            {**SyncRunSerializer(inflight).data, 'detail': 'sync already in progress'},
            status=status.HTTP_202_ACCEPTED,
        )

    def _worker():
        try:
            run_full_sync(full_history=full)
        except Exception:
            logger.exception('[trigger_sync] background sync failed')
        finally:
            # Worker thread owns its own DB connections — close them so they
            # don't leak past the thread's lifetime.
            connections.close_all()

    threading.Thread(target=_worker, name='manual-sync', daemon=True).start()
    return Response(
        {'status': 'running', 'full': full, 'detail': 'sync started'},
        status=status.HTTP_202_ACCEPTED,
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def sync_logs(request):
    runs = SyncRun.objects.prefetch_related('logs').order_by('-started_at')[:20]
    return Response(SyncRunSerializer(runs, many=True).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def scheduler_status(request):
    """
    Report whether the background scheduler is alive, based on its heartbeat.
    The scheduler writes a timestamp every minute (SystemSetting
    'scheduler_heartbeat').  If the last beat is older than the threshold, the
    scheduler process is considered down — the UI can then warn the operator.
    """
    from datetime import datetime, timezone as _tz
    from apps.config.models import SystemSetting
    from apps.sync.tasks import SCHEDULER_HEARTBEAT_KEY

    THRESHOLD_SECONDS = 180   # 3× the 1-min heartbeat

    last_iso = None
    seconds_ago = None
    running = False
    try:
        s = SystemSetting.objects.filter(key=SCHEDULER_HEARTBEAT_KEY).first()
        if s and s.value:
            last_iso = s.value
            last = datetime.fromisoformat(s.value)
            if last.tzinfo is None:
                last = last.replace(tzinfo=_tz.utc)
            seconds_ago = (datetime.now(_tz.utc) - last).total_seconds()
            running = seconds_ago <= THRESHOLD_SECONDS
    except Exception:
        pass

    return Response({
        'running':        running,
        'last_heartbeat': last_iso,
        'seconds_ago':    int(seconds_ago) if seconds_ago is not None else None,
        'threshold':      THRESHOLD_SECONDS,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def branch_health(request):
    """
    Network Sybase reachability — HQ + every operational branch.

    Reads the persisted health map (apps.delivery.branch_watchdog), which is now
    fed by apps.sync.network_health.probe_all_nodes and therefore includes HQ
    (softech_branch_id '100'). Each node is enriched with its Arabic name and an
    is_hq flag so the UI can render the HQ node distinctly and show "N/N" honestly.

    Pass ?probe=1 to run a fresh live sweep before returning (used by a manual
    "test connections" button); otherwise the last persisted snapshot is returned.
    """
    from apps.delivery.branch_watchdog import get_health_snapshot, CHRONIC_THRESHOLD
    from apps.sync.network_health import HQ_BRANCH_ID
    from apps.branches.models import Branch

    if request.query_params.get('probe') in ('1', 'true', 'yes'):
        try:
            from apps.sync.network_health import probe_all_nodes
            probe_all_nodes(record=True)
        except Exception as exc:
            logger.warning('[branch_health] live probe failed: %s', exc)

    snapshot = get_health_snapshot()   # { host: {branch_id, consecutive_failures, ...} }

    # Branch-id → Arabic display name, for friendly labels.
    name_by_id = {
        b.softech_branch_id: (b.name_ar or b.name)
        for b in Branch.objects.only('softech_branch_id', 'name', 'name_ar')
    }

    nodes = []
    ok = down = chronic = 0
    for host, rec in snapshot.items():
        fails = rec.get('consecutive_failures', 0) or 0
        if fails == 0:
            state = 'ok'; ok += 1
        elif fails >= CHRONIC_THRESHOLD:
            state = 'chronic'; chronic += 1
        else:
            state = 'down'; down += 1
        bid = rec.get('branch_id', '?')
        nodes.append({
            'host':                 host,
            'branch_id':            bid,
            'name':                 name_by_id.get(bid, ''),
            'is_hq':                bid == HQ_BRANCH_ID,
            'state':                state,
            'consecutive_failures': fails,
            'first_failed_at':      rec.get('first_failed_at'),
            'last_ok_at':           rec.get('last_ok_at'),
            'last_checked_at':      rec.get('last_checked_at'),
            'last_error':           rec.get('last_error'),
            'last_elapsed_ms':      rec.get('last_elapsed_ms'),
        })

    # HQ first, then worst-first (chronic → down by streak → ok).
    order = {'chronic': 0, 'down': 1, 'ok': 2}
    nodes.sort(key=lambda b: (0 if b['is_hq'] else 1, order[b['state']], -b['consecutive_failures']))

    return Response({
        'summary':  {'total': len(nodes), 'ok': ok, 'down': down, 'chronic': chronic},
        # 'branches' key kept for backward-compat with the existing frontend.
        'branches': nodes,
        'nodes':    nodes,
        'chronic_threshold': CHRONIC_THRESHOLD,
    })
