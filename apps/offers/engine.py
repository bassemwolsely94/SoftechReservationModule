"""
apps/offers/engine.py — DETERMINISTIC offer evaluation (Phase 3).

Given a basket + context, decide which offers apply and compute the exact EGP
discount, with full conflict resolution and per-offer reasons. Pure function:
NO side effects, NO SOFTECH writes, NO LLM (rules 2/7/10). The same inputs always
produce the same plan — that invariant is locked by test_offers_engine.

Output = a PROPOSED discount plan the cashier/UI shows and a later gated batch
executes through the established SOFTECH discount methodology (never from here).

Money math mirrors pos_orders.pricing: Decimal + ROUND_HALF_UP at 2 dp.
"""
from decimal import Decimal, ROUND_HALF_UP
from django.utils import timezone

Q2 = Decimal('0.01')


def _d(v):
    return v if isinstance(v, Decimal) else Decimal(str(v or 0))


def _r2(v):
    return _d(v).quantize(Q2, rounding=ROUND_HALF_UP)


class _Line:
    __slots__ = ('index', 'item', 'softech_id', 'qty', 'unit_price', 'gross', 'pos_discp')

    def __init__(self, index, item, softech_id, qty, unit_price):
        self.index = index
        self.item = item
        self.softech_id = softech_id
        self.qty = _d(qty)
        self.unit_price = _d(unit_price)
        self.gross = _r2(self.qty * self.unit_price)
        # The item card's authorized POS discount % (magnitude source in item_card mode).
        self.pos_discp = _d(getattr(item, 'pos_discp', 0)) if item is not None else Decimal('0')


def _normalize(basket):
    """basket = list of dicts {item(optional Item), softech_id, qty, unit_price}."""
    lines = []
    for i, raw in enumerate(basket):
        item = raw.get('item')
        lines.append(_Line(
            index=i,
            item=item,
            softech_id=raw.get('softech_id') or (item.softech_id if item else ''),
            qty=raw.get('qty', 0),
            unit_price=raw.get('unit_price', 0),
        ))
    return lines


# ── targeting ─────────────────────────────────────────────────────────────────
def _qualifies(offer, line, cache):
    from .targeting import item_matches_spec, classification_match
    item = line.item
    # manual exclusion wins over everything ("keep some, leave out some")
    if item is not None and cache['exclude_ids'] and item.id in cache['exclude_ids']:
        return False

    matched = False
    if offer.target_all:
        matched = True
    elif item is None:
        matched = False
    elif cache['item_ids'] and item.id in cache['item_ids']:
        matched = True
    elif cache['category_ids'] and item.category_id in cache['category_ids']:
        matched = True
    elif cache['tag_ids'] and item.id in cache['tagged_item_ids']:
        matched = True
    elif cache['classification_filters'] and classification_match(cache['classification_filters'], item):
        matched = True
    elif cache['spec'] and item_matches_spec(cache['spec'], item):
        matched = True

    if not matched:
        return False
    # stock gate (overridable): require branch stock unless require_stock is off
    if offer.require_stock and cache.get('stock_ids') is not None:
        if item is None or item.id not in cache['stock_ids']:
            return False
    return True


def item_matches_offer_targeting(offer, item, cache=None):
    """Public: does `item` fall within `offer`'s targeting? Reuses _qualifies."""
    cache = cache or _target_cache(offer)

    class _Stub:
        __slots__ = ('item',)
    s = _Stub()
    s.item = item
    return _qualifies(offer, s, cache)


def _target_cache(offer):
    item_ids = set(offer.items.values_list('id', flat=True))
    category_ids = set(offer.categories.values_list('id', flat=True))
    tag_ids = set(offer.tags.values_list('id', flat=True))
    tagged_item_ids = set()
    if tag_ids:
        from apps.catalog.models import Item
        tagged_item_ids = set(Item.objects.filter(tags__in=tag_ids).values_list('id', flat=True))
    return {
        'item_ids': item_ids,
        'category_ids': category_ids,
        'tag_ids': tag_ids,
        'tagged_item_ids': tagged_item_ids,
        'exclude_ids': set(offer.excluded_items.values_list('id', flat=True)),
        'classification_filters': offer.classification_filters or {},
        'spec': offer.target_spec or {},
        'stock_ids': None,   # injected per-eval when a branch + require_stock apply
    }


