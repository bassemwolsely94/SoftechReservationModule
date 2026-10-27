"""
apps/purchasing/phantom.py — Phantom substitution detector (مبيعات وهمية).

A contract patient sells his prescribed drug back to the pharmacy. SOFTECH books
it as a PURCHASE (doccode 10) from an internal buy-back "supplier" account plus an
immediate CONTRACT-channel SALE (doccode 115). The unit is never sourced from a
real distributor and holds ~0 net stock. Those "sales" are NOT genuine demand, so
the demand sheet must not order (or must heavily reduce) them.

Signal (validated 2026-09-14 against DAIVOBET/EPREX vs CH-ALPHA/CONTROLOC):
    phantom_ratio = buyback_qty / sold_qty   over a rolling window
Flag when phantom_ratio >= THRESHOLD (default 0.50) with volume floors. The
buy-back accounts are self-discovering (personsdata.personname LIKE Contract/
General Supplier). Contract-channel share is stored as CONTEXT only, never a gate
(some true phantoms sell cash/delivery — market-scarce specialty drugs).

Recommended order fraction = 1 − recency-weighted ratio, so an item that returns
to distributor sourcing (e.g. DAIVOBET after its shortage) auto-heals: the recent
ratio falls and ordering restores without manual un-flagging.

READ-ONLY w.r.t. SOFTECH — this module only SELECTs SOFTECH and writes the local
catalog.Item flag. It never changes replenishment math (the engine applies
phantom_order_pct in a separate, gated step).
"""
import logging
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# Tunable via settings; defaults locked with the owner (2026-09-14/15).
THRESHOLD      = float(getattr(settings, 'PHANTOM_FLAG_THRESHOLD', 0.50))   # STRONG: buyback/sold to flag
WATCH_THRESHOLD = float(getattr(settings, 'PHANTOM_WATCH_THRESHOLD', 0.30)) # WATCH: lower ratio, high volume
WATCH_MIN_BUYBACK = float(getattr(settings, 'PHANTOM_WATCH_MIN_BUYBACK', 100))  # abs. phantom units for WATCH
FLAG_MONTHS    = int(getattr(settings, 'PHANTOM_FLAG_WINDOW_MONTHS', 12))   # window for the flag ratio
RECENT_MONTHS  = int(getattr(settings, 'PHANTOM_RECENT_WINDOW_MONTHS', 3))  # recent window for auto-heal
RECENT_WEIGHT  = float(getattr(settings, 'PHANTOM_RECENT_WEIGHT', 0.6))     # blend weight on recent ratio
MIN_SOLD       = float(getattr(settings, 'PHANTOM_MIN_SOLD', 12))           # volume floor (window sold qty)
MIN_BUYBACK    = float(getattr(settings, 'PHANTOM_MIN_BUYBACK', 6))         # volume floor (window buyback qty)
MIN_RECENT_SOLD = 3.0   # need at least this much recent sold qty to trust the recent ratio
# ── Order-qty reduction (DORMANT by default — owner activates per engine run) ──
APPLY_REDUCTION_DEFAULT = bool(getattr(settings, 'PHANTOM_APPLY_REDUCTION', False))
SAFETY_FLOOR_WEEKS = float(getattr(settings, 'PHANTOM_SAFETY_FLOOR_WEEKS', 1.0))  # genuine cushion kept


def _clamp01(x):
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def classify(flag_ratio, sold_flag, buyback_flag):
    """Volume-aware flag → ('' | 'watch' | 'strong').

    STRONG = clearly phantom-dominated (ratio >= THRESHOLD). WATCH = a lower ratio
    but a LARGE absolute buy-back volume (massively-sold items like Controloc /
    CH-Alpha), so their big phantom quantity is still monitored. Both are flagged;
    the tier only conveys severity. Shared by the scanner and the review 'reset'.
    """
    if sold_flag < MIN_SOLD or buyback_flag < MIN_BUYBACK:
        return ''
    if flag_ratio >= THRESHOLD:
        return 'strong'
    if flag_ratio >= WATCH_THRESHOLD and buyback_flag >= WATCH_MIN_BUYBACK:
        return 'watch'
    return ''


