"""
apps/invoices/pricing.py

Pure functions that map an OCR'd/confirmed InvoiceLine to the SOFTECH stktrans
purchase-line columns, per the empirically captured golden template (doc 130/10/11946;
see docs/architecture/SOFTECH_SUPPLIER_INVOICE_WRITEBACK.md §5).

Confirmed on real data (HALOPERIDOL line): public itemsaleprice 28.000 × (1 − pharmacydiscp 21.0714%)
= unit cost transprice 22.10 = newcostprice; transprice_total = ×qty.

No DB access, no SOFTECH — deterministic and unit-testable.
"""
from __future__ import annotations


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def compute_line(*, public_price, unit_price, qty, discount_pct=0,
                 extra_discount_pct=0, vat_pct=0) -> dict:
    """
    Returns the SOFTECH stktrans line money fields for one purchase line.

    `unit_price` is the net pharmacist (purchase) price/pack. When it is 0 we derive
    it from the public price and the discounts (public × (1−disc) × (1−extra)).
    `pharmacydiscp` is recomputed as the EFFECTIVE public→net discount % so it
    round-trips to the same net the native screen shows.
    """
    public = _f(public_price)
    qty_f  = _f(qty)
    disc   = _f(discount_pct)
    extra  = _f(extra_discount_pct)
    vat    = _f(vat_pct)

    net = _f(unit_price)
    if net == 0 and public > 0:
        net = round(public * (1 - disc / 100) * (1 - extra / 100), 4)

    trans_price_total = round(net * qty_f, 4)

    # effective single discount % from public → net (what SOFTECH stores in pharmacydiscp)
    pharmacy_discp = round((1 - net / public) * 100, 4) if public > 0 and net <= public else 0.0

    # pre-tax retail + line VAT amount (0 for tax-exempt items, as in the golden row)
    if vat > 0:
        item_sale_price_tax = round(public / (1 + vat / 100), 4)
        item_sale_tax       = round(trans_price_total - trans_price_total / (1 + vat / 100), 4)
    else:
        item_sale_price_tax = public
        item_sale_tax       = 0.0

    return {
        'transprice':          round(net, 4),
        'newcostprice':        round(net, 4),     # landed cost = net (trigger recomputes weighted-avg on insert)
        'transprice_total':    trans_price_total,
        'itemsaleprice':       round(public, 4),
        'itemsaleprice_tax':   item_sale_price_tax,
        'itemsalestax':        item_sale_tax,
        'pharmacydiscp':       pharmacy_discp,
        'additionaldiscp':     round(extra, 4),
        'origintaxp':          round(vat, 4),
    }


def compute_header(computed_lines: list[dict]) -> dict:
    """Header totals. Purchases leave docvalue1/2/3 = 0 (confirmed on the golden row);
    only docvalue (= Σ line totals) is populated."""
    doc_value = round(sum(_f(c['transprice_total']) for c in computed_lines), 4)
    return {
        'doc_value':  doc_value,
        'doc_value1': 0.0,
        'doc_value2': 0.0,
        'doc_value3': 0.0,
    }
