"""
apps/marketplace/eligibility.py — may this listing be sold on its channel at all?

Deterministic, safety-first (CLAUDE.md rules 4/10). Reuses catalog.safety; no rules duplicated here.
Rx/controlled status is not reliably in SOFTECH, so human approval per item is the Rx gate.
"""
from apps.catalog.safety import blocks_sale, item_safety_flags


def listing_problem(listing) -> str:
    """'' when sellable, else 'not_approved' | 'blocked' | 'restricted' | 'fridge' (checked in that order)."""
    if not listing.approved:
        return 'not_approved'
    item = listing.item
    if blocks_sale(item):
        return 'blocked'
    flags = item_safety_flags(item)
    if any(f['severity'] == 'warn' for f in flags):
        return 'restricted'
    if any(f['code'] == 'fridge' for f in flags) and not listing.allow_fridge:
        return 'fridge'
    return ''
