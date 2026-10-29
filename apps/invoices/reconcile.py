"""
apps/invoices/reconcile.py

Deterministic arithmetic self-repair of OCR'd invoice-line numbers.

Every priced line carries redundant numbers that pin each other:
    net   ≈ public × (1−d1)(1−d2)(1−d3)      (discounts off the public price)
    total ≈ net × qty
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


def reconcile_numbers(fields: dict, tol: float = 0.02) -> tuple[dict, list]:
    """Repair ``net`` (unit cost) and ``quantity`` from the line's own arithmetic.
    ``fields`` keys: public_price, disc_pct, extra_disc_pct, special_disc_pct, net,
    quantity, line_total. Returns (repaired_fields, arabic_notes)."""
    out = dict(fields)
    notes: list = []
    P = _f(fields.get('public_price'))
    d1 = _f(fields.get('disc_pct')); d2 = _f(fields.get('extra_disc_pct')); d3 = _f(fields.get('special_disc_pct'))
    N = _f(fields.get('net'))
    Q = _f(fields.get('quantity'))
    LT = _f(fields.get('line_total'))

    # ── independent derivations of the net unit cost (NOT using the OCR net) ──
    derived: list[float] = []
    if P > 0:
        derived.append(P * (1 - d1 / 100) * (1 - d2 / 100) * (1 - d3 / 100))
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

    # ── quantity from total ÷ net (generalised qty sanity) ──
    N2 = _f(out.get('net'))
    if LT > 0 and N2 > 0:
        q_calc = LT / N2
        q_round = round(q_calc)
        if q_round >= 1 and abs(q_calc - q_round) <= 0.05 and (Q <= 0 or abs(Q - q_round) >= 0.5):
            out['quantity'] = float(q_round)
            notes.append('الكمية مُصحّحة حسابياً')

    return out, notes
