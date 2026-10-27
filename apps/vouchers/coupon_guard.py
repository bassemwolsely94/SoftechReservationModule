"""
apps/vouchers/coupon_guard.py

Redemption guard for gift coupons sold on the indirect POS (/pos → apps/pos_orders).
A SERVED coupon line (item 118639, −50 EGP) is accepted only when its serial — the number
printed on the paper coupon, entered in the line's `batchno` — is a real, issued, unused
coupon held by the order's branch, and the order carries the coupon OWNER's customer code
(owner's decision 2026-10-06: family members may use it, but the owner's PIC is entered).

Every check reads SOFTECH live and READ-ONLY (history from HQ, the branch stock row from
the branch node) plus our own open POS orders, so a coupon issued minutes ago is accepted
and one already used — or sitting in another open order — is refused. Fail-closed: if the
coupon cannot be verified the line is refused (financial accuracy beats convenience).

Switch: settings.COUPON_POS_GUARD_ENABLED (default False until the POS screen collects the
serial). Rule toggles: COUPON_GUARD_REQUIRE_ISSUED / _REQUIRE_OWNER / _REQUIRE_BRANCH_STOCK
(default True). Spec: docs/architecture/SOFTECH_GIFT_VOUCHER_STOCKING.md §8.
"""
import logging
from decimal import Decimal

from django.conf import settings

from . import coupons

logger = logging.getLogger('elrezeiky.vouchers')

_DB = 'SOFTECHDB9.dbo'
# POS orders that already hold their coupon (not yet visible as a settled 115 in SOFTECH).
_OPEN_ORDER_STATUSES = ('ready', 'queued', 'pushing', 'pushed', 'push_failed')


def guard_enabled():
    return bool(getattr(settings, 'COUPON_POS_GUARD_ENABLED', False))


def _flag(name):
    return bool(getattr(settings, name, True))


def _dec(v):
    try:
        return Decimal(str(v if v is not None else 0))
    except Exception:
        return Decimal('0')


def _s(v):
    return '' if v is None else str(v).strip()


