"""
apps/purchasing/distribution.py — L3 «توزيعة» proactive distribution engine (read-only).

Beyond demand-driven replenishment (L2), this finds stock that should be spread so it
gets a chance to sell instead of sitting dormant/متكدس — especially NEW / no-rate items
that never get pulled because they have no sales rate. Four categories (owner-chosen):

  • hq_dormant    — HQ (br100) holds stock the branches aren't pulling (barely moves)
  • over_piled    — a branch holds stock ABOVE its SOFTECH max-stock ceiling (the
                    maxnowqty its purchase screen warns above) → move the excess to
                    branches that sell the item and have room under their own ceiling
  • new_no_rate   — item has stock but ZERO network sales (new/forgotten) → seed for trial
  • never_stocked — item sells at some branches but is absent at others → introduce it

Pure analysis over the latest engine run's ItemDemandMetrics / ItemDemandAggregated
(current_stock + monthly_avg per item×branch). Suggestions feed the L2 ISR writer
(HQ→branch, or surplus-branch→HQ→branch) — this module NEVER writes to SOFTECH.
"""
import logging
from collections import defaultdict

from django.utils import timezone

logger = logging.getLogger('elrezeiky.purchasing')

HQ_CODE          = '100'
DORMANT_AVG_MAX  = 0.15    # network monthly_avg ≤ this ⇒ effectively dormant
# over_piled uses the SOFTECH ceilings (owner, 2026-09-28) instead of the old
# "stock > 3 × engine need" rule, so توزيعة agrees with the purchase-screen warning and
# the overstock report (measure_overstock).
CEILING_TOL      = 0.05    # 1dp tolerance: stock must exceed the ceiling by more than this
MIN_MOVE_PACKS   = 1       # never propose moving less than one whole pack
CEILING_CACHE_S  = 600     # live ceilings cached 10 min (5 branch-server reads per preview)
ESTABLISHED_FRAC = 0.8     # sells at ≥ this fraction of operational branches (with a real
                           #   rate) ⇒ ESTABLISHED — no seeding / introducing / HQ-push by توزيعة
                           #   (that is for NEW/immature items); only over_piled moves (excess
                           #   above a branch ceiling → branches that sell it with room) apply.
AGE_NEW_DAYS     = 540     # first-stocked within this many days ⇒ NEW code (age signal).
                           #   Combined with breadth: skip only OLD + broad-selling (truly established).


def _item_ages(codes):
    """{itemcode: first-stocked date} via SOFTECH stkbal MIN(opendate) — the item-age
    signal (an old code has a 2016-19 opendate; a new one 2024+). Excludes the
    1900-01-01 placeholder rows. Best-effort: {} if SOFTECH is unreachable."""
    from config.sybase import get_sybase_connection
    out = {}
    codes = [str(c).strip() for c in codes if str(c).strip()]
    if not codes:
        return out
    try:
        conn = get_sybase_connection()
        cur = conn.cursor()
        for i in range(0, len(codes), 500):
            chunk = codes[i:i + 500]
            ph = ','.join("'" + c.replace("'", "''") + "'" for c in chunk)
            cur.execute(f"SELECT itemcode, min(opendate) FROM SOFTECHDB9.dbo.stkbal "
                        f"WHERE opendate > '2005-01-01' AND itemcode IN ({ph}) GROUP BY itemcode")
            for r in cur.fetchall():
                if r[1] is not None:
                    out[str(r[0]).strip()] = r[1]
        conn.close()
    except Exception as exc:
        logger.warning('[distribution] item-age read failed (%s) — breadth-only', exc)
    return out
def _branch_ceilings(branch_codes):
    """{branchcode: {itemcode: (stock, ceiling)}} read LIVE from each branch's own server
    for rows that have a ceiling (maxnowqty > 0 — items that sell there). The ceiling is
    the max stock SOFTECH's purchase screen warns above (rate × coverage, ≥ 1 pack).
    HQ (100) is never read — its stock is warehouse stock, not متكدس. An unreachable
    branch is left out (it can't be judged over-piled or receive). Cached briefly."""
    from django.core.cache import cache
    from apps.branches.models import Branch
    from apps.purchasing.rate_writer import resolve_store, _read_conn_for_target
    out = {}
    for b in Branch.objects.filter(softech_branch_id__in=[c for c in branch_codes if c != HQ_CODE]):
        bc = b.softech_branch_id
        key = f'distribution_ceilings_{bc}'
        data = cache.get(key)
        if data is None:
            try:
                conn = _read_conn_for_target(b, 'node')
                cur = conn.cursor()
                cur.execute("SELECT itemcode, nowqty, maxnowqty FROM stkbal "
                            "WHERE branchcode=? AND storecode=? AND maxnowqty > 0",
                            [bc, resolve_store(b)])
                data = {str(r[0]).strip(): (float(r[1] or 0), float(r[2] or 0))
                        for r in cur.fetchall()}
                cur.close()
                conn.close()
                cache.set(key, data, CEILING_CACHE_S)
            except Exception as exc:
                logger.warning('[distribution] ceilings for branch %s unavailable: %s', bc, exc)
                continue
        out[bc] = data
    return out


