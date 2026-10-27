"""
apps/insurance/reprice.py

Pure, deterministic recompute for a SOFTECH insurance-receipt price edit.  READ-ONLY
helpers — they compute what the new SOFTECH rows WOULD be; they never touch Sybase.
The writeback service (P3) consumes these; the preview (P2) displays them.

Verified against live goldens (2026-09-13, doccode 115):
  BETADINE 10% (taxed 14%, contract 17%): 85 → 95 produced
    itemsaleprice_tax = 95/1.14   = 83.3333   (price ex-VAT)
    transprice        = 95×0.83    = 78.85      (net unit after contract discount)
    itemsalestax      = 78.85×14/114 = 9.6833   (VAT portion of the net)
    transprice_total  = 78.85×qty
  Header re-foot:  docvalue1(gross)=Σ(itemsaleprice×qty),
                   docvalue(net)=Σ transprice_total,  docvalue3(VAT)=Σ(itemsalestax×qty).
  docvalue2 (total cost = Σ newcostprice×qty) is INDEPENDENT of sale price → untouched.
  personnewbal (contract-client running Σ docvalue) is handled by a SEPARATE rebalance
  pass, never here.
"""
from decimal import Decimal, ROUND_HALF_UP

_Q2 = Decimal('0.01')
_Q4 = Decimal('0.0001')


def _d(v, default='0') -> Decimal:
    if v is None:
        return Decimal(default)
    return Decimal(str(v))


def r2(v) -> Decimal:
    return _d(v).quantize(_Q2, rounding=ROUND_HALF_UP)


def r4(v) -> Decimal:
    return _d(v).quantize(_Q4, rounding=ROUND_HALF_UP)


def recompute_line(*, new_price, transqty, custdiscp, vat_rate) -> dict:
    """
    Recompute a stktrans line's price-dependent fields for a new public price.

    Inputs (Decimals/str/num):
      new_price  — new itemsaleprice (public, VAT-inclusive)
      transqty   — pack fraction / units (unchanged by a re-price)
      custdiscp  — contract discount rate % (e.g. 17), unchanged
      vat_rate   — additionaldiscp: line VAT rate (14 for taxed, 0 otherwise), unchanged

    Returns the new values for: itemsaleprice, itemsaleprice_tax, transprice,
    itemsalestax, transprice_total.  All other stktrans columns stay as-is.
    """
    P = _d(new_price)
    qty = _d(transqty)
    cd = _d(custdiscp)
    vat = _d(vat_rate)

    net_unit = P * (Decimal('100') - cd) / Decimal('100')          # after contract discount
    itemsaleprice_tax = (P / (Decimal('1') + vat / Decimal('100'))) if vat else P
    itemsalestax_unit = (net_unit * vat / (Decimal('100') + vat)) if vat else Decimal('0')
    transprice_total = r2(net_unit * qty)

    return {
        'itemsaleprice':     r2(P),
        'itemsaleprice_tax': r4(itemsaleprice_tax),
        'transprice':        r4(net_unit),
        'itemsalestax':      r4(itemsalestax_unit),
        'transprice_total':  transprice_total,
        # carried through unchanged (echoed for the diff/audit)
        'transqty':          qty,
        'custdiscp':         cd,
        'additionaldiscp':   vat,
    }


def refoot_header(lines: list[dict]) -> dict:
    """
    Re-foot the stktransm header from the (new) line set.

    Each line dict needs: itemsaleprice, transqty, transprice_total, itemsalestax.
    Returns {docvalue (net), docvalue1 (gross), docvalue3 (VAT total)}.
    docvalue2 (total cost) is deliberately NOT computed here — it is price-independent
    and must be carried over from the existing header unchanged.
    """
    gross = sum((_d(l['itemsaleprice']) * _d(l['transqty']) for l in lines), Decimal('0'))
    net = sum((_d(l['transprice_total']) for l in lines), Decimal('0'))
    vat = sum((_d(l['itemsalestax']) * _d(l['transqty']) for l in lines), Decimal('0'))
    return {
        'docvalue1': r2(gross),   # gross before discount
        'docvalue':  r2(net),     # net (what the tender must equal)
        'docvalue3': r2(vat),     # VAT total
    }