def _basket_stock_ids(item_ids, branch_id):
    """Subset of item_ids that have available stock at the branch (for the stock gate)."""
    if not item_ids:
        return set()
    from apps.catalog.models import ItemStock, EXCLUDED_STORE_CODES
    from django.db.models import Sum
    rows = (ItemStock.objects
            .filter(item_id__in=item_ids, branch_id=branch_id)
            .exclude(softech_store_code__in=EXCLUDED_STORE_CODES)
            .values('item_id').annotate(q=Sum('quantity_on_hand')).filter(q__gt=0))
    return {r['item_id'] for r in rows}


# ── eligibility (offer-level gates) ─────────────────────────────────────────────
def _eligible(offer, *, at, customer, branch_id, channel, basket_total, qlines):
    if offer.status != 'active':
        return False, 'ليس فعّالاً'
    if offer.starts_at and at < offer.starts_at:
        return False, 'لم يبدأ بعد'
    if offer.ends_at and at > offer.ends_at:
        return False, 'انتهى'
    if offer.segments:
        seg = getattr(customer, 'segment', '') if customer else ''
        if seg not in offer.segments:
            return False, 'شريحة العميل غير مؤهلة'
    if channel and offer.channels and channel not in offer.channels:
        return False, 'قناة البيع غير مؤهلة'
    if branch_id is not None:
        b_ids = set(offer.branches.values_list('id', flat=True))
        if b_ids and branch_id not in b_ids:
            return False, 'الفرع غير مؤهل'
    if offer.min_basket_amount and basket_total < _d(offer.min_basket_amount):
        return False, 'أقل من الحد الأدنى للسلة'
    if offer.min_qty:
        if sum((l.qty for l in qlines), Decimal('0')) < offer.min_qty:
            return False, 'أقل من الحد الأدنى للكمية المؤهلة'
    # usage limits (max_uses_total / per_customer) — only queries when a limit is set
    if offer.max_uses_total is not None or offer.max_uses_per_customer is not None:
        from .usage import offer_exhausted
        exhausted, scope = offer_exhausted(offer, customer)
        if exhausted:
            return False, ('استُنفد حد العرض' if scope == 'total' else 'استُنفد حد العرض لهذا العميل')
    return True, ''


# ── per-type discount → {line_index: Decimal} ───────────────────────────────────
def _compute(offer, qlines, lines=None):
    """
    Dispatch per offer type. `authorization_source` decides the MAGNITUDE:
      item_card → bounded by / sourced from each item's pos_discp (the owner model:
                  the item card IS the discount; a genuine 1+1 = an item posdiscp=100).
      offer     → the Offer's own value/get% (approval-gated upstream).
    """
    lines = lines if lines is not None else qlines
    item_card = getattr(offer, 'authorization_source', 'item_card') == 'item_card'

    if offer.offer_type == 'bxgy':
        if getattr(offer, 'bxgy_scope', 'group_cheapest') == 'same_item':
            per = _bxgy_same_item(offer, qlines, item_card)
        else:
            per = _bxgy_group_cheapest(offer, qlines, item_card)
        return per   # magnitude already chosen per unit; no extra cap

    if offer.offer_type == 'mix_match':
        return _mix_match(offer, qlines, item_card)   # magnitude chosen per unit
    if offer.offer_type == 'bundle':
        return _bundle(offer, lines)                  # fixed group price, self-capped

    if offer.offer_type == 'percent':
        per = _percent(offer, qlines)
    elif offer.offer_type == 'fixed':
        per = _fixed(offer, qlines)
    elif offer.offer_type == 'qty_tier':
        per = _qty_tier(offer, qlines)
    else:
        return {}

    # item_card authorization: no line may be discounted beyond its posdiscp.
    if item_card:
        per = _cap_to_posdiscp(per, qlines)
    return per


