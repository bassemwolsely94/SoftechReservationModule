"""
apps/marketplace/availability.py — per-branch quantity and platform price for a listing (read-only).

Nothing here writes to SOFTECH. Quantity = on-hand in sellable stores, minus stock already promised to
open platform orders, minus the channel buffer; whole units, floored at 0, optionally capped.
"""
import math
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q, Sum

from apps.catalog.models import ItemStock
from apps.marketplace.eligibility import listing_problem
from apps.marketplace.models import ExternalOrder, ExternalOrderLine, MarketplaceChannel
from apps.pos_orders.models import SoftechSalesOrder

# 102 unreturnable expired, 103 cosmetics, 105 returnable, 110 closed branch store (book residue).
QUARANTINE_STORE_CODES = frozenset({'102', '103', '105', '110'})
OPEN_STATUSES = (ExternalOrder.STATUS_ACCEPTED, ExternalOrder.STATUS_PREPARING, ExternalOrder.STATUS_READY)
_QUARTER = Decimal('0.25')


def _qty(on_hand, reserved, channel) -> Decimal:
    """Single formula for both sellable_qty and snapshot (whole units, floored at 0, optional cap)."""
    qty = Decimal(math.floor(max(Decimal(0), on_hand - reserved - channel.stock_buffer)))
    if channel.max_qty_per_item is not None:
        qty = min(qty, Decimal(channel.max_qty_per_item))
    return qty


def _open_lines(branch):
    return (ExternalOrderLine.objects
            .filter(order__branch=branch, order__status__in=OPEN_STATUSES)
            .filter(Q(order__pos_order__isnull=True) | ~Q(order__pos_order__status=SoftechSalesOrder.STATUS_SETTLED)))


def _stock_qs(branch):
    return ItemStock.objects.filter(branch=branch).exclude(softech_store_code__in=QUARANTINE_STORE_CODES)


def sellable_qty(listing, branch) -> Decimal:
    if listing_problem(listing):
        return Decimal(0)
    on_hand = (_stock_qs(branch).filter(item_id=listing.item_id)
               .aggregate(t=Sum('quantity_on_hand'))['t'] or Decimal(0))
    reserved = (_open_lines(branch).filter(item_id=listing.item_id)
                .aggregate(t=Sum('qty'))['t'] or Decimal(0))
    return _qty(on_hand, reserved, listing.channel)


def platform_price(listing) -> Decimal:
    shelf = listing.item.pack_price_tax or Decimal(0)
    channel = listing.channel
    if channel.price_rule == MarketplaceChannel.PRICE_SHELF_PLUS_PCT:
        raw = shelf * (1 + channel.price_pct / Decimal(100))
        return ((raw / _QUARTER).quantize(Decimal(1), rounding=ROUND_HALF_UP) * _QUARTER).quantize(Decimal('0.01'))
    return shelf.quantize(Decimal('0.01'))


def snapshot(channel, store) -> list:
    """One row per listing of the channel, for the store's branch (constant query count)."""
    branch = store.branch
    listings = list(channel.listings.select_related('item', 'channel').order_by('id'))
    item_ids = [l.item_id for l in listings]
    on_hand = {r['item_id']: r['t'] for r in _stock_qs(branch).filter(item_id__in=item_ids)
               .values('item_id').annotate(t=Sum('quantity_on_hand'))}
    reserved = {r['item_id']: r['t'] for r in _open_lines(branch).filter(item_id__in=item_ids)
                .values('item_id').annotate(t=Sum('qty'))}
    rows = []
    for l in listings:
        problem = listing_problem(l)
        qty = Decimal(0) if problem else _qty(on_hand.get(l.item_id) or Decimal(0),
                                              reserved.get(l.item_id) or Decimal(0), channel)
        rows.append({'listing_id': l.id, 'item_id': l.item_id, 'external_sku': l.external_sku,
                     'qty': qty, 'price': platform_price(l), 'problem': problem})
    return rows