def _pick_surplus(code, ceilings, op_codes):
    """(branch, excess) — the retail branch holding the most stock ABOVE its ceiling,
    or (None, 0.0). HQ never counts as over-piled."""
    best, best_ex = None, 0.0
    for bc in op_codes:
        if bc == HQ_CODE:
            continue
        c = ceilings.get(bc, {}).get(code)
        if not c:
            continue
        stock, cap = c
        ex = stock - cap
        if ex > CEILING_TOL and ex > best_ex:
            best, best_ex = bc, ex
    return best, best_ex


def _room_targets(code, ceilings, op_codes, source):
    """{branch: room} — branches that sell the item (have a ceiling) and sit at least one
    pack below it. Excludes the source and HQ."""
    room = {}
    for bc in op_codes:
        if bc in (source, HQ_CODE):
            continue
        c = ceilings.get(bc, {}).get(code)
        if not c:
            continue
        stock, cap = c
        if cap - stock >= MIN_MOVE_PACKS:
            room[bc] = cap - stock
    return room


def _allocate(excess, targets, room):
    """[(branch, whole packs)] — give each target up to its room, in order, never more
    than the excess in total; stops when less than one pack is left."""
    alloc, left = [], float(excess)
    for b in targets:
        q = int(min(room.get(b, 0.0), left))
        if q < MIN_MOVE_PACKS:
            continue
        alloc.append((b, q))
        left -= q
        if left < MIN_MOVE_PACKS:
            break
    return alloc


SEED_QTY         = 2       # default packs to seed a branch (pack-aware, see _seed_qty)
HIGH_PRICE       = 300.0   # pack_price ≥ this ⇒ seed fewer (1) — expensive items
MAX_TARGETS      = 4       # spread a seed to at most this many branches at once
ROTATE_DAYS      = 45      # trial window; a branch seeded within this is "in trial"


def _operational_branches():
    from apps.branches.models import Branch
    return {b.softech_branch_id: b.name for b in
            Branch.objects.filter(is_active=True, is_operational=True)
            .exclude(db_host='').exclude(db_host__isnull=True)}


def _seed_qty(pack_price) -> int:
    """Pack-aware seed size: 1 pack for expensive items, else SEED_QTY."""
    return 1 if float(pack_price or 0) >= HIGH_PRICE else SEED_QTY


def _seeded_history():
    """{(itemcode, dest_branchcode): latest seeded date} from prior توزيعة ISRs
    (kind hq_to_branch / branch_to_hq, pushed or approved). Powers rotation: don't
    re-seed a branch still in its trial window, and skip branches already tried."""
    from datetime import date
    from apps.purchasing.models import IsrPush
    hist = {}
    qs = (IsrPush.objects.filter(kind__in=[IsrPush.KIND_HQ_TO_BRANCH, IsrPush.KIND_BRANCH_TO_HQ],
                                 status__in=[IsrPush.STATUS_APPROVED, IsrPush.STATUS_PUSHED])
          .only('dest_branchcode', 'lines_snapshot', 'created_at', 'pushed_at'))
    for p in qs.iterator():
        dest = str(p.dest_branchcode or '').strip()
        if not dest:
            continue
        when = (p.pushed_at or p.created_at)
        d = when.date() if hasattr(when, 'date') else when
        for ln in (p.lines_snapshot or []):
            code = str(ln.get('itemcode') or '').strip()
            if code:
                key = (code, dest)
                if key not in hist or (d and hist[key] and d > hist[key]):
                    hist[key] = d
    return hist


