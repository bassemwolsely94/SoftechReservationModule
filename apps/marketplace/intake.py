"""
apps/marketplace/intake.py — order intake, accept/reject and the status machine (doc 38).

Deterministic rules only. Nothing here writes to SOFTECH: accept() hands off to to_pos.convert (draft POS
order). Every transition writes an ExternalOrderEvent and an AuditLog row; customer_phone is never put
in audit data or event notes.
"""
import logging
from decimal import Decimal

from django.db import IntegrityError, transaction

from apps.audit.models import AuditLog
from apps.marketplace import push, to_pos
from apps.marketplace.availability import sellable_qty
from apps.marketplace.eligibility import listing_problem
from apps.marketplace.models import (ChannelListing, ChannelStore, ExternalOrder, ExternalOrderEvent,
                                     ExternalOrderLine, MarketplaceChannel)
from apps.pos_orders.models import SoftechSalesOrder

logger = logging.getLogger('elrezeiky.marketplace')

S = ExternalOrder
ALLOWED = {
    S.STATUS_RECEIVED: {S.STATUS_ACCEPTED, S.STATUS_REJECTED, S.STATUS_CANCELLED},
    S.STATUS_ACCEPTED: {S.STATUS_PREPARING, S.STATUS_CANCELLED},
    S.STATUS_PREPARING: {S.STATUS_READY, S.STATUS_CANCELLED},
    S.STATUS_READY: {S.STATUS_HANDED_OVER, S.STATUS_CANCELLED},
    S.STATUS_HANDED_OVER: {S.STATUS_DELIVERED},
}
ILLEGAL = 'انتقال غير مسموح'
USE_ACTION = {S.STATUS_ACCEPTED: 'استخدم زر «قبول» — القبول يفحص الأصناف وينشئ مسودة نقطة البيع.',
              S.STATUS_REJECTED: 'استخدم زر «رفض» واكتب سبب الرفض.'}
CANCEL_NOTE_REQUIRED = 'اكتب سبب الإلغاء.'
PUSHED_DRAFT_NOTE = 'المسودة أُرسلت للكاشير — ألغها من نقطة البيع أو اعمل مرتجع'
# Problem codes from _apply_problems / eligibility.listing_problem → the words staff see (same wording as
# the /marketplace listings grid, frontend shared.jsx LISTING_PROBLEM).
PROBLEM_TEXT = {
    'not_listed': 'غير مضاف للمنصة', 'not_approved': 'غير معتمد', 'blocked': 'ممنوع',
    'restricted': 'مقيد (يحتاج مراجعة)', 'fridge': 'ثلاجة', 'out_of_stock': 'غير متوفر',
}


def _resolve_store(channel, external_store_id):
    qs = ChannelStore.objects.filter(channel=channel, is_active=True).select_related('branch')
    if channel.scope == MarketplaceChannel.SCOPE_PER_BRANCH:
        store = qs.filter(external_store_id=external_store_id).first()
    else:
        stores = list(qs[:2])
        store = stores[0] if len(stores) == 1 else None
    if store is None:
        raise ValueError('لا يوجد فرع مرتبط بهذا المتجر')
    return store


def _find_listing(channel, line):
    qs = ChannelListing.objects.filter(channel=channel).select_related('item', 'channel')
    listing = None
    if line.external_sku:
        listing = qs.filter(external_sku=line.external_sku).first()
    if listing is None and line.item_id:
        listing = qs.filter(item_id=line.item_id).first()
    return listing


def _event(order, from_status, to_status, user, note=''):
    ExternalOrderEvent.objects.create(order=order, from_status=from_status, to_status=to_status,
                                      by=user, note=note[:300])


def _audit(order, from_status, to_status, user, request=None, note=''):
    AuditLog.log(f'marketplace_order_{to_status}', user=user, obj=order, request=request,
                 old_data={'status': from_status}, new_data={'status': to_status},
                 extra={'channel': order.channel.code, 'external_id': order.external_id,
                        'branch_id': order.branch_id, 'note': note[:300]})


def _apply_problems(order):
    """Set line.problem on every line (same item on several lines: summed qty); return [(line, detail)]."""
    lines = list(order.lines.select_related('listing__item', 'listing__channel'))
    summed = {}
    for l in lines:
        if l.listing_id:
            summed[l.listing_id] = summed.get(l.listing_id, Decimal(0)) + l.qty
    problems = []
    for l in lines:
        problem, detail = ExternalOrderLine.PROBLEM_NONE, ''
        if l.listing is None:
            problem, detail = ExternalOrderLine.PROBLEM_NOT_LISTED, 'not_listed'
        else:
            lp = listing_problem(l.listing)
            if lp:
                problem, detail = ExternalOrderLine.PROBLEM_BLOCKED, lp
            elif summed[l.listing_id] > sellable_qty(l.listing, order.branch):
                problem, detail = ExternalOrderLine.PROBLEM_OOS, 'out_of_stock'
        if l.problem != problem:
            l.problem = problem
            l.save(update_fields=['problem'])
        if problem:
            problems.append((l, detail))
    return problems


