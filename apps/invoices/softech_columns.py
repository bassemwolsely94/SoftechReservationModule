"""
apps/invoices/softech_columns.py

The SOFTECH purchase-line COLUMN ENGINE — a pure, deterministic replica of the
`مشتريات من الموردين` grid's cell dependencies, so the editable invoice screen
behaves exactly like the native SofTech screen (edit one cell → the dependent
cells recompute the same way SofTech would).

Empirically verified (2026-10-14) against 50+ real stktrans doccode-10 lines:

  Pb (itemsaleprice_tax, السعر الأساسي)  = P / (1 + rate/100)     ← the discount BASE
  C  (transprice,        تكلفة الوحدة)   = Pb · (1−D1/100) · (1−D2/100)   [compound]
  Tx (itemsalestax,      مبلغ الضريبة)   = C · rate/100
  CT (transprice_total,  الإجمالي)       = C · Q
  newqty (رصيد حالي)                      = stkbal.nowqty ± Q   (added by the writer)

  Golden checks:  P=144 Pb=144 D1=18.667 D2=4.940 → C=111.334
                  P=85  Pb=74.561 (rate 14) D1=20 D2=1.65 → C=58.665
                  P=550 Pb=482.456 (rate 14) → C=419.737, Tx=58.763

NOTE: the discount base is the PRE-TAX price (Pb), NOT the public price. The
legacy ``pricing.compute_line`` discounts the full public price → it over-states
cost on taxed items; this module is the corrected replacement (wiring it into the
writer is a separate, approval-gated step).

No DB access, no SOFTECH — unit-testable.
"""
from __future__ import annotations


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _r(v, n=4) -> float:
    return round(_f(v), n)


# Editable cells and which native stktrans column each maps to. Mirrors the
# «مشتريات من الموردين» grid left→right (RTL right→left). Catalog columns are
# read-only; the rest are editable/OCR'd with the dependencies modelled in
# ``recompute``.
FIELD_TO_SOFTECH = {
    'public_price':        'itemsaleprice',       # سعر البيع للجمهور (catalog, RO)
    'base_price':          'itemsaleprice_tax',   # السعر الأساسى (pre-VAT, catalog, RO)
    'disc_pct':            'pharmacydiscp',        # خصم أساسى  (d1)
    'extra_disc_pct':      'additionaldiscp',      # خصم إضافى  (d2)
    'special_disc_pct':    'specialdiscp',          # خصم خاص (d3) — VERIFIED 2026-10-17 on 10 real lines
    'tax_type':            '(% | value)',           # نوع الضريبة
    'vat_pct':             'origintaxp / rate',     # % ضريبة القيمة المضافة
    'vat_amount':          'itemsalestax',          # مبلغ الضريبة
    'tax_from_cost':       '(checkbox: tax base = cost vs base price)',  # الضريبة من التكلفة
    'unit_cost':           'transprice',            # تكلفة الوحدة بدون ضريبة
    'unit_cost_incl_tax':  '(transprice + itemsalestax)',  # إجمالى تكلفة الوحدة
    'cost_total':          'transprice_total',      # إجمالى تكلفة بدون ضريبة
    'cost_total_incl_tax': '(transprice_total + tax·qty)', # إجمالى التكلفة
    'quantity':            'transqty',              # كمية
    'bonus_qty':           '(expanded to a 2nd free line)',
}

# the three purchase discounts, in the order SofTech applies them (compound)
_DISCOUNTS = ('disc_pct', 'extra_disc_pct', 'special_disc_pct')


