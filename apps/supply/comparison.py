"""
apps/supply/comparison.py — cross-supplier price comparison of the daily «الوارد» lists.

Owner decisions (2026-10-07, memory supplier_price_comparison):
  • Sources compared HEAD-TO-HEAD: distributors (SOFTECH supplier class 60) and manufacturers
    (70). Medicine warehouses (50 / 20) are a SEPARATE tier (own column). Virtual / contract /
    general (80), clearing (40), services (96) and misc (10) are never a price to beat —
    except a supplier that actually SENDS a «وارد» list is always a source (AKHNATON is
    filed under 10).
  • An offer stays valid OFFER_DAYS (14) days; the latest list from a supplier wins.
  • Recommend another supplier when it is more than BETTER_PCT (1 %) cheaper, or — within
    that 1 % — when it gives a bonus.
  • Fair across public-price changes: every cost is compared as a DISCOUNT % off the public
    price in force for that offer / purchase (PurchaseLine.public_price is stamped per line),
    applied to the item's CURRENT public price. A purchase made at another public price is
    marked «سعر قديم».

How an offer's cost is estimated (deterministic, per pack, at the current public price P) —
from OUR SAVED PURCHASE HISTORY ONLY (owner 2026-10-08). A «وارد» list tells us THAT a
supplier sells the item (remembered — see offer_history) and its bonus; its written prices /
discounts are not used:
  1. this supplier's LAST real purchase discount for this item (12 months)       «history»
  2. else the same company's other branch / account for this item                «group_history»
     («المصرية» شريف / زيتون / الحرية; أخناتون 124 / 3031 / 3030)
  3. else this supplier's median discount on the same manufacturer's items         «producer»
  then the list's bonus «buy N get M» → cost × N / (N + M).

Read-only: proposes, never orders / writes SOFTECH.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

OFFER_DAYS = 14
HISTORY_DAYS = 365
BETTER_PCT = 1.0
EXCLUDED_CLASSES = {'80', '40', '96', '10'}
WAREHOUSE_CLASSES = {'50', '20'}
TIERS = {'60': 'distributor', '70': 'manufacturer'}
# How firm an offer's cost figure is (lower = firmer) — a tie-break inside the 1 % band.
BASIS_RANK = {'history': 1, 'group_history': 2, 'producer': 3}
# Accounts of ONE company share their history: «المصرية» = EGY DRUG شريف / زيتون / الحرية
# (owner 2026-10-07); أخناتون sends lists as 124 «اخناتون ايفا» but we buy under 3031
# (أدوية) / 3030 (اكسسوار) — 124 has no purchases (owner 2026-10-08).
SUPPLIER_GROUPS = [{'786', '4327', '519'}, {'124', '3031', '3030'}]
TIER_LABELS = {'distributor': 'موزع', 'manufacturer': 'شركة منتجة', 'other': 'مورد', 'warehouse': 'مخزن'}
TIER_ORDER = {'distributor': 0, 'manufacturer': 1, 'other': 2, 'warehouse': 3}
SIGNAL_LABELS = {'last_qty': 'آخر كمية', 'limited': 'كمية محدودة', 'back_in_stock': 'رجع بعد غياب',
                 'scarce_variant': 'التركيز قليل', 'hot': '🔥', 'flag': '🚩', 'quota': 'كوتة',
                 'half_quota': 'نصف كوتة'}


def _f(v):
    return float(v) if v is not None else None


def _round(v, n=2):
    return None if v is None else round(float(v), n)


def _tier(classif: str, is_source: bool):
    """distributor / manufacturer / warehouse / other — or None (never a price to beat)."""
    c = (classif or '').strip()
    if c in WAREHOUSE_CLASSES:
        return 'warehouse'
    if c in TIERS:
        return TIERS[c]
    if is_source:
        return 'other'                  # sends lists, filed under another SOFTECH class
    return None if c in EXCLUDED_CLASSES or c else 'other'


def _profiles(codes) -> dict:
    """{supplier_code: {'name', 'classif'}} from the procurement supplier profiles."""
    from apps.procurement.models import SupplierProfile
    codes = {str(c) for c in codes if c}
    return {p['supplier_code']: {'name': p['supplier_name'], 'classif': p['classif_code'] or ''}
            for p in SupplierProfile.objects.filter(supplier_code__in=codes)
            .values('supplier_code', 'supplier_name', 'classif_code')}


# ── 1. Offers: the latest line per (item, supplier) in the window ─────────────────────

def _supplier_key(batch) -> tuple:
    """(key, softech code, display name) of a list's supplier."""
    v = batch.supplier if batch.supplier_id else None
    code = ((v.softech_personcode if v else '') or '').strip()
    name = (v.name if v else '') or batch.supplier_name or '—'
    return (code or f'name:{name}'), code, name


