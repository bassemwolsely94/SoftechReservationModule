"""
apps/replacement/redemption.py — B2: the patient's بدل balance in Customer 360 / the POS, and funding a
POS order from it (doc 25 §22).

Never a second balance: every figure comes from legs.available() (= the case ledger, a projection of the
native SOFTECH A/P balance, minus product orders already reserved on it). Funding an order only RECORDS
which case(s) pay for it — one PostingOperation per case, exactly like a product order prepared from the
case workspace; it never touches the order's lines, prices or tenders. The POS flow pushes the order as
usual, the cashier makes the سداد voucher natively, and the daily check verifies it (reconstruct
._own_receipts recognises the settled order).

Rules: only LIVE cases are redeemable (a reconstructed case's patient is a matcher's guess — shown for
review only); same branch as the order; the order is a cash / delivery sale on the patient's PIC or the
«عميل تبديل» account (owner Q5); oldest balance first unless the operator names the cases; the patient
may top up within MAX_TOPUP_PCT; unfunding is allowed until the cashier settles the order. Owner D14: the
balance is never printed for the patient — staff with the replacement «view» right only.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from . import authz
from . import config as C
from .models import PostingOperation as Op, ReplacementCase as RC

CENT = Decimal('0.01')
REDEEMABLE_STATUSES = (RC.STATUS_EXECUTING, RC.STATUS_ENTITLEMENT_ACTIVE, RC.STATUS_SETTLED, RC.STATUS_RECONCILED)
FUNDABLE_ORDER_STATUSES = ('draft', 'ready', 'queued', 'push_failed', 'pushed')     # not settled / cancelled


def _cases_for(pic):
    return (RC.objects.filter(softech_pic__iexact=(pic or '').strip()).exclude(softech_pic='')
            .select_related('branch').order_by('purchase_date', 'id'))


def patient_balance(pic, *, staff, branch_id=None) -> dict | None:
    """{total_available, cases:[…], historical:{count, amount}} — None when the viewer may not see it."""
    from .legs import available
    if not pic or staff is None or not authz.allows(staff, 'view'):
        return None
    ids = staff.accessible_branch_ids
    rows, total = [], Decimal('0')
    live = _cases_for(pic).filter(origin=RC.ORIGIN_LIVE, status__in=REDEEMABLE_STATUSES,
                                  purchase_ref__isnull=False).exclude(settlement_mode=RC.MODE_CASH)
    for c in live:
        if ids is not None and c.branch_id not in ids:
            continue
        av = available(c)['available']
        if av <= 0:
            continue
        here = branch_id is None or c.branch_id == int(branch_id)
        rows.append({'id': c.pk, 'number': c.number, 'branchcode': c.branchcode, 'available': str(av),
                     'purchase_date': c.purchase_date.isoformat(), 'redeemable_here': here})
        if here:
            total += av
    hist = (_cases_for(pic).filter(origin=RC.ORIGIN_RECONSTRUCTED, outstanding__gt=CENT)
            .exclude(status__in=[RC.STATUS_UNCLAIMED, RC.STATUS_CANCELLED]))
    if ids is not None:
        hist = hist.filter(branch_id__in=ids)
    h = hist.aggregate(n=Sum('outstanding'))
    return {'total_available': str(total), 'cases': rows,
            'historical': {'count': hist.count(), 'amount': str(h['n'] or 0)}}


def order_total(order) -> Decimal:
    """Priced total once the POS priced it, else the POS engine's estimate (same as a workspace order)."""
    from .legs import estimate_order
    lines = list(order.lines.all())
    priced = sum((l.trans_price_total for l in lines), Decimal('0'))
    if priced > 0:
        return priced.quantize(CENT)
    return estimate_order([{'item_sale_price': str(l.item_sale_price), 'sale_tax_pct': str(l.sale_tax_pct),
                            'qty': str(l.qty), 'cust_discp': str(l.cust_discp)} for l in lines])


def order_funding(order) -> list[Op]:
    return list(Op.objects.filter(kind=Op.KIND_PRODUCT_SALE, sales_order=order)
                .exclude(status=Op.ST_CANCELLED).select_related('case'))


