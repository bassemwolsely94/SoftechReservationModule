"""
apps/pos_orders/pos_cancel_read.py

READ-ONLY reader for SOFTECH `pos_cancel` — the «سجل المبيعات الغير مخزنة» log: every POS line
ENTERED then NOT committed to `stktrans` (decoded 2026-09-14, see memory softech_pos_cancel_log).
This is the lost-sale / cancellation audit trail. We only SELECT — never write.

Columns used: branchcode, doccode ('115' would-be sale / '30' would-be return), itemcode,
mitemname (cached name), transqty (0 ⇒ item selected/cleared without a qty), itemsaleprice
(public/list), transprice (unit sale after disc), transprice_total (amount), custcode, usercode
(cashier/seller), trans_time.

Design mirrors batch_availability.py: a thin live-read layer + a PURE shaping function that is
unit-testable without any Sybase contact.
"""
from config.sybase import get_branch_connection

# aggregate top-N abandoned items by the money that was on-screen then removed
_TOP_ITEMS_SQL = (
    "SELECT itemcode, max(mitemname), count(*), "
    "       sum(CASE WHEN transqty>0 THEN 1 ELSE 0 END), "
    "       sum(transprice_total) "
    "  FROM pos_cancel "
    " WHERE branchcode=? AND trans_time >= ? AND itemcode IS NOT NULL AND itemcode<>'' "
    " GROUP BY itemcode ORDER BY sum(transprice_total) DESC"
)
_BY_CASHIER_SQL = (
    "SELECT usercode, count(*), "
    "       sum(CASE WHEN transqty>0 THEN 1 ELSE 0 END), "
    "       sum(transprice_total) "
    "  FROM pos_cancel "
    " WHERE branchcode=? AND trans_time >= ? "
    " GROUP BY usercode ORDER BY sum(transprice_total) DESC"
)
# NOTE: no COUNT(DISTINCT) here — on a large pos_cancel it blows the query timeout. Distinct
# cashier/item counts are derived cheaply from the (small) grouped result sets instead.
_TOTALS_SQL = (
    "SELECT count(*), "
    "       sum(CASE WHEN transqty>0 THEN 1 ELSE 0 END), "
    "       sum(transprice_total) "
    "  FROM pos_cancel WHERE branchcode=? AND trans_time >= ?"
)
_READ_TIMEOUT = 90   # these aggregates scan a period of pos_cancel; give them room


def read_pos_cancel(db_host, branchcode, since, db_port=5000, db_name='SOFTECHDB9',
                    top_items=25):
    """ONE connection → raw aggregates from pos_cancel for a branch since `since` (datetime or
    'YYYY-MM-DD HH:MM:SS' string). Returns (totals_row, item_rows, cashier_rows). Read-only."""
    # jConnect can't bind a python datetime — pass an ASE-parseable string (implicit convert).
    since_s = since.strftime('%Y-%m-%d %H:%M:%S') if hasattr(since, 'strftime') else str(since)
    conn = get_branch_connection(db_host, db_port or 5000, db_name or 'SOFTECHDB9')
    try:
        cur = conn.cursor()
        cur.execute(_TOTALS_SQL, [str(branchcode), since_s], timeout=_READ_TIMEOUT)
        totals = cur.fetchone()
        cur.execute("SET ROWCOUNT %d" % int(top_items))
        cur.execute(_TOP_ITEMS_SQL, [str(branchcode), since_s], timeout=_READ_TIMEOUT)
        items = cur.fetchall()
        cur.execute("SET ROWCOUNT 0")
        cur.execute(_BY_CASHIER_SQL, [str(branchcode), since_s], timeout=_READ_TIMEOUT)
        cashiers = cur.fetchall()
        return totals, items, cashiers
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _f(v):
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _i(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def shape_lost_sales(totals, item_rows, cashier_rows, item_names=None, cashier_names=None):
    """PURE: raw pos_cancel aggregates → API response dict. `item_names` maps itemcode→full name
    (our catalog, better than the truncated mitemname); `cashier_names` maps usercode→staff name.
    `lost_value` = money that was on the POS screen (priced lines) then removed = Σ transprice_total."""
    item_names = item_names or {}
    cashier_names = cashier_names or {}
    tot = totals or (0, 0, 0)
    summary = {
        'events': _i(tot[0]),                 # total logged POS lines (incl. qty=0 clears)
        'priced_events': _i(tot[1]),          # lines that had a qty>0 then were cancelled
        'lost_value': _f(tot[2]),             # Σ transprice_total (money removed from the screen)
        # derived from the (small, uncapped) cashier groups; items list is capped so its distinct
        # count would be misleading — omitted on purpose.
        'distinct_cashiers': len(cashier_rows or []),
    }
    items = []
    for r in (item_rows or []):
        code = str(r[0]).strip()
        items.append({
            'itemcode': code,
            'name': item_names.get(code) or (str(r[1]).strip() if r[1] else code),
            'events': _i(r[2]),
            'priced_events': _i(r[3]),
            'lost_value': _f(r[4]),
        })
    cashiers = []
    for r in (cashier_rows or []):
        code = str(r[0]).strip()
        cashiers.append({
            'usercode': code,
            'name': cashier_names.get(code) or code,
            'events': _i(r[1]),
            'priced_events': _i(r[2]),
            'lost_value': _f(r[3]),
        })
    return {'summary': summary, 'top_items': items, 'by_cashier': cashiers}
