"""
apps/purchasing/shortage.py

Market-shortage detector (نواقص السوق) + revision engine.

Surfaces items highly in demand that we can't keep in stock (no supplier, or a
quota below demand), as CANDIDATES a human confirms into the sticky
catalog.Item.in_shortage flag.

Beyond one-shot detection it tracks change over time via a per-run snapshot, so
the review screen shows only what CHANGED (new / recovering / re-entered) and can
flag a confirmed item as "possibly resolved" when supply looks restored. Dismissed
items (variants / on-request / obsolete …) are held out of the candidate list but
resurface if a strong new signal appears. Manually-added items are watched to see
if the engine's own signals start catching them (they become auto-detectable).

Signal (per stockable item, from the latest demand run + sales history):
  • regular demand   — sold in ≥ MIN_SALE_MONTHS months, ≥ MIN_ANNUAL_QTY / year
  • depletion        — on-hand < COVERAGE_MAX month of *historical* demand
  • suppression      — recent 30-day sales collapsed vs the yearly run-rate
Recovery (a confirmed item looks resolved):
  • coverage back ≥ HEALTHY_COVERAGE months AND suppression ≤ HEALTHY_SUPPRESSION,
    sustained over RECOVERY_RUNS consecutive snapshots.

Read-only w.r.t. the in_shortage flag — only the API's human actions write it.
"""
from dataclasses import dataclass, field

# ── Detection thresholds ─────────────────────────────────────────────────────
MIN_ANNUAL_QTY   = 12
MIN_SALE_MONTHS  = 3
COVERAGE_MAX     = 0.5
TIER1_COVERAGE   = 0.30
TIER1_SUPPRESS   = 0.50
TIER2_COVERAGE   = 0.25

# ── Recovery / trend thresholds ──────────────────────────────────────────────
HEALTHY_COVERAGE    = 1.0     # ≥ 1 month on hand
HEALTHY_SUPPRESSION = 0.25    # selling ~normally again
RECOVERY_RUNS       = 2       # consecutive healthy snapshots → possibly resolved
AUTODETECT_RUNS     = 4       # look-back window for the manual-item trend
AUTODETECT_HITS     = 3       # detected in ≥ this many → "now auto-detectable"

TIER_STOCKOUT = '1-نفاد مؤكد'
TIER_SEVERE   = '2-نقص حاد'
TIER_WATCH    = '3-مراقبة'
TIER_COUNT_KEYS = [TIER_STOCKOUT, TIER_SEVERE, TIER_WATCH]


@dataclass
class ShortageCandidate:
    item_id:      int
    softech_id:   str
    name:         str
    unit_price:   float
    med_type:     str          # general classification label (medicine / cosmetics / …)
    med_type_code: str
    annual_qty:   float
    monthly_hist: float
    stock:        float
    coverage:     float
    qty_30d:      float
    sale_months:  int
    suppression:  float
    tier:         str
    score:        float
    lost_monthly:  float = 0.0   # EGP/month of demand we can't fulfil (business case)
    stockout_days: int   = 0     # consecutive days observed out of stock
    already_flagged: bool = False
    dismissed:       bool = False


def _tier(coverage, suppression):
    if coverage < TIER1_COVERAGE and suppression >= TIER1_SUPPRESS:
        return TIER_STOCKOUT
    if coverage < TIER2_COVERAGE:
        return TIER_SEVERE
    return TIER_WATCH


def _healthy(coverage, suppression):
    return coverage >= HEALTHY_COVERAGE and suppression <= HEALTHY_SUPPRESSION


def _latest_run(run):
    from apps.purchasing.models import DemandCalculationRun
    if run is not None:
        return run
    return (DemandCalculationRun.objects.filter(status='success')
            .order_by('-started_at').first())


