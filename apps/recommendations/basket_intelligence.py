"""
recommendations/basket_intelligence.py — the POS Basket-Intelligence + Sales-
Opportunity service.

Composes EXISTING signals (never re-mines): FrequentlyBoughtTogether pairs,
per-customer CustomerRecommendation, and catalog.ProductBundle completion. Emits
one DETERMINISTIC, ranked list of opportunities (rule 7/10 — server decides the
ranking, React only renders it). No LLM.

Two hard rules:
  • SAFETY WINS (rule 4): any item that fails catalog.safety.blocks_sale is
    dropped — an upsell can never surface a non-sellable/blocked item.
  • Never suggest something already in the basket.

`score` is a plain weighted sum of the contributing signals, so the same inputs
always rank the same way. Stock is annotated (flagged), never used to silently
drop a suggestion.
"""
from django.db.models import Sum

from apps.catalog.models import Item, ItemStock, EXCLUDED_STORE_CODES
from apps.catalog.safety import item_safety_flags, blocks_sale

# Signal weights (deterministic). Personalized refill > personalized > bundle > FBT.
W_FBT = 1.0
W_PERSONAL = 1.5
W_REFILL = 2.0
W_BUNDLE = 1.2

# Segment re-rank multiplier (deterministic): high-value customers see premium cross-sells
# ranked up; at-risk customers see their own repeat items ranked up (retention). Never drops
# a suggestion — only reorders — so the safety filter and FBT logic are untouched.
SEGMENT_BOOST = 1.3
_PREMIUM_SEGMENTS = {'vip', 'loyal'}
_RETENTION_SEGMENTS = {'at_risk', 'dormant'}


def _customer_segment(customer_id):
    if not customer_id:
        return ''
    from apps.customers.models import Customer
    return (Customer.objects.filter(pk=customer_id)
            .values_list('segment', flat=True).first() or '')


def _latest_run():
    from .models import RecommendationEngineRun
    return RecommendationEngineRun.objects.filter(status='success').order_by('-started_at').first()


def basket_intelligence(item_codes, *, customer_id=None, branch_id=None, limit=6):
    """Ranked opportunities for the current basket. item_codes = list of softech_id."""
    basket = list(Item.objects.filter(softech_id__in=[c for c in item_codes if c]))
    basket_ids = {i.id for i in basket}

    # candidate_id -> {'score': float, 'reasons': set()}
    cand = {}

    def bump(item_id, weight, reason):
        if item_id in basket_ids or item_id is None:
            return
        slot = cand.setdefault(item_id, {'score': 0.0, 'reasons': set()})
        slot['score'] += weight
        slot['reasons'].add(reason)

    run = _latest_run()
    if run and basket_ids:
        _add_fbt(run, basket_ids, bump)
    if run and customer_id:
        _add_customer_recs(run, customer_id, bump)
    if basket_ids:
        _add_bundle_completion(basket_ids, bump)

    if not cand:
        return []

    items = {i.id: i for i in Item.objects.filter(id__in=cand.keys())}
    stock = _branch_stock(list(cand.keys()), branch_id) if branch_id else {}

    # segment re-rank inputs (deterministic)
    segment = _customer_segment(customer_id)
    basket_avg = _avg_price(basket)

    rows = []
    for iid, slot in cand.items():
        it = items.get(iid)
        if not it or blocks_sale(it):      # SAFETY: drop blocked/non-sellable
            continue
        score, boost = slot['score'], None
        price = float(it.pack_price or 0)
        if segment in _PREMIUM_SEGMENTS and basket_avg and price > basket_avg:
            score *= SEGMENT_BOOST; boost = 'premium'      # VIP/loyal → premium upsell
        elif segment in _RETENTION_SEGMENTS and ({'refill', 'personal'} & slot['reasons']):
            score *= SEGMENT_BOOST; boost = 'retention'     # at-risk → their own repeat items
        rows.append({
            'item_id': it.id,
            'softech_id': it.softech_id,
            'name': it.name,
            'pack_price': price,
            'score': round(score, 4),
            'reasons': sorted(slot['reasons']),
            'boost': boost,
            'qty_at_branch': stock.get(iid) if branch_id else None,
            'safety_flags': item_safety_flags(it),
        })

    rows.sort(key=lambda r: (-r['score'], r['name']))
    return rows[:limit]


def _avg_price(basket):
    prices = [float(i.pack_price or 0) for i in basket if i.pack_price]
    return sum(prices) / len(prices) if prices else 0.0


def _add_fbt(run, basket_ids, bump):
    from .models import FrequentlyBoughtTogether
    pairs = (FrequentlyBoughtTogether.objects
             .filter(run=run, item_a_id__in=basket_ids)
             .values('item_b_id', 'score'))
    for p in pairs:
        bump(p['item_b_id'], W_FBT * float(p['score'] or 0), 'fbt')


def _add_customer_recs(run, customer_id, bump):
    from .models import CustomerRecommendation
    recs = (CustomerRecommendation.objects
            .filter(run=run, customer_id=customer_id)
            .values('item_id', 'score', 'is_chronic_related'))
    for r in recs:
        w = (W_REFILL if r['is_chronic_related'] else W_PERSONAL) * (0.5 + float(r['score'] or 0))
        bump(r['item_id'], w, 'refill' if r['is_chronic_related'] else 'personal')


def _add_bundle_completion(basket_ids, bump):
    from apps.catalog.models import BundleItem
    # bundles the basket already touches → suggest their other members
    bundle_ids = set(BundleItem.objects.filter(item_id__in=basket_ids)
                     .values_list('bundle_id', flat=True))
    if not bundle_ids:
        return
    others = (BundleItem.objects.filter(bundle_id__in=bundle_ids)
              .exclude(item_id__in=basket_ids).values_list('item_id', flat=True))
    for iid in others:
        bump(iid, W_BUNDLE, 'bundle')


def _branch_stock(item_ids, branch_id):
    rows = (ItemStock.objects
            .filter(item_id__in=item_ids, branch_id=branch_id)
            .exclude(softech_store_code__in=EXCLUDED_STORE_CODES)
            .values('item_id').annotate(qty=Sum('quantity_on_hand')))
    return {r['item_id']: float(r['qty'] or 0) for r in rows}
