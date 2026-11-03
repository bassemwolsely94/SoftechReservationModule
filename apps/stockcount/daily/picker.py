"""
apps/stockcount/daily/picker.py — which items each salesperson counts today.

Deterministic and explainable. Every eligible item at the branch gets a risk weight from data we
already mirror, each with a plain reason; then a weighted random draw (seeded by branch + date, so a
re-run gives the same lists) is dealt out so nobody at the branch shares an item that day.

Eligible: active, stockable items with a non-zero balance in the branch's operational stores
(`ItemStock` mirror; quarantine stores 102/103/105 excluded; a NEGATIVE balance is eligible and
high risk). Items counted clean within `rotation_days` are skipped unless they carry a flag.

Signals (each 0..1) × editable weights (DailyCountSettings):
  value    on-hand × cost, percentile in the branch              «قيمة عالية»
  rate     sales rate (ItemStock.monthly_qty), percentile         «سريع الحركة»
  adjust   SOFTECH count adjustments 50/150 in the window         «تسوية حديثة»
  finding  open stock-audit finding on the item                   «ملاحظة تدقيق مفتوحة»
  loss     past daily-count differences, or a negative balance    «فروق سابقة» / «رصيد سالب»
  expiry   a batch expiring within `expiry_days`                  «قرب انتهاء» (asks the shelf expiry)
  never    never counted, or long since the last count            «لم يُجرد من قبل» / «لم يُجرد منذ N يوم»
weight = 0.1 + Σ wᵢ·sᵢ   (the 0.1 floor keeps every eligible item drawable).
"""
from __future__ import annotations

import datetime as dt
import random
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

QUARANTINE_STORES = ('102', '103', '105')
HIGH_PERCENTILE = 0.8          # value / rate reason threshold
LOSS_LOOKBACK_DAYS = 90
STALE_DAYS = 180               # 'never' signal saturates at this many days since the last count


@dataclass
class Candidate:
    item_code: str
    item_name: str
    weight: float
    reasons: list = field(default_factory=list)
    ask_expiry: bool = False


def _percentiles(values: dict) -> dict:
    """{key: v} → {key: rank in 0..1} (ties share the lower rank); empty / single → 0."""
    if len(values) < 2:
        return {k: 0.0 for k in values}
    ordered = sorted(values.items(), key=lambda kv: kv[1])
    n = len(ordered) - 1
    out, prev_v, prev_r = {}, None, 0.0
    for i, (k, v) in enumerate(ordered):
        r = prev_r if v == prev_v else i / n
        out[k], prev_v, prev_r = r, v, r
    return out


def _last_counts(branch_code: str, today: dt.date) -> tuple[dict, dict]:
    """(last count date per item, number of non-zero differences in LOSS_LOOKBACK_DAYS per item)
    from daily-count attempts and the classic count sessions of this branch."""
    from apps.stockcount.models import DailyCountAttempt, StockCountSnapshot
    last, losses = {}, defaultdict(int)
    since = today - dt.timedelta(days=LOSS_LOOKBACK_DAYS)
    for code, created, diff in (DailyCountAttempt.objects
                                .filter(pick__session__branch_code=branch_code)
                                .values_list('pick__item_code', 'created_at', 'difference')):
        d = created.date()
        if code not in last or d > last[code]:
            last[code] = d
        if diff and d >= since:
            losses[code] += 1
    for code, when, diff in (StockCountSnapshot.objects
                             .filter(session__branch_code=branch_code, counted_qty__isnull=False)
                             .exclude(session__mode='daily')
                             .values_list('item_code', 'session__variance_at', 'difference')):
        if not when:
            continue
        d = when.date()
        if code not in last or d > last[code]:
            last[code] = d
        if diff and d >= since:
            losses[code] += 1
    return last, losses