def item_signals(run=None):
    """
    Per-item shortage signals for the run: item_id → dict. Covers every stockable
    item that has demand, PLUS any confirmed/dismissed item (so its state is known
    even when its signal is currently quiet). Includes catalog flags.
    """
    from django.db import connection
    from django.db.models import Sum
    from apps.purchasing.models import ItemDemandMetrics
    from apps.catalog.models import Item

    run = _latest_run(run)
    if run is None:
        return {}, None

    stock = {r['item_id']: float(r['s'] or 0)
             for r in ItemDemandMetrics.objects.filter(run=run)
             .values('item_id').annotate(s=Sum('current_stock'))}

    with connection.cursor() as cur:
        cur.execute("""
            SELECT item_id,
                   SUM(CASE WHEN doc_date >= CURRENT_DATE - 30  THEN net_qty ELSE 0 END),
                   SUM(CASE WHEN doc_date >= CURRENT_DATE - 365 THEN net_qty ELSE 0 END),
                   COUNT(DISTINCT date_trunc('month', doc_date))
                         FILTER (WHERE doc_date >= CURRENT_DATE - 365 AND net_qty > 0)
            FROM purchasing_salestransactionline
            WHERE item_id IS NOT NULL AND doccode = '115'
            GROUP BY item_id
        """)
        sales = {r[0]: (float(r[1] or 0), float(r[2] or 0), int(r[3] or 0))
                 for r in cur.fetchall()}

    items = {i.id: i for i in Item.objects.filter(is_stockable=True).only(
        'id', 'softech_id', 'name', 'unit_price', 'pack_price', 'medicine_type',
        'medicine_type_name_ar', 'medicine_type_name',
        'in_shortage', 'shortage_source', 'shortage_dismissed')}

    out = {}
    for item_id, item in items.items():
        q30, q365, months = sales.get(item_id, (0.0, 0.0, 0))
        hist = q365 / 12.0
        st   = stock.get(item_id, 0.0)
        coverage = st / hist if hist > 0 else (0.0 if st == 0 else 999.0)
        suppression = max(0.0, 1.0 - (q30 / hist)) if hist > 0 else 0.0
        is_candidate = (q365 >= MIN_ANNUAL_QTY and months >= MIN_SALE_MONTHS
                        and hist > 0 and coverage < COVERAGE_MAX)
        # keep items that matter to the review: a live signal OR a saved state
        if not (is_candidate or item.in_shortage or item.shortage_dismissed):
            continue
        # Lost monthly REVENUE = demand we can't fulfil (historical run-rate minus
        # what recently sold) × box price. The business case for chasing it.
        price = float(item.pack_price or 0)
        lost_units = max(0.0, hist - q30)
        lost_monthly = round(lost_units * price, 2)
        out[item_id] = {
            'item': item,
            'annual_qty': q365, 'monthly_hist': hist, 'stock': st,
            'coverage': round(coverage, 3), 'qty_30d': q30, 'sale_months': months,
            'suppression': round(suppression, 3), 'price': price,
            'lost_monthly': lost_monthly,
            'is_candidate': is_candidate,
            'tier': _tier(coverage, suppression) if is_candidate else '',
            'score': round(hist * (1 - min(coverage, 1)) * (0.4 + 0.6 * suppression), 2)
                     if is_candidate else 0.0,
            'healthy': _healthy(coverage, suppression),
        }
    return out, run


def stockout_map(max_snaps=30):
    """
    item_id → consecutive DAYS observed out of stock (coverage ≈ 0) across the most
    recent snapshots. A real severity/duration metric; accumulates as the engine runs.
    """
    from apps.purchasing.models import ShortageObservation
    snaps = _recent_snapshots(max_snaps)          # most recent first
    if not snaps:
        return {}
    order = {s.id: i for i, s in enumerate(snaps)}
    sdate = {s.id: s.created_at for s in snaps}
    latest = snaps[0].created_at
    per = {}
    for o in (ShortageObservation.objects
              .filter(snapshot_id__in=list(order)).values('item_id', 'snapshot_id', 'coverage')):
        per.setdefault(o['item_id'], []).append((order[o['snapshot_id']], o['coverage'], sdate[o['snapshot_id']]))
    out = {}
    for iid, obs in per.items():
        obs.sort()                                # 0 = most recent
        start_date, expected = None, 0
        for idx, cov, dt in obs:
            if idx != expected or cov > 0.001:    # streak broken (gap or has stock)
                break
            start_date, expected = dt, expected + 1
        if start_date is not None:
            out[iid] = max(0, (latest - start_date).days)
    return out


