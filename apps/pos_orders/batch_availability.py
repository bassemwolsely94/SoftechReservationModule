"""
apps/pos_orders/batch_availability.py

Live per-batch stock availability for the POS batch-pick modal and out-of-stock
detection.

SOURCE (confirmed read-only @br130, 2026-06-23): **`stkbalexpiry`**, keyed by
**`storecode`** (the `branchcode` column is an unused `'0'`). Each row is
`(itemcode, itemexpirydate, itemqty[, batchno])` and the per-item batch sum reconciles
exactly to `stkbal.nowqty` (e.g. item 100038 → 2.0+1.0+3.0 = 6.0). It is maintained by
the encrypted procs `sp_expirytrans` / `sp_stkbalexpiry_from_stkbal`; we only READ it.

This is the same table the dispense (تسليم حجز 180) modal reads, and the absence of any
rows for an item means it is out of stock → the reservation (حجز 80) pathway applies.
"""
from config.sybase import get_branch_connection

_SQL = ("SELECT itemexpirydate, itemqty, batchno FROM stkbalexpiry "
        "WHERE storecode=? AND itemcode=? AND itemqty>0 ORDER BY itemexpirydate")
# items.itemtrans: '0' = NON-stockable (service/fee item — no stock, no batch, no reservation).
# Anything else is stock-controlled. Same field the writer reads for _allocate_line stock_controlled.
_ITEMTRANS_SQL = "SELECT itemtrans FROM items WHERE itemcode=?"


def _is_stockable(itemtrans):
    return not (itemtrans is not None and str(itemtrans).strip() == '0')


def _parse_rows(rows):
    """Pure: DB rows → sorted batch dicts (earliest expiry first = FEFO)."""
    out = []
    for r in rows:
        out.append({
            'expiry': (str(r[0])[:10] if r[0] else None),
            'qty': float(r[1] or 0),
            'batchno': (str(r[2]).strip() if r[2] else ''),
        })
    return out


def available_batches(db_host, storecode, itemcode, db_port=5000, db_name='SOFTECHDB9'):
    """Read the live batches for one item at one store (read-only)."""
    conn = get_branch_connection(db_host, db_port or 5000, db_name or 'SOFTECHDB9')
    try:
        cur = conn.cursor()
        cur.execute(_SQL, [str(storecode), str(itemcode)])
        return _parse_rows(cur.fetchall())
    finally:
        try:
            conn.close()
        except Exception:
            pass


def item_availability(db_host, storecode, itemcode, db_port=5000, db_name='SOFTECHDB9'):
    """ONE connection → (batches, stockable). stockable=False ⇒ service/non-stocked item: the POS
    adds a single plain line (no batch pick, NO reservation), matching the writer's _allocate_line.
    Without this, a service item (no stkbalexpiry rows) looks out-of-stock and is wrongly reserved."""
    conn = get_branch_connection(db_host, db_port or 5000, db_name or 'SOFTECHDB9')
    try:
        cur = conn.cursor()
        cur.execute(_ITEMTRANS_SQL, [str(itemcode)])
        r = cur.fetchone()
        stockable = _is_stockable(r[0] if r else None)
        cur.execute(_SQL, [str(storecode), str(itemcode)])
        return _parse_rows(cur.fetchall()), stockable
    finally:
        try:
            conn.close()
        except Exception:
            pass


def summarize(batches):
    """{total, count, out_of_stock} — out_of_stock ⇒ reservation pathway (stock items only)."""
    total = round(sum(b['qty'] for b in batches), 5)
    return {'total': total, 'count': len(batches), 'out_of_stock': total <= 0}


def batch_action(batches, batch_required=False, stockable=True):
    """The authoritative POS batch matrix (CASE 1-5) as a pure decision — backend owns the rule
    (CLAUDE.md §7); the POS renders/enforces it, it does not invent it.

    `batch_required` = SOFTECH items.itempartno «رقم القطعة أو الباتش» (mandatory batch selection).
    Returns one of:
      'plain'       — non-stockable service/fee line, no batch, no حجز (CASE: itemtrans=0).
      'reserve'     — no batch stock at all → reservation pathway (CASE 3, any item).
      'auto_select' — mandatory batch + exactly ONE available batch → SOFTECH auto-selects it
                      (CASE 2, owner-confirmed); returns `batch` = that single batch.
      'must_select' — mandatory batch + multiple batches → cashier MUST pick before push (CASE 1).
      'optional'    — not mandatory + stock exists → current FEFO helper, pick optional (CASE 4/5).
    """
    if not stockable:
        return {'action': 'plain', 'batch': None}
    total = round(sum(b['qty'] for b in batches), 5)
    if total <= 0 or not batches:
        return {'action': 'reserve', 'batch': None}
    if batch_required:
        if len(batches) == 1:
            return {'action': 'auto_select', 'batch': batches[0]}
        return {'action': 'must_select', 'batch': None}
    return {'action': 'optional', 'batch': None}
