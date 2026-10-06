"""
apps/purchasing/catchup.py

Robust "catch-up" sync for when the scheduled 2 AM SOFTECH sync didn't run or
couldn't reach SOFTECH, leaving SalesTransactionLine stale.

Why this exists (not just the normal engine sync):
  The engine's incremental sync fetches sales with ONE unbounded query
  (docdate >= today − N). When the gap is small (daily runs) that's fine, but
  once the data falls tens of days behind, that single GROUP BY over the whole
  window hangs on SOFTECH and the run auto-expires (observed: run #42, 20 min,
  0 rows). This module instead marches the backfill in small DATE-BOUNDED chunks
  (~15 days, ~7s query each) so it completes reliably at any gap size. It then
  runs the normal engine (whose remaining sync gap is now ~0) to refresh stock
  and recompute metrics.

READ-ONLY on SOFTECH — SELECT only, never writes back.
"""
import datetime
import logging
from decimal import Decimal

logger = logging.getLogger('elrezeiky.purchasing')

# Date-BOUNDED variant of QUERY_SALES_INCREMENTAL (queries.py). doccode
# '115' = sale, '30' = return; SUM collapses expiry-batch split lines.
QUERY_SALES_RANGE = """
    SELECT st.branchcode, st.itemcode, st.doccode, st.docnumber, st.docdate,
           SUM(st.transqty), SUM(COALESCE(st.transprice_total, 0))
    FROM SOFTECHDB9.dbo.stktrans st
    WHERE st.docdate >= ? AND st.docdate < ?
      AND st.doccode IN ('115', '30')
      AND st.itemcode IS NOT NULL AND st.itemcode != '' AND st.transqty > 0
    GROUP BY st.branchcode, st.itemcode, st.doccode, st.docnumber, st.docdate
"""

CHUNK_DAYS   = 15    # window per Sybase query — small enough to never time out
OVERLAP_DAYS = 2     # re-fetch the last couple of synced days (late-arriving rows)
MAX_BACKFILL_DAYS = 365   # never go beyond the rolling window


def softech_reachable(timeout_probe: bool = True) -> bool:
    """Quick connectivity probe so the endpoint can fail fast when SOFTECH is down."""
    try:
        from config.sybase import get_sybase_connection
        conn = get_sybase_connection()
        cur = conn.cursor()
        cur.execute('SELECT 1')
        cur.fetchone()
        conn.close()
        return True
    except Exception as exc:
        logger.warning('[catchup] SOFTECH probe failed: %s', exc)
        return False


def _set_progress(run, phase, pct, message):
    """Persist live progress onto the run for the dashboard banner to poll."""
    if run is None:
        return
    run.progress = {'phase': phase, 'pct': int(round(pct)), 'message': message}
    try:
        run.save(update_fields=['progress'])
    except Exception:
        pass


