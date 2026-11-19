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
  • stock_audit    → stock_audit.StockLedgerSyncRun (doc 32 stktrans mirror).

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
    'purchase_expiry': {'label_ar': 'صلاحيات الشراء', 'source': 'purchase_expiry', 'cadence_min': 1440, 'kind': 'snapshot'},
    'attendance': {'label_ar': 'الحضور والبصمة', 'source': 'attendance', 'cadence_min': 60, 'kind': 'snapshot'},
    'stock_audit': {'label_ar': 'حركات المخزون (التدقيق)', 'source': 'stock_audit', 'cadence_min': 120, 'kind': 'snapshot'},
    'gl_drafting': {'label_ar': 'ترحيل القيود من سوفتيك', 'source': 'gl_drafting', 'cadence_min': 1440, 'kind': 'snapshot'},
    'gl_compare': {'label_ar': 'مقارنة الحسابات بسوفتيك', 'source': 'gl_compare', 'cadence_min': 1440, 'kind': 'snapshot'},
    # Finance mirror (P-43): P&L snapshots refresh with the slow lane; journal and
    # expenses come from the 02:15 nightly sync_finance (last 3 months).
    'finance_pl':       {'label_ar': 'الأرباح والخسائر', 'source': 'finance_pl',       'cadence_min': 60,   'kind': 'snapshot'},
    'finance_expenses': {'label_ar': 'المصروفات',        'source': 'finance_expenses', 'cadence_min': 1440, 'kind': 'snapshot'},
    'finance_journal':  {'label_ar': 'القيود والخزينة',   'source': 'finance_journal',  'cadence_min': 1440, 'kind': 'snapshot'},
    'ap_reconciliation': {'label_ar': 'سداد الموردين',  'source': 'ap_reconciliation', 'cadence_min': 1440, 'kind': 'snapshot'},
    'calls':             {'label_ar': 'المكالمات (سجل السنترال)', 'source': 'calls', 'cadence_min': 10, 'kind': 'snapshot'},
    'ar_contracts':      {'label_ar': 'مستحقات التعاقدات', 'source': 'ar_contracts',    'cadence_min': 1440, 'kind': 'snapshot'},
    # Lost-sale log (pos_cancel) — PosCancelDaily mirror, rolled up by the nightly sync_pos_cancel.
    'pos_cancel':        {'label_ar': 'المبيعات غير المخزنة', 'source': 'pos_cancel',    'cadence_min': 1440, 'kind': 'snapshot'},
    # ETA history mirror (doc 36 §history), one per ETA system.
    'eta_history_preprod':    {'label_ar': 'سجل المصلحة (التجريبية)', 'source': 'eta_history_preprod', 'cadence_min': 1440, 'kind': 'snapshot'},
    'eta_history_production': {'label_ar': 'سجل المصلحة (الفعلية)', 'source': 'eta_history_production', 'cadence_min': 1440, 'kind': 'snapshot'},
}

# A domain is "stale" once its last success is older than this many sync
# intervals (so a single missed tick is tolerated, a sustained gap is flagged).
STALE_FACTOR = int(getattr(settings, 'SYNC_FRESHNESS_STALE_FACTOR', 3))


def _lane_minutes():
    return {
        'fast': int(getattr(settings, 'SYNC_FAST_MINUTES', 5)),
        'slow': int(getattr(settings, 'SYNC_SLOW_MINUTES', 60)),
    }


# ── custom-source readers ──────────────────────────────────────────────────────
#
# Each custom source is read through PROBES: "the newest row of this queryset". Every probe of every
# wanted source goes into ONE `UNION ALL` query (perf Stage 3 — this used to be two queries per
# source, 46 per call, on a bar every user polls each minute). A probe keeps the exact filter and
# ordering the old per-source `.first()` / MAX used, so it finds the same row.
#
# A probe row carries two times, `a` and `b`; its moment is `b or a` (a run row: finished_at, else
# started_at; a single-time row: the same field twice) and the row's status.
#
# Two shapes of source:
#   'run' — `<key>:ok` (newest success) and `<key>:last` (newest attempt, and whether it failed)
#   'at'  — one or more `<key>:at` probes; the newest of them is both the success and the attempt

def _probe(tag, qs, order, a, b=None, status=None):
    from django.db.models import CharField, F, Value
    return (qs.order_by(*order)
            .annotate(fp_tag=Value(tag, output_field=CharField()), fp_a=F(a), fp_b=F(b or a),
                      fp_status=F(status) if status else Value('', output_field=CharField()))
            .values_list('fp_tag', 'fp_a', 'fp_b', 'fp_status')[:1])


def _run_log(key, qs, ok_statuses):
    """The usual run log: the newest run in `ok_statuses` is the last success; the newest run of any
    status is the last attempt (finished_at, else started_at)."""
    return [_probe(f'{key}:ok', qs.filter(status__in=ok_statuses), ['-started_at'],
                   'started_at', 'finished_at', 'status'),
            _probe(f'{key}:last', qs, ['-started_at'], 'started_at', 'finished_at', 'status')]


