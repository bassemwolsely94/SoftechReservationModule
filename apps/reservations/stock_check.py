"""
apps/reservations/stock_check.py — C33: a reservation's stock check covers EVERY line.

A reservation asks for its header item (the first item) plus any extra ReservationLine rows —
the same list the detail screen shows. Before C33 the automatic «متوفر» promotion
(notify_stock_available) looked at the header item only, and at any single stock row (sellable or
not), so a basket with one short line still showed «متوفر» and the customer came to a partial order.

Rule (deterministic, no AI): each catalog line is checked against SELLABLE on-hand stock at the
reservation's branch (catalog.exclude_unsellable — the one sellable rule, owner 2026-11-13).
The same item on several lines is checked against their total. A free-text (manual) line has no
stock to check, so it is «manual» and the reservation is never auto-promoted for it — a person
checks it by hand. Read-only: Postgres ItemStock mirror only, never SOFTECH.
"""
from decimal import Decimal

from django.db.models import Sum

OK, SHORT, OUT, MANUAL = 'ok', 'short', 'out', 'manual'
LINE_LABELS = {OK: 'متوفر', SHORT: 'كمية غير كافية', OUT: 'غير متوفر', MANUAL: 'صنف يدوي — راجع يدوياً'}

ALL_AVAILABLE, PARTIAL, NONE_AVAILABLE, NEEDS_REVIEW = 'all', 'partial', 'none', 'review'
OVERALL_LABELS = {
    ALL_AVAILABLE: 'كل الأصناف متوفرة',
    PARTIAL: 'بعض الأصناف ناقصة',
    NONE_AVAILABLE: 'لا شيء متوفر',
    NEEDS_REVIEW: 'فيه أصناف يدوية — راجع يدوياً',
}


def requirements(reservation, lines=None):
    """[(key, item_id or None, label, qty)] — header item first, then extra lines."""
    out = []
    if reservation.item_id or (reservation.manual_item_name or '').strip():
        label = reservation.item.name if reservation.item_id else reservation.manual_item_name
        out.append(('header', reservation.item_id, label,
                    Decimal(str(reservation.quantity_requested or 1))))
    for ln in (lines if lines is not None else reservation.lines.select_related('item')):
        label = ln.item.name if ln.item_id else (ln.manual_item_name or '(صنف غير مكوَّد)')
        out.append((f'line:{ln.pk}', ln.item_id, label, Decimal(str(ln.quantity_requested or 1))))
    return out


def sellable_on_hand(branch_id, item_ids):
    """{item_id: Decimal} sellable on-hand at one branch (one query)."""
    from apps.catalog.models import ItemStock, exclude_unsellable
    if not branch_id or not item_ids:
        return {}
    rows = (exclude_unsellable(ItemStock.objects.filter(branch_id=branch_id, item_id__in=item_ids))
            .values('item_id').annotate(q=Sum('quantity_on_hand')))
    return {r['item_id']: Decimal(str(r['q'] or 0)) for r in rows}


def check(reservation, lines=None):
    """Per-line availability at the reservation's branch + one overall verdict.

    Returns {'overall': str, 'overall_label': str, 'lines': [{key, item, label, requested,
    on_hand, status, status_label}]}. `on_hand` is the item's sellable total at the branch.
    """
    reqs = requirements(reservation, lines)
    stock = sellable_on_hand(reservation.branch_id, {i for _, i, _, _ in reqs if i})
    need = {}
    for _, item_id, _, qty in reqs:
        if item_id:
            need[item_id] = need.get(item_id, Decimal('0')) + qty

    rows = []
    for key, item_id, label, qty in reqs:
        if not item_id:
            status, on_hand = MANUAL, None
        else:
            on_hand = stock.get(item_id, Decimal('0'))
            if on_hand <= 0:
                status = OUT
            elif on_hand < need[item_id]:
                status = SHORT
            else:
                status = OK
        rows.append({'key': key, 'item': item_id, 'label': label, 'requested': float(qty),
                     'on_hand': float(on_hand) if on_hand is not None else None,
                     'status': status, 'status_label': LINE_LABELS[status]})

    statuses = {r['status'] for r in rows}
    if not rows:
        overall = NEEDS_REVIEW
    elif MANUAL in statuses:
        overall = NEEDS_REVIEW
    elif statuses == {OK}:
        overall = ALL_AVAILABLE
    elif OK in statuses or SHORT in statuses:
        overall = PARTIAL
    else:
        overall = NONE_AVAILABLE
    return {'overall': overall, 'overall_label': OVERALL_LABELS[overall], 'lines': rows}


def summary_text(result):
    """One Arabic line for the chatter / status log, e.g. «باراسيتامول 20/2 · فيتامين 3/1»."""
    parts = []
    for r in result['lines']:
        if r['on_hand'] is None:
            parts.append(f"{r['label']}: يدوي")
        else:
            parts.append(f"{r['label']}: {r['on_hand']:g} متاح / {r['requested']:g} مطلوب")
    return ' · '.join(parts)
