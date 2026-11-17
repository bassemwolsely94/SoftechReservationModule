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

# 102 unreturnable expired, 103 cosmetics, 105 returnable, 110 closed branch store (book residue).
QUARANTINE_STORE_CODES = frozenset({'102', '103', '105', '110'})
OPEN_STATUSES = (ExternalOrder.STATUS_ACCEPTED, ExternalOrder.STATUS_PREPARING, ExternalOrder.STATUS_READY)
_QUARTER = Decimal('0.25')


def sellable_qty(listing, branch) -> Decimal:
    if listing_problem(listing):
        return Decimal(0)
    channel = listing.channel
    on_hand = (ItemStock.objects.filter(item_id=listing.item_id, branch=branch)
               .exclude(softech_store_code__in=QUARANTINE_STORE_CODES)
               .aggregate(t=Sum('quantity_on_hand'))['t'] or Decimal(0))
    reserved = (ExternalOrderLine.objects
                .filter(item_id=listing.item_id, order__branch=branch, order__status__in=OPEN_STATUSES)
                .filter(Q(order__pos_order__isnull=True) | ~Q(order__pos_order__status='settled'))
                .aggregate(t=Sum('qty'))['t'] or Decimal(0))
    qty = max(Decimal(0), on_hand - reserved - channel.stock_buffer)
    qty = Decimal(math.floor(qty))
    if channel.max_qty_per_item is not None:
        qty = min(qty, Decimal(channel.max_qty_per_item))
    return qty


def platform_price(listing) -> Decimal:
    shelf = listing.item.pack_price_tax or Decimal(0)
    channel = listing.channel
    if channel.price_rule == MarketplaceChannel.PRICE_SHELF_PLUS_PCT:
        raw = shelf * (1 + channel.price_pct / Decimal(100))
        return ((raw / _QUARTER).quantize(Decimal(1), rounding=ROUND_HALF_UP) * _QUARTER).quantize(Decimal('0.01'))
    return shelf


def snapshot(channel, store) -> list:
    """One row per listing of the channel, for the store's branch."""
    rows = []
    for l in channel.listings.select_related('item', 'channel').order_by('id'):
        rows.append({
            'listing_id': l.id, 'item_id': l.item_id, 'external_sku': l.external_sku,
            'qty': sellable_qty(l, store.branch), 'price': platform_price(l), 'problem': listing_problem(l),
        })
    return rows
