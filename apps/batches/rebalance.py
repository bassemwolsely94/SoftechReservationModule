"""
apps/batches/rebalance.py — network-wide near-expiry rebalancing worklist (B3, owner 2026-10-07).

ADVISORY. Lists every short-dated batch that will NOT sell before it expires at its branch and the
branches that sell the item fast enough to clear it, sorted by money at risk. A line becomes a DRAFT
transfer request through the existing /transfers/ API (the transfers team submits + approves as usual).
Nothing here writes to SOFTECH or creates anything by itself.

Complements the per-item A4 dialog (expiry_audit.rebalance_suggest, live stkbal) — this is the
whole-network sweep, batch-level and FEFO-aware, from the daily StockExpiryBalance mirror.

Deterministic rules
  * stock  = StockExpiryBalance, quarantine stores excluded, qty > 0 (all branch nodes, daily mirror)
  * rate   = ItemDemandMetrics.qty_90d / 90 per (item, branch), latest engine run
  * source, per item, batches in expiry order (FEFO): a batch expiring in d days sells
            min(qty, rate·d − already-sold); the rest is AT RISK
  * only batches with MIN_DAYS ≤ d ≤ HORIZON are actionable (sooner = too late to move →
            markdown / return, counted separately)
  * target headroom for that batch = rate_t · (d − TRANSIT_DAYS) − target stock expiring on/before
            it (FEFO competition) − what this run already planned there
  * most urgent batch first, then highest headroom target; whole packs; HQ never a target (no sales)
  * a line with an open transfer (draft / pending / approved / needs revision) for the same item
            source → target is flagged so it is not created twice
Settings: EXPIRY_REBALANCE_HORIZON_DAYS (180) · _MIN_DAYS (30) · _TRANSIT_DAYS (7).
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

OPEN_TRANSFER = ('draft', 'pending', 'approved', 'needs_revision')


def _cfg(name, default):
    return int(getattr(settings, f'EXPIRY_REBALANCE_{name}', default))


def plan(batches, rates, target_stock, *, today, horizon, min_days, transit, hq_codes=frozenset()):
    """Pure core. batches: [{item, branch, batch_no, expiry, qty}] (source stock, all branches);
    rates: {(item, branch): units/day}; target_stock: {(item, branch): [(expiry, qty)]}.
    Returns (lines, buckets) — lines: one per (batch, target); buckets: at_risk / too_late / no_target
    quantities per (item, branch)."""
    by_src = defaultdict(list)
    for b in batches:
        by_src[(b['item'], b['branch'])].append(b)
    risks = []                                  # (expiry, item, branch, batch_no, at_risk_qty, d)
    too_late = defaultdict(float)
    for (item, br), rows in by_src.items():
        rate, sold = rates.get((item, br), 0.0), 0.0
        for b in sorted(rows, key=lambda r: (r['expiry'], r['batch_no'])):
            d = (b['expiry'] - today).days
            if d < 0:
                continue                         # already expired — disposal, not rebalancing
            sells = max(0.0, min(b['qty'], rate * d - sold))
            sold += sells
            at_risk = b['qty'] - sells
            if at_risk < 0.5:
                continue
            if d < min_days:
                too_late[(item, br)] += at_risk
            elif d <= horizon:
                risks.append((b['expiry'], item, br, b['batch_no'], at_risk, d))

    planned = defaultdict(list)                  # (item, target) → [(expiry, qty)] added by this run
    lines, no_target = [], defaultdict(float)
    branches = {br for (_, br) in rates}
    for expiry, item, src, batch_no, at_risk, d in sorted(risks, key=lambda r: (r[0], r[1], r[2])):
        sell_days = max(0, d - transit)
        heads = []
        for t in branches:
            if t == src or t in hq_codes:
                continue
            r = rates.get((item, t), 0.0)
            if r <= 0:
                continue
            competing = sum(q for e, q in target_stock.get((item, t), []) + planned[(item, t)] if e <= expiry)
            h = r * sell_days - competing
            if h >= 1:
                heads.append((h, t, r))
        remaining = at_risk
        for h, t, r in sorted(heads, key=lambda x: (-x[0], x[1])):
            qty = int(min(remaining, h))
            if qty < 1:
                continue
            lines.append({'item': item, 'from': src, 'to': t, 'batch_no': batch_no, 'expiry': expiry,
                          'days_to_expiry': d, 'qty': qty, 'source_rate': rates.get((item, src), 0.0),
                          'target_rate': r, 'at_risk': at_risk})
            planned[(item, t)].append((expiry, qty))
            remaining -= qty
            if remaining < 1:
                break
        if remaining >= 1:
            no_target[(item, src)] += remaining
    return lines, {'too_late': dict(too_late), 'no_target': dict(no_target)}


def _load(today, horizon):
    from apps.batches.models import StockExpiryBalance
    from apps.branches.models import Branch
    from apps.purchasing.models import ItemDemandMetrics
    from django.db.models import Max

    live = (StockExpiryBalance.objects.filter(is_quarantine=False, qty__gt=0)
            .values('item_code', 'branch_code', 'batch_no', 'expiry_date')
            .annotate(q=Sum('qty')))
    batches, target_stock, items = [], defaultdict(list), set()
    for r in live:
        key = (r['item_code'], r['branch_code'])
        target_stock[key].append((r['expiry_date'], float(r['q'])))
        if r['expiry_date'] <= today + dt.timedelta(days=horizon):
            items.add(r['item_code'])
            batches.append({'item': r['item_code'], 'branch': r['branch_code'], 'batch_no': r['batch_no'] or '',
                            'expiry': r['expiry_date'], 'qty': float(r['q'])})
    meta = {b.softech_branch_id: b for b in Branch.objects.filter(is_active=True)}
    rates = {}
    latest = ItemDemandMetrics.objects.aggregate(m=Max('calc_date'))['m']
    if latest:
        for ic, bc, q90 in (ItemDemandMetrics.objects.filter(calc_date=latest, item__softech_id__in=items)
                            .values_list('item__softech_id', 'branch__softech_branch_id', 'qty_90d')):
            if bc in meta:
                rates[(str(ic), str(bc))] = float(q90 or 0) / 90.0
    hq = {c for c, b in meta.items() if getattr(b, 'kind', '') == 'hq' or not b.can_transact}
    return batches, rates, target_stock, meta, hq, bool(latest)


def _open_transfers(lines, meta):
    from apps.transfers.models import TransferRequestItem
    if not lines:
        return {}
    item_codes = {l['item'] for l in lines}
    out = {}
    for ic, src, dst, num in (TransferRequestItem.objects
                              .filter(item__softech_id__in=item_codes, request__status__in=OPEN_TRANSFER)
                              .values_list('item__softech_id', 'request__supplying_branch__softech_branch_id',
                                           'request__requesting_branch__softech_branch_id', 'request__request_number')):
        out[(str(ic), str(src), str(dst))] = num
    return out


def worklist(*, branch=None, item=None, today=None):
    """The screen's data: rebalancing lines + totals (value at cost)."""
    from apps.catalog.models import Item
    today = today or timezone.localdate()
    horizon, min_days, transit = _cfg('HORIZON_DAYS', 180), _cfg('MIN_DAYS', 30), _cfg('TRANSIT_DAYS', 7)
    batches, rates, target_stock, meta, hq, have_rates = _load(today, horizon)
    lines, buckets = plan(batches, rates, target_stock, today=today, horizon=horizon, min_days=min_days,
                          transit=transit, hq_codes=frozenset(hq))
    if branch:
        lines = [l for l in lines if l['from'] == str(branch) or l['to'] == str(branch)]
    if item:
        lines = [l for l in lines if l['item'] == str(item)]
    codes = {l['item'] for l in lines} | {k[0] for b in buckets.values() for k in b}
    items = {i.softech_id: i for i in Item.objects.filter(softech_id__in=codes).only('id', 'softech_id', 'name', 'cost_price')}
    open_tr = _open_transfers(lines, meta)

    def cost(ic):
        it = items.get(ic)
        return float(it.cost_price or 0) if it else 0.0

    def bname(code):
        b = meta.get(code)
        return (b.name_ar or b.name) if b else code

    rows = []
    for l in lines:
        it = items.get(l['item'])
        rows.append({
            'item_code': l['item'], 'item_id': it.id if it else None, 'item_name': it.name if it else l['item'],
            'from_branch': l['from'], 'from_branch_id': meta[l['from']].id if l['from'] in meta else None,
            'from_branch_name': bname(l['from']),
            'to_branch': l['to'], 'to_branch_id': meta[l['to']].id if l['to'] in meta else None,
            'to_branch_name': bname(l['to']),
            'batch_no': l['batch_no'], 'expiry': l['expiry'].isoformat(), 'days_to_expiry': l['days_to_expiry'],
            'qty': l['qty'], 'value': round(l['qty'] * cost(l['item']), 2),
            'source_rate_month': round(l['source_rate'] * 30, 2), 'target_rate_month': round(l['target_rate'] * 30, 2),
            'open_transfer': open_tr.get((l['item'], l['from'], l['to']), ''),
        })
    rows.sort(key=lambda r: (r['days_to_expiry'], -r['value']))

    def total(bucket):
        return round(sum(q * cost(ic) for (ic, br), q in bucket.items()
                         if (not branch or br == str(branch)) and (not item or ic == str(item))), 2)
    return {
        'have_rates': have_rates,
        'settings': {'horizon_days': horizon, 'min_days': min_days, 'transit_days': transit},
        'rows': rows,
        'totals': {'rescuable_value': round(sum(r['value'] for r in rows), 2),
                   'lines': len(rows),
                   'too_late_value': total(buckets['too_late']),
                   'no_target_value': total(buckets['no_target'])},
    }
