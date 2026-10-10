"""
apps/supply/engine/sourcing.py — supplier comparison + historical deal intelligence.

For a residual procurement gap, rank the ways to buy it by EFFECTIVE acquisition cost, not
nominal price (§12), and flag when we historically got a better deal (§13). Reuses the
procurement layer's authoritative data:

  • current offers  → apps.supply.AvailabilityLine (price / FOC / supplier_qty from the inbox)
  • supplier map    → apps.procurement.SupplierItemMapping (last / avg / min price, is_primary)
  • deal history    → apps.procurement.PurchaseLine (effective_cost + bonus_qty — the REAL FOC)

EFFECTIVE UNIT COST (the §12 rule):
    effective = price × qty / (qty + foc)
  10 units × 100 + 2 FOC → 1000 / 12 = 83.33  (beats 10 × 90 + 0 = 90.00)
The procurement engine computes the same quantity tax-inclusively on PurchaseLine
(effective_cost = (net_value + vat) / (net_qty + bonus_qty)); we read that for history.
"""
from __future__ import annotations


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def effective_unit_cost(price, qty, foc=0) -> float:
    """price × qty / (qty + foc). FOC lowers the true per-unit cost. qty ≤ 0 → price."""
    price = _f(price)
    qty = _f(qty)
    foc = _f(foc)
    received = qty + foc
    if qty <= 0 or received <= 0:
        return price
    return round(price * qty / received, 4)


def historical_best_deal(item_id, *, months=None) -> dict | None:
    """The cheapest past acquisition of this item, by effective cost, from the procurement
    purchase-line cache. Returns {effective_cost, unit_price, foc, supplier_code, date} or
    None. This is the negotiation baseline for §13 ("we paid X, with FOC, last time")."""
    from apps.procurement.models import PurchaseLine

    qs = (PurchaseLine.objects
          .filter(item_id=int(item_id), is_return=False, effective_cost__gt=0)
          .only('effective_cost', 'unit_price', 'bonus_qty', 'supplier_code', 'doc_date'))
    best = None
    for pl in qs.iterator():
        eff = _f(pl.effective_cost)
        if best is None or eff < best['effective_cost']:
            best = {
                'effective_cost': eff,
                'unit_price': _f(pl.unit_price),
                'foc': _f(pl.bonus_qty),
                'supplier_code': pl.supplier_code,
                'date': pl.doc_date.isoformat() if pl.doc_date else None,
            }
    return best


def supplier_options(item_id, residual_gap, *, availability_lines=None) -> dict:
    """Rank the ways to buy the residual gap by effective unit cost.

    Options come from (a) current availability offers passed in (AvailabilityLine rows with
    price / FOC) and (b) the historical supplier map. Each option carries the effective cost
    for the qty we actually need. Cheapest effective cost wins — NOT cheapest nominal price.
    """
    from apps.catalog.models import Item
    from apps.procurement.models import SupplierItemMapping

    gap = max(0.0, _f(residual_gap))
    options = []

    # (a) Current live offers from the availability inbox.
    for ln in (availability_lines or []):
        if ln.price is None:
            continue
        offered = _f(ln.supplier_qty) or gap
        # FOC we'd actually earn on the qty we need (proportional to the offer's ratio):
        # «25+1» = buy 25 get 1 (bonus_buy); an older line kept the "buy" in supplier_qty.
        base = _f(getattr(ln, 'bonus_buy', None)) or _f(ln.supplier_qty)
        foc_ratio = (_f(ln.foc_qty) / base) if base else 0.0
        buy_qty = min(offered, gap) if gap else offered
        foc_on_buy = buy_qty * foc_ratio
        options.append({
            'source': 'availability',
            'supplier_id': ln.batch.supplier_id,
            'supplier_name': (ln.batch.supplier.name if ln.batch.supplier_id else ln.batch.supplier_name),
            'unit_price': _f(ln.price),
            'foc_qty': _f(ln.foc_qty),
            'available_qty': _f(ln.supplier_qty),
            'effective_cost': effective_unit_cost(ln.price, buy_qty or 1, foc_on_buy),
            'expiry': ln.expiry,
            'availability_line_id': ln.id,
        })

    # (b) Historical supplier map (no live price, but a known last price).
    try:
        sid = Item.objects.only('softech_id').get(pk=int(item_id)).softech_id
    except Item.DoesNotExist:
        sid = None
    if sid:
        for m in (SupplierItemMapping.objects
                  .filter(item_code=sid, last_price__gt=0)
                  .only('supplier_code', 'supplier_name', 'last_price', 'avg_price', 'is_primary')):
            options.append({
                'source': 'history',
                'supplier_code': m.supplier_code,
                'supplier_name': m.supplier_name,
                'unit_price': _f(m.last_price),
                'foc_qty': 0.0,
                'avg_price': _f(m.avg_price),
                'is_primary': m.is_primary,
                'effective_cost': effective_unit_cost(m.last_price, 1, 0),
            })

    options.sort(key=lambda o: o['effective_cost'])
    best = options[0] if options else None

    # §13 — did we historically get a materially better deal than the best on offer now?
    hist = historical_best_deal(item_id)
    better_historical = None
    if best is not None and hist is not None:
        # 2% tolerance so trivial noise doesn't nag.
        if hist['effective_cost'] < best['effective_cost'] * 0.98:
            better_historical = {
                **hist,
                'current_best_effective': best['effective_cost'],
                'gap_pct': round((best['effective_cost'] / hist['effective_cost'] - 1) * 100, 1),
            }

    return {
        'options': options,
        'best': best,
        'historical_best_deal': hist,
        'better_historical_deal': better_historical,
    }