def _max_of(key, qs, field):
    """MAX(field) as a probe: the newest non-null value."""
    from django.db.models import F
    return _probe(f'{key}:at', qs.filter(**{f'{field}__isnull': False}), [F(field).desc()], field)


def _probes_expiry():
    """FEFO expiry mirror — batches.StockExpirySyncRun. 'partial' still means data was refreshed
    (some nodes ok), so it counts as a success."""
    from apps.batches.models import StockExpirySyncRun
    return _run_log('expiry', StockExpirySyncRun.objects.all(), ['success', 'partial'])


def _probes_purchases():
    """Purchase/transit mirror — procurement.ProcurementEngineRun."""
    from apps.procurement.models import ProcurementEngineRun
    return _run_log('purchases', ProcurementEngineRun.objects.all(), ['success'])


def _probes_purchase_expiry():
    """Purchase-expiry mirror (the supplier attribution of the return calendar, P-29) —
    batches.PurchaseExpiryAuditRun."""
    from apps.batches.models import PurchaseExpiryAuditRun
    return _run_log('purchase_expiry', PurchaseExpiryAuditRun.objects.all(), ['success'])


def _probes_stock_audit():
    """Stock-audit ledger (doc 32) — stock_audit.StockLedgerSyncRun. 'partial' still refreshed some
    days, so it counts as a success (like the expiry sweep)."""
    from apps.stock_audit.models import StockLedgerSyncRun
    return _run_log('stock_audit', StockLedgerSyncRun.objects.all(), ['success', 'partial'])


def _probes_attendance():
    """HR attendance (stage 1) — hr.CollectionRun, one row per agent visit to a machine."""
    from apps.hr.models import CollectionRun
    return _run_log('attendance', CollectionRun.objects.all(), ['success'])


def _probes_gl_drafting():
    """GL drafting (finance-gl Plan 2) — GLDraftRun. 'partial' still drafted most documents, so it
    counts as a success."""
    from apps.finance.models import GLDraftRun
    return _run_log('gl_drafting', GLDraftRun.objects.all(), ['success', 'partial'])


def _probes_gl_compare():
    """Ledger-vs-SOFTECH comparison (finance-gl Plan 3) — the newest GLComparisonLine.computed_at."""
    from apps.finance.models import GLComparisonLine
    return [_probe('gl_compare:at', GLComparisonLine.objects.all(), ['-computed_at'], 'computed_at')]


def _probes_ar_contracts():
    """Contract receivables (P-41) — the customer-side mirror sync of the tracked contract accounts."""
    from apps.finance.recon_models import ReconciliationRun
    return _run_log('ar_contracts', ReconciliationRun.objects.filter(party_type='customer'),
                    ['success', 'partial'])


def _probes_calls():
    """Calls — the PBX CDR mirror (pbx.CdrSyncRun, every 10 min)."""
    from apps.pbx.models import CdrSyncRun
    return _run_log('calls', CdrSyncRun.objects.all(), ['success'])


def _probes_finance_pl():
    """P&L snapshots — FinancialSnapshot.computed_at (auto_now on every refresh)."""
    from apps.finance.models import FinancialSnapshot
    return [_max_of('finance_pl', FinancialSnapshot.objects.all(), 'computed_at')]


def _finance_run(key, stat_key):
    """Last finance sync run that actually brought `stat_key` rows (a run that skipped or found
    nothing for that table does not count as fresh)."""
    from apps.finance.models import FinanceSyncRun
    ok = FinanceSyncRun.objects.filter(status='success', finished_at__isnull=False,
                                       **{f'records_synced__{stat_key}__gt': 0})
    return [_probe(f'{key}:ok', ok, ['-finished_at'], 'finished_at'),
            _probe(f'{key}:last', FinanceSyncRun.objects.all(), ['-started_at'],
                   'started_at', 'finished_at', 'status')]


def _probes_pos_cancel():
    """Lost-sale log — pos_orders.PosCancelDaily, the nightly sync_pos_cancel rollup of SOFTECH
    pos_cancel. No dedicated run log, so use the latest row write time."""
    from apps.pos_orders.models import PosCancelDaily
    return [_max_of('pos_cancel', PosCancelDaily.objects.all(), 'synced_at')]


def _probes_ap_reconciliation():
    """A/P reconciliation (doc 23) — the engine run that follows the 07:30 mirror sync."""
    from apps.finance.recon_models import ReconciliationRun
    runs = ReconciliationRun.objects.filter(party_type__in=['supplier', ''])   # P-41: customer runs feed ar_contracts
    return _run_log('ap_reconciliation', runs, ['success', 'partial'])


def _probes_eta_history(key, system):
    """Newest moment anything from this ETA system reached the mirror — the same three times as
    apps.tax_invoicing.eta_history.last_loaded_at."""
    from apps.tax_invoicing.models import EtaHistoryWindow, EtaMirrorDocument, EtaMirrorReceipt
    return [_max_of(key, EtaMirrorDocument.objects.filter(system=system), 'fetched_at'),
            _max_of(key, EtaMirrorReceipt.objects.filter(system=system), 'fetched_at'),
            _max_of(key, EtaHistoryWindow.objects.filter(system=system), 'loaded_at')]