def latest_offers(*, days=OFFER_DAYS, item_ids=None, now=None) -> dict:
    """{(item_id, supplier_key): AvailabilityLine} — each supplier's latest offer per item."""
    from django.utils import timezone
    from .models import AvailabilityLine
    since = (now or timezone.now()) - timedelta(days=days)
    qs = (AvailabilityLine.objects.filter(batch__created_at__gte=since, item__isnull=False)
          .select_related('batch', 'batch__supplier', 'item').order_by('batch__created_at', 'id'))
    if item_ids is not None:
        qs = qs.filter(item_id__in=list(item_ids))
    out = {}
    for ln in qs:
        out[(ln.item_id, _supplier_key(ln.batch)[0])] = ln          # later overwrites earlier
    return out


# ── 2. The supplier network of an item ────────────────────────────────────────────────

def _line_discount(pl):
    """A purchase line's real discount off ITS public price, after the free units."""
    public = _f(pl['public_price']) or 0
    units = (_f(pl['net_qty']) or 0) + (_f(pl['bonus_qty']) or 0)
    if public <= 0 or units <= 0:
        return None, None
    cost = ((_f(pl['net_value']) or 0) + (_f(pl['vat_value']) or 0)) / units
    return 1 - cost / public, cost


def purchase_history(item_codes, *, days=HISTORY_DAYS, today=None) -> dict:
    """{(item_code, supplier_code): {'last': {...}, 'best': {...}, 'qty', 'n'}} — real buys
    in the last `days` (returns excluded), each with its discount off the public price then."""
    from django.utils import timezone
    from apps.procurement.models import PurchaseLine
    since = (today or timezone.localdate()) - timedelta(days=days)
    out: dict = {}
    for pl in (PurchaseLine.objects.filter(item_code__in=list(item_codes), doc_date__gte=since,
                                           is_return=False, net_qty__gt=0, public_price__gt=0)
               .order_by('doc_date', 'id')
               .values('item_code', 'supplier_code', 'doc_date', 'net_qty', 'bonus_qty', 'net_value',
                       'vat_value', 'public_price', 'unit_price')):
        d, cost = _line_discount(pl)
        if d is None:
            continue
        rec = {'date': pl['doc_date'].isoformat(), 'discount_pct': round(d * 100, 2),
               'unit_cost': round(cost, 2), 'public_price': _f(pl['public_price']),
               'qty': _f(pl['net_qty']), 'bonus_qty': _f(pl['bonus_qty']) or 0}
        h = out.setdefault((pl['item_code'], pl['supplier_code']), {'qty': 0.0, 'n': 0})
        h['last'] = rec
        if 'best' not in h or rec['discount_pct'] > h['best']['discount_pct']:
            h['best'] = rec
        h['qty'] += rec['qty']
        h['n'] += 1
    return out


def offer_history(item_ids) -> dict:
    """{item_id: [{supplier, code, name, last_offered, times, confirmed}]} — every supplier that
    ever offered the item in a «وارد» list (all time). This is what a list is remembered for:
    THAT the supplier sells the item (owner 2026-10-08) — not its written prices."""
    from django.db.models import Count, Max, Q
    from .models import AvailabilityLine
    out = defaultdict(list)
    for r in (AvailabilityLine.objects.filter(item_id__in=list(item_ids))
              .values('item_id', 'batch__supplier__softech_personcode', 'batch__supplier__name', 'batch__supplier_name')
              .annotate(last=Max('batch__created_at'), times=Count('batch', distinct=True),
                        confirmed=Count('id', filter=Q(is_confirmed=True)))):
        code = (r['batch__supplier__softech_personcode'] or '').strip()
        name = r['batch__supplier__name'] or r['batch__supplier_name'] or '—'
        out[r['item_id']].append({'supplier': code or f'name:{name}', 'code': code, 'name': name,
                                  'last_offered': r['last'].isoformat() if r['last'] else None,
                                  'times': r['times'], 'confirmed': r['confirmed'] > 0})
    for v in out.values():
        v.sort(key=lambda x: x['last_offered'] or '', reverse=True)
    return out