def _cap_to_posdiscp(per_line, qlines):
    """Cap each line's discount at line.gross × pos_discp / 100 (item-card ceiling)."""
    by_index = {l.index: l for l in qlines}
    capped = {}
    for idx, amt in per_line.items():
        line = by_index.get(idx)
        if line is None:
            capped[idx] = amt
            continue
        ceiling = _r2(line.gross * line.pos_discp / Decimal('100'))
        capped[idx] = min(amt, ceiling)
    return capped


def _percent(offer, qlines):
    pct = _d(offer.value)
    per = {l.index: _r2(l.gross * pct / Decimal('100')) for l in qlines}
    if offer.max_discount_amount:
        cap = _d(offer.max_discount_amount)
        total = sum(per.values(), Decimal('0'))
        if total > cap and total > 0:
            # scale proportionally to the cap, deterministically
            scaled = {}
            running = Decimal('0')
            items = list(per.items())
            for idx, amt in items[:-1]:
                s = _r2(amt * cap / total)
                scaled[idx] = s
                running += s
            scaled[items[-1][0]] = _r2(cap - running)   # last absorbs rounding
            per = scaled
    return per


def _fixed(offer, qlines):
    subtotal = sum((l.gross for l in qlines), Decimal('0'))
    if subtotal <= 0:
        return {}
    amount = min(_d(offer.value), subtotal)
    per, running = {}, Decimal('0')
    for l in qlines[:-1]:
        s = _r2(amount * l.gross / subtotal)
        per[l.index] = s
        running += s
    per[qlines[-1].index] = _r2(amount - running)   # last absorbs rounding
    return per


