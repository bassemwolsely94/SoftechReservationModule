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


def summarize(batches):
    """{total, count, out_of_stock} — out_of_stock ⇒ reservation pathway."""
    total = round(sum(b['qty'] for b in batches), 5)
    return {'total': total, 'count': len(batches), 'out_of_stock': total <= 0}