def supplier_network(item_ids, *, history=None, sources=()) -> dict:
    """{item_id: {'main', 'carriers', 'offered_by', 'bought'}} — who SOFTECH lists as the main
    supplier, who carries the item (itemssuppliers mirror), which suppliers offered it in their
    «وارد» lists (remembered), and who we really bought from in the last 12 months (cost after bonus, as a discount off the public price then). Virtual / contract
    / clearing suppliers are left out (never a price to beat)."""
    from apps.catalog.models import Item, ItemSupplierLink
    items = {i.id: i for i in Item.objects.filter(pk__in=list(item_ids))
             .only('id', 'softech_id', 'pack_price', 'supplier_code')}
    sids = {i.softech_id: iid for iid, i in items.items() if i.softech_id}
    links = defaultdict(list)
    for l in ItemSupplierLink.objects.filter(item_code__in=list(sids)).values('item_code', 'supp_code', 'is_main'):
        links[sids[l['item_code']]].append(l)
    history = history if history is not None else purchase_history(sids)
    codes = {l['supp_code'] for ls in links.values() for l in ls} | {s for (_i, s) in history} | \
            {i.supplier_code for i in items.values() if i.supplier_code}
    prof = _profiles(codes)
    sources = set(sources)
    offered = offer_history(items)

    def sup(code):
        p = prof.get(code, {})
        return {'code': code, 'name': p.get('name') or code,
                'tier': _tier(p.get('classif', ''), code in sources)}

    out = {}
    for iid, it in items.items():
        price = _f(it.pack_price) or 0
        main = next((l['supp_code'] for l in links.get(iid, []) if l['is_main']), None) \
            or (it.supplier_code or '').strip() or None
        carriers = [sup(l['supp_code']) for l in links.get(iid, [])]
        bought = []
        for (code_i, scode), h in history.items():
            if code_i != it.softech_id:
                continue
            s = sup(scode)
            if s['tier'] is None:
                continue
            last = h['last']
            bought.append({**s, 'last': last, 'best': h['best'], 'qty_12m': round(h['qty'], 2), 'buys': h['n'],
                           'old_price': bool(price and abs(last['public_price'] - price) > 0.005),
                           'cost_now': round(price * (1 - last['discount_pct'] / 100), 2) if price else None})
        bought.sort(key=lambda b: b['last']['date'], reverse=True)
        out[iid] = {'main': sup(main) if main else None,
                    'carriers': [c for c in carriers if c['tier'] is not None],
                    'offered_by': offered.get(iid, []),
                    'bought': bought}
    return out


# ── 3. Offer cost, normalized to the current public price ────────────────────────────

def estimate_offer(ln, public_price, *, history=None) -> dict:
    """Cost of one offer per pack at the CURRENT public price: the discount from our purchase
    history (`history` = (discount %, basis) or None), then the list's bonus. The list's own
    written price / discount is NOT used (owner 2026-10-08)."""
    P = float(public_price or 0)
    out = {'basis': None, 'unit_cost': None, 'effective_cost': None, 'discount_pct': None}
    if P <= 0 or history is None:
        return out
    disc, basis = history
    base = P * (1 - disc / 100)
    buy = _f(ln.bonus_buy) or 0
    free = _f(ln.foc_qty) or 0
    eff = base * buy / (buy + free) if buy > 0 and free > 0 else base
    out.update(basis=basis, unit_cost=round(base, 2), effective_cost=round(eff, 2),
               discount_pct=round((1 - eff / P) * 100, 2))
    return out


def _bonus_text(ln) -> str:
    tiers = ln.bonus_tiers or ([[float(ln.bonus_buy), float(ln.foc_qty)]] if ln.bonus_buy and ln.foc_qty else [])
    fmt = lambda v: str(int(v)) if float(v) == int(float(v)) else str(v)
    if tiers:
        return ' · '.join(f'{fmt(b)}+{fmt(f)}' for b, f in tiers)
    return f'+{fmt(ln.foc_qty)}' if ln.foc_qty else ''