@transaction.atomic
def fund_order(order_id, *, user, case_ids=None, request=None) -> list[Op]:
    """Fund a POS cash / delivery order from the patient's live بدل balance (oldest first, or the named
    cases in order). Idempotent: an order already funded returns its operations unchanged."""
    from apps.pos_orders.models import SoftechSalesOrder
    from .legs import available
    from .reconstruct import tabdeel_pics
    from .workflow import _audit, _bump
    order = SoftechSalesOrder.objects.select_for_update().select_related('branch').get(pk=order_id)
    existing = order_funding(order)
    if existing:
        return existing
    if order.channel not in ('cash', 'delivery'):
        raise ValidationError('رصيد البدل يموّل فواتير النقدي أو التوصيل فقط.')
    if order.status not in FUNDABLE_ORDER_STATUSES:
        raise ValidationError('الطلب مُحصّل أو ملغى — لا يمكن تمويله.')
    pic = (order.softech_pic or '').strip()
    if not pic:
        raise ValidationError('الطلب بدون كود عميل — رصيد البدل على كود المريض أو «عميل تبديل» فقط.')
    named = [int(i) for i in (case_ids or [])]
    if named:
        cases = list(RC.objects.select_for_update().filter(pk__in=named))
        cases.sort(key=lambda c: named.index(c.pk))
        if len(cases) != len(set(named)):
            raise ValidationError('حالة غير موجودة.')
        tabdeel = pic in tabdeel_pics()
        for c in cases:
            if c.softech_pic != pic and not tabdeel:
                raise ValidationError(f'الحالة {c.number} لمريض آخر.')
    else:
        cases = list(_cases_for(pic).select_for_update(of=('self',)).filter(origin=RC.ORIGIN_LIVE))
    pool = []
    for c in cases:
        if (c.origin != RC.ORIGIN_LIVE or c.status not in REDEEMABLE_STATUSES or not c.purchase_ref_id
                or c.settlement_mode == RC.MODE_CASH):
            if named:
                raise ValidationError(f'الحالة {c.number} ليس لها رصيد منتجات قابل للصرف.')
            continue
        if c.branch_id != order.branch_id:
            if named:
                raise ValidationError(f'الحالة {c.number} من فرع آخر — الصرف من نفس الفرع فقط.')
            continue
        authz.require(user, 'post', case=c)
        av = available(c)['available']
        if av > 0:
            pool.append((c, av))
    if not pool:
        raise ValidationError('لا يوجد رصيد بدل متاح لهذا المريض في هذا الفرع.')
    total = order_total(order)
    if total <= 0:
        raise ValidationError('الطلب بدون أصناف.')
    pool_total = sum((av for _, av in pool), Decimal('0'))
    funded_total = min(total, pool_total)
    topup = total - funded_total
    if topup > pool_total * C.get('MAX_TOPUP_PCT'):
        raise ValidationError(f'قيمة الطلب ({total}) تتجاوز رصيد البدل المتاح ({pool_total}) بأكثر من المسموح.')
    ops, left = [], funded_total
    for c, av in pool:
        if left <= 0:
            break
        amount = min(av, left)
        left -= amount
        op = Op.objects.create(
            case=c, kind=Op.KIND_PRODUCT_SALE, idempotency_key=f'{c.pk}:pos:{order.pk}', sales_order=order,
            expected_value=amount, requested_by=user,
            result={'from_pos': True, 'order_total': str(total), 'funded_total': str(funded_total),
                    'customer_topup': str(topup if left <= 0 else 0)})
        ops.append(op)
        _bump(c, 'status')
        _audit('replacement_leg_prepared', c, user, request=request,
               new={'kind': op.kind, 'op': str(op.op_id), 'order': order.pk, 'funded': str(amount),
                    'order_total': str(total), 'topup': str(topup), 'from_pos': True})
    return ops


@transaction.atomic
def unfund_order(order_id, *, user, reason, request=None) -> int:
    """Release the balance reserved on a POS order (e.g. the patient changed the basket) — only until the
    cashier settles it; after that a correction is a return (B4)."""
    from apps.pos_orders.models import SoftechSalesOrder
    from .workflow import _audit, _bump
    if not (reason or '').strip():
        raise ValidationError('سبب إلغاء التمويل مطلوب.')
    order = SoftechSalesOrder.objects.select_for_update().get(pk=order_id)
    if order.status == 'settled' or order.softech_final_docnumber:
        raise ValidationError('الطلب مُحصّل — التصحيح يكون بمرتجع.')
    n = 0
    for op in order_funding(order):
        authz.require(user, 'post', case=op.case)
        op.status = Op.ST_CANCELLED
        op.idempotency_key = f'{op.idempotency_key}:void:{op.pk}'
        op.save(update_fields=['status', 'idempotency_key', 'updated_at'])
        _bump(RC.objects.select_for_update().get(pk=op.case_id), 'status')
        _audit('replacement_case_updated', op.case, user, request=request, note=reason,
               new={'unfunded_order': order.pk, 'op': str(op.op_id), 'released': str(op.expected_value)})
        n += 1
    return n