def recompute(cells: dict, changed: str | None = None) -> dict:
    """Return a fully-consistent SofTech purchase row given the current cell values
    and which cell the operator just changed — a faithful replica of the native
    «مشتريات من الموردين» grid.

    Columns (``cells`` keys, all optional/0):
      public_price (سعر الجمهور, RO)       base_price (السعر الأساسى, pre-VAT, RO)
      quantity (كمية)
      disc_pct (خصم أساسى)  extra_disc_pct (خصم إضافى)  special_disc_pct (خصم خاص)
      tax_type ('%'|'value', نوع الضريبة)   vat_pct (% ض.ق.م)   vat_amount (مبلغ الضريبة)
      tax_from_cost (bool, الضريبة من التكلفة — tax base = cost, else base_price)
      unit_cost (تكلفة الوحدة بدون ضريبة)   unit_cost_incl_tax (إجمالى تكلفة الوحدة)
      cost_total (إجمالى تكلفة بدون ضريبة)  cost_total_incl_tax (إجمالى التكلفة)

    Dependencies (what SofTech does):
      • Pb/P are catalog; derive the missing one via the VAT rate; editing base_price
        re-derives public_price.
      • unit_cost C = Pb·∏(1−Di/100) over the THREE discounts (compound).
      • editing unit_cost / cost_total / unit_cost_incl_tax back-solves the MAIN
        discount d1 (keeping d2, d3) so the row stays consistent.
      • tax base = C (الضريبة من التكلفة) or Pb; vat_amount ⟷ vat_pct are bidirectional
        (edit either → the other recomputes). unit_cost_incl_tax = C + vat_amount.
      • cost_total = C·Q ;  cost_total_incl_tax = unit_cost_incl_tax·Q.
    """
    P    = _f(cells.get('public_price'))
    Pb   = _f(cells.get('base_price'))
    # VAT rate: accept the new name ``vat_pct`` or the legacy ``tax_rate``.
    R    = _f(cells.get('vat_pct')) if cells.get('vat_pct') not in (None, '') else _f(cells.get('tax_rate'))
    Q    = _f(cells.get('quantity')) or 0.0
    D1   = _f(cells.get('disc_pct'))
    D2   = _f(cells.get('extra_disc_pct'))
    D3   = _f(cells.get('special_disc_pct'))
    C    = _f(cells.get('unit_cost'))
    Cin  = _f(cells.get('unit_cost_incl_tax'))
    CT   = _f(cells.get('cost_total'))
    TaxA = _f(cells.get('vat_amount'))
    B    = _f(cells.get('bonus_qty'))
    tax_type = (cells.get('tax_type') or '%')
    tax_from_cost = bool(cells.get('tax_from_cost', True))

    # 1. public ⟷ base via the item's VAT rate (catalog values; derive only the
    #    missing side, except when the operator explicitly edits base_price).
    if changed == 'base_price' and Pb > 0:
        P = Pb * (1 + R / 100.0)
    elif Pb <= 0 and P > 0:
        Pb = P / (1 + R / 100.0) if (1 + R / 100.0) else P
    elif P <= 0 and Pb > 0:
        P = Pb * (1 + R / 100.0)
    Pb = round(Pb, 4)
    P  = round(P, 4)

    # 2. cost ⟷ discounts (3-discount compound chain)
    if changed in ('unit_cost', 'cost_total', 'unit_cost_incl_tax'):
        if changed == 'cost_total':
            C = CT / Q if Q else 0.0
        elif changed == 'unit_cost_incl_tax':
            # strip tax back off the incl-tax cost the operator typed
            if tax_from_cost and R:
                C = Cin / (1 + R / 100.0)
            elif TaxA:
                C = Cin - TaxA
            else:
                C = Cin
        # keep d2, d3; back-solve the main discount d1 so Pb·(1−d1)(1−d2)(1−d3)=C
        denom = Pb * (1 - D2 / 100.0) * (1 - D3 / 100.0)
        D1 = (1 - C / denom) * 100.0 if denom > 0 else 0.0
    else:
        C = Pb * (1 - D1 / 100.0) * (1 - D2 / 100.0) * (1 - D3 / 100.0)

    C  = round(C, 4)
    D1 = round(D1, 4); D2 = round(D2, 4); D3 = round(D3, 4)

    # 3. tax: bidirectional %↔value; base = cost (الضريبة من التكلفة) or base price
    tax_base = C if tax_from_cost else Pb
    if changed == 'vat_amount':
        R = (TaxA / tax_base * 100.0) if tax_base > 0 else 0.0
        tax_type = 'value'
        Tx = TaxA
    else:
        Tx = tax_base * R / 100.0
    R  = round(R, 4)
    Tx = round(Tx, 4)

    Cin = round(C + Tx, 4)                         # إجمالى تكلفة الوحدة (incl tax)
    CT  = round(C * Q, 4)                           # إجمالى تكلفة بدون ضريبة
    CTin = round(Cin * Q, 4)                        # إجمالى التكلفة (incl tax)
    eff = round((1 - C / Pb) * 100.0, 4) if Pb > 0 else 0.0   # single effective discount

    return {
        'public_price':        P,
        'base_price':          Pb,
        'tax_rate':            R,            # legacy alias of vat_pct (kept)
        'vat_pct':             R,
        'quantity':            round(Q, 4),
        'disc_pct':            D1,
        'extra_disc_pct':      D2,
        'special_disc_pct':    D3,
        'tax_type':            tax_type,
        'tax_from_cost':       tax_from_cost,
        'unit_cost':           C,
        'unit_cost_incl_tax':  Cin,
        'cost_total':          CT,
        'cost_total_incl_tax': CTin,
        'vat_amount':          Tx,
        'effective_disc_pct':  eff,
        'bonus_qty':           round(B, 4),
    }