def _group_of(code):
    return next((g for g in SUPPLIER_GROUPS if code in g), {code})


def producer_discounts(supplier_codes, producers, *, days=HISTORY_DAYS, today=None) -> dict:
    """{(supplier_code, producer_name): median discount %} over the last `days` — what a
    supplier usually gives on a manufacturer's products (a fallback when it never sold us
    this exact item)."""
    from statistics import median
    from django.utils import timezone
    from apps.procurement.models import PurchaseLine
    producers = {p for p in producers if p}
    if not producers or not supplier_codes:
        return {}
    since = (today or timezone.localdate()) - timedelta(days=days)
    acc = defaultdict(list)
    for pl in (PurchaseLine.objects.filter(supplier_code__in=list(supplier_codes), doc_date__gte=since,
                                           is_return=False, net_qty__gt=0, public_price__gt=0,
                                           item__producer_name__in=list(producers))
               .values('supplier_code', 'item__producer_name', 'net_qty', 'bonus_qty', 'net_value',
                       'vat_value', 'public_price')):
        d, _c = _line_discount(pl)
        if d is not None and -0.5 < d < 0.9:
            acc[(pl['supplier_code'], pl['item__producer_name'])].append(d * 100)
    return {k: round(median(v), 2) for k, v in acc.items() if len(v) >= 3}


# ── 4. The board ─────────────────────────────────────────────────────────────────────

def _demand(item_ids) -> dict:
    """{item_id: {...}} company-level need, stock, in-transit, internal cover, sales rate —
    the SAME numbers the supplier-list review uses (engine/demand + internal cover)."""
    from apps.purchasing.models import ItemDemandMetrics
    from .engine.demand import net_demand_many
    from .position import latest_demand_run
    nd = net_demand_many(item_ids) if item_ids else {}
    over, rate = defaultdict(float), defaultdict(float)
    run = latest_demand_run()
    if run is not None:
        for m in ItemDemandMetrics.objects.filter(run=run, item_id__in=list(item_ids)).values('item_id', 'gap', 'monthly_avg'):
            g = float(m['gap'] or 0)
            if g < 0:
                over[m['item_id']] += -g
            rate[m['item_id']] += float(m['monthly_avg'] or 0)
    out = {}
    for iid in item_ids:
        n = nd.get(iid) or {}
        required = float(n.get('required') or 0)
        internal = min(required, over[iid])
        out[iid] = {'required': round(required, 2), 'internal_cover': round(internal, 2),
                    'residual': round(max(0.0, required - internal), 2),
                    'stock': round(float(n.get('current_stock') or 0), 2),
                    'in_transit': round(float(n.get('confirmed_incoming') or 0), 2),
                    'monthly_rate': round(rate[iid], 2), 'has_run': bool(n.get('has_run'))}
    return out