def buyback_accounts(conn):
    """Self-discovering set of internal buy-back supplier personcodes.

    The pharmacy books patient buy-backs under a small set of generic accounts
    named 'مورد شركات … - Contract Supplier' / 'مورد عام - General Supplier'
    (codes 3068/4069/4469-4472/5014). The English tag is ASCII-safe to LIKE.
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT RTRIM(personcode) FROM SOFTECHDB9.dbo.personsdata "
        "WHERE personname LIKE '%Contract Supplier%' OR personname LIKE '%General Supplier%'",
        timeout=60,
    )
    return {str(r[0]) for r in cur.fetchall() if r[0] is not None}


def _sales_metrics(conn):
    """item -> (sold_flag, contract_flag, sold_recent) over FLAG_MONTHS / RECENT_MONTHS."""
    sql = f"""SELECT st.itemcode,
        SUM(st.transqty),
        SUM(CASE WHEN RTRIM(sm.ptclassifcode) IN ('10','15') THEN st.transqty ELSE 0 END),
        SUM(CASE WHEN sm.docdate >= DATEADD(month,-{RECENT_MONTHS},GETDATE()) THEN st.transqty ELSE 0 END)
    FROM SOFTECHDB9.dbo.stktransm sm
    JOIN SOFTECHDB9.dbo.stktrans st
        ON st.branchcode=sm.branchcode AND st.doccode=sm.doccode
       AND st.docnumber=sm.docnumber AND st.docdate=sm.docdate
    WHERE sm.doccode='115' AND sm.docdate >= DATEADD(month,-{FLAG_MONTHS},GETDATE())
      AND st.transqty > 0 AND st.itemcode IS NOT NULL AND st.itemcode != ''
    GROUP BY st.itemcode"""
    cur = conn.cursor(); cur.execute(sql, timeout=300)
    return {str(r[0]): (float(r[1] or 0), float(r[2] or 0), float(r[3] or 0)) for r in cur.fetchall()}


def _purchase_metrics(conn, bb):
    """item -> (buyback_flag, buyback_recent) over FLAG_MONTHS / RECENT_MONTHS."""
    if not bb:
        return {}
    bblist = ",".join(f"'{c}'" for c in bb)
    sql = f"""SELECT st.itemcode,
        SUM(CASE WHEN RTRIM(sm.cust_branch_code) IN ({bblist}) THEN st.transqty ELSE 0 END),
        SUM(CASE WHEN RTRIM(sm.cust_branch_code) IN ({bblist})
                  AND sm.docdate >= DATEADD(month,-{RECENT_MONTHS},GETDATE()) THEN st.transqty ELSE 0 END)
    FROM SOFTECHDB9.dbo.stktransm sm
    JOIN SOFTECHDB9.dbo.stktrans st
        ON st.branchcode=sm.branchcode AND st.doccode=sm.doccode
       AND st.docnumber=sm.docnumber AND st.docdate=sm.docdate
    WHERE sm.doccode='10' AND sm.docdate >= DATEADD(month,-{FLAG_MONTHS},GETDATE())
      AND st.transqty > 0 AND st.itemcode IS NOT NULL AND st.itemcode != ''
    GROUP BY st.itemcode"""
    cur = conn.cursor(); cur.execute(sql, timeout=300)
    return {str(r[0]): (float(r[1] or 0), float(r[2] or 0)) for r in cur.fetchall()}


def score_item(sold_flag, contract_flag, sold_recent, buyback_flag, buyback_recent):
    """Pure scoring for one item's window metrics → the fields we persist.

    Returns dict(phantom_ratio, contract_ratio, order_pct, genuine_need, tier,
    is_phantom). order_pct is 1 − recency-weighted ratio (auto-heal); the flag is
    volume-aware (classify → 'strong'/'watch'/''). No DB / SOFTECH access here
    (unit-testable)."""
    flag_ratio = (buyback_flag / sold_flag) if sold_flag > 0 else 0.0
    contract_ratio = (contract_flag / sold_flag) if sold_flag > 0 else 0.0
    recent_ratio = (buyback_recent / sold_recent) if sold_recent >= MIN_RECENT_SOLD else None
    if recent_ratio is None:
        eff = flag_ratio
    else:
        eff = RECENT_WEIGHT * recent_ratio + (1 - RECENT_WEIGHT) * flag_ratio
    order_pct = _clamp01(1.0 - eff)
    genuine_need = max(0.0, sold_flag - buyback_flag)
    tier = classify(flag_ratio, sold_flag, buyback_flag)
    return {
        'phantom_ratio': round(flag_ratio, 4),
        'contract_ratio': round(contract_ratio, 4),
        'order_pct': round(order_pct, 4),
        'genuine_need': round(genuine_need, 3),
        'tier': tier,
        'is_phantom': bool(tier),
    }


def reduced_order_qty(required_qty, order_pct, *, apply, monthly_avg=0.0):
    """Recommended purchase qty for a phantom item.

    DORMANT BY DEFAULT (apply=False → returns required_qty unchanged): the module
    only flags/monitors and SHOWS the order-% (per owner). When reduction is
    activated at engine-run time (apply=True), scale the required qty by order_pct
    (the genuine, non-phantom fraction), but never below a small genuine cushion
    (SAFETY_FLOOR_WEEKS × weekly genuine demand) so a 100%-phantom essential still
    keeps a buffer. Pure + unit-testable."""
    if not apply or required_qty <= 0 or (order_pct if order_pct is not None else 1.0) >= 1.0:
        return required_qty
    reduced = required_qty * _clamp01(order_pct)
    floor = min(required_qty, max(0.0, (monthly_avg / 4.0) * SAFETY_FLOOR_WEEKS))
    return max(reduced, floor)


def scan(persist=True):
    """Score every item with sales/purchase activity in the window and (optionally)
    update catalog.Item phantom fields. Human overrides are respected:
      override='excluded'  → never flag; override='confirmed' → always flag.
    Returns a summary dict. SELECT-only against SOFTECH."""
    from apps.catalog.models import Item
    from config.sybase import get_sybase_connection
    conn = get_sybase_connection()
    try:
        bb = buyback_accounts(conn)
        sales = _sales_metrics(conn)
        purch = _purchase_metrics(conn, bb)
    finally:
        try: conn.close()
        except Exception: pass

    codes = set(sales) | set(purch)
    scored = {}
    flagged = 0
    for code in codes:
        s_flag, c_flag, s_recent = sales.get(code, (0.0, 0.0, 0.0))
        b_flag, b_recent = purch.get(code, (0.0, 0.0))
        r = score_item(s_flag, c_flag, s_recent, b_flag, b_recent)
        r['buyback_qty'] = b_flag
        r['sold_qty'] = s_flag
        scored[code] = r
        if r['is_phantom']:
            flagged += 1

    updated = 0
    if persist and scored:
        now = timezone.now()
        # Update in chunks by softech_id (itemcode).
        items = Item.objects.filter(softech_id__in=list(scored.keys())).only(
            'id', 'softech_id', 'phantom_override', 'is_stockable')
        bulk = []
        for it in items:
            r = scored.get((it.softech_id or '').strip())
            if r is None:
                continue
            auto = r['is_phantom'] and it.is_stockable
            if it.phantom_override == 'excluded':
                effective = False
            elif it.phantom_override == 'confirmed':
                effective = True
            else:
                effective = auto
            it.is_phantom_substitution = effective
            it.phantom_ratio = r['phantom_ratio']
            it.phantom_contract_ratio = r['contract_ratio']
            it.phantom_order_pct = r['order_pct']
            it.phantom_buyback_qty = r['buyback_qty']
            it.phantom_sold_qty = r['sold_qty']
            it.phantom_genuine_need = r['genuine_need']
            it.phantom_detected_at = now
            if not it.phantom_source:
                it.phantom_source = 'auto'
            bulk.append(it)
        if bulk:
            Item.objects.bulk_update(bulk, [
                'is_phantom_substitution', 'phantom_ratio', 'phantom_contract_ratio',
                'phantom_order_pct', 'phantom_buyback_qty', 'phantom_sold_qty',
                'phantom_genuine_need', 'phantom_detected_at', 'phantom_source',
            ], batch_size=500)
            updated = len(bulk)

    summary = {
        'buyback_accounts': len(bb),
        'scored_items': len(scored),
        'flagged': flagged,
        'persisted': updated,
        'threshold': THRESHOLD,
        'flag_window_months': FLAG_MONTHS,
    }
    logger.info('[PHANTOM] scan %s', summary)
    return summary
