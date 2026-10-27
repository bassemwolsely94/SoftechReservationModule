"""
apps/sync/network_health.py

Unified connectivity probe for the WHOLE SOFTECH network — HQ + every operational
retail branch — in one sweep. This is the single source of truth for the "6/6
connected" panel.

Why this exists:
    Health used to be a side-effect of `sync_crm_orders` (branches only) and HQ
    was never probed at all, even though the entire master-data sync depends on
    it. This probe covers all N nodes on a fixed cadence, in PARALLEL and
    fail-fast (config.sybase.probe_connection makes one short-timeout attempt),
    and feeds the existing branch_watchdog map so down/chronic/recovered
    notifications keep working — now for HQ too.

Node set:
    • HQ (softech_branch_id '100') → settings.SYBASE_HOST / SYBASE_PORT
    • Every branch that is_operational AND has a db_host (the 5 retail branches)

Closed / cancelled / call-center branches (is_operational=False, no db_host) are
intentionally excluded — they have no server to reach.
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.conf import settings

logger = logging.getLogger('elrezeiky.sync')

HQ_BRANCH_ID = '100'


def _node_list():
    """
    Build the list of nodes to probe: (branch_id, host, port, db_name, is_hq).
    HQ first, then operational retail branches.
    """
    from apps.branches.models import Branch

    nodes = [(
        HQ_BRANCH_ID,
        settings.SYBASE_HOST,
        int(getattr(settings, 'SYBASE_PORT', 5000) or 5000),
        'SOFTECHDB9',
        True,
    )]

    # Retail nodes with a reachable local DB. `kind` is the curated truth; the
    # db_host guard skips any retail branch not yet wired to a server.
    branches = (Branch.objects.retail().with_local_db()
                .exclude(softech_branch_id=HQ_BRANCH_ID))
    for b in branches.order_by('softech_branch_id'):
        nodes.append((b.softech_branch_id, b.db_host, b.db_port or 5000,
                      b.db_name or 'SOFTECHDB9', False))
    return nodes


def probe_all_nodes(record=True) -> dict:
    """
    Probe every node in parallel and return a results dict keyed by host:

        { host: {'branch_id', 'ok', 'elapsed_ms', 'error'}, ... }

    When `record` is True (the scheduled path) the results are persisted through
    branch_watchdog.record_run so the health map, streak tracking, and outage
    notifications all update — HQ included.
    """
    import jpype
    from config.sybase import probe_connection, _ensure_jvm

    nodes = _node_list()
    results = {}

    # Warm the JVM ONCE in this thread — jpype.startJVM is not thread-safe, so if
    # the worker threads each raced to start it we'd get "JVM is already started".
    _ensure_jvm()

    # Short login timeout for a health sweep: we want a down node to fail fast,
    # not hang the probe for the full work-timeout.
    probe_timeout = int(getattr(settings, 'SYBASE_HEALTH_TIMEOUT', 8))

    def _probe(node):
        branch_id, host, port, db_name, is_hq = node
        # Each worker must be attached to the JVM before calling into Java.
        if not jpype.isThreadAttachedToJVM():
            jpype.attachThreadToJVM()
        r = probe_connection(host, port, db_name, login_timeout=probe_timeout)
        r['branch_id'] = branch_id
        return host, r

    # Parallel so one slow/down node doesn't serialise the whole sweep.
    with ThreadPoolExecutor(max_workers=min(8, len(nodes) or 1)) as pool:
        futures = [pool.submit(_probe, n) for n in nodes]
        for fut in as_completed(futures):
            try:
                host, r = fut.result()
                results[host] = r
            except Exception as exc:      # a probe should never raise, but be safe
                logger.warning('[network_health] probe crashed: %s', exc)

    if record and results:
        try:
            from apps.delivery.branch_watchdog import record_run
            record_run(results)
        except Exception as exc:
            logger.warning('[network_health] record_run failed: %s', exc)

    ok = sum(1 for r in results.values() if r.get('ok'))
    logger.info('[network_health] nodes reachable %d/%d', ok, len(results))
    return results