def build_board(*, days=OFFER_DAYS, item_ids=None, now=None) -> dict:
    """One row per offered item, one cell per supplier (warehouses in their own column), the
    estimated cost at today's public price, the need, and a buy-from recommendation."""
    from django.utils import timezone
    from .availability import whole_units
    now = now or timezone.now()
    offers = latest_offers(days=days, item_ids=item_ids, now=now)
    iids = sorted({i for (i, _k) in offers})
    by_item = defaultdict(list)
    sup_meta = {}
    for (iid, key), ln in offers.items():
        k, code, name = _supplier_key(ln.batch)
        by_item[iid].append((key, ln))
        sup_meta.setdefault(key, {'key': key, 'code': code, 'name': name})
    sources = {m['code'] for m in sup_meta.values() if m['code']}
    prof = _profiles(sources)
    for m in sup_meta.values():
        p = prof.get(m['code'], {})
        m['name'] = p.get('name') or m['name']
        m['tier'] = _tier(p.get('classif', ''), True)
        m['tier_label'] = TIER_LABELS[m['tier']]
        m['items'] = 0

    from apps.catalog.models import Item
    items = {i.id: i for i in Item.objects.filter(pk__in=iids)
             .only('id', 'softech_id', 'name', 'pack_price', 'supplier_code', 'producer_name')}
    hist = purchase_history({i.softech_id for i in items.values() if i.softech_id})
    group_codes = set().union(*(_group_of(c) for c in sources)) if sources else set()
    prod = producer_discounts(group_codes, {i.producer_name for i in items.values()})
    network = supplier_network(iids, history=hist, sources=sources)
    demand = _demand(iids)

    rows, summary = [], defaultdict(int)
    for iid in iids:
        it = items[iid]
        P = _f(it.pack_price) or 0
        net = network.get(iid) or {}
        main_code = (net.get('main') or {}).get('code')
        cells = []
        for key, ln in by_item[iid]:
            meta = sup_meta[key]
            meta['items'] += 1
            ref, last = _history_ref(meta['code'], it, hist, prod)
            est = estimate_offer(ln, P, history=ref)
            cells.append({
                'supplier': key, 'supplier_name': meta['name'], 'tier': meta['tier'],
                'line_id': ln.id, 'batch_id': ln.batch_id,
                'offered_at': ln.batch.created_at.isoformat(), 'confirmed': ln.is_confirmed,
                'raw_text': ln.raw_text, 'quota': _f(ln.quota), 'supplier_qty': _f(ln.supplier_qty),
                'bonus': _bonus_text(ln), 'has_bonus': bool(ln.foc_qty), 'promo': ln.promo,
                'expiry': ln.expiry,
                'signals': [SIGNAL_LABELS.get(s, s) for s in (ln.signals or [])],
                'is_main': bool(main_code and meta['code'] == main_code),
                'last_buy': ({**last, 'old_price': bool(P and abs(last['public_price'] - P) > 0.005)}
                             if last else None),
                **est,
            })
        rows.append(_decide(it, P, cells, net, demand.get(iid) or {}, whole_units))
        summary[rows[-1]['state']] += 1

    rows.sort(key=lambda r: ({'buy': 0, 'compare': 1, 'not_needed': 2}[r['state']], -(r['need'] or 0), r['item_name']))
    suppliers = sorted(sup_meta.values(), key=lambda m: (TIER_ORDER[m['tier']], -m['items'], m['name']))
    return {'days': days, 'better_pct': BETTER_PCT, 'generated_at': now.isoformat(),
            'suppliers': [s for s in suppliers if s['tier'] != 'warehouse'],
            'warehouses': [s for s in suppliers if s['tier'] == 'warehouse'],
            'rows': rows, 'summary': {'items': len(rows), **dict(summary)}}


def _history_ref(code, it, hist, prod):
    """((discount %, basis), last purchase) from OUR purchase history: this supplier's last
    buy of the item, else the same company's other account, else its median discount on the
    same manufacturer. (None, None) when we never bought from that company."""
    if not code:
        return None, None
    own = hist.get((it.softech_id, code))
    if own:
        return (own['last']['discount_pct'], 'history'), {**own['last'], 'supplier_code': code}
    sisters = [{**hist[(it.softech_id, c)]['last'], 'supplier_code': c} for c in _group_of(code) - {code}
               if (it.softech_id, c) in hist]
    if sisters:
        last = max(sisters, key=lambda r: r['date'])
        return (last['discount_pct'], 'group_history'), last
    for c in sorted(_group_of(code), key=lambda c: c != code):
        if (c, it.producer_name) in prod:
            return (prod[(c, it.producer_name)], 'producer'), None
    return None, None


