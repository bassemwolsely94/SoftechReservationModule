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
    return ExternalOrder.objects.select_for_update().select_related('channel', 'store', 'branch').get(pk=order.pk)


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
        raise ValueError('؛ '.join(f'{l.name or l.external_sku}: {detail}' for l, detail in problems))
    push.push_status(order)
    return order


def reject(order, user, reason, request=None):
    with transaction.atomic():
        order = _locked(order)
        if order.status != S.STATUS_RECEIVED:
            raise ValueError(ILLEGAL)
        order.reject_reason = (reason or '')[:200]
        order.save(update_fields=['reject_reason'])
        _transition(order, S.STATUS_REJECTED, user, note=order.reject_reason, request=request)
    push.push_status(order)
    return order


def set_status(order, to_status, user, note='', request=None):
    with transaction.atomic():
        order = _locked(order)
        _transition(order, to_status, user, note=note, request=request)
    push.push_status(order)
    return order
