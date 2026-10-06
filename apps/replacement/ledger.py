"""
apps/replacement/ledger.py — the ONLY writer of EntitlementLedgerEntry (doc 25 §6).

Append-only: entries are never updated or deleted. A changed classification (e.g. an
anonymous receipt confirmed by a person) is recorded as a REVERSAL of the old entry plus
the new entries, so the history of what we believed and when stays visible.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum

from .models import EntitlementLedgerEntry as E

D0 = Decimal('0')


def balance(case) -> Decimal:
    return case.ledger.aggregate(s=Sum('amount'))['s'] or D0


def active_entries(case, document=None):
    """Entries not reversed and not themselves reversals."""
    qs = case.ledger.filter(reversed_by__isnull=True).exclude(entry_type=E.TYPE_REVERSAL)
    if document is not None:
        qs = qs.filter(document=document)
    return qs


def ensure(case, entry_type, amount, document=None, note='', user=None, origin=None) -> E | None:
    """Create the entry unless an ACTIVE entry of this type already exists for the document.
    Idempotent — re-running reconstruction never double-posts."""
    amount = Decimal(amount).quantize(Decimal('0.01'))
    if amount == 0:
        return None
    if document is not None and active_entries(case, document).filter(entry_type=entry_type).exists():
        return None
    return E.objects.create(case=case, entry_type=entry_type, amount=amount, document=document,
                            note=note[:300], created_by=user,
                            origin=origin or case.origin)


def reverse(entry: E, note='', user=None) -> E:
    return E.objects.create(case=entry.case, entry_type=E.TYPE_REVERSAL, amount=-entry.amount,
                            document=entry.document, reverses=entry, note=note[:300],
                            created_by=user, origin=entry.case.origin)


def reclassify_voucher(case, voucher_doc, product: Decimal, cash: Decimal, unclassified: Decimal,
                       note='', user=None) -> bool:
    """Make the voucher's active debits equal (product, cash, unclassified). Reverses the
    current debits and appends the new split only when it actually differs."""
    want = {E.TYPE_PRODUCT: -product, E.TYPE_CASH: -cash, E.TYPE_UNCLASSIFIED: -unclassified}
    want = {k: Decimal(v).quantize(Decimal('0.01')) for k, v in want.items() if v}
    current = {}
    for e in active_entries(case, voucher_doc).filter(entry_type__in=want.keys() | {
            E.TYPE_PRODUCT, E.TYPE_CASH, E.TYPE_UNCLASSIFIED}):
        current[e.entry_type] = current.get(e.entry_type, D0) + e.amount
    if current == want:
        return False
    for e in active_entries(case, voucher_doc).filter(
            entry_type__in=[E.TYPE_PRODUCT, E.TYPE_CASH, E.TYPE_UNCLASSIFIED]):
        reverse(e, note=note or 'إعادة تصنيف', user=user)
    for t, amt in want.items():
        E.objects.create(case=case, entry_type=t, amount=amt, document=voucher_doc,
                         note=(note or 'إعادة تصنيف')[:300], created_by=user, origin=case.origin)
    return True


def totals(case) -> dict:
    """Signed Σ per economic bucket over ALL entries (reversals net out by document type)."""
    out = {k: D0 for k in ('created', 'product', 'cash', 'unclassified', 'supplier_return',
                           'return_settled', 'pos_return')}
    tmap = {E.TYPE_CREATED: 'created', E.TYPE_PRODUCT: 'product', E.TYPE_CASH: 'cash',
            E.TYPE_UNCLASSIFIED: 'unclassified', E.TYPE_SUPPLIER_RET: 'supplier_return',
            E.TYPE_RETURN_SETTLED: 'return_settled', E.TYPE_POS_RETURN: 'pos_return'}
    for e in case.ledger.select_related('reverses'):
        t = e.reverses.entry_type if e.entry_type == E.TYPE_REVERSAL and e.reverses_id else e.entry_type
        key = tmap.get(t)
        if key:
            out[key] += e.amount
    return out