def _decide(it, P, cells, net, dem, whole_units) -> dict:
    """Rank the head-to-head offers, give each a verdict, allocate the need (quota-aware)."""
    hh = [c for c in cells if c['tier'] != 'warehouse']
    wh = [c for c in cells if c['tier'] == 'warehouse']
    known = [c for c in hh if c['effective_cost'] is not None]
    chosen = None
    if known:
        best_cost = min(c['effective_cost'] for c in known)
        bucket = [c for c in known if c['effective_cost'] <= best_cost * (1 + BETTER_PCT / 100)]
        # within 1 %: a bonus wins, then the firmer figure (the offer's own price / this
        # item's real last price before a branch's or a manufacturer-median estimate), then
        # SOFTECH's main supplier, then the cheaper, then the latest list
        chosen = sorted(bucket, key=lambda c: (not c['has_bonus'], BASIS_RANK.get((c['basis'] or '').split('+')[0], 9),
                                               not c['is_main'], c['effective_cost'], -c['line_id']))[0]
    elif hh:
        # nothing can be costed (names only, no purchase history): bonus, then main supplier
        chosen = sorted(hh, key=lambda c: (not c['has_bonus'], not c['is_main'], -c['line_id']))[0]
    for c in cells:
        if c is chosen:
            c['verdict'] = 'best'
        elif c['effective_cost'] is None:
            c['verdict'] = 'no_price'
        elif chosen is not None and chosen['effective_cost'] is not None:
            gap = (c['effective_cost'] / chosen['effective_cost'] - 1) * 100
            c['gap_pct'] = round(gap, 2)
            if c['tier'] == 'warehouse':
                c['verdict'] = 'cheaper' if gap < -BETTER_PCT else 'pricier' if gap > BETTER_PCT else 'similar'
            else:
                c['verdict'] = 'pricier' if gap > BETTER_PCT else ('other_bonus' if chosen['has_bonus']
                                                                  and not c['has_bonus'] else 'similar')
        else:
            c['verdict'] = 'no_compare'

    need = whole_units(dem.get('residual') or 0)
    # quota-aware split: the winner first, then the next cheapest head-to-head offers
    order = ([chosen] if chosen else []) + sorted([c for c in known if c is not chosen],
                                                  key=lambda c: c['effective_cost'])
    order += [c for c in hh if c not in order]
    left, alloc = need, []
    for c in order:
        if left <= 0:
            break
        caps = [v for v in (c['quota'], c['supplier_qty']) if v]
        q = min([left] + caps)
        if q > 0:
            alloc.append({'supplier': c['supplier'], 'supplier_name': c['supplier_name'], 'qty': q,
                          'effective_cost': c['effective_cost']})
            left -= q
    cheaper_wh = sorted([c for c in wh if c.get('verdict') == 'cheaper'], key=lambda c: c['effective_cost'])
    best_wh = min((c for c in wh if c['effective_cost'] is not None), key=lambda c: c['effective_cost'], default=None)
    state = ('not_needed' if need <= 0 else 'buy' if chosen is not None and chosen['effective_cost'] is not None
             else 'compare')
    flags = []
    if cheaper_wh:
        flags.append('warehouse_cheaper')
    if need > 0 and left > 0 and alloc:
        flags.append('quota_short')
    bought = net.get('bought') or []
    offered = {c['supplier'] for c in cells}
    elsewhere = max((b for b in bought if b['code'] not in offered and b['tier'] != 'warehouse'),
                    key=lambda b: b['last']['discount_pct'], default=None)
    return {
        'item_id': it.id, 'item_code': it.softech_id, 'item_name': it.name, 'public_price': P,
        'need': need, 'required': dem.get('required'), 'internal_cover': dem.get('internal_cover'),
        'stock': dem.get('stock'), 'in_transit': dem.get('in_transit'),
        'monthly_rate': dem.get('monthly_rate'), 'has_run': dem.get('has_run'),
        'state': state, 'flags': flags, 'cells': cells,
        'best': ({k: chosen[k] for k in ('supplier', 'supplier_name', 'effective_cost', 'discount_pct', 'basis')}
                 if chosen else None),
        'allocation': alloc, 'uncovered': max(0, left) if need > 0 else 0,
        'best_warehouse': ({k: best_wh[k] for k in ('supplier', 'supplier_name', 'effective_cost', 'discount_pct')}
                           if best_wh else None),
        'main_supplier': net.get('main'),
        'bought_elsewhere': ({'code': elsewhere['code'], 'name': elsewhere['name'],
                              'discount_pct': elsewhere['last']['discount_pct'], 'date': elsewhere['last']['date']}
                             if elsewhere else None),
        'network': {'carriers': len(net.get('carriers') or []), 'bought': bought[:8],
                    'offered_by': net.get('offered_by') or []},
    }


# ── 5. Excel ──────────────────────────────────────────────────────────────────────────

VERDICT_LABELS = {'best': '✔ الأفضل', 'pricier': 'أغلى', 'similar': 'مماثل', 'other_bonus': 'الآخر ببونص',
                  'no_price': 'بدون سعر', 'no_compare': '—', 'cheaper': 'أرخص'}
