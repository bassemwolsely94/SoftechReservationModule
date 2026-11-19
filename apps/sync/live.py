"""
apps/sync/live.py — "freshness changed" when a sync run or lane finishes (performance Stage 5).

The data-freshness bar, the sync-status chip in the layout and the dashboard summary used to poll
every 60–90 s on every open tab. They now refetch when this event arrives (and keep a slow fallback
poll while the socket is down). The event names only the freshness DOMAINS that changed
(apps/sync/freshness.DOMAINS keys) and a time — never rows, customers or phones.

Receivers are connected from SyncConfig.ready() for every process, the scheduler included (that is
where the runs finish); the broadcast goes out through the shared Channels layer after commit.
"""
import logging

logger = logging.getLogger('elrezeiky.sync')

# A run log row that reaches one of these states means "done" — new freshness to show.
FINISHED = frozenset({'success', 'partial', 'failed'})

# Custom-source run logs (freshness.py `source` domains) → the domains they feed.
SOURCE_MODELS = {
    'batches.StockExpirySyncRun':       ('expiry',),
    'batches.PurchaseExpiryAuditRun':   ('purchase_expiry',),
    'procurement.ProcurementEngineRun': ('purchases',),
    'stock_audit.StockLedgerSyncRun':   ('stock_audit',),
    'hr.CollectionRun':                 ('attendance',),
    'finance.GLDraftRun':               ('gl_drafting',),
    'pbx.CdrSyncRun':                   ('calls',),
    'finance.FinanceSyncRun':           ('finance_expenses', 'finance_journal'),
    'finance.ReconciliationRun':        None,   # by party_type, see _source_domains
}

# SyncRun lanes that are housekeeping, not data.
_NO_DATA_LANES = frozenset({'retention'})


def lane_domains(lane: str):
    """The freshness domains a main-sync SyncRun of this lane refreshes."""
    from apps.sync.freshness import DOMAINS
    lane = (lane or '').strip()
    if lane in _NO_DATA_LANES:
        return []
    table_domains = {k: v for k, v in DOMAINS.items() if 'tables' in v}
    if lane in ('fast', 'slow'):
        return sorted(k for k, v in table_domains.items() if v.get('lane') == lane)
    if lane == 'items':
        return ['catalog']
    # 'full', blank (older rows / one-off commands) and any other lane: every main-sync domain
    return sorted(table_domains)


def _source_domains(label, instance):
    if label == 'finance.ReconciliationRun':
        return ('ar_contracts',) if getattr(instance, 'party_type', '') == 'customer' else ('ap_reconciliation',)
    return SOURCE_MODELS.get(label) or ()


def _on_syncrun_saved(sender, instance, **kwargs):
    if getattr(instance, 'status', None) not in FINISHED:
        return
    _broadcast(lane_domains(getattr(instance, 'lane', '')))


def _on_source_run_saved(sender, instance, **kwargs):
    if getattr(instance, 'status', None) not in FINISHED:
        return
    _broadcast(_source_domains(sender._meta.label, instance))


def _broadcast(domains):
    if not domains:
        return
    try:
        from apps.notifications.live import broadcast_freshness
        broadcast_freshness(domains)
    except Exception as exc:   # a live hint must never break a sync run's save
        logger.debug('freshness broadcast skipped: %s', exc)


def connect_signals():
    from django.apps import apps
    from django.db.models.signals import post_save
    from apps.sync.models import SyncRun

    post_save.connect(_on_syncrun_saved, sender=SyncRun, dispatch_uid='sync.live.syncrun')
    for label in SOURCE_MODELS:
        try:
            model = apps.get_model(label)
        except (LookupError, ValueError):
            logger.debug('freshness source %s not installed — no live event for it', label)
            continue
        post_save.connect(_on_source_run_saved, sender=model, dispatch_uid=f'sync.live.{label}')
