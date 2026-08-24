"""
apps/pos_orders/points.py — SOFTECH PIC loyalty-points for the Indirect-POS.

CRACKED + VERIFIED LIVE (2026-08-19, branch 100/130 finalized sales + a live writer round-trip):

  personnewbal = Σ per line  floor( line_net × rate[line] / 100 )
      rate[line] = custdiscounts[ <channel rep>, items.itemcode_alt3 ]   (%)
      channel rep = CashCust (cash) / HomeDlvry (delivery)   (personsdata.personglobalcode)

Key facts established by live testing:
  • The item's CONTRACT-DISCOUNT classification (تصنيف خصم التعاقدات) for POINTS is
    `items.itemcode_alt3` — NOT `itemstoreclassif` (that drives line discounts). The rate is read
    from the channel-rep's `custdiscounts` schedule (the "Items Pricing" tab of CashCust/HomeDlvry).
  • Per-line FLOOR, then sum (verified: today's 853 basket → 15+28+88+90 = 221, exact).
  • Points are AWARDED BY SOFTECH AT THE CASHIER'S FINALIZATION, which COPIES the pending header's
    `personnewbal` (it does NOT recompute). So OUR writer MUST write the correct personnewbal —
    which we now compute here, using the LIVE current schedule (same one SOFTECH's POS reads).
  • Eligibility: cash + delivery earn; contract/insurance earn 0. Enrollment =
    localcustomers.picpoints=1 (SOFTECH gates the actual award).
  • Returns deduct (negative personnewbal / picpoints).
"""
import math

from django.conf import settings

# channels whose sales carry a points programme (retail cash-style). Contract/insurance = 0.
POINTS_ELIGIBLE_CHANNELS = set(getattr(
    settings, 'POS_POINTS_ELIGIBLE_CHANNELS', {'cash', 'delivery'}))


def channel_earns_points(channel) -> bool:
    return channel in POINTS_ELIGIBLE_CHANNELS


def compute_points(reader, channel, line_values, *, sign=1):
    """Points a sale earns: Σ per line floor( net × custdiscounts[rep, itemcode_alt3] / 100 ).
    `line_values`: iterable of (itemcode, line_net). `sign=-1` for a return. Returns (total:int,
    breakdown:list[{itemcode, alt3, rate, points}]). (0, []) if not eligible / rep unresolved."""
    if not channel_earns_points(channel):
        return 0, []
    rep = reader.customer_personcode(channel)   # CashCust / HomeDlvry personcode
    if not rep:
        return 0, []
    total, breakdown = 0, []
    for itemcode, net in line_values:
        alt3 = reader.item_alt3(itemcode)
        rate = 0.0
        if alt3:
            c = reader.contracted(rep, alt3)     # (custdiscp, allow_sell) or None
            if c is not None:
                rate = float(c[0])
        pts = math.floor(float(net or 0) * rate / 100.0) * sign   # per-line points (signed = line vf4)
        total += pts
        breakdown.append({'itemcode': str(itemcode), 'alt3': alt3, 'rate': rate, 'points': pts})
    return total, breakdown


def order_points(order):
    """personnewbal for an order, via a live branch read of the channel-rep schedule (current,
    exactly what SOFTECH's POS uses). Returns (points:int, breakdown:list). Graceful (0, []) on
    non-eligible channel or branch unreachable. Uses each line's net (trans_price_total)."""
    if not channel_earns_points(order.channel):
        return 0, []
    try:
        from .discount_authority import DiscountAuthorityReader
        reader = DiscountAuthorityReader(order.branch.effective_db_host,
                                         order.branch.effective_db_port,
                                         order.branch.db_name or 'SOFTECHDB9')
        try:
            # DISCOUNT ⊻ POINTS: a discounted line earns NO points (native rule — points and discounts
            # are mutually exclusive), so its net contributes 0. Points only accrue on undiscounted lines.
            lv = [(l.softech_itemcode, (0 if float(l.cust_discp or 0) > 0 else (l.trans_price_total or 0)))
                  for l in order.lines.all()]
            sign = -1 if order.doc_kind == 'return' else 1
            return compute_points(reader, order.channel, lv, sign=sign)
        finally:
            reader.close()
    except Exception:
        return 0, []


def is_enrolled(softech_pic: str) -> bool:
    """Live check of SOFTECH purchase-points enrollment (localcustomers.picpoints = 1).
    Delegates to the loyalty pic_bridge (central SOFTECH read); False on any error/absence."""
    pic = (softech_pic or '').strip()
    if not pic:
        return False
    try:
        from apps.loyalty.pic_bridge import is_softech_points_enrolled
        return bool(is_softech_points_enrolled(pic))
    except Exception:
        return False
