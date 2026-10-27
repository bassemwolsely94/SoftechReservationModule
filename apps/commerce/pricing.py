"""
apps/commerce/pricing.py — pluggable pricing strategies for commerce documents.

Phase 1 ships `manual_line` (quotations & retail): prices are hand-typed and
VAT-inclusive; the VAT portion of flagged lines is back-computed for display and
totals, never added on top.  The strategy is chosen by DocumentType.pricing_profile
so new document behaviours are config, not branches.
"""
from decimal import Decimal

_Q = Decimal('0.01')


def _q(v):
    return Decimal(str(v or 0)).quantize(_Q)


def _manual_line(document) -> dict:
    """Sum VAT-inclusive line totals; VAT is the back-computed portion of flagged
    lines (inclusive), so total == Σ line_total and subtotal == total − vat."""
    rate = Decimal(str(document.vat_rate or 0))
    total = vat = Decimal('0')
    for ln in document.lines.all():
        total += ln.line_total
        vat   += ln.vat_amount(rate)
    total = _q(total)
    vat   = _q(vat)
    return {'subtotal_ex_vat': _q(total - vat), 'vat_total': vat, 'total': total}


def _none(document) -> dict:
    total = Decimal('0')
    for ln in document.lines.all():
        total += ln.line_total
    return {'subtotal_ex_vat': _q(total), 'vat_total': Decimal('0.00'), 'total': _q(total)}


_STRATEGIES = {
    'manual_line': _manual_line,
    'none':        _none,
    # 'pq_aggregate' is served by apps.insurance for now; wired in at adoption (P4).
}


def compute_document_totals(document) -> dict:
    """Return {subtotal_ex_vat, vat_total, total} for a CommerceDocument using the
    strategy named by its type.  Unknown/insurance profiles fall back to a plain sum."""
    profile = getattr(document.doc_type, 'pricing_profile', 'manual_line')
    strategy = _STRATEGIES.get(profile, _manual_line)
    return strategy(document)