def ingest(channel, incoming, *, source, user=None):
    """Create an ExternalOrder (+lines, event, audit). Returns (order, created); a duplicate is (existing, False)."""
    existing = ExternalOrder.objects.filter(channel=channel, external_id=incoming.external_id).first()
    if existing:
        return existing, False
    store = _resolve_store(channel, incoming.external_store_id)
    try:
        with transaction.atomic():
            order = ExternalOrder.objects.create(
                channel=channel, store=store, branch=store.branch, external_id=incoming.external_id,
                source=source, customer_name=incoming.customer_name, customer_phone=incoming.customer_phone,
                delivery_address=incoming.address, payment_mode=incoming.payment_mode,
                platform_total=incoming.total, raw_payload=incoming.raw or {}, created_by=user)
            for l in incoming.lines:
                listing = _find_listing(channel, l)
                ExternalOrderLine.objects.create(
                    order=order, listing=listing, item=listing.item if listing else None,
                    external_sku=l.external_sku, name=l.name, qty=l.qty, platform_unit_price=l.unit_price)
            _apply_problems(order)
            _event(order, '', S.STATUS_RECEIVED, user)
            _audit(order, '', S.STATUS_RECEIVED, user)
    except IntegrityError:
        existing = ExternalOrder.objects.filter(channel=channel, external_id=incoming.external_id).first()
        if existing:
            return existing, False
        raise
    return order, True


def _transition(order, to_status, user, note='', request=None):
    """Validate, then write status + event + audit. The caller holds the row lock / transaction."""
    from_status = order.status
    if to_status not in ALLOWED.get(from_status, ()):
        raise ValueError(ILLEGAL)
    order.status = to_status
    order.save(update_fields=['status', 'updated_at'])
    _event(order, from_status, to_status, user, note)
    _audit(order, from_status, to_status, user, request, note)


def _locked(order):
    return (ExternalOrder.objects.select_for_update(of=('self',))
            .select_related('channel', 'store', 'branch', 'pos_order').get(pk=order.pk))


def accept(order, user, request=None):
    with transaction.atomic():
        order = _locked(order)
        if order.status != S.STATUS_RECEIVED:
            raise ValueError(ILLEGAL)
        problems = _apply_problems(order)
        if not problems:
            _transition(order, S.STATUS_ACCEPTED, user, request=request)
            to_pos.convert(order, user)  # a ValueError here rolls the status change back
    if problems:  # raised after the block so the refreshed line.problem values are kept
        raise ValueError('؛ '.join(f'{l.name or l.external_sku}: {PROBLEM_TEXT.get(detail, detail)}'
                                   for l, detail in problems))
    transaction.on_commit(lambda: push.push_status(order))
    return order


def reject(order, user, reason, request=None):
    with transaction.atomic():
        order = _locked(order)
        if order.status != S.STATUS_RECEIVED:
            raise ValueError(ILLEGAL)
        order.reject_reason = (reason or '')[:200]
        order.save(update_fields=['reject_reason'])
        _transition(order, S.STATUS_REJECTED, user, note=order.reject_reason, request=request)
    transaction.on_commit(lambda: push.push_status(order))
    return order


def _cancel_pos_draft(order, user, request=None):
    """Cancelling an order that already has a POS draft (rule: never touch SOFTECH from here).
    Never sent to the cashier (draft / ready) → the draft is cancelled in PG and audited; returns ''.
    Already sent (queued / pushing / pushed / push_failed / settled) → nothing is touched, the order is
    flagged needs_review and the returned text goes on the cancel event."""
    pos = order.pos_order
    if pos is None or pos.status == SoftechSalesOrder.STATUS_CANCELLED:
        return ''
    if pos.status in (SoftechSalesOrder.STATUS_DRAFT, SoftechSalesOrder.STATUS_READY):
        before = pos.status
        pos.status = SoftechSalesOrder.STATUS_CANCELLED
        pos.save(update_fields=['status', 'updated_at'])
        AuditLog.log('marketplace_pos_draft_cancelled', user=user, obj=order, request=request,
                     old_data={'pos_order_id': pos.pk, 'status': before},
                     new_data={'pos_order_id': pos.pk, 'status': pos.status},
                     extra={'channel': order.channel.code, 'external_id': order.external_id})
        return ''
    order.needs_review = True
    order.save(update_fields=['needs_review', 'updated_at'])
    return PUSHED_DRAFT_NOTE


def set_status(order, to_status, user, note='', request=None):
    """Status moves after acceptance (and cancel). Accept / reject go through accept() / reject() only;
    cancel needs a reason and takes care of the order's POS draft in the same transaction."""
    if to_status in USE_ACTION:
        raise ValueError(USE_ACTION[to_status])
    note = (note or '').strip()
    if to_status == S.STATUS_CANCELLED and not note:
        raise ValueError(CANCEL_NOTE_REQUIRED)
    with transaction.atomic():
        order = _locked(order)
        if to_status not in ALLOWED.get(order.status, ()):
            raise ValueError(ILLEGAL)
        if to_status == S.STATUS_CANCELLED:
            extra = _cancel_pos_draft(order, user, request)
            if extra:
                note = f'{note} — {extra}'
        _transition(order, to_status, user, note=note, request=request)
    transaction.on_commit(lambda: push.push_status(order))
    return order
