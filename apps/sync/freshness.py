"""
apps/sync/freshness.py

Unified per-DOMAIN data freshness — one source of truth for "how current is the
data this module depends on". Replaces scattered, inconsistent freshness checks
(global SyncRun time in DataFreshnessBar, insights.data_freshness, purchasing
Run.data_through_date, procurement synced_at) with a single answer keyed by the
data domain a module actually relies on.

Why per-domain (not a single "last sync"): after the tiered sync, a FAST lane
refreshes stock + sales every ~5 min while a SLOW lane refreshes items/prices and
customers every ~60 min. A single "last sync 2 min ago" is therefore misleading —
prices may be ~58 min old. Each domain reads from its OWN authoritative run log:

  • main-sync domains (stock/sales/catalog/customers/branches/users) → the
    per-table SyncLog of SUCCESSFUL runs.
  • expiry (FEFO)  → batches.StockExpirySyncRun (its own daily sweep log).
  • purchases      → procurement.ProcurementEngineRun (its own purchase sync log).

Depth:
  • snapshot domains: freshness = age of the last successful sync of that domain.
  • timeseries domains (sales): additionally carry data_through (latest mirrored
    business date) + trailing-window interior gaps (reusing insights.rules).
"""
import datetime as _dt

from django.conf import settings
from django.db.models import Max
from django.utils import timezone

# domain → how to read it. Either `tables` (SyncLog table_name list + sync lane)
# or `source` (a custom run-log reader) + explicit `cadence_min`.
DOMAINS = {
    'stock':     {'label_ar': 'المخزون',          'tables': ['stkbal'],                                'lane': 'fast', 'kind': 'snapshot'},
    'sales':     {'label_ar': 'المبيعات',         'tables': ['stktrans'],                              'lane': 'fast', 'kind': 'timeseries'},
    'branches':  {'label_ar': 'الفروع',           'tables': ['branches'],                              'lane': 'fast', 'kind': 'snapshot'},
    'catalog':   {'label_ar': 'الأصناف والأسعار', 'tables': ['items', 'itembarcodes', 'itemsclassif'], 'lane': 'slow', 'kind': 'snapshot'},
    'customers': {'label_ar': 'العملاء',          'tables': ['localcustomers'],                        'lane': 'slow', 'kind': 'snapshot'},
    'users':     {'label_ar': 'المستخدمون والصلاحيات', 'tables': ['users', 'erp_permissions'],         'lane': 'slow', 'kind': 'snapshot'},
    # Custom-source domains — their own run-log model, separate from the main sync.
    'expiry':    {'label_ar': 'صلاحية المخزون',   'source': 'expiry',    'cadence_min': 1440, 'kind': 'snapshot'},
    'purchases': {'label_ar': 'المشتريات والوارد', 'source': 'purchases', 'cadence_min': 1440, 'kind': 'snapshot'},
}

# A domain is "stale" once its last success is older than this many sync
# intervals (so a single missed tick is tolerated, a sustained gap is flagged).
STALE_FACTOR = int(getattr(settings, 'SYNC_FRESHNESS_STALE_FACTOR', 3))


def _lane_minutes():
    return {
        'fast': int(getattr(settings, 'SYNC_FAST_MINUTES', 5)),
        'slow': int(getattr(settings, 'SYNC_SLOW_MINUTES', 60)),
    }


# ── custom-source readers (return raw datetimes) ───────────────────────────────

def _source_expiry():
    """FEFO expiry mirror freshness — batches.StockExpirySyncRun. 'partial' still
    means data was refreshed (some nodes ok), so it counts as a success."""
    from apps.batches.models import StockExpirySyncRun
    ok = (StockExpirySyncRun.objects.filter(status__in=['success', 'partial'])
          .order_by('-started_at').first())
    last = StockExpirySyncRun.objects.order_by('-started_at').first()
    return {
        'last_success_at': (ok.finished_at or ok.started_at) if ok else None,
        'last_attempt_at': (last.finished_at or last.started_at) if last else None,
        'last_run_failed': bool(last and last.status == 'failed'),
    }


