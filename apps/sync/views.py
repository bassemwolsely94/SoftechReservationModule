import logging

from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser

from core.permissions import matrix_permission

SYNC = matrix_permission('sync')      # sync logs / scheduler state = sync view (Batch 4, Z-4)
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
                  'records_synced', 'error_message', 'duration_seconds',
                  'progress', 'lane', 'manual', 'logs']


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
    from apps.sync.tasks import run_full_sync, run_fast_sync, run_slow_sync

    # `lane` picks a tiered lane; `full` (legacy) runs everything. The per-module
    # freshness bars pass lane='fast' (stock+sales, ~15s) so a refresh is cheap.
    lane = (request.data.get('lane') or '').strip().lower()
    full = bool(request.data.get('full', False))
    if lane == 'fast':
        worker, label = (lambda: run_fast_sync(manual=True)), 'fast'
    elif lane == 'slow':
        worker, label = (lambda: run_slow_sync(manual=True)), 'slow'
    else:
        worker, label = (lambda: run_full_sync(full_history=full, manual=True)), 'full'

    # Don't pile a second run on top of one already in flight. The scheduled
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
            worker()
        except Exception:
            logger.exception('[trigger_sync] background %s sync failed', label)
        finally:
            # Worker thread owns its own DB connections — close them so they
            # don't leak past the thread's lifetime.
            connections.close_all()

    threading.Thread(target=_worker, name=f'manual-sync-{label}', daemon=True).start()
    return Response(
        {'status': 'running', 'lane': label, 'full': full, 'detail': 'sync started'},
        status=status.HTTP_202_ACCEPTED,
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated, SYNC])
def sync_logs(request):
    runs = SyncRun.objects.prefetch_related('logs').order_by('-started_at')[:20]
    return Response(SyncRunSerializer(runs, many=True).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def data_freshness(request):
    """
    Per-domain data freshness for the module-level freshness bars.

    ?domains=stock,sales limits the response to those domains (one request per
    page, cheap). Omit for all domains. See apps/sync/freshness.py.
    """
    from apps.sync.freshness import get_freshness
    raw = request.query_params.get('domains')
    wanted = [d.strip() for d in raw.split(',') if d.strip()] if raw else None
    return Response(get_freshness(wanted))


@api_view(['GET'])
@permission_classes([IsAuthenticated, SYNC])
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


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def softech_load(request):
    """
    What the platform asks of SOFTECH (doc 30): logins, queries, rows and time over
    the last ?hours= (default 24, max 720), grouped by job/source, calling code and
    server, plus an hourly series. Admin only. Counts from other processes (the
    scheduler) are saved about once a minute.
    """
    from django.db.models import Sum, Max
    from django.utils import timezone
    from datetime import timedelta
    from apps.users.permissions import IsAdminRole
    from apps.branches.models import Branch
    from . import softech_load as sl
    from .models import SoftechLoadStat

    if not IsAdminRole().has_permission(request, None):
        return Response({'detail': 'admin only'}, status=status.HTTP_403_FORBIDDEN)
    try:
        hours = max(1, min(int(request.query_params.get('hours', 24)), 720))
    except (TypeError, ValueError):
        hours = 24
    sl.flush()   # include this process's latest counts

    since = timezone.now() - timedelta(hours=hours)
    qs = SoftechLoadStat.objects.filter(hour__gte=since.replace(minute=0, second=0, microsecond=0))
    fields = ('connects', 'connect_failures', 'connect_ms', 'queries', 'query_errors', 'query_ms', 'rows')
    sums = {f: Sum(f) for f in fields}

    def rows_by(key, limit=None):
        out = []
        for r in qs.values(key).annotate(**sums, max_query_ms=Max('max_query_ms')).order_by('-query_ms', '-connects'):
            out.append({k: (r[k] or 0) if k != key else r[k] for k in r})
        return out[:limit] if limit else out

    host_names = {}
    for b in Branch.objects.exclude(db_host='').only('db_host', 'name', 'name_ar', 'softech_branch_id'):
        host_names[b.db_host] = f'{b.softech_branch_id} {b.name_ar or b.name}'
    nodes = rows_by('node')
    for n in nodes:
        kind, _, host = n['node'].partition(' ')
        n['label'] = 'HQ' if n['node'] == 'HQ' else f"{kind} · {host_names.get(host, host)}"

    totals = qs.aggregate(**sums, max_query_ms=Max('max_query_ms'))
    hourly = [{'hour': r['hour'].isoformat(), **{f: r[f] or 0 for f in ('connects', 'queries', 'rows', 'query_ms')}}
              for r in qs.values('hour').annotate(**sums).order_by('hour')]
    return Response({
        'hours': hours,
        'enabled': sl.enabled(),
        'totals': {k: v or 0 for k, v in totals.items()},
        'by_scope': rows_by('scope', 40),
        'by_caller': rows_by('caller', 40),
        'by_node': nodes,
        'hourly': hourly,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def slow_requests(request):
    """
    Top 10 slowest API endpoints over the last ?days= (default 14, max 30) by p95
    duration, from SlowRequest (P-56: measure before optimising). Only requests
    slower than SLOW_REQUEST_MS are recorded, so `count` is "slow calls", not all
    calls. Admin only.
    """
    from datetime import timedelta
    from django.utils import timezone
    from apps.users.permissions import IsAdminRole
    from .models import SlowRequest

    if not IsAdminRole().has_permission(request, None):
        return Response({'detail': 'admin only'}, status=status.HTTP_403_FORBIDDEN)
    try:
        days = max(1, min(int(request.query_params.get('days', 14)), 30))
    except (TypeError, ValueError):
        days = 14
    since = timezone.now() - timedelta(days=days)
    by_path = {}
    for path, method, ms in (SlowRequest.objects.filter(at__gte=since)
                             .values_list('path', 'method', 'duration_ms')):
        by_path.setdefault((path, method), []).append(ms)
    rows = []
    for (path, method), vals in by_path.items():
        vals.sort()
        p95 = vals[min(len(vals) - 1, int(round(0.95 * (len(vals) - 1))))]
        rows.append({'path': path, 'method': method, 'count': len(vals),
                     'p95_ms': p95, 'max_ms': vals[-1]})
    rows.sort(key=lambda r: (-r['p95_ms'], -r['count']))
    from django.conf import settings
    return Response({'days': days, 'threshold_ms': int(getattr(settings, 'SLOW_REQUEST_MS', 1000)),
                     'endpoints': rows[:10]})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def writer_switches(request):
    """
    P-54 switch table: every SOFTECH writer flag with its .env value, its effective state
    (WRITER_INSTANCE and flag), the code default (always OFF) and what it protects, plus
    this instance's role and the kill-switch. Read-only. Admin only.
    """
    from django.conf import settings
    from apps.users.permissions import IsAdminRole
    from config.writers import WRITER_FLAGS, WRITER_JOBS, writer_allowed, writer_instance

    if not IsAdminRole().has_permission(request, None):
        return Response({'detail': 'admin only'}, status=status.HTTP_403_FORBIDDEN)
    return Response({
        'writer_instance': writer_instance(),
        'softech_read_only': bool(getattr(settings, 'SOFTECH_READ_ONLY', False)),
        'writer_jobs': list(WRITER_JOBS),
        'flags': [{
            'flag': flag,
            'protects': info['protects'],
            'value': bool(getattr(settings, flag, False)),
            'effective': writer_allowed(flag),
            'code_default': False,
        } for flag, info in WRITER_FLAGS.items()],
    })
