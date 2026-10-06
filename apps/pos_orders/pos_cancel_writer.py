"""
apps/pos_orders/pos_cancel_writer.py — Wave 3 inc3.

Batch-write OUR POS item-selection telemetry (PosSelectionEvent) into the SOFTECH `pos_cancel`
activity log, so our indirect-POS feeds the native «المبيعات غير المخزنة» report exactly like the
native POS does. `pos_cancel` is an append-only LOG (no stock / document / money / e-invoice) — this
never touches a transactional or financial table.

Fidelity: rows match the native pos_cancel schema (12 cols) column-for-column; values come from the
captured selection at the moment it happened (list/unit/qty/total, seller, customer, time).

Exclusion (owner: "every add, exclude sold"): an 'add' whose cart (`cart_token` == the order's
client_token) reached a real SOFTECH sale document (order status pushing/pushed/settled) AND contains
that item is suppressed — it went to the cashier, so it lives in stktrans, not the lost-sale log.
'clear' (qty=0) events are always written (mirror native's zero rows).

Safety:
  • Gated by settings.POS_CANCEL_WRITE_ENABLED (default False → dry-run only).
  • Idempotency without a PK on pos_cancel: we CLAIM events (set softech_written_at) BEFORE the
    Sybase insert and UN-CLAIM them if it fails. A crash can therefore only UNDER-post (a few log
    rows retried/skipped) — it can NEVER double-post. Same "never double-post" guarantee as writer.py.
  • Per-branch: writes to each branch's own node (pos_cancel is per-node, branchcode-keyed);
    an unreachable branch is skipped and retried next run.
"""
import logging

from django.conf import settings
from django.utils import timezone

from .models import PosSelectionEvent, SoftechSalesOrder

logger = logging.getLogger('elrezeiky.pos_orders')

# Order statuses that mean "this reached a real SOFTECH sale document" → its items are NOT lost sales.
_REACHED_SOFTECH = {SoftechSalesOrder.STATUS_PUSHING,
                    SoftechSalesOrder.STATUS_PUSHED,
                    SoftechSalesOrder.STATUS_SETTLED}


def write_enabled():
    return bool(getattr(settings, 'POS_CANCEL_WRITE_ENABLED', False))


def _sold_codes_by_cart(tokens):
    """{cart_token: set(item_codes)} for carts whose order reached a real SOFTECH sale document."""
    out = {}
    qs = (SoftechSalesOrder.objects
          .filter(client_token__in=list(tokens), status__in=_REACHED_SOFTECH)
          .prefetch_related('lines'))
    for o in qs:
        out[o.client_token] = {str(l.softech_itemcode).strip()
                               for l in o.lines.all() if l.softech_itemcode}
    return out


def _row_from_event(e):
    """Native pos_cancel row (dict, ordered like the table). Datetimes as ASE-castable string
    literals; NOT NULL varchar codes default to '0' (never empty)."""
    occ = timezone.localtime(e.occurred_at) if timezone.is_aware(e.occurred_at) else e.occurred_at
    return {
        'branchcode':       (e.softech_branchcode or '')[:5] or '0',
        'doccode':          '30' if e.doc_kind == 'return' else '115',
        'itemcode':         (e.item_code or '').strip()[:6],
        'itemsaleprice':    round(float(e.itemsaleprice or 0), 2),
        'transprice':       round(float(e.transprice or 0), 4),
        'transqty':         round(float(e.transqty or 0), 5),
        'transprice_total': round(float(e.transprice_total or 0), 4),
        'custcode':         (e.custcode or '').strip()[:8] or '0',
        'usercode':         (e.seller_usercode or '').strip()[:5] or '0',
        'trans_time':       occ.strftime('%Y-%m-%d %H:%M:%S'),
        'trans_date':       occ.strftime('%Y-%m-%d 00:00:00'),
        'mitemname':        ((e.item_name or '').strip()[:20] or None),
    }


def write_pos_cancel_batch(*, dry_run=None, limit=2000, min_age_minutes=360):
    """Write qualifying selection events into SOFTECH pos_cancel, per branch. `dry_run` defaults to
    (not write_enabled()). `min_age_minutes` lets carts finalize before we decide sold-vs-lost.
    Returns a summary dict; in dry-run it also returns a small sample of the rows it WOULD write."""
    from . import writer as W
    from config.sybase import get_branch_connection

    if dry_run is None:
        dry_run = not write_enabled()

    from datetime import timedelta
    cutoff = timezone.now() - timedelta(minutes=max(0, int(min_age_minutes)))
    events = list(PosSelectionEvent.objects
                  .filter(softech_written_at__isnull=True, occurred_at__lt=cutoff)
                  .select_related('branch').order_by('occurred_at')[:limit])
    summary = {'candidates': len(events), 'written': 0, 'skipped_sold': 0,
               'dry_run': dry_run, 'write_enabled': write_enabled(), 'branches': {}}
    if not events:
        return summary

    sold = _sold_codes_by_cart({e.cart_token for e in events if e.cart_token})

    to_write, skip_ids = [], []
    for e in events:
        if (e.event_type == PosSelectionEvent.EVENT_ADD and e.cart_token in sold
                and (e.item_code or '').strip() in sold[e.cart_token]):
            skip_ids.append(e.id)
            continue
        to_write.append(e)
    summary['skipped_sold'] = len(skip_ids)

    now = timezone.now()
    if skip_ids and not dry_run:                       # sold → processed, never inserted (no dup risk)
        PosSelectionEvent.objects.filter(id__in=skip_ids).update(softech_written_at=now,
                                                                 write_error='skip:sold')

    by_branch = {}
    for e in to_write:
        by_branch.setdefault(e.branch, []).append(e)

    for branch, evs in by_branch.items():
        bc = branch.softech_branch_id
        rows = [_row_from_event(e) for e in evs]
        if dry_run:
            summary['branches'][bc] = {'would_write': len(rows), 'sample': rows[:3]}
            continue

        ids = [e.id for e in evs]
        # CLAIM before the write so a crash can only under-post, never double-post.
        PosSelectionEvent.objects.filter(id__in=ids).update(softech_written_at=now, write_error='')
        conn = None
        try:
            conn = get_branch_connection(branch.effective_db_host, branch.effective_db_port,
                                         branch.db_name or 'SOFTECHDB9', charset=W._write_charset())
            conn.begin()
            for row in rows:
                W._exec_insert(conn, 'pos_cancel', row)
            conn.commit()
        except Exception as exc:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            # UN-CLAIM → retried next run (branch unreachable, or a write error)
            PosSelectionEvent.objects.filter(id__in=ids).update(softech_written_at=None,
                                                                write_error=str(exc)[:200])
            summary['branches'][bc] = {'error': str(exc)[:200], 'attempted': len(rows)}
            logger.warning('[pos_cancel_writer] branch %s write failed (un-claimed): %s', bc, exc)
            continue
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
        summary['written'] += len(rows)
        summary['branches'][bc] = {'written': len(rows)}
        logger.info('[pos_cancel_writer] branch %s wrote %d pos_cancel rows', bc, len(rows))

    return summary