def backfill_sales(run=None) -> dict:
    """
    Chunked date-bounded sales backfill from the last synced day → today.
    If `run` is given, live progress is written to run.progress each chunk.
    Returns {rows_upserted, chunks, start, end, latest}.
    """
    import math
    from django.db.models import Max
    from config.sybase import get_sybase_connection
    from apps.purchasing.models import SalesTransactionLine
    from apps.catalog.models import Item
    from apps.branches.models import Branch

    latest = SalesTransactionLine.objects.aggregate(mx=Max('doc_date'))['mx']
    today  = datetime.date.today()
    if latest:
        start = latest - datetime.timedelta(days=OVERLAP_DAYS)
    else:
        start = today - datetime.timedelta(days=MAX_BACKFILL_DAYS)
    start = max(start, today - datetime.timedelta(days=MAX_BACKFILL_DAYS))
    end   = today + datetime.timedelta(days=1)   # inclusive of today
    total_chunks = max(1, math.ceil((end - start).days / CHUNK_DAYS))

    # Resolve maps over ALL items (incl. discontinued no_more_use) and active branches.
    item_map   = dict(Item.objects.values_list('softech_id', 'id'))
    branch_map = {str(b).strip(): bid for b, bid in
                  Branch.objects.filter(is_active=True).values_list('softech_branch_id', 'id')}

    _set_progress(run, 'backfill', 0,
                  f'مزامنة المبيعات المتأخرة — {(end - start).days} يوم على {total_chunks} دفعات')

    conn = get_sybase_connection()
    total = 0
    chunks = 0
    cursor_start = start
    try:
        while cursor_start < end:
            cursor_end = min(cursor_start + datetime.timedelta(days=CHUNK_DAYS), end)
            cur = conn.cursor()
            cur.execute(QUERY_SALES_RANGE, [cursor_start.isoformat(), cursor_end.isoformat()])
            rows = cur.fetchall()
            cur.close()

            objs = {}
            for r in rows:
                bc = str(r[0] or '').strip(); ic = str(r[1] or '').strip()
                dc = str(r[2] or '').strip(); dn = str(r[3] or '').strip()
                dd = r[4]
                dd = dd.date() if hasattr(dd, 'date') else dd
                qty = float(r[5] or 0); rev = float(r[6] or 0)
                if not bc or not ic or qty <= 0:
                    continue
                is_sale = dc == '115'
                objs[(bc, ic, dc, dn, dd)] = SalesTransactionLine(
                    softech_branchcode=bc, softech_itemcode=ic, doccode=dc,
                    docnumber=dn, doc_date=dd,
                    item_id=item_map.get(ic), branch_id=branch_map.get(bc),
                    transqty=Decimal(str(round(qty, 3))),
                    net_qty=Decimal(str(round(qty if is_sale else -qty, 3))),
                    net_revenue=Decimal(str(round(rev if is_sale else -rev, 3))),
                )
            if objs:
                SalesTransactionLine.objects.bulk_create(
                    list(objs.values()), batch_size=2000, update_conflicts=True,
                    unique_fields=['softech_branchcode', 'softech_itemcode',
                                   'doccode', 'docnumber', 'doc_date'],
                    update_fields=['transqty', 'net_qty', 'net_revenue',
                                   'item', 'branch', 'synced_at'],
                )
            total += len(objs)
            chunks += 1
            logger.info('[catchup] chunk %s..%s: %d rows upserted', cursor_start, cursor_end, len(objs))
            _set_progress(run, 'backfill', chunks / total_chunks * 100,
                          f'مزامنة المبيعات حتى {cursor_end} — {total:,} صف ({chunks}/{total_chunks})')
            cursor_start = cursor_end
    finally:
        try:
            conn.close()
        except Exception:
            pass

    new_latest = SalesTransactionLine.objects.aggregate(mx=Max('doc_date'))['mx']
    logger.info('[catchup] backfill done: %d rows over %d chunks, latest=%s',
                total, chunks, new_latest)
    return {'rows_upserted': total, 'chunks': chunks,
            'start': start, 'end': end, 'latest': new_latest}


def run_catchup(run_id=None) -> dict:
    """
    Full catch-up: chunked sales backfill (any gap size) → normal engine run
    (its remaining sync gap is now ~0, so it refreshes stock + recomputes fast).

    run_id: an already-created DemandCalculationRun (status='running') — the
    endpoint creates it up front so the frontend sees it immediately; we drive
    its backfill progress, then hand it to the engine so the whole operation is
    ONE continuous run for the dashboard banner. Safe in a background thread.
    """
    from apps.purchasing.engine import DemandEngine
    from apps.purchasing.models import DemandCalculationRun

    run = DemandCalculationRun.objects.filter(pk=run_id).first() if run_id else None
    try:
        summary = backfill_sales(run=run)
        _set_progress(run, 'calc', 100, 'إعادة تشغيل المحرك وحساب المؤشرات…')
        logger.info('[catchup] starting engine run after backfill')
        # Reuse the same run so backfill + sync + calc are one continuous run.
        result_run = DemandEngine().run(existing_run=run)
        summary['run_id'] = result_run.pk
        summary['run_status'] = result_run.status
        summary['items_processed'] = result_run.items_processed
        return summary
    except Exception as exc:
        logger.exception('[catchup] failed: %s', exc)
        if run and run.status == 'running':
            run.status = 'failed'
            run.error_message = f'catch-up failed: {exc}'[:500]
            run.progress = {'phase': 'failed', 'pct': 100, 'message': str(exc)[:200]}
            from django.utils import timezone as _tz
            run.finished_at = _tz.now()
            run.save(update_fields=['status', 'error_message', 'progress', 'finished_at'])
        raise
