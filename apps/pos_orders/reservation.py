"""
apps/pos_orders/reservation.py — SOFTECH reservation (حجز, doccode 80) writeback.

A حجز holds an out-of-stock line so the sale can be saved before the item physically
arrives. It is written to `stktransm`/`stktrans` (NOT the `*5` pending tables) and is
**stock-affecting**: the line carries `newqty = transqty` (a stock-IN) so the concurrent
sale (115) can draw it. Structure verified read-only @br130 (doc
SOFTECH_POS_RESERVATION_FLOW.md), e.g. حجز 80#33938 → sale 452840.

Links to the sale via header `docnumber2 = <sale docnumber>` and line
`r_doccode='115' / r_docnumber=<sale>`. The real batch is chosen later at dispense
(تسليم حجز 180); the حجز itself uses a PLACEHOLDER expiry (no batch known yet).

⚠️ SAFETY: unlike the pending-sale writeback (side-effect-free until settled), a حجز moves
inventory. There is no test instance, so this module is **probe-first**: `probe_reservation`
executes the real INSERTs then ROLLS BACK (zero residue). `push_reservation` commits and is
gated behind POS_WRITER_ENABLED + an explicit `confirm` — keep it off until validated on a
test instance.

OPEN QUESTION (validate before committing): native حجز rows observed link to the FINAL sale
(452840) and use the branch-own `lastdocnumberin` counter — i.e. created at/after settlement,
not at the pending stage. Confirm the exact trigger point (seller vs cashier) and whether the
حجز should reference the pending (`stktransm5`) docnumber or the final one in our flow.
"""
from decimal import Decimal

from django.conf import settings

from config.sybase import get_branch_connection
from .writer import (
    _exec_insert, _q1, _raw_value, _TODAY_MIDNIGHT, _NOW, _write_charset, WriterDisabled,
    writer_enabled,
)

# The placeholder expiry a حجز line carries before the real batch is known (observed
# 2012-12-11 on native reservations). Overridable for installs that use a different sentinel.
PLACEHOLDER_EXPIRY = getattr(settings, 'POS_RESERVATION_PLACEHOLDER_EXPIRY', '2012-12-11')
RESERVATION_DOCCODE = '80'
RESERVATION_COUNTER = 'lastdocnumberin'     # branch row (ver_branch=1)


def _placeholder():
    return _raw_value({'__dt__': f'{PLACEHOLDER_EXPIRY} 00:00:00'})


def _hagz_header(order, docnumber, sale_docnumber, seller, doc_value):
    """stktransm header for a حجز (doccode 80) linked to its sale via docnumber2."""
    return {
        'branchcode': order.softech_branchcode, 'doccode': RESERVATION_DOCCODE,
        'docnumber': int(docnumber), 'docdate': _TODAY_MIDNIGHT,
        'docnumber2': int(sale_docnumber),                 # ← the sale this reservation fulfils
        'docvalue': float(doc_value), 'docvalue1': float(doc_value), 'docvalue2': float(doc_value),
        'cust_branch_code': '-80', 'storecode': order.store_code,
        'ptcode': '-1', 'ptclassifcode': '-1', 'cust_professional': '0',
        'usercode': seller or '1', 'cashiercode': seller or '1',
        'phcode': order.softech_pic or '', 'bcurrency': '1', 'docvaluebc': float(doc_value),
        'bcrate': 1.0, 'mitemsys': 'AR', 'origdoc': '5',
        'fatstatuscode': '11', 'fatcurrentstatus': '15', 'trans_time': _NOW,
    }


