"""
apps/purchasing/in_transit.py — ONE definition of "quantity in transit", shared by the
demand engine (gap = target − stock − in_transit) and the branch-request fulfilment plan
(apps/purchasing/isr_fulfillment.py) so the two can never disagree.

In transit = SOFTECH inter-branch transfers (doccode 125, mirrored in
apps.transits.InTransitTransfer) dispatched but not yet received at their receiving branch
(transit_status 'in_transit'), issued within EngineConfig.in_transit_max_age_days (default
14). Older rows are stale / unreconciled documents, not live pipeline. 0 = no age limit.
Quantities are each transfer's items_snapshot qty (packs), summed per receiving branch.
"""
from __future__ import annotations

import datetime
import logging
from collections import defaultdict

from django.utils import timezone

logger = logging.getLogger(__name__)
DEFAULT_MAX_AGE_DAYS = 14


def max_age_days() -> int:
    """The engine's configured freshness window (EngineConfig), else 14."""
    try:
        from apps.purchasing.models import EngineConfig
        return int(EngineConfig.get().in_transit_max_age_days)
    except Exception:
        return DEFAULT_MAX_AGE_DAYS


def live_rows(max_age: int | None = None):
    """((receiving_branch_id, items_snapshot) rows, excluded_stale_count, max_age)."""
    from apps.transits.models import InTransitTransfer
    max_age = max_age_days() if max_age is None else int(max_age)
    qs = InTransitTransfer.objects.filter(transit_status='in_transit', receiving_branch__isnull=False)
    excluded = 0
    if max_age and max_age > 0:
        cutoff = timezone.localdate() - datetime.timedelta(days=max_age)
        excluded = qs.filter(issue_date__lt=cutoff).count()
        qs = qs.filter(issue_date__gte=cutoff)
    return qs.values_list('receiving_branch_id', 'items_snapshot'), excluded, max_age


def sum_by(rows, *, item_key, branch_key) -> dict:
    """{(item_key(itemcode), branch_key(branch_id)): qty}; a None key skips the line."""
    out = defaultdict(float)
    for branch_id, snapshot in rows.iterator() if hasattr(rows, 'iterator') else rows:
        b = branch_key(branch_id)
        if b is None:
            continue
        for line in (snapshot or []):
            k = item_key(str(line.get('itemcode') or '').strip())
            if k is None:
                continue
            try:
                out[(k, b)] += float(line.get('qty') or 0)
            except (TypeError, ValueError):
                pass
    return dict(out)


def by_branch_code(itemcodes, max_age: int | None = None) -> tuple:
    """({softech branchcode: {itemcode: qty}}, max_age) for the given items — what the
    fulfilment plan stores in its snapshot."""
    from apps.branches.models import Branch
    wanted = {str(c).strip() for c in itemcodes}
    rows, _excluded, max_age = live_rows(max_age)
    codes = dict(Branch.objects.values_list('id', 'softech_branch_id'))
    flat = sum_by(rows, item_key=lambda c: c if c in wanted else None,
                  branch_key=lambda bid: (codes.get(bid) or None))
    out = defaultdict(dict)
    for (code, bc), q in flat.items():
        if q:
            out[str(bc).strip()][code] = round(q, 3)
    return dict(out), max_age