def _bxgy_same_item(offer, qlines, item_card):
    """Buy N of the SAME item, get some of that same item discounted (per line)."""
    group = (offer.buy_qty or 0) + (offer.get_qty or 0)
    if group <= 0 or offer.get_qty <= 0:
        return {}
    offer_pct = _d(offer.get_discount_percent)
    per = {}
    for l in qlines:
        groups = int(l.qty // group)
        if groups <= 0:
            continue
        free_units = groups * offer.get_qty
        pct = l.pos_discp if item_card else offer_pct   # magnitude source
        per[l.index] = _r2(Decimal(free_units) * l.unit_price * pct / Decimal('100'))
    return per


def _bxgy_group_cheapest(offer, qlines, item_card):
    """
    Cross-item BXGY: buy across the qualifying group, the LESSER-priced unit(s) are
    the promo units (the 1+1 / 1+½ mechanic). Each promo unit is discounted at its
    OWN item's pos_discp (item_card) or the offer's get% (offer mode). Per-line
    discounts sum the promo units that map back to each line.
    """
    B, G = (offer.buy_qty or 0), (offer.get_qty or 0)
    group = B + G
    if group <= 0 or G <= 0:
        return {}
    offer_pct = _d(offer.get_discount_percent)

    # expand qualifying lines into individual units (price, line index, posdiscp)
    units = []
    for l in qlines:
        n = int(l.qty)   # whole units; fractional qty not eligible for BXGY pairing
        for _ in range(n):
            units.append((l.unit_price, l.index, l.pos_discp))
    if len(units) < group:
        return {}

    # For every complete (B+G) group the customer buys, G units become promo units,
    # and they are the CHEAPEST ones (owner: "لازم يكون الصنف الأقل سعرًا"). Over the
    # whole eligible set that is the (n_groups × G) cheapest units overall — the
    # customer-favourable reading, consistent with D1.
    n_groups = len(units) // group
    promo_count = n_groups * G
    units.sort(key=lambda u: u[0])            # cheapest first
    per = {}
    for price, idx, pd in units[:promo_count]:
        pct = pd if item_card else offer_pct
        per[idx] = per.get(idx, Decimal('0')) + _r2(price * pct / Decimal('100'))
    return {k: _r2(v) for k, v in per.items()}


def _qty_tier(offer, qlines):
    tiers = sorted(((int(t['min_qty']), _d(t['percent'])) for t in (offer.qty_tiers or [])),
                   key=lambda t: t[0])
    if not tiers:
        return {}
    per = {}
    for l in qlines:
        pct = Decimal('0')
        for min_qty, tier_pct in tiers:
            if l.qty >= min_qty:
                pct = tier_pct
        if pct > 0:
            per[l.index] = _r2(l.gross * pct / Decimal('100'))
    return per


def _mix_match(offer, qlines, item_card):
    """Buy any N (min_qty) from the target group → the cheapest N (per complete set)
    are discounted at value% (offer) or their own posdiscp (item_card)."""
    N = int(offer.min_qty or 0)
    if N <= 0:
        return {}
    offer_pct = _d(offer.value)
    units = []
    for l in qlines:
        for _ in range(int(l.qty)):
            units.append((l.unit_price, l.index, l.pos_discp))
    if len(units) < N:
        return {}
    promo_count = (len(units) // N) * N
    units.sort(key=lambda u: u[0])
    per = {}
    for price, idx, pd in units[:promo_count]:
        pct = pd if item_card else offer_pct
        per[idx] = per.get(idx, Decimal('0')) + _r2(price * pct / Decimal('100'))
    return {k: _r2(v) for k, v in per.items()}


def _bundle(offer, lines):
    """The target `items` sold together for `bundle_price`: discount the members
    proportionally so their combined total hits the fixed bundle price."""
    price = offer.bundle_price
    if price is None:
        return {}
    member_ids = set(offer.items.values_list('id', flat=True))
    if not member_ids:
        return {}
    member_lines = {}
    for l in lines:
        if l.item is not None and l.item.id in member_ids and l.item.id not in member_lines:
            member_lines[l.item.id] = l
    if len(member_lines) < len(member_ids):
        return {}   # not all bundle members present
    mlines = list(member_lines.values())
    n_sets = min(int(l.qty) for l in mlines) or 1
    sum_unit = sum((l.unit_price for l in mlines), Decimal('0'))
    price = _d(price)
    if sum_unit <= price:
        return {}   # bundle not cheaper → nothing
    ratio = price / sum_unit
    per = {}
    for l in mlines:
        per[l.index] = _r2(Decimal(n_sets) * l.unit_price * (Decimal('1') - ratio))
    return per


def _compute_reward(offer, qlines, lines, item_card):
    """
    gift / spend_threshold: reward a gift item (buy buy_qty of target → get gift_item
    at get%). Returns (per_line, suggestions). If the gift isn't in the basket, a
    suggestion tells the POS to add it. spend_threshold's amount gate is enforced in
    _eligible (min_basket_amount); here buy_qty=0 means "just give the gift".
    """
    gid = offer.gift_item_id
    if not gid:
        # spend_threshold with no gift → treat as a percent reward on the target
        per = _percent(offer, qlines)
        return (_cap_to_posdiscp(per, qlines) if item_card else per), []

    B = int(offer.buy_qty or 0)
    qualifying_qty = sum(int(l.qty) for l in qlines if not (l.item and l.item.id == gid))
    if B and qualifying_qty < B:
        return {}, []
    G = int(offer.get_qty or 1)
    rewards = (qualifying_qty // B) * G if B else G
    if rewards <= 0:
        return {}, []

    gift_line = next((l for l in lines if l.item and l.item.id == gid), None)
    if gift_line is not None:
        pct = gift_line.pos_discp if item_card else _d(offer.get_discount_percent)
        units = min(int(gift_line.qty), rewards)
        per = {gift_line.index: _r2(Decimal(units) * gift_line.unit_price * pct / Decimal('100'))} if units else {}
        sug = []
        if rewards > units:
            sug.append(_gift_suggestion(offer, offer.gift_item, rewards - units, pct))
        return per, sug

    gi = offer.gift_item
    pct = _d(getattr(gi, 'pos_discp', 0)) if item_card else _d(offer.get_discount_percent)
    return {}, [_gift_suggestion(offer, gi, rewards, pct)]


def _gift_suggestion(offer, gift_item, qty, pct):
    return {
        'offer_id': offer.id, 'name': offer.name_ar or offer.name,
        'item_id': getattr(gift_item, 'id', None),
        'softech_id': getattr(gift_item, 'softech_id', ''),
        'item_name': getattr(gift_item, 'name', ''),
        'qty': qty, 'cust_discp': float(pct),
        'unit_price': float(getattr(gift_item, 'pack_price', 0) or 0),
    }


# ── main ────────────────────────────────────────────────────────────────────────
def _pct(v):
    v = _d(v)
    return int(v) if v == v.to_integral_value() else v


def _completion(offer, qlines, lines, basket_total):
    """READ-ONLY 'this can be completed with another' hint: how to turn a NEAR-MISS offer into an
    applied one (add N more qualifying units, complete a bundle, or spend a bit more). No discount is
    applied — purely informational for the cashier. Returns a dict or None. Only called for offers
    that qualify by targeting but miss a QTY/AMOUNT threshold (never for wrong channel/segment/time)."""
    t = offer.offer_type
    q = int(sum((l.qty for l in qlines), Decimal('0')))

    def out(msg, need=None):
        return {'offer_id': offer.id, 'name': offer.name_ar or offer.name,
                'offer_type': t, 'need': need, 'message': msg}

    if t == 'bxgy':
        group = (offer.buy_qty or 0) + (offer.get_qty or 0)   # a full BXGY group needs buy+get units
        if group > 0 and 0 < q < group:
            return out(f'أضِف {group - q} من أصناف العرض للحصول على {offer.get_qty} '
                       f'بخصم {_pct(offer.get_discount_percent)}%', group - q)
    if t == 'qty_tier':
        for m, pct in sorted((int(x.get('min_qty', 0)), x.get('percent', 0)) for x in (offer.qty_tiers or [])):
            if m > 0 and q < m:
                return out(f'أضِف {m - q} لتصل إلى شريحة خصم {_pct(pct)}%', m - q)
    if t == 'mix_match' and offer.min_qty and q < offer.min_qty:
        return out(f'اختر {offer.min_qty - q} صنفاً إضافياً من المجموعة لخصم {_pct(offer.value)}%',
                   offer.min_qty - q)
    if t == 'gift' and offer.buy_qty and q < offer.buy_qty:
        g = offer.gift_item.name if offer.gift_item_id else 'هدية'
        return out(f'أضِف {offer.buy_qty - q} للحصول على هدية: {g}', offer.buy_qty - q)
    if t == 'spend_threshold' and offer.min_basket_amount:
        gap = _d(offer.min_basket_amount) - basket_total
        if gap > 0:
            g = f' والحصول على {offer.gift_item.name}' if offer.gift_item_id else ''
            return out(f'أنفِق {_r2(gap)} ج إضافية{g}')
    if t == 'bundle':
        members = list(offer.items.all())
        if members:
            present = {l.item.id for l in lines if l.item is not None}
            missing = [m for m in members if m.id not in present]
            if missing and len(missing) <= 3:
                return out(f'أضِف: {"، ".join(m.name for m in missing)} '
                           f'لإكمال الباقة بسعر {offer.bundle_price} ج')
    # generic min-qty gate (percent / fixed offers that need a minimum qualifying qty)
    if offer.min_qty and q < offer.min_qty:
        return out(f'أضِف {offer.min_qty - q} للوصول للحد الأدنى وتفعيل العرض', offer.min_qty - q)
    return None


# threshold rejections that a cashier CAN fix by adding to the basket (→ a completion hint)
_COMPLETABLE_REJECTS = ('أقل من الحد الأدنى للسلة', 'أقل من الحد الأدنى للكمية المؤهلة')


def evaluate_offers(basket, *, customer=None, branch_id=None, channel=None, at=None,
                    offers=None, margin_cfg=None):
    """Return the deterministic discount plan for a basket."""
    at = at or timezone.now()
    lines = _normalize(basket)
    basket_total = sum((l.gross for l in lines), Decimal('0'))

    if offers is None:
        from .models import Offer
        offers = list(Offer.objects.filter(status='active')
                      .prefetch_related('items', 'categories', 'tags', 'branches', 'excluded_items'))

    # Branch stock for the basket items — computed ONCE, used by the (overridable)
    # stock gate of any offer that requires it.
    stock_ids = None
    if branch_id is not None and any(getattr(o, 'require_stock', False) for o in offers):
        stock_ids = _basket_stock_ids([l.item.id for l in lines if l.item is not None], branch_id)

    candidates, rejected, suggestions, completions = [], [], [], []
    for offer in offers:
        cache = _target_cache(offer)
        cache['stock_ids'] = stock_ids
        qlines = [l for l in lines if _qualifies(offer, l, cache)]
        if not qlines:
            rejected.append(_reject(offer, 'لا أصناف مؤهلة'))
            continue
        ok, why = _eligible(offer, at=at, customer=customer, branch_id=branch_id,
                            channel=channel, basket_total=basket_total, qlines=qlines)
        if not ok:
            rejected.append(_reject(offer, why))
            # a threshold miss (qty / basket amount) is completable — tell the cashier how
            if why in _COMPLETABLE_REJECTS:
                c = _completion(offer, qlines, lines, basket_total)
                if c:
                    completions.append(c)
            continue

        item_card = getattr(offer, 'authorization_source', 'item_card') == 'item_card'
        sug = []
        if offer.offer_type in ('gift', 'spend_threshold'):
            per_line, sug = _compute_reward(offer, qlines, lines, item_card)
        else:
            per_line = _compute(offer, qlines, lines)
        discount = sum(per_line.values(), Decimal('0'))
        if discount <= 0 and not sug:
            rejected.append(_reject(offer, 'خصم صفري'))
            # eligible but the reward threshold isn't reached yet → "add N more" hint
            c = _completion(offer, qlines, lines, basket_total)
            if c:
                completions.append(c)
            continue
        suggestions.extend(sug)
        if discount > 0:
            candidates.append({'offer': offer, 'per_line': per_line, 'discount': discount})

    chosen, conflict_rejected = _resolve_conflicts(candidates)
    rejected.extend(conflict_rejected)

    # combine chosen offers per line, then cap each line at its gross
    gross_by_index = {l.index: l.gross for l in lines}
    combined = {}
    for c in chosen:
        for idx, amt in c['per_line'].items():
            combined[idx] = combined.get(idx, Decimal('0')) + amt
    for idx in list(combined):
        combined[idx] = min(combined[idx], gross_by_index.get(idx, Decimal('0')))

    total_discount = _r2(sum(combined.values(), Decimal('0')))

    margin = _margin_analysis(lines, combined, margin_cfg)
    # offer-mode magnitude (value not from the item card) always needs sign-off.
    offer_mode = any(getattr(c['offer'], 'authorization_source', 'item_card') == 'offer'
                     for c in chosen)
    # A margin breach forces approval EXCEPT when every applied offer is item_card:
    # the item card's posdiscp already authorized that depth (a genuine 1+1 = free),
    # so it is pre-authorized and needs no extra margin sign-off (owner model).
    all_item_card = bool(chosen) and all(
        getattr(c['offer'], 'authorization_source', 'item_card') == 'item_card' for c in chosen)
    margin_forces_approval = margin['breached'] and not all_item_card
    requires_approval = (any(c['offer'].requires_approval for c in chosen)
                         or offer_mode or margin_forces_approval)

    return {
        'basket_total': _r2(basket_total),
        'total_discount': total_discount,
        'net_total': _r2(basket_total - total_discount),
        'applied': [_applied(c, lines) for c in chosen],
        'rejected': rejected,
        'requires_approval': requires_approval,
        'margin': margin,
        'suggestions': suggestions,   # gift lines to ADD (not in basket) — POS offers them
        'completions': completions,   # near-miss offers + how to complete them (read-only hints)
    }


def _margin_analysis(lines, combined, margin_cfg):
    """
    Post-discount margin per discounted line. margin% = (net − cogs) / net × 100.
    A line whose margin drops below the floor flags the plan for approval. Cost
    comes from Item.cost_price; lines with no resolved item are skipped (unknown).
    Cost-bearing fields are masked for unauthorized roles at the view layer.
    """
    if margin_cfg is not None:
        floor = _d(getattr(margin_cfg, 'min_margin_percent', 0))
        enforce = bool(getattr(margin_cfg, 'enforce', True))
    else:
        floor, enforce = Decimal('0'), False

    by_index = {l.index: l for l in lines}
    detail, breached = [], False
    for idx, disc in combined.items():
        line = by_index.get(idx)
        if line is None or line.item is None:
            continue
        cogs = _r2(_d(getattr(line.item, 'cost_price', 0)) * line.qty)
        net = _r2(line.gross - disc)
        if net <= 0:
            margin_pct = Decimal('-100.00')
        else:
            margin_pct = _r2((net - cogs) / net * Decimal('100'))
        line_breached = enforce and margin_pct < floor
        breached = breached or line_breached
        detail.append({
            'index': idx, 'cogs': cogs, 'net': net,
            'margin_pct': margin_pct, 'breached': line_breached,
        })

    return {
        'floor': _r2(floor),
        'enforce': enforce,
        'breached': breached,
        'lines': detail,
    }


def _resolve_conflicts(candidates):
    """
    Best-customer-saving between (a) all stackable offers combined and (b) the
    single best non-stackable offer. On a tie, prefer the stackable set. A
    non-stackable offer cannot be combined with anything else.
    """
    if not candidates:
        return [], []
    stackable = [c for c in candidates if c['offer'].stackable]
    nonstack = [c for c in candidates if not c['offer'].stackable]
    stack_total = sum((c['discount'] for c in stackable), Decimal('0'))

    best_nonstack = None
    if nonstack:
        best_nonstack = max(nonstack, key=lambda c: (c['offer'].priority, c['discount'], -c['offer'].id))

    if best_nonstack and best_nonstack['discount'] > stack_total:
        chosen = [best_nonstack]
        rej = [_reject(c['offer'], 'استُبعد لصالح عرض أوفر') for c in candidates if c is not best_nonstack]
    else:
        chosen = stackable
        rej = [_reject(c['offer'], 'عرض حصري — استُبعد لصالح عروض قابلة للدمج أوفر') for c in nonstack]
    return chosen, rej


def _applied(c, lines):
    o = c['offer']
    return {
        'offer_id': o.id, 'name': o.name_ar or o.name, 'offer_type': o.offer_type,
        'authorization_source': getattr(o, 'authorization_source', 'item_card'),
        'discount': _r2(c['discount']),
        'stackable': o.stackable, 'priority': o.priority,
        'requires_approval': o.requires_approval or getattr(o, 'authorization_source', '') == 'offer',
        'lines': [{'index': idx, 'discount': _r2(amt)} for idx, amt in sorted(c['per_line'].items())],
        'reason': 'applied',
    }


def _reject(offer, reason):
    return {'offer_id': offer.id, 'name': offer.name_ar or offer.name,
            'offer_type': offer.offer_type, 'reason': reason}
