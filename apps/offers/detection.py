"""
apps/offers/detection.py — find HISTORICAL manual promos in the sales mirror.

READ-ONLY provenance layer (Phase-3 exec step 2). It scans
`customers_purchasehistoryline` for customer-discounted lines (`disc_customer_pct
> 0`) and classifies each, writing only to the PG `ManualOfferMatch` table — NEVER
to SOFTECH, NEVER mutating the invoice. Deterministic (fixed thresholds); never
auto-creates an Offer.

Classification precedence (per §7b of the design):
  1. exact_offer       — item is targeted by a defined Offer AND the observed
                         discount % matches that offer's magnitude → HIGH.
  2. bxgy_cheapest      — the 1+1 / 1+½ fingerprint: the cheapest-priced line in the
                         invoice carries ~100%/~50% while a dearer line does not → MEDIUM.
  3. unmapped_discount  — any other customer discount, no matching offer → LOW.
"""
from collections import defaultdict
from decimal import Decimal

from .engine import _target_cache, item_matches_offer_targeting

PCT_TOL = Decimal('0.5')      # % tolerance for magnitude matching
BXGY_FULL = Decimal('100')
BXGY_HALF = Decimal('50')


def _d(v):
    return v if isinstance(v, Decimal) else Decimal(str(v or 0))


def _expected_magnitude(offer, item):
    """The % this offer would put on a qualifying line (for exact matching)."""
    if getattr(offer, 'authorization_source', 'item_card') == 'item_card':
        return _d(getattr(item, 'pos_discp', 0))
    if offer.offer_type == 'percent':
        return _d(offer.value)
    if offer.offer_type == 'bxgy':
        return _d(offer.get_discount_percent)
    return None   # fixed / qty_tier → not a single flat %; skip exact match


def _line_discount_amount(ln):
    gross = _d(ln.list_price) * _d(ln.quantity)
    if gross <= 0:
        gross = _d(ln.unit_price) * _d(ln.quantity)
    amt = gross - _d(ln.line_total)
    return amt if amt > 0 else (gross * _d(ln.disc_customer_pct) / Decimal('100'))


def classify_line(ln, invoice_lines, offers, caches):
    """Return a match dict for one discounted line (no DB writes)."""
    D = _d(ln.disc_customer_pct)
    amount = _line_discount_amount(ln).quantize(Decimal('0.01'))

    # 1. exact match to a defined offer
    for offer in offers:
        if not item_matches_offer_targeting(offer, ln.item, caches.get(offer.id)):
            continue
        expected = _expected_magnitude(offer, ln.item)
        if expected is not None and abs(D - expected) <= PCT_TOL:
            return _m('exact_offer', 'high', D, amount, offer)

    # 2. cheapest-unit BXGY fingerprint
    min_price = min((_d(l.unit_price) for l in invoice_lines), default=_d(ln.unit_price))
    is_cheapest = _d(ln.unit_price) <= min_price
    dearer_exists = any(_d(l.unit_price) > _d(ln.unit_price) for l in invoice_lines)
    near_full = abs(D - BXGY_FULL) <= PCT_TOL
    near_half = abs(D - BXGY_HALF) <= PCT_TOL
    if is_cheapest and dearer_exists and (near_full or near_half):
        # attach a bxgy offer that targets this item if one exists (else unmapped-but-bxgy)
        covering = next((o for o in offers
                         if o.offer_type == 'bxgy'
                         and item_matches_offer_targeting(o, ln.item, caches.get(o.id))), None)
        return _m('bxgy_cheapest', 'medium', D, amount, covering,
                  detail={'shape': '1+1' if near_full else '1+½'})

    # 3. unmapped
    return _m('unmapped_discount', 'low', D, amount, None)


def detect_manual_offers(*, since=None, branch_id=None, limit=None, persist=True):
    """Scan the sales mirror; return a summary. Writes only ManualOfferMatch rows."""
    from apps.customers.models import PurchaseHistoryLine
    from .models import Offer, ManualOfferMatch

    offers = list(Offer.objects.prefetch_related('items', 'categories', 'tags', 'branches'))
    caches = {o.id: _target_cache(o) for o in offers}

    disc_qs = (PurchaseHistoryLine.objects
               .filter(disc_customer_pct__gt=0, purchase__doc_code='115', item__isnull=False)
               .select_related('purchase', 'purchase__branch', 'item'))
    if since:
        disc_qs = disc_qs.filter(purchase__invoice_date__gte=since)
    if branch_id:
        disc_qs = disc_qs.filter(purchase__branch_id=branch_id)
    disc_qs = disc_qs.order_by('-purchase__invoice_date')
    if limit:
        disc_qs = disc_qs[:limit]

    disc_lines = list(disc_qs)
    invoice_ids = {l.purchase_id for l in disc_lines}

    # Full per-invoice line context (incl. the UNDISCOUNTED dearer lines) so the
    # cheapest-unit BXGY fingerprint can tell there is a dearer, unpromoted line.
    context = defaultdict(list)
    for ln in (PurchaseHistoryLine.objects
               .filter(purchase_id__in=invoice_ids)
               .select_related('item').iterator(chunk_size=2000)):
        context[ln.purchase_id].append(ln)

    counts = {'exact_offer': 0, 'bxgy_cheapest': 0, 'unmapped_discount': 0, 'scanned': 0}
    for ln in disc_lines:
        counts['scanned'] += 1
        m = classify_line(ln, context[ln.purchase_id], offers, caches)
        counts[m['pattern']] += 1
        if persist:
                ManualOfferMatch.objects.update_or_create(
                    purchase_id=ln.purchase_id, item=ln.item,
                    defaults={
                        'matched_offer': m['offer'],
                        'pattern': m['pattern'], 'confidence': m['confidence'],
                        'disc_pct': m['disc_pct'], 'discount_amount': m['amount'],
                        'branch': ln.purchase.branch, 'invoice_date': ln.purchase.invoice_date,
                        'detail': m['detail'],
                    })
    return counts


def _m(pattern, confidence, disc_pct, amount, offer, detail=None):
    return {'pattern': pattern, 'confidence': confidence, 'disc_pct': disc_pct,
            'amount': amount, 'offer': offer, 'detail': detail or {}}