def _to_candidate(item_id, s, stockout=None):
    it = s['item']
    return ShortageCandidate(
        item_id=item_id, softech_id=it.softech_id, name=it.name,
        unit_price=float(it.unit_price or 0),
        med_type=(it.medicine_type_name_ar or it.medicine_type_name or it.medicine_type or ''),
        med_type_code=it.medicine_type or '',
        annual_qty=s['annual_qty'], monthly_hist=round(s['monthly_hist'], 2),
        stock=round(s['stock'], 2), coverage=s['coverage'], qty_30d=s['qty_30d'],
        sale_months=s['sale_months'], suppression=s['suppression'],
        tier=s['tier'], score=s['score'],
        lost_monthly=s.get('lost_monthly', 0.0),
        stockout_days=(stockout or {}).get(item_id, 0),
        already_flagged=it.in_shortage, dismissed=it.shortage_dismissed,
    )


def compute_shortage_candidates(run=None):
    """Ranked candidate list (excludes dismissed items)."""
    sig, run = item_signals(run)
    so = stockout_map()
    rows = [_to_candidate(iid, s, so) for iid, s in sig.items()
            if s['is_candidate'] and not s['item'].shortage_dismissed]
    rows.sort(key=lambda c: (c.tier, -c.score))
    return rows


# ── Snapshot persistence (enables the delta view + recovery tracking) ─────────
def ensure_snapshot(run=None):
    """
    Persist a ShortageSnapshot for the run if one doesn't exist yet. Idempotent —
    safe to call on every screen load; only the first call per run writes.
    """
    from apps.purchasing.models import ShortageSnapshot, ShortageObservation
    sig, run = item_signals(run)
    if run is None:
        return None
    snap = ShortageSnapshot.objects.filter(run=run).first()
    if snap is not None:
        return snap

    snap = ShortageSnapshot.objects.create(
        run=run,
        n_candidates=sum(1 for s in sig.values()
                         if s['is_candidate'] and not s['item'].shortage_dismissed),
        n_confirmed=sum(1 for s in sig.values() if s['item'].in_shortage),
    )
    obs = [ShortageObservation(
        snapshot=snap, item_id=iid, tier=s['tier'],
        coverage=s['coverage'], suppression=s['suppression'],
        annual_qty=s['annual_qty'], is_candidate=s['is_candidate'],
        is_confirmed=s['item'].in_shortage, healthy=s['healthy'],
    ) for iid, s in sig.items()]
    ShortageObservation.objects.bulk_create(obs, batch_size=1000)
    return snap


def _recent_snapshots(limit):
    from apps.purchasing.models import ShortageSnapshot
    return list(ShortageSnapshot.objects.order_by('-created_at')[:limit])


def recovery_map():
    """
    item_id → True for confirmed items that have looked healthy across the last
    RECOVERY_RUNS snapshots (→ 'possibly resolved', pending human close).
    """
    from apps.purchasing.models import ShortageObservation
    snaps = _recent_snapshots(RECOVERY_RUNS)
    if len(snaps) < RECOVERY_RUNS:
        return {}
    snap_ids = [s.id for s in snaps]
    healthy_counts = {}
    for o in ShortageObservation.objects.filter(snapshot_id__in=snap_ids, is_confirmed=True) \
            .values('item_id', 'healthy'):
        healthy_counts.setdefault(o['item_id'], []).append(o['healthy'])
    return {iid: True for iid, flags in healthy_counts.items()
            if len(flags) >= RECOVERY_RUNS and all(flags)}


def autodetectable_map():
    """
    item_id → hit-count for MANUAL confirmed items whose engine signal has been
    detecting them (is_candidate) in ≥ AUTODETECT_HITS of the last AUTODETECT_RUNS
    snapshots — i.e. they've become auto-detectable and no longer need to be manual.
    """
    from apps.purchasing.models import ShortageObservation
    snaps = _recent_snapshots(AUTODETECT_RUNS)
    if not snaps:
        return {}
    snap_ids = [s.id for s in snaps]
    hits = {}
    for o in ShortageObservation.objects.filter(snapshot_id__in=snap_ids, is_candidate=True) \
            .values('item_id'):
        hits[o['item_id']] = hits.get(o['item_id'], 0) + 1
    return {iid: n for iid, n in hits.items() if n >= AUTODETECT_HITS}


def operational_branches():
    """Branch ids/codes that actually sell — the set a matching product must cover."""
    from apps.purchasing.models import ItemDemandMetrics
    run = _latest_run(None)
    if run is None:
        return []
    return list(ItemDemandMetrics.objects.filter(run=run)
                .values_list('branch_id', 'branch__code').distinct())