def _hagz_line(order, ln, docnumber, sale_docnumber, seller):
    """stktrans line for a حجز: stock-IN (newqty=transqty), placeholder expiry, refs the sale."""
    qty = float(ln.qty or 0)
    price = float(ln.trans_price or ln.item_sale_price or 0)
    total = float(ln.trans_price_total or (price * qty))
    return {
        'branchcode': order.softech_branchcode, 'doccode': RESERVATION_DOCCODE,
        'docnumber': int(docnumber), 'docdate': _TODAY_MIDNIGHT, 'storecode': order.store_code,
        'itemcode': ln.softech_itemcode, 'transqty': qty, 'transprice': price,
        'newqty': qty,                                      # ← the stock injected by the حجز
        'newcostprice': float(ln.new_cost_price or price),
        'itemexpirydate': _placeholder(),                   # ← real batch picked at dispense (180)
        'itemsaleprice': float(ln.item_sale_price or 0),
        'itemsalestax': float(ln.item_sale_tax or 0),
        'itemsaleprice_tax': float(ln.item_sale_price_tax or ln.item_sale_price or 0),
        'transprice_total': total, 'custdiscp': float(ln.cust_discp or 0),
        'pharmacydiscp': 0.0, 'additionaldiscp': 0.0, 'specialdiscp': 0.0,
        'bonusqty': 0.0, 'dblitemflag': 1, 'retqty': 0.0,
        'r_doccode': '115', 'r_docnumber': int(sale_docnumber), 'r_docdate': _TODAY_MIDNIGHT,
        's_doccode': '100', 'usercode': seller or '1', 'item_partno': 'Reservation',
    }


def _execute_reservation(conn, order, sale_docnumber, seller):
    """Allocate the حجز serial (native read+1) and insert header + lines. Returns readback."""
    cur_no = _q1(conn, f"SELECT {RESERVATION_COUNTER} FROM lastdocnumbers HOLDLOCK "
                       "WHERE branchcode=? AND ver_branch=1", [order.softech_branchcode])
    docnumber = int(cur_no[0]) + 1
    doc_value = float(order.doc_value or sum(float(l.trans_price_total or 0) for l in order.lines.all()))

    _exec_insert(conn, 'stktransm', _hagz_header(order, docnumber, sale_docnumber, seller, doc_value))
    for ln in order.lines.all():
        _exec_insert(conn, 'stktrans', _hagz_line(order, ln, docnumber, sale_docnumber, seller))

    hdr = _q1(conn, "SELECT docnumber, docnumber2, docvalue FROM stktransm "
                    "WHERE branchcode=? AND doccode=? AND docnumber=?",
              [order.softech_branchcode, RESERVATION_DOCCODE, docnumber])
    nlines = int(_q1(conn, "SELECT COUNT(*) FROM stktrans WHERE branchcode=? AND doccode=? AND docnumber=?",
                     [order.softech_branchcode, RESERVATION_DOCCODE, docnumber])[0])
    return {
        'reservation_docnumber': docnumber, 'sale_docnumber': int(sale_docnumber),
        'header': [str(x) for x in hdr] if hdr else None,
        'lines_found': nlines, 'lines_expected': order.lines.count(),
        'ok': bool(hdr is not None and nlines == order.lines.count()),
    }


def _conn(order):
    return get_branch_connection(order.branch.db_host, order.branch.db_port or 5000,
                                 order.branch.db_name or 'SOFTECHDB9', charset=_write_charset())


def probe_reservation(order, sale_docnumber, seller=None):
    """Execute the real حجز INSERTs in a transaction, verify, then ROLL BACK (zero residue)."""
    seller = seller or order.seller_usercode or getattr(settings, 'POS_DEFAULT_SELLER_USERCODE', '')
    conn = _conn(order)
    try:
        conn.begin()
        res = _execute_reservation(conn, order, sale_docnumber, seller)
        res['mode'] = 'rollback_probe'
        res['committed'] = False
        return res
    finally:
        try:
            conn.rollback()
        finally:
            conn.close()


def push_reservation(order, sale_docnumber, seller=None, confirm=False):
    """Commit a real حجز (stock-affecting). Gated: writer must be enabled AND confirm=True."""
    if not writer_enabled():
        raise WriterDisabled('POS writer is disabled (POS_WRITER_ENABLED=False).')
    if not confirm:
        raise WriterDisabled('Reservation commit requires confirm=True (stock-affecting write).')
    seller = seller or order.seller_usercode or getattr(settings, 'POS_DEFAULT_SELLER_USERCODE', '')
    conn = _conn(order)
    try:
        conn.begin()
        res = _execute_reservation(conn, order, sale_docnumber, seller)
        if not res['ok']:
            conn.rollback()
            res['committed'] = False
            return res
        conn.commit()
        res['mode'] = 'commit'
        res['committed'] = True
        return res
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
