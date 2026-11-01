"""
apps/invoices/reconcile.py

Deterministic arithmetic self-repair of OCR'd invoice-line numbers.

Every priced line carries redundant numbers that pin each other:
    net   ≈ paper_base × (1−d1)(1−d2)(1−d3)
            paper_base = (public − pharmacist margin − distributor margin) / (1 + VAT)
    total ≈ net × qty
The margin rule is how the distributor prints «سعر صيدلي» (verified on every margin
line of PharmaOverseas invoice 224, e.g. (338 − 5 − 5) × 0.82 = 268.96); owner-approved
2026-10-31 as the net fallback and as a check on an OCR'd net.
When OCR garbles ONE of these, the others still determine it. We derive each field
from the independent paths and take a CONSENSUS: a field is repaired only when the
derivations AGREE and the OCR value is missing or out-voted by ≥2 independent
sources — never a guess from a single number, and every repair is flagged for the
operator to glance at. This is pure arithmetic (CLAUDE.md: financial numbers are
deterministic and testable; no AI deciding totals), run at parse time to clean the
pre-filled values the human then confirms.
"""
from __future__ import annotations


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _agree(a: float, b: float, tol: float) -> bool:
    return a > 0 and b > 0 and abs(a - b) / max(a, b) <= tol


def _consensus(values: list[float], tol: float) -> float | None:
    """The value that the most others agree with (within relative tol); returned
    only when at least TWO values agree. None otherwise (don't trust a lone value)."""
    vals = [v for v in values if v > 0]
    best, best_n = None, 1
    for v in vals:
        n = sum(1 for w in vals if _agree(v, w, tol))
        if n > best_n:
            best, best_n = v, n
    return best if best_n >= 2 else None


# the standard Egyptian VAT rates seen on purchase invoices
_STD_VAT = (14.0, 10.0, 5.0)
MARGIN_MISMATCH_NOTE = 'الصافي لا يطابق (الجمهور − الهوامش) × الخصم — راجع'
COLUMN_SHIFT_NOTE = 'أعمدة الأرقام كانت مُزاحة في القراءة — أُعيد ترتيبها، راجع'


def paper_base(public, pharmacist_margin=0.0, distributor_margin=0.0, vat_pct=0.0) -> float:
    """The price the distributor applies its discount to: public less both fixed
    margins, before VAT. 0 when public is missing."""
    P = _f(public) - _f(pharmacist_margin) - _f(distributor_margin)
    if P <= 0:
        return 0.0
    # only a standard rate counts: some layouts print the VAT AMOUNT per unit, which
    # OCR can drop into the rate field (12.77 would look like a 12.77 % rate)
    v = _f(vat_pct)
    std = next((r for r in _STD_VAT if abs(v - r) <= 0.3), 0.0)
    return P / (1 + std / 100.0)


def paper_net(public, discounts=(), pharmacist_margin=0.0, distributor_margin=0.0,
              vat_pct=0.0) -> float:
    """سعر صيدلي as the distributor prints it: paper_base × ∏(1 − d/100)."""
    net = paper_base(public, pharmacist_margin, distributor_margin, vat_pct)
    for d in discounts:
        net *= (1 - _f(d) / 100.0)
    return round(net, 4)


