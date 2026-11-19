"""
apps/pos_orders/offer_uses.py — commit offer uses after a sale really posted (D-12, owner 2026-11-19).

One function for every path that posts a POS order: the interactive push (views.push_order), the
supervisor «flush now» (views.flush_now) and the scheduled flush (cmd flush_pos_orders). Before D-12
only the interactive push consumed uses, so a sale queued while the branch was offline and posted
later never counted against the offer's limits (audit BE-4).

Safe on retry: apps.offers.usage.consume_offer_uses is idempotent per order (an OfferApplication
already was_applied=True for this order is skipped) and serialised on the Offer row lock. It is a
no-op for an order with no offer line, so it changes nothing while offers are switched off.
PostgreSQL only — never touches SOFTECH.
"""
import logging

logger = logging.getLogger('pos_orders')


def posted(result) -> bool:
    """True when push_order's result means the sale is in SOFTECH (fresh write or already there)."""
    return bool(isinstance(result, dict) and (result.get('ok') or result.get('already_pushed')))


def consume_after_post(order, *, customer=None) -> dict:
    """Consume the offer uses of a POSTED order. Returns the keys to merge into the push result:
    {'offer_uses_consumed': n} | {'offer_overuse': True} | {}. Never raises for a usage limit — the
    sale is already posted; an over-limit race is logged and flagged for review."""
    from apps.offers.usage import consume_offer_uses, UsageLimitExceeded
    if customer is None:
        from apps.offers.order_attach import resolve_order_customer
        customer = resolve_order_customer(order)
    try:
        consumed = consume_offer_uses(order, customer=customer)
    except UsageLimitExceeded as e:
        logger.error('[pos_orders] order=%s POSTED but offer overused (%s) — flagged for review',
                     order.pk, e.scope)
        return {'offer_overuse': True}
    return {'offer_uses_consumed': len(consumed)} if consumed else {}