def candidates(branch, today: dt.date, settings=None) -> list[Candidate]:
    from apps.batches.models import StockExpiryBalance
    from apps.catalog.models import ItemStock
    from apps.stock_audit.models import StockAuditFinding, StockLedgerLine
    from apps.stockcount.models import DailyCountSettings

    s = settings or DailyCountSettings.get()
    code = branch.softech_branch_id

    on_hand, rate, names, cost = defaultdict(Decimal), defaultdict(Decimal), {}, {}
    rows = (ItemStock.objects.filter(branch=branch, item__is_active=True)
            .exclude(softech_store_code__in=QUARANTINE_STORES)
            .exclude(item__is_stockable=False)
            .values_list('item__softech_id', 'item__name', 'item__cost_price',
                         'quantity_on_hand', 'monthly_qty'))
    for ic, name, cp, qty, mq in rows:
        on_hand[ic] += qty or 0
        rate[ic] += mq or 0
        names[ic], cost[ic] = name, cp or Decimal('0')
    pool = [ic for ic, q in on_hand.items() if q != 0]
    if not pool:
        return []

    p_value = _percentiles({ic: float(abs(on_hand[ic]) * cost[ic]) for ic in pool})
    p_rate = _percentiles({ic: float(rate[ic]) for ic in pool})

    adj_since = today - dt.timedelta(days=s.adjust_window_days)
    adjustments = defaultdict(int)
    for ic in (StockLedgerLine.objects.filter(branchcode=code, doccode__in=('50', '150'),
                                              docdate__gte=adj_since, itemcode__in=pool)
               .values_list('itemcode', flat=True)):
        adjustments[ic] += 1
    findings = set(StockAuditFinding.objects.filter(branchcode=code, status=StockAuditFinding.ST_OPEN,
                                                    itemcode__in=pool).values_list('itemcode', flat=True))
    expiring = set(StockExpiryBalance.objects.filter(
        branch_code=code, item_code__in=pool, qty__gt=0, is_quarantine=False,
        expiry_date__lte=today + dt.timedelta(days=s.expiry_days)).values_list('item_code', flat=True))
    last, losses = _last_counts(code, today)

    w = {k: float(getattr(s, f'w_{k}')) for k in ('value', 'rate', 'adjust', 'finding', 'loss', 'expiry', 'never')}
    out = []
    for ic in pool:
        reasons = []
        sig = {'value': p_value[ic], 'rate': p_rate[ic]}
        if sig['value'] >= HIGH_PERCENTILE:
            reasons.append('قيمة عالية')
        if sig['rate'] >= HIGH_PERCENTILE and rate[ic] > 0:
            reasons.append('سريع الحركة')
        sig['adjust'] = min(1.0, adjustments[ic] / 2)
        if adjustments[ic]:
            reasons.append('تسوية حديثة')
        sig['finding'] = 1.0 if ic in findings else 0.0
        if ic in findings:
            reasons.append('ملاحظة تدقيق مفتوحة')
        negative = on_hand[ic] < 0
        sig['loss'] = 1.0 if negative else min(1.0, losses[ic] / 2)
        if losses[ic]:
            reasons.append('فروق سابقة')
        if negative:
            reasons.append('رصيد سالب')
        sig['expiry'] = 1.0 if ic in expiring else 0.0
        if ic in expiring:
            reasons.append('قرب انتهاء')
        seen = last.get(ic)
        if seen is None:
            sig['never'] = 1.0
            reasons.append('لم يُجرد من قبل')
        else:
            days = (today - seen).days
            flagged = bool(losses[ic] or negative or ic in findings or adjustments[ic])
            if days < s.rotation_days and not flagged:
                continue                                   # counted clean recently — rotate out
            sig['never'] = min(1.0, days / STALE_DAYS)
            if days >= 90:
                reasons.append(f'لم يُجرد منذ {days} يوم')
        weight = 0.1 + sum(w[k] * sig[k] for k in w)
        out.append(Candidate(item_code=ic, item_name=names[ic], weight=round(weight, 4),
                             reasons=reasons, ask_expiry=ic in expiring))
    return out


def draw(cands: list[Candidate], people: list, per_person: int, seed: str) -> dict:
    """Weighted sample without replacement (Efraimidis–Spirakis: key = u^(1/w), take the largest),
    dealt round-robin from the highest key down so every person gets a mix of the riskiest items.
    Fewer candidates than needed → some people get fewer; an item is never given twice."""
    out = {p: [] for p in people}
    if not people or per_person <= 0 or not cands:
        return out
    rng = random.Random(seed)
    keyed = sorted(((rng.random() ** (1.0 / max(c.weight, 1e-6)), c.item_code, c) for c in cands),
                   key=lambda t: (-t[0], t[1]))
    chosen = [c for _, _, c in keyed[:per_person * len(people)]]
    for i, c in enumerate(chosen):
        out[people[i % len(people)]].append(c)
    return out