# source → (shape, probes)
_SOURCE_PROBES = {
    'expiry':            ('run', _probes_expiry),
    'ap_reconciliation': ('run', _probes_ap_reconciliation),
    'purchases':         ('run', _probes_purchases),
    'ar_contracts':      ('run', _probes_ar_contracts),
    'calls':             ('run', _probes_calls),
    'stock_audit':       ('run', _probes_stock_audit),
    'attendance':        ('run', _probes_attendance),
    'purchase_expiry':   ('run', _probes_purchase_expiry),
    'gl_drafting':       ('run', _probes_gl_drafting),
    'finance_expenses':  ('run', lambda: _finance_run('finance_expenses', 'expense_records')),
    'finance_journal':   ('run', lambda: _finance_run('finance_journal', 'journal_entries')),
    'finance_pl':        ('at', _probes_finance_pl),
    'gl_compare':        ('at', _probes_gl_compare),
    'pos_cancel':        ('at', _probes_pos_cancel),
    'eta_history_preprod':    ('at', lambda: _probes_eta_history('eta_history_preprod', 'preprod')),
    'eta_history_production': ('at', lambda: _probes_eta_history('eta_history_production', 'production')),
}


def _read_sources(sources):
    """{source: {last_success_at, last_attempt_at, last_run_failed}} for the given custom sources,
    in one query."""
    probes = [p for s in sources for p in _SOURCE_PROBES[s][1]()]
    rows = {}
    if probes:
        for tag, a, b, status in probes[0].union(*probes[1:], all=True):
            rows.setdefault(tag, []).append((b or a, status))

    out = {}
    for s in sources:
        if _SOURCE_PROBES[s][0] == 'at':
            at = _newest(t for t, _ in rows.get(f'{s}:at', ()))
            out[s] = {'last_success_at': at, 'last_attempt_at': at, 'last_run_failed': False}
        else:
            ok, last = rows.get(f'{s}:ok'), rows.get(f'{s}:last')
            out[s] = {'last_success_at': ok[0][0] if ok else None,
                      'last_attempt_at': last[0][0] if last else None,
                      'last_run_failed': bool(last and last[0][1] == 'failed')}
    return out


# source → reader of that one source ({last_success_at, last_attempt_at, last_run_failed}); kept for
# callers and tests that read a single source. get_freshness reads them all at once.
_SOURCES = {s: (lambda s=s: _read_sources([s])[s]) for s in _SOURCE_PROBES}

def _sync_log_times(tables):
    """{table_name: (last success, last attempt)} from the main sync's per-table log, one query."""
    from django.db.models import Q
    from apps.sync.models import SyncLog
    rows = (SyncLog.objects.filter(table_name__in=tables).values('table_name')
            .annotate(succ=Max('created_at', filter=Q(sync_run__status='success')),
                      attempt=Max('created_at'))
            .order_by())
    return {r['table_name']: (r['succ'], r['attempt']) for r in rows}


def _newest(times):
    times = [t for t in times if t]
    return max(times) if times else None


# ── public API ─────────────────────────────────────────────────────────────────

def get_freshness(domains=None):
    """
    Return freshness for the requested domains (all when None):

        {'server_now': iso, 'domains': {key: {...}, ...}}

    Each domain carries last_success_at / last_attempt_at / age_seconds / stale /
    cadence_minutes / last_run_failed; the sales domain additionally carries
    data_through / behind_days / empty_days / low_days / complete.

    A fixed number of queries whatever the data (perf Stage 3): the last main sync run, one grouped
    read of the main sync's table log, one read of every custom source, two for sales completeness.
    """
    from apps.sync.models import SyncRun

    lane = _lane_minutes()
    now = timezone.now()
    wanted = [k for k in (domains or list(DOMAINS.keys())) if k in DOMAINS]

    main_failed, log_times = False, {}
    tables = sorted({t for k in wanted for t in DOMAINS[k].get('tables', ())})
    if tables:
        # Global "last main sync failed" flag — applied to SyncLog-based domains.
        last_run = SyncRun.objects.order_by('-started_at').first()
        main_failed = bool(last_run and last_run.status == 'failed')
        log_times = _sync_log_times(tables)
    sources = _read_sources(list(dict.fromkeys(DOMAINS[k]['source'] for k in wanted
                                               if 'source' in DOMAINS[k])))

    out = {}
    for key in wanted:
        spec = DOMAINS[key]

        if 'source' in spec:
            raw = sources[spec['source']]
            succ = raw['last_success_at']
            attempt = raw['last_attempt_at']
            failed = raw['last_run_failed']
            cadence = int(spec['cadence_min'])
        else:
            times = [log_times.get(t, (None, None)) for t in spec['tables']]
            succ = _newest(s for s, _ in times)
            attempt = _newest(a for _, a in times)
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