def row_to_write(r: dict) -> dict:
    """Map an ALREADY-recomputed row (from ``recompute``) to the stktrans money
    columns — no re-recompute, so a back-solved cost is preserved exactly."""
    return {
        'itemsaleprice':      r['public_price'],
        'itemsaleprice_tax':  r['base_price'],
        'transprice':         r['unit_cost'],
        'newcostprice':       r['unit_cost'],   # purchase omits it in the DML; kept for returns/compat
        'transprice_total':   r['cost_total'],
        'itemsalestax':       r['vat_amount'],
        'pharmacydiscp':      r['disc_pct'],          # خصم أساسى (d1)
        'additionaldiscp':    r['extra_disc_pct'],    # خصم إضافى (d2)
        'specialdiscp':       r.get('special_disc_pct', 0.0),  # خصم خاص (d3) — VERIFIED col
        'origintaxp':         0.0,   # line origintaxp is 0 on captured purchases; VAT lives in itemsalestax
    }


def to_write_fields(cells: dict) -> dict:
    """Recompute ``cells`` then map to the stktrans money columns — the single
    source of truth both the grid and the writer agree on."""
    return row_to_write(recompute(cells))


# ── FOC / bonus expansion ───────────────────────────────────────────────────────

def expand_foc(cells: dict) -> list[dict]:
    """A line with a bonus quantity becomes TWO stktrans lines (the convention):
      1. the PAID line  — quantity Q at the normal cost
      2. the FREE line  — quantity = bonus_qty at ZERO cost (lowers weighted-avg)
    Both share the itemcode; the writer already differentiates repeats via
    ``dblitemflag`` + the cumulative ``newqty`` running balance.

    Returns [paid] when there is no bonus, else [paid, free]."""
    paid = recompute(cells)
    B = _f(cells.get('bonus_qty'))
    if B <= 0:
        return [{'role': 'paid', **paid}]
    free_cells = dict(cells)
    free_cells.update({'quantity': B, 'unit_cost': 0.0, 'disc_pct': 100.0,
                       'extra_disc_pct': 0.0, 'bonus_qty': 0.0})
    free = recompute(free_cells, changed='unit_cost')
    return [{'role': 'paid', **paid}, {'role': 'free', **free}]


# ── New-price / old-price comparison (retail price decision) ────────────────────

def price_comparison(invoice_public: float, catalog_public: float, *, tol=0.001) -> dict:
    """Compare the public price READ on the invoice with the item's CURRENT catalog
    retail price, so the operator can decide per line whether to keep the old price
    or adopt the new one. Pure data — applying a master-price change is a separate,
    approval-gated SOFTECH write (never done automatically here)."""
    inv = _f(invoice_public)
    cat = _f(catalog_public)
    changed = cat > 0 and abs(inv - cat) > tol
    return {
        'invoice_price':  round(inv, 4),
        'catalog_price':  round(cat, 4),
        'changed':        bool(changed),
        'delta':          round(inv - cat, 4) if cat else None,
        'delta_pct':      round((inv / cat - 1) * 100, 2) if cat else None,
        'direction':      ('up' if inv > cat else 'down') if changed else 'same',
    }
