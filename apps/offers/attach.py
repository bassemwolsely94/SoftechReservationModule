"""
apps/offers/attach.py — convert an offer plan into per-line `cust_discp` and
RECONCILE it against SOFTECH's own line math. DRY-RUN ONLY: computes exactly what
would be written to `SoftechSalesOrderLine.cust_discp`, writes nothing, contacts
no SOFTECH.

Why reconcile: the engine works in EGP amounts, but the SOFTECH line field is a
percent at 2 dp (`cust_discp`). We convert amount→% (`ROUND_HALF_UP`, customer-
favourable per D1) and then recompute the ACTUAL discount SOFTECH would apply via
`pos_orders.pricing.compute_line`. That recomputed number is the audited figure;
the tiny `delta` (≤ 2-dp rounding) is asserted small by tests.
"""
from decimal import Decimal, ROUND_HALF_UP

from apps.pos_orders import pricing
from .engine import evaluate_offers, _d, _r2

Q2 = Decimal('0.01')


def cust_discp_for(discount, gross):
    """amount→percent at 2 dp, rounded in the customer's favour (D1)."""
    if gross <= 0:
        return Decimal('0.00')
    return (_d(discount) / _d(gross) * Decimal('100')).quantize(Q2, rounding=ROUND_HALF_UP)


def build_attach_plan(basket, *, customer=None, branch_id=None, channel=None, margin_cfg=None):
    """
    Return {plan, lines[], reconciliation, dry_run} — the per-line cust_discp we
    WOULD write plus SOFTECH-recomputed discounts. Nothing is persisted.
    """
    plan = evaluate_offers(basket, customer=customer, branch_id=branch_id,
                           channel=channel, margin_cfg=margin_cfg)

    # sum the engine's per-line discount across all applied offers
    eng_by_index = {}
    for ap in plan['applied']:
        for ln in ap['lines']:
            eng_by_index[ln['index']] = eng_by_index.get(ln['index'], Decimal('0')) + _d(ln['discount'])

    lines = []
    for i, raw in enumerate(basket):
        isp = _d(raw.get('unit_price', 0))
        qty = _d(raw.get('qty', 0))
        gross = _r2(isp * qty)
        eng_disc = _r2(eng_by_index.get(i, Decimal('0')))
        cd = cust_discp_for(eng_disc, gross)
        c = pricing.compute_line(item_sale_price=isp, sale_tax_pct=0, qty=qty, cust_discp=cd)
        softech_disc = _r2(c['line_gross'] - c['trans_price_total'])
        lines.append({
            'index': i,
            'softech_id': raw.get('softech_id'),
            'qty': qty,
            'unit_price': isp,
            'gross': gross,
            'engine_discount': eng_disc,
            'cust_discp': cd,                 # ← what would be written to the line
            'softech_discount': softech_disc,  # ← the authoritative applied amount
            'delta': _r2(eng_disc - softech_disc),
        })

    eng_total = _r2(sum(eng_by_index.values(), Decimal('0')))
    soft_total = _r2(sum((l['softech_discount'] for l in lines), Decimal('0')))
    max_delta = max((abs(l['delta']) for l in lines), default=Decimal('0.00'))

    return {
        'plan': plan,
        'lines': lines,
        'reconciliation': {
            'engine_total': eng_total,
            'softech_total': soft_total,
            'max_line_delta': max_delta,
        },
        'dry_run': True,
    }