def analyze(run=None, *, categories=None, limit=None, use_age=True, ceilings=None):
    """Return a list of distribution suggestions (read-only). Each carries both
    signals — n_selling_ops (breadth) + age_days / is_new_age (SOFTECH stkbal opendate)
    — so established (old + broad) items are protected and new codes are prioritized.
    use_age=False skips the SOFTECH age read (breadth-only; used in tests / offline).
    ceilings = {branch: {itemcode: (stock, ceiling)}}; None → read live from the branch
    servers (only when over_piled is requested)."""
    from apps.purchasing.models import (DemandCalculationRun, ItemDemandMetrics,
                                        ItemDemandAggregated)
    run = run or (DemandCalculationRun.objects.filter(status='success')
                  .order_by('-finished_at', '-id').first())
    if run is None:
        raise ValueError('لا يوجد تشغيل ناجح لمحرك الطلب.')

    want = set(categories) if categories else {'hq_dormant', 'over_piled', 'new_no_rate', 'never_stocked'}
    ops = _operational_branches()          # softech_branch_id -> name
    op_codes = set(ops)

    # items that have stock somewhere (only these can be distributed)
    agg = {a.item_id: a for a in ItemDemandAggregated.objects
           .filter(run=run, total_current_stock__gt=0)
           .select_related('item')
           .only('item_id', 'total_current_stock', 'total_monthly_avg',
                 'item__softech_id', 'item__name', 'item__pack_price')}
    if not agg:
        return []

    ages = _item_ages([a.item.softech_id for a in agg.values()]) if use_age else {}
    if ceilings is None:
        ceilings = _branch_ceilings(op_codes) if 'over_piled' in want else {}

    # per-branch stock/avg/safety for those items
    per_item = defaultdict(dict)   # item_id -> {branchcode: (stock, avg, safety)}
    for m in (ItemDemandMetrics.objects.filter(run=run, item_id__in=list(agg.keys()))
              .select_related('branch')
              .only('item_id', 'current_stock', 'monthly_avg', 'safety_stock',
                    'branch__softech_branch_id')).iterator():
        bc = m.branch.softech_branch_id if m.branch_id else None
        if bc:
            per_item[m.item_id][bc] = (float(m.current_stock or 0),
                                       float(m.monthly_avg or 0), float(m.safety_stock or 0))

    seeded = _seeded_history()             # (itemcode, dest) -> last seeded date
    today = timezone.localdate()
    established_min = max(2, round(ESTABLISHED_FRAC * len(op_codes)))  # e.g. 5 ops → 4

    out = []
    for item_id, a in agg.items():
        code = str(a.item.softech_id or '').strip()
        name = a.item.name or ''
        net_stock = float(a.total_current_stock or 0)
        net_avg = float(a.total_monthly_avg or 0)
        pack_price = float(a.item.pack_price or 0)
        bmap = per_item.get(item_id, {})
        with_stock = {bc: v for bc, v in bmap.items() if v[0] > 0}
        selling    = {bc for bc, v in bmap.items() if v[1] > 0}
        absent_ops = [bc for bc in op_codes if bmap.get(bc, (0, 0, 0))[0] <= 0]
        if not with_stock:
            continue

        # ── ESTABLISHED guard (BOTH signals): skip only OLD + broadly-selling items
        #    with a real rate — those belong to demand replenishment (L0/L1/L2). A NEW
        #    code (young opendate) is NEVER skipped (even if it spread fast); a narrow
        #    seller is a candidate. توزيعة = new/immature items needing allocation. ────
        n_selling_ops = len(selling & op_codes)
        od = ages.get(code)
        od = od.date() if hasattr(od, 'date') else od
        age_days = (today - od).days if (od and today) else None
        is_new_age = age_days is not None and age_days <= AGE_NEW_DAYS
        broad_established = n_selling_ops >= established_min and net_avg > DORMANT_AVG_MAX
        established = broad_established and not is_new_age

        # ── SOURCE: the retail branch with the most stock ABOVE its SOFTECH ceiling
        #    (HQ is a warehouse — its stock isn't متكدس) > HQ > most-stock ──────────
        surplus, best_excess = _pick_surplus(code, ceilings, op_codes)
        # Owner decision (2026-10-02, option B): an ESTABLISHED item (old code, sells
        # broadly) is never seeded / introduced / pushed from HQ by توزيعة — it follows
        # its sales rates — BUT when it is piled up above a branch ceiling, the excess
        # may move to branches that sell it and have room under their own ceiling.
        if established and not surplus:
            continue
        source = surplus or (HQ_CODE if with_stock.get(HQ_CODE) else
                             max(with_stock, key=lambda b: with_stock[b][0]))
        avail = best_excess if surplus else with_stock[source][0]

        # ── CATEGORY (one per item — dedup over_piled∩never_stocked) ─────────────
        if net_avg <= 0.0001:
            cat, reason = 'new_no_rate', 'صنف بلا معدل بيع — توزيع تجريبي'
        elif source == HQ_CODE and net_avg <= DORMANT_AVG_MAX:
            cat, reason = 'hq_dormant', 'راكد بالمخزن الرئيسي — دفعه للفروع'
        elif surplus:
            s_stock, s_cap = ceilings[surplus][code]
            cat, reason = ('over_piled',
                           f'فوق الحد الأقصى بفرع {surplus} (رصيد {s_stock:.1f} / الحد {s_cap:.1f})')
        elif selling:
            cat, reason = 'never_stocked', 'يُباع بفروع وغائب عن أخرى — إدخاله'
        else:
            continue
        if cat not in want:
            continue

        # ── TARGETS with ROTATION ────────────────────────────────────────────────
        room = {}
        if cat == 'over_piled':                  # sells there + room under ITS ceiling
            room = _room_targets(code, ceilings, op_codes, source)
            cands = sorted(room, key=lambda b: -room[b])
        else:                                    # seeding: branches that lack the item
            cands = [b for b in absent_ops if b != source and b not in selling]
        tgts = []
        for b in cands:
            sd = seeded.get((code, b))
            if sd is not None:
                age = (today - sd).days if today and sd else 999
                if age < ROTATE_DAYS:
                    continue                     # still in trial window — don't re-seed
                if b not in selling:
                    continue                     # tried before & still not selling → rotate away
            tgts.append(b)
        tgts = tgts[:MAX_TARGETS]
        if not tgts:
            continue

        # ── QUANTITY ─────────────────────────────────────────────────────────────
        if cat == 'over_piled':
            # move the real excess: each target up to its room, never more than excess
            alloc = _allocate(best_excess, tgts, room)
            if not alloc:
                continue
            tgts = [b for b, _ in alloc]
            per_qty = dict(alloc)
            qty_each = max(per_qty.values())
        else:
            # seeding: PACK-AWARE trial qty, capped by source availability
            qty_each = _seed_qty(pack_price)
            if avail > 0:
                qty_each = min(qty_each, max(1, int(avail) // len(tgts)))
                if int(avail) < len(tgts):       # not enough to seed 1 each → trim
                    tgts, qty_each = tgts[:max(1, int(avail))], 1
            per_qty = {b: qty_each for b in tgts}
        # signals that qualified this item (for the owner to compare age vs breadth)
        signals = []
        if established:
            signals.append('established')     # only reachable via over_piled (option B)
        if is_new_age:
            signals.append('new_code')
        if net_avg <= DORMANT_AVG_MAX:
            signals.append('no/low_rate')
        if n_selling_ops < established_min:
            signals.append('narrow')
        out.append(_sug(cat, code, name, source, tgts, qty_each, ops, net_stock, net_avg, reason,
                        n_selling_ops=n_selling_ops, n_ops=len(op_codes),
                        age_days=age_days, is_new_age=is_new_age, signals=signals,
                        per_qty=per_qty))
        if limit and len(out) >= limit:
            break
    return out


def _sug(category, code, name, src, tgts, qty_each, ops, net_stock, net_avg, reason,
         *, n_selling_ops=0, n_ops=0, age_days=None, is_new_age=False, signals=None,
         per_qty=None):
    per_qty = per_qty or {t: int(qty_each) for t in tgts}
    return {
        'category': category, 'itemcode': code, 'item_name': name,
        'from_branch': src, 'from_name': ops.get(src, src),
        'to_branches': [{'code': t, 'name': ops.get(t, t), 'qty': int(per_qty.get(t, qty_each))}
                        for t in tgts],
        'qty_each': int(qty_each), 'total_qty': sum(int(per_qty.get(t, qty_each)) for t in tgts),
        'reason': reason, 'network_stock': round(net_stock, 1), 'network_avg': round(net_avg, 2),
        'sells_at': n_selling_ops, 'of_branches': n_ops,
        'age_days': age_days, 'is_new_code': bool(is_new_age),
        'signals': signals or [],
    }


def summary(run=None):
    """Counts per category (for a dashboard tile)."""
    sugs = analyze(run=run)
    by_cat = defaultdict(lambda: {'count': 0, 'qty': 0})
    for s in sugs:
        by_cat[s['category']]['count'] += 1
        by_cat[s['category']]['qty'] += s['total_qty']
    return {'total': len(sugs), 'by_category': dict(by_cat)}
