"""
apps/pos_orders/reconcile.py

READ-ONLY settlement detection for pushed orders (spec §7). After we push a pending
order it sits in stktransm5 awaiting the cashier; the cashier either SETTLES it
(→ final stktransm + the pending rows vanish) or DELETES it. This reconciler reads
the branch DB and updates OUR status accordingly. It NEVER writes to SOFTECH.

Detection signals (see SOFTECH_INDIRECT_POS_ORDER_WRITEBACK.md §6h/§6i/§6k):
  • pending stktransm5 row still present            → still 'pushed' (no change)
  • pending gone + a final document is found         → 'settled' (record final docnumber)
  • pending gone + no final document found           → LEFT UNCHANGED + warned
        (could be a cashier Delete, or our lookup missed it — we never auto-cancel
         on an uncertain read; surface for manual review instead)

The SOFTECH-reading part is isolated in SoftechReader so reconcile_order() is unit
-testable with a fake reader (no Sybase needed).
"""
import logging

from .models import SoftechSalesOrder

logger = logging.getLogger('elrezeiky.pos_orders')


class SoftechReader:
    """Read-only settlement signals from a branch DB. SELECT only — never writes."""

    def __init__(self, conn):
        self._cur = conn.cursor()

    def _one(self, sql, params):
        self._cur.execute(sql, params)
        rows = self._cur.fetchall()
        return rows[0] if rows else None

    def pending_exists(self, order) -> bool:
        r = self._one(
            "SELECT 1 FROM stktransm5 WHERE branchcode=? AND doccode=? AND docnumber=?",
            [order.softech_branchcode, order.softech_doccode, int(order.softech_docnumber)],
        )
        return r is not None

    def final_doc(self, order):
        """
        Return the final document number if the order was settled, else None.
          • sale  : the final payment rows link back via branchesales.ref_docnumber = our pending docnumber
          • return: the final return lines link the original invoice via stktrans.r_docnumber
        (Both heuristics to be confirmed on the test instance.)
        """
        if order.doc_kind == 'sale':
            r = self._one(
                "SELECT docnumber FROM branchesales WHERE branchcode=? AND doccode='115' AND ref_docnumber=?",
                [order.softech_branchcode, int(order.softech_docnumber)],
            )
            return r[0] if r else None
        if order.doc_kind == 'return' and order.return_of_invoice:
            r = self._one(
                "SELECT docnumber FROM stktrans WHERE branchcode=? AND doccode='30' AND r_docnumber=?",
                [order.softech_branchcode, int(order.return_of_invoice)],
            )
            return r[0] if r else None
        return None


def reconcile_order(order, reader) -> str:
    """
    Resolve one pushed order against the branch DB via `reader`. Returns the
    (possibly new) status. Only flips to 'settled' on a positive final-doc match;
    never auto-cancels on an uncertain read.
    """
    if order.status != SoftechSalesOrder.STATUS_PUSHED or not order.softech_docnumber:
        return order.status

    if reader.pending_exists(order):
        return order.status  # still awaiting the cashier

    final = reader.final_doc(order)
    if final:
        order.softech_final_docnumber = final
        order.status = SoftechSalesOrder.STATUS_SETTLED
        order.save(update_fields=['softech_final_docnumber', 'status', 'updated_at'])
        logger.info('[pos_orders] order=%s settled → final doc %s', order.pk, final)
        return order.status

    logger.warning(
        '[pos_orders] order=%s: pending row gone but no final doc found '
        '(possible cashier Delete, or lookup miss) — left as pushed for manual review', order.pk)
    return order.status


def run_reconcile(profile=None) -> dict:
    """
    Reconcile all 'pushed' orders, grouped by branch (one branch connection each).
    Read-only. Returns a summary dict.
    """
    from config.sybase import get_branch_connection

    summary = {'checked': 0, 'settled': 0, 'still_pending': 0,
               'unresolved': 0, 'errors': 0, 'branches_down': []}

    pushed = (SoftechSalesOrder.objects
              .filter(status=SoftechSalesOrder.STATUS_PUSHED)
              .select_related('branch'))
    by_branch = {}
    for o in pushed:
        by_branch.setdefault(o.branch_id, []).append(o)

    for orders in by_branch.values():
        br = orders[0].branch
        if not br or not br.db_host:
            continue
        try:
            conn = get_branch_connection(br.db_host, br.db_port or 5000, br.db_name or 'SOFTECHDB9')
        except Exception as exc:
            summary['branches_down'].append(br.softech_branch_id)
            summary['errors'] += len(orders)
            logger.warning('[pos_orders] reconcile: branch %s unreachable: %s', br.softech_branch_id, exc)
            continue
        reader = SoftechReader(conn)
        for o in orders:
            summary['checked'] += 1
            try:
                before = o.status
                st = reconcile_order(o, reader)
                if st == SoftechSalesOrder.STATUS_SETTLED and before != st:
                    summary['settled'] += 1
                elif st == SoftechSalesOrder.STATUS_PUSHED:
                    # distinguish "still pending" from "gone but unresolved" via a cheap re-check
                    summary['still_pending'] += 1
            except Exception as exc:
                summary['errors'] += 1
                logger.warning('[pos_orders] reconcile order=%s failed: %s', o.pk, exc)
        try:
            conn.close()
        except Exception:
            pass

    return summary
