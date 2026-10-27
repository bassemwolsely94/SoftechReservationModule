"""
apps/pos_orders/stock.py — live out-of-stock guard for the Indirect-POS writer.

Native SOFTECH refuses to dispense an item with insufficient balance when the reservation system
is off ("رصيد الصنف لا يسمح بالبيع كما أن نظام الحجز غير مفعل"); finalizing such a pending raises
RAISERROR 21225 (منع الصرف). Our writer only writes normal sale lines (doccode 115) — it does NOT
write a حجز (80) reservation document — so an out-of-stock line would ALWAYS fail finalization
(negative balance) regardless of branch. Therefore we reject OOS sale lines up front, matching the
native behaviour, instead of writing an un-finalizable order.

(When the حجز-80 reservation writeback is built + validated, OOS lines on a reservation-ENABLED
branch can instead be routed there; until then we reject.)
"""
from collections import defaultdict

from django.conf import settings

from config.sybase import get_branch_connection


def enabled() -> bool:
    return bool(getattr(settings, 'POS_ENFORCE_STOCK', True))


def reservation_enabled(order) -> bool:
    """True when SOFTECH's reservation system (نظام الحجز) is on for this branch — there an OOS line
    is written as a حجز (the cashier's finalization auto-creates the حجز 80) instead of rejected."""
    return str(order.branch.softech_branch_id) in set(getattr(settings, 'POS_RESERVATION_BRANCHES', []))


def check_order_stock(order):
    """Return a list of {index, itemcode, available, needed, detail} for SALE lines whose item is
    out of stock at the order's store (live stkbal read). Empty for returns, or when all in stock.
    On a RESERVATION-ENABLED branch, OOS is allowed (written as حجز) → returns []. Graceful: on a
    branch-read error returns [] (never blocks on a transient outage)."""
    if order.doc_kind != 'sale' or reservation_enabled(order):
        return []
    lines = list(order.lines.all())
    if not lines:
        return []
    # aggregate the qty needed per item (same item can appear on multiple lines)
    need = defaultdict(float)
    for ln in lines:
        need[str(ln.softech_itemcode).strip()] += float(ln.qty or 0)
    try:
        conn = get_branch_connection(order.branch.effective_db_host, order.branch.effective_db_port,
                                     order.branch.db_name or 'SOFTECHDB9')
    except Exception:
        return []
    avail, service = {}, set()
    try:
        for code in need:
            cur = conn.cursor()
            cur.execute("SELECT nowqty FROM stkbal WHERE branchcode=? AND storecode=? AND itemcode=?",
                        [order.softech_branchcode, order.store_code, code])
            r = cur.fetchone()
            avail[code] = float(r[0]) if r and r[0] is not None else 0.0
            # service / non-stocked item (items.itemtrans='0') has no physical stock → always available
            ce = conn.cursor()
            ce.execute("SELECT itemtrans FROM items WHERE itemcode=?", [code])
            er = ce.fetchone()
            if er and er[0] is not None and str(er[0]).strip() == '0':
                service.add(code)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    errors, flagged = [], set()
    for i, ln in enumerate(lines):
        code = str(ln.softech_itemcode).strip()
        if code in flagged or code in service:   # services are never out of stock
            continue
        if avail.get(code, 0.0) < need[code] - 1e-9:
            flagged.add(code)
            errors.append({
                'index': i, 'itemcode': code, 'available': avail.get(code, 0.0), 'needed': need[code],
                'detail': (f'رصيد الصنف {code} غير كافٍ (متاح {avail.get(code, 0.0):g}, مطلوب {need[code]:g}) — '
                           'لا يُسمح بالصرف بدون رصيد (نظام الحجز غير مفعّل).'),
            })
    return errors


def check_item_restrictions(order):
    """Return [{index, itemcode, detail}] for lines whose item is PROHIBITED for this doc_kind — matching
    native's per-item handling on the item card ('التعامل في الصنف' → العملاء), stored in items.itemtrans3:
        0 = بيع+ارتجاع (sale & return)   1 = بيع فقط (sale only, no return)
        2 = ارتجاع فقط (return only, no sale)   3 = إيقاف كامل (full stop — neither)
    Plus items.itemarchive='1' = archived (prohibited entirely, e.g. item 100000). A SALE is blocked when
    itemtrans3 ∈ {2,3} or archived; a RETURN when itemtrans3 ∈ {1,3} or archived. Native refuses these
    (منع الصرف / منع الإرجاع); we reject up front so the order is never un-finalizable. Graceful [] on error."""
    lines = list(order.lines.all())
    if not lines:
        return []
    is_return = order.doc_kind == 'return'
    block_t3 = {'1', '3'} if is_return else {'2', '3'}
    try:
        conn = get_branch_connection(order.branch.effective_db_host, order.branch.effective_db_port,
                                     order.branch.db_name or 'SOFTECHDB9')
    except Exception:
        return []
    errors, seen = [], {}
    try:
        for i, ln in enumerate(lines):
            code = str(ln.softech_itemcode).strip()
            if code not in seen:
                cur = conn.cursor()
                cur.execute("SELECT itemarchive, itemtrans3 FROM items WHERE itemcode=?", [code])
                r = cur.fetchone()
                arch = (str(r[0]).strip() == '1') if (r and r[0] is not None) else False
                t3 = (str(r[1]).strip() if (r and r[1] is not None) else '0')
                seen[code] = (arch, t3)
            arch, t3 = seen[code]
            if arch or t3 in block_t3:
                reason = ('صنف مؤرشف — ممنوع التعامل' if arch else
                          ('ممنوع إرجاع هذا الصنف' if is_return else 'ممنوع بيع/صرف هذا الصنف (منع الصرف)'))
                errors.append({'index': i, 'itemcode': code, 'detail': f'الصنف {code}: {reason}.'})
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return errors