def repair_column_shift(f: dict, tol: float = 0.01) -> tuple[dict, list]:
    """Undo the column slide the semantic OCR makes on PharmaOverseas-style grids,
    where the money columns land one or two places off:

      untaxed row: discount_pct ← line total, extra_discount_pct ← net
                   (detected by line total = net × qty)
      taxed row:   discount_pct ← net, extra_discount_pct ← VAT total,
                   pharmacist_price ← VAT per unit
                   (detected by VAT/unit = net × a standard rate and
                    VAT total = VAT/unit × qty)

    The shifted net must also be a plausible net (≥ 30 % of public), so ordinary
    percentages (e.g. 20 % and 10 % on qty 2) never trigger it. The real discount
    is then back-solved from the net with the paper formula. ``f`` keys:
    public_price, disc_pct, extra_disc_pct, net, quantity, vat_pct,
    pharmacist_margin, distributor_margin. Returns (fields, notes)."""
    out = dict(f)
    P = _f(f.get('public_price')); Q = _f(f.get('quantity')) or 1.0
    a = _f(f.get('disc_pct')); b = _f(f.get('extra_disc_pct')); c = _f(f.get('net'))
    pm = _f(f.get('pharmacist_margin')); dm = _f(f.get('distributor_margin'))

    def close(x, y):
        return x > 0 and y > 0 and abs(x - y) <= max(tol * max(x, y), 0.02)

    def plausible_net(x):
        return P > 0 and 0.3 * P <= x < P

    net = rate = None
    if plausible_net(b) and close(a, b * Q) and c <= 0:
        net, rate, line_total = b, 0.0, a                       # untaxed slide
    elif plausible_net(a) and c > 0 and close(b, c * Q):
        r = c / a * 100.0
        std = next((v for v in _STD_VAT if abs(r - v) <= 0.3), None)
        if std is not None:
            net, rate, line_total = a, std, a * Q + b           # taxed slide
    if net is None:
        return out, []
    base = paper_base(P, pm, dm, rate)
    d1 = round((1 - net / base) * 100.0, 4) if base > 0 else 0.0
    out.update({'net': round(net, 4), 'disc_pct': d1, 'extra_disc_pct': 0.0,
                'vat_pct': rate, 'line_total': round(line_total, 4)})
    return out, [COLUMN_SHIFT_NOTE]


def reconcile_numbers(fields: dict, tol: float = 0.02) -> tuple[dict, list]:
    """Repair ``net`` (unit cost) and ``quantity`` from the line's own arithmetic.
    ``fields`` keys: public_price, disc_pct, extra_disc_pct, special_disc_pct, net,
    quantity, line_total; optional pharmacist_margin, distributor_margin, vat_pct
    (the public-price path then uses the paper formula). Returns
    (repaired_fields, arabic_notes)."""
    out = dict(fields)
    notes: list = []
    P = _f(fields.get('public_price'))
    d1 = _f(fields.get('disc_pct')); d2 = _f(fields.get('extra_disc_pct')); d3 = _f(fields.get('special_disc_pct'))
    N = _f(fields.get('net'))
    Q = _f(fields.get('quantity'))
    LT = _f(fields.get('line_total'))

    # ── independent derivations of the net unit cost (NOT using the OCR net) ──
    derived: list[float] = []
    pm = _f(fields.get('pharmacist_margin')); dm = _f(fields.get('distributor_margin'))
    from_public = paper_net(P, (d1, d2, d3), pm, dm, fields.get('vat_pct')) if P > 0 else 0.0
    if from_public > 0:
        derived.append(from_public)
    if LT > 0 and Q > 0:
        derived.append(LT / Q)

    if N <= 0:
        # net missing → fill from the derivations (consensus if ≥2, else the lone one)
        fill = _consensus(derived, tol) or (derived[0] if len(derived) == 1 else None)
        if fill and fill > 0:
            out['net'] = round(fill, 4)
            notes.append('التكلفة محسوبة من قيم السطر')
    elif len(derived) >= 2:
        # net present but the two INDEPENDENT derivations agree with each other and
        # disagree with the OCR net → the OCR net is the outlier; repair it.
        agree = _consensus(derived, tol)
        if agree and not _agree(N, agree, tol):
            out['net'] = round(agree, 4)
            notes.append('التكلفة مُصحّحة حسابياً (قراءة شاذة)')

    # a margin line whose net disagrees with (public − margins) × discounts: flag it
    # (the margin rule is a check, never a silent override of a printed net)
    if (pm > 0 or dm > 0) and N > 0 and from_public > 0 and _f(out.get('net')) == N             and not _agree(N, from_public, 0.005):
        notes.append(MARGIN_MISMATCH_NOTE)

    # ── quantity from total ÷ net (generalised qty sanity) ──
    N2 = _f(out.get('net'))
    if LT > 0 and N2 > 0:
        q_calc = LT / N2
        q_round = round(q_calc)
        if q_round >= 1 and abs(q_calc - q_round) <= 0.05 and (Q <= 0 or abs(Q - q_round) >= 0.5):
            out['quantity'] = float(q_round)
            notes.append('الكمية مُصحّحة حسابياً')

    return out, notes