BASIS_LABELS = {'history': 'آخر شراء', 'group_history': 'آخر شراء من حساب آخر لنفس الشركة',
                'producer': 'متوسط خصم المورد لنفس الشركة المنتجة'}
STATE_LABELS = {'buy': 'اشترِ', 'compare': 'قارن يدوياً', 'not_needed': 'غير مطلوب'}


def cell_text(c) -> str:
    parts = []
    if c.get('discount_pct') is not None:
        parts.append(f"خصم فعلي {c['discount_pct']:g}% ({BASIS_LABELS.get(c['basis'], c['basis'])})")
    if c.get('bonus'):
        parts.append(f"بونص {c['bonus']}")
    if c.get('quota'):
        parts.append(f"كوتة {c['quota']:g}")
    if c.get('promo'):
        parts.append(f"عرض {c['promo']}")
    if c.get('signals'):
        parts.append(' '.join(c['signals']))
    lb = c.get('last_buy')
    if lb:
        parts.append(f"آخر شراء {lb['date']} خصم {lb['discount_pct']:g}%" + (' (سعر قديم)' if lb.get('old_price') else ''))
    parts.append(VERDICT_LABELS.get(c.get('verdict'), ''))
    return ' · '.join(p for p in parts if p)


def to_excel(board) -> bytes:
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    navy, white = '022871', 'FFFFFF'
    hfont, hfill = Font(name='Arial', bold=True, color=white), PatternFill('solid', fgColor=navy)
    good = PatternFill('solid', fgColor='D9F2E3')
    body = Font(name='Arial', size=10)
    wb = Workbook()
    ws = wb.active
    ws.title = 'مقارنة الموردين'
    ws.sheet_view.rightToLeft = True
    sups = board['suppliers']
    ws.append([f'مقارنة عروض الموردين — آخر {board["days"]} يوم · الأفضل = أرخص بأكثر من '
               f'{board["better_pct"]:g}% أو ببونص · التكلفة محسوبة كخصم من سعر الجمهور الحالي'])
    ws['A1'].font = Font(name='Arial', size=12, bold=True, color=navy)
    heads = ['كود', 'الصنف', 'سعر الجمهور', 'معدل البيع الشهري', 'الرصيد', 'بالطريق', 'الاحتياج',
             'القرار', 'اشترِ من', 'خصم فعلي %', 'الكميات المقترحة'] + \
            [f"{s['name']} ({s['tier_label']})" for s in sups] + ['المخازن', 'اشترينا سابقاً بخصم أفضل من', 'إشارات']
    ws.append(heads)
    for c in ws[2]:
        c.font, c.fill, c.alignment = hfont, hfill, Alignment(horizontal='center', vertical='center', wrap_text=True)
    flag_labels = {'warehouse_cheaper': 'مخزن أرخص', 'quota_short': 'الكوتة لا تكفي'}
    for r in board['rows']:
        by = {c['supplier']: c for c in r['cells']}
        wh = [c for c in r['cells'] if c['tier'] == 'warehouse']
        best = r['best'] or {}
        alloc = ' + '.join(f"{a['supplier_name']}: {a['qty']:g}" for a in r['allocation'])
        el = r['bought_elsewhere']
        row = [r['item_code'], r['item_name'], r['public_price'], r['monthly_rate'], r['stock'], r['in_transit'],
               r['need'], STATE_LABELS[r['state']], best.get('supplier_name', ''), best.get('discount_pct'), alloc] + \
              [cell_text(by[s['key']]) if s['key'] in by else '' for s in sups] + \
              [' | '.join(f"{c['supplier_name']}: {cell_text(c)}" for c in wh),
               f"{el['name']} {el['discount_pct']:g}% ({el['date']})" if el else '',
               ' · '.join(flag_labels.get(f, f) for f in r['flags'])]
        ws.append(row)
        rr = ws.max_row
        for c in ws[rr]:
            c.font = body
            c.alignment = Alignment(vertical='top', wrap_text=True)
        for j, s in enumerate(sups):
            if s['key'] in by and by[s['key']].get('verdict') == 'best':
                ws.cell(rr, 12 + j).fill = good
    widths = [9, 38, 10, 10, 8, 8, 9, 11, 18, 10, 24] + [30] * len(sups) + [34, 26, 22]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(2, i).column_letter].width = w
    ws.freeze_panes = 'C3'
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