def branch_availability(item_ids):
    """
    For each item id → where it's actually on the shelf across operational branches.
    { item_id: {'ok': bool, 'have': [codes], 'missing': [codes]} }. A matching
    product is only a real substitute if it's stocked in EVERY operational branch.
    """
    from apps.catalog.models import ItemStock
    item_ids = [i for i in item_ids if i]
    if not item_ids:
        return {}
    branches = operational_branches()
    branch_codes = {bid: code for bid, code in branches}
    all_codes = set(branch_codes.values())

    have = {iid: set() for iid in item_ids}
    for s in (ItemStock.objects.filter(item_id__in=item_ids, quantity_on_hand__gt=0)
              .values('item_id', 'branch_id')):
        code = branch_codes.get(s['branch_id'])
        if code:
            have[s['item_id']].add(code)
    out = {}
    for iid in item_ids:
        h = have[iid]
        missing = sorted(all_codes - h)
        out[iid] = {'ok': not missing, 'have': sorted(h), 'missing': missing}
    return out


def compute_deltas(run=None):
    """
    What changed since the previous snapshot:
      new         — a candidate now that wasn't a candidate last run
      recovering  — confirmed items now looking healthy (possibly resolved)
      re_entered  — a DISMISSED item showing a strong (tier 1/2) signal again
    Returns dict of ShortageCandidate lists + counts.
    """
    snap = ensure_snapshot(run)
    sig, run = item_signals(run)
    snaps = _recent_snapshots(2)
    prev = snaps[1] if len(snaps) >= 2 else None

    prev_candidates = set()
    if prev is not None:
        from apps.purchasing.models import ShortageObservation
        prev_candidates = set(ShortageObservation.objects
            .filter(snapshot=prev, is_candidate=True)
            .values_list('item_id', flat=True))

    recovery = recovery_map()
    so = stockout_map()
    new, recovering, re_entered = [], [], []
    for iid, s in sig.items():
        it = s['item']
        cand = _to_candidate(iid, s, so)
        if it.in_shortage and iid in recovery:
            recovering.append(cand)
        elif it.shortage_dismissed and s['is_candidate'] and s['tier'] in (TIER_STOCKOUT, TIER_SEVERE):
            re_entered.append(cand)
        elif s['is_candidate'] and not it.shortage_dismissed and not it.in_shortage \
                and (prev is None or iid not in prev_candidates):
            new.append(cand)

    new.sort(key=lambda c: (c.tier, -c.score))
    recovering.sort(key=lambda c: -c.coverage)
    re_entered.sort(key=lambda c: (c.tier, -c.score))
    return {
        'has_baseline': prev is not None,
        'new': new, 'recovering': recovering, 're_entered': re_entered,
        'counts': {'new': len(new), 'recovering': len(recovering), 're_entered': len(re_entered)},
    }


def notify_shortage_changes():
    """
    Push alerts to the purchasing team for NEW stockout-confirmed shortages and for
    confirmed items that look recovered. Called after each engine run. Dedup'd so the
    same item doesn't spam. Returns the number of notifications sent.
    """
    from apps.notifications.models import Notification
    d = compute_deltas()
    if not d['has_baseline']:
        return 0
    sent = 0
    for c in [x for x in d['new'] if x.tier == TIER_STOCKOUT][:50]:
        loss = f' · خسارة ~{c.lost_monthly:,.0f} ج.م/شهر' if c.lost_monthly else ''
        sent += Notification.send_to_roles(
            roles=['admin', 'purchasing', 'supervisor'],
            notification_type='system',
            title='🚨 نقص سوق جديد (نفاد مؤكد)',
            body=f'{c.softech_id} — {c.name} · طلب {c.annual_qty:.0f}/سنة{loss}',
            dedup_key=f'shortage_new_{c.item_id}',
        )
    for c in d['recovering'][:50]:
        sent += Notification.send_to_roles(
            roles=['admin', 'purchasing', 'supervisor'],
            notification_type='system',
            title='🔄 نقص سوق قد يكون توفّر',
            body=f'{c.softech_id} — {c.name} · عاد المخزون والمبيعات، راجِع الإغلاق',
            dedup_key=f'shortage_recovered_{c.item_id}',
        )
    return sent