# ── SOFTECH reads (SELECT only) ────────────────────────────────────────────────
def read_serial_history(conn, serial):
    """From HQ (consolidated history): stocked qty on the served leg, net redemptions,
    net issues to customers and who the coupon was issued to."""
    served, points = coupons.served_item(), coupons.points_item()
    out = {'stocked': Decimal('0'), 'redeemed': Decimal('0'), 'issued': Decimal('0'),
           'issued_pic': '', 'last_redeem': None}
    cur = conn.cursor()
    cur.execute(f"""
        SELECT itemcode, doccode, sum(transqty), max(docdate) FROM {_DB}.stktrans
        WHERE itemcode IN (?, ?) AND item_partno = ?
          AND doccode IN ('10', '115', '180', '30', '81', '170', '70')
        GROUP BY itemcode, doccode
    """, [served, points, serial])
    for item, doccode, qty, last in cur.fetchall():
        item, doccode, qty = _s(item), _s(doccode), _dec(qty)
        if item == served:
            if doccode == '10':
                out['stocked'] += qty
            elif doccode in ('115', '180'):
                out['redeemed'] += qty
                out['last_redeem'] = max(filter(None, [out['last_redeem'], coupons.to_date(last)]), default=None)
            elif doccode in ('30', '81'):
                out['redeemed'] -= qty
        elif item == points:
            if doccode == '170':
                out['issued'] += qty
            elif doccode == '70':
                out['issued'] -= qty
    if out['issued'] > 0:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT m.phcode, t.docdate FROM {_DB}.stktrans t, {_DB}.stktransm m
            WHERE t.itemcode = ? AND t.item_partno = ? AND t.doccode = '170'
              AND m.branchcode = t.branchcode AND m.doccode = t.doccode AND m.docnumber = t.docnumber
            ORDER BY t.docdate DESC
        """, [points, serial])
        row = cur.fetchone()
        out['issued_pic'] = _s(row[0]) if row else ''
    return out


def read_branch_stock(conn, store_code, serial):
    """(qty, expiry) of this serial's stock row in the order's store (branch node)."""
    cur = conn.cursor()
    cur.execute(f"SELECT sum(itemqty), max(itemexpirydate) FROM {_DB}.stkbalexpiry "
                f"WHERE storecode = ? AND itemcode = ? AND batchno = ?",
                [str(store_code), coupons.served_item(), serial])
    row = cur.fetchone()
    return _dec(row[0] if row else 0), (coupons.to_date(row[1]) if row else None)


def open_orders_holding(serial, exclude_order_id=None):
    """Our own open POS orders that already carry this coupon serial."""
    from apps.pos_orders.models import SoftechSalesOrderLine
    qs = (SoftechSalesOrderLine.objects
          .filter(softech_itemcode=coupons.served_item(), batchno__iexact=serial,
                  order__status__in=_OPEN_ORDER_STATUSES))
    if exclude_order_id:
        qs = qs.exclude(order_id=exclude_order_id)
    return list(qs.values_list('order_id', flat=True).distinct())


# ── rules (pure) ───────────────────────────────────────────────────────────────
def evaluate(serial, history, branch_qty, customer_pic, held_by):
    """Deterministic rule set → list of Arabic error messages ([] = accept)."""
    errs = []
    stocked = history['stocked']
    if stocked <= 0:
        errs.append(f'السريال {serial} غير مسجل كمخزون كوبونات — تأكد من الرقم المطبوع على الكوبون.')
        return errs
    if history['redeemed'] >= stocked:
        when = f' بتاريخ {history["last_redeem"]}' if history['last_redeem'] else ''
        errs.append(f'الكوبون {serial} مستخدم من قبل{when} — لا يمكن استخدامه مرة أخرى.')
    if held_by:
        errs.append(f'الكوبون {serial} مضاف بالفعل في أمر بيع مفتوح آخر (#{", #".join(map(str, held_by))}).')
    if _flag('COUPON_GUARD_REQUIRE_ISSUED') and history['issued'] <= 0:
        errs.append(f'الكوبون {serial} لم يُصرف لعميل من الكول سنتر — لا يمكن استخدامه.')
    if (_flag('COUPON_GUARD_REQUIRE_OWNER') and history['issued_pic']
            and _s(customer_pic) != history['issued_pic']):
        errs.append(f'يجب تسجيل الفاتورة على كود صاحب الكوبون ({history["issued_pic"]}).')
    if _flag('COUPON_GUARD_REQUIRE_BRANCH_STOCK') and branch_qty is not None and branch_qty <= 0:
        errs.append(f'الكوبون {serial} غير موجود في مخزون هذا الفرع — يجب تحويله للفرع أولاً.')
    return errs


# ── entry points ───────────────────────────────────────────────────────────────
def check_serial(raw, *, branch=None, store_code='', customer_pic='', exclude_order_id=None,
                 hq_conn=None, branch_conn=None):
    """Full check of one coupon serial. Returns {ok, serial, errors, info}. Opens (and
    closes) its own read-only connections unless given. Fail-closed on read errors."""
    parsed = coupons.parse_serial(raw)
    if not parsed:
        return {'ok': False, 'serial': _s(raw), 'info': {},
                'errors': ['أدخل سريال الكوبون كما هو مطبوع (مثال 27301-ABC123).']}
    serial = parsed[2]
    from config.sybase import get_branch_connection, get_sybase_connection
    own_hq = own_br = False
    try:
        if hq_conn is None:
            hq_conn, own_hq = get_sybase_connection(), True
        history = read_serial_history(hq_conn, serial)
        branch_qty, expiry = None, None
        if store_code:
            if branch_conn is None and branch is not None and getattr(branch, 'effective_db_host', ''):
                branch_conn, own_br = get_branch_connection(
                    branch.effective_db_host, branch.effective_db_port, branch.db_name or 'SOFTECHDB9'), True
            branch_qty, expiry = read_branch_stock(branch_conn or hq_conn, store_code, serial)
            if not _flag('COUPON_GUARD_REQUIRE_BRANCH_STOCK'):
                branch_qty = None
    except Exception as exc:
        logger.warning('[coupon_guard] cannot verify %s: %s', serial, exc)
        return {'ok': False, 'serial': serial, 'info': {},
                'errors': [f'تعذّر التحقق من الكوبون {serial} من SOFTECH — حاول مرة أخرى.']}
    finally:
        for c, own in ((hq_conn, own_hq), (branch_conn, own_br)):
            if own and c is not None:
                try:
                    c.close()
                except Exception:
                    pass
    held_by = open_orders_holding(serial, exclude_order_id)
    errors = evaluate(serial, history, branch_qty, customer_pic, held_by)
    info = {'stocked': float(history['stocked']), 'redeemed': float(history['redeemed']),
            'issued': float(history['issued']), 'issued_to': history['issued_pic'],
            'branch_qty': (float(branch_qty) if branch_qty is not None else None),
            'expiry': (expiry.isoformat() if expiry else None),
            'held_by_orders': held_by}
    return {'ok': not errors, 'serial': serial, 'errors': errors, 'info': info}


def validate_order_coupons(order):
    """Hook for apps/pos_orders/validators.validate_order. Returns {} or
    {'coupons': [messages]} for the order's served-coupon lines."""
    if not guard_enabled():
        return {}
    lines = [ln for ln in order.lines.all() if _s(ln.softech_itemcode) == coupons.served_item()]
    if not lines:
        return {}
    msgs, seen = [], set()
    for i, ln in enumerate(lines, start=1):
        if _dec(ln.qty) != 1:
            msgs.append(f'كوبون في السطر {i}: سطر منفصل لكل كوبون (الكمية 1) مع سريال كل كوبون.')
            continue
        parsed = coupons.parse_serial(ln.batchno)
        if parsed and parsed[2] in seen:
            msgs.append(f'الكوبون {parsed[2]} مكرر في نفس الأمر.')
            continue
        if parsed:
            seen.add(parsed[2])
        res = check_serial(ln.batchno, branch=order.branch, store_code=order.store_code,
                           customer_pic=order.softech_pic, exclude_order_id=order.pk)
        msgs.extend(res['errors'])
    return {'coupons': msgs} if msgs else {}
