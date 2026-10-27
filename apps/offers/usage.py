"""
apps/offers/usage.py — offer usage limits + concurrency-safe consumption.

A "use" is an OfferApplication with was_applied=True (flipped at push). Two phases:
  • CHECK (eval/attach) — `offer_exhausted` filters an offer that has hit its
    `max_uses_total` / `max_uses_per_customer`, so it never even attaches.
  • CONSUME (push, step 5) — `consume_offer_uses` runs under `select_for_update`
    on the Offer row so two concurrent cashiers can't both take the last use;
    the loser gets UsageLimitExceeded. Idempotent per order.

Read-only vs SOFTECH (only the PG OfferApplication table changes).
"""
from django.db import transaction


class UsageLimitExceeded(Exception):
    def __init__(self, offer, scope):
        self.offer = offer
        self.scope = scope          # 'total' | 'per_customer'
        super().__init__(f'offer {getattr(offer, "pk", "?")} usage limit reached ({scope})')


def committed_uses(offer, customer=None, *, exclude_order=None):
    """(total, per_customer) count of applied uses. per_customer is None if no customer."""
    from .models import OfferApplication
    qs = OfferApplication.objects.filter(offer=offer, was_applied=True)
    if exclude_order is not None:
        qs = qs.exclude(pos_order=exclude_order)
    total = qs.count()
    per_customer = qs.filter(customer=customer).count() if customer is not None else None
    return total, per_customer


def offer_exhausted(offer, customer=None, *, exclude_order=None):
    """True if applying `offer` (for `customer`) would exceed a configured limit."""
    if offer.max_uses_total is None and offer.max_uses_per_customer is None:
        return False, ''
    total, per_customer = committed_uses(offer, customer, exclude_order=exclude_order)
    if offer.max_uses_total is not None and total >= offer.max_uses_total:
        return True, 'total'
    if (offer.max_uses_per_customer is not None and customer is not None
            and per_customer is not None and per_customer >= offer.max_uses_per_customer):
        return True, 'per_customer'
    return False, ''


def precheck_order(order, customer=None):
    """
    Read-only guard used BEFORE a live push: return a reason string if any offer
    already attached to the order is exhausted (so we never post an over-limit
    promo), else None. The authoritative arbitration is the locked consume below.
    """
    from .models import Offer
    offer_ids = (order.lines.filter(discount_source='offer', applied_offer__isnull=False)
                 .values_list('applied_offer_id', flat=True).distinct())
    for oid in offer_ids:
        offer = Offer.objects.get(pk=oid)
        exhausted, scope = offer_exhausted(offer, customer, exclude_order=order)
        if exhausted:
            return f'استُنفد حد العرض: {offer.name_ar or offer.name}'
    return None


@transaction.atomic
def consume_offer_uses(order, *, customer=None):
    """
    Commit the offer uses on `order` (flip its OfferApplication rows to
    was_applied=True), enforcing limits under a row lock. Idempotent: an order
    whose uses are already committed is a no-op. Raises UsageLimitExceeded if a
    limit would be broken (the caller must abort the push).
    """
    from .models import Offer, OfferApplication

    offer_ids = list(
        order.lines.filter(discount_source='offer', applied_offer__isnull=False)
        .values_list('applied_offer_id', flat=True).distinct())

    consumed = []
    for oid in offer_ids:
        offer = Offer.objects.select_for_update().get(pk=oid)   # serialize contenders

        # idempotency: this order already consumed this offer → skip
        if OfferApplication.objects.filter(offer=offer, pos_order=order, was_applied=True).exists():
            continue

        exhausted, scope = offer_exhausted(offer, customer, exclude_order=order)
        if exhausted:
            raise UsageLimitExceeded(offer, scope)

        OfferApplication.objects.filter(offer=offer, pos_order=order).update(
            was_applied=True, customer=customer)
        consumed.append(oid)
    return consumed