def _source_purchases():
    """Purchase/transit mirror freshness — procurement.ProcurementEngineRun."""
    from apps.procurement.models import ProcurementEngineRun
    ok = ProcurementEngineRun.objects.filter(status='success').order_by('-started_at').first()
    last = ProcurementEngineRun.objects.order_by('-started_at').first()
    return {
        'last_success_at': (ok.finished_at or ok.started_at) if ok else None,
        'last_attempt_at': (last.finished_at or last.started_at) if last else None,
        'last_run_failed': bool(last and last.status == 'failed'),
    }


_SOURCES = {'expiry': _source_expiry, 'purchases': _source_purchases}


# ── public API ─────────────────────────────────────────────────────────────────

def get_freshness(domains=None):
    """
    Return freshness for the requested domains (all when None):

        {'server_now': iso, 'domains': {key: {...}, ...}}

    Each domain carries last_success_at / last_attempt_at / age_seconds / stale /
    cadence_minutes / last_run_failed; the sales domain additionally carries
    data_through / behind_days / empty_days / low_days / complete.
    """
    from apps.sync.models import SyncLog, SyncRun

    lane = _lane_minutes()
    now = timezone.now()
    wanted = domains or list(DOMAINS.keys())

    # Global "last main sync failed" flag — applied to SyncLog-based domains.
    last_run = SyncRun.objects.order_by('-started_at').first()
    main_failed = bool(last_run and last_run.status == 'failed')

    out = {}
    for key in wanted:
        spec = DOMAINS.get(key)
        if not spec:
            continue

        if 'source' in spec:
            raw = _SOURCES[spec['source']]()
            succ = raw['last_success_at']
            attempt = raw['last_attempt_at']
            failed = raw['last_run_failed']
            cadence = int(spec['cadence_min'])
        else:
            tables = spec['tables']
            succ = (SyncLog.objects.filter(table_name__in=tables, sync_run__status='success')
                    .aggregate(mx=Max('created_at'))['mx'])
            attempt = (SyncLog.objects.filter(table_name__in=tables)
                       .aggregate(mx=Max('created_at'))['mx'])
            failed = main_failed
            cadence = lane[spec['lane']]

        age = (now - succ).total_seconds() if succ else None
        stale = (succ is None) or (age is not None and age > cadence * 60 * STALE_FACTOR)

        entry = {
            'label_ar':        spec['label_ar'],
            'kind':            spec['kind'],
            'lane':            spec.get('lane'),   # None for custom-source domains
            'cadence_minutes': cadence,
            'last_success_at': succ.isoformat() if succ else None,
            'last_attempt_at': attempt.isoformat() if attempt else None,
            'age_seconds':     int(age) if age is not None else None,
            'stale':           stale,
            'last_run_failed': failed,
        }
        if spec['kind'] == 'timeseries' and key == 'sales':
            entry.update(_sales_completeness(window_days=14))
        out[key] = entry

    return {'server_now': now.isoformat(), 'domains': out}


def _sales_completeness(window_days=14):
    """
    data_through (latest mirrored invoice date) + interior gaps over the trailing
    window. "complete through yesterday" is on-time (today is still in progress).
    Reuses insights.rules._period_sales_gaps so there is one gap definition.
    """
    from apps.customers.models import PurchaseHistory

    mx = PurchaseHistory.objects.aggregate(mx=Max('invoice_date'))['mx']
    data_through = mx.date() if mx else None
    today = timezone.localdate()
    behind = None
    if data_through:
        behind = max(0, (today - data_through).days - 1)   # yesterday = on-time

    empty_days, low_days = [], []
    try:
        from apps.insights.rules import _period_sales_gaps
        g = _period_sales_gaps(today - _dt.timedelta(days=window_days),
                               today - _dt.timedelta(days=1))   # exclude in-progress today
        empty_days, low_days = g['empty_days'], g['low_days']
    except Exception:
        pass

    return {
        'data_through': data_through.isoformat() if data_through else None,
        'behind_days':  behind,
        'empty_days':   empty_days,
        'low_days':     low_days,
        'complete':     (behind == 0) and not empty_days and not low_days,
    }
