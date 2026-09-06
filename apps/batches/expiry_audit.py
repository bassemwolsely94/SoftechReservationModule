"""
apps/batches/expiry_audit.py

Purchase-Expiry Physical Audit engine.

Two responsibilities:
  1. run_backfill()      — mirror doccode-10 purchase lines that carry an entered
                           expiry, from "main" suppliers, into PurchaseExpiryEntry
                           (month-chunked, idempotent, re-runnable).
  2. audit_candidates()  — the report: distinct items that (a) have such a
                           purchase entry inside a chosen period AND (b) are
                           on-hand right now → a physical re-check worklist.

"Main" suppliers are resolved from the EXISTING procurement supplier taxonomy
(SupplierSegmentation) — categories OFFICIAL_DISTRIBUTOR + MANUFACTURER by
default. Re-running the backfill after re-classifying more suppliers pulls the
newly-included suppliers' history in (unique key → only missing rows inserted).

SOFTECH is read-only here; the only writes are to the PostgreSQL mirror.
"""
import datetime as _dt
import logging
from decimal import Decimal, InvalidOperation

logger = logging.getLogger('elrezeiky.batches')

# Default "main / trusted-expiry" supplier categories (procurement taxonomy).
MAIN_SUPPLIER_CATEGORIES = ('OFFICIAL_DISTRIBUTOR', 'MANUFACTURER')

# Doccodes that ADD stock to a branch (an "arrival"), used for the stock-age /
# "how long has it sat here" signal: purchase, transfer-in, sales return, surplus.
ARRIVAL_DOCCODES = ('10', '25', '30', '50')

# Guard against SOFTECH sentinel / garbage expiry dates.
_MIN_EXPIRY_YEAR = 2000
_MAX_EXPIRY_YEAR = 2100

# C1/C2: a batch is "short-dated" if its shelf life at receipt is below this.
SHORT_DATED_MONTHS  = 6
# C1: only alert on deliveries received within this recent window.
RECENT_RECEIPT_DAYS = 45

# A5.1 — near-expiry markdown RECOMMENDATION (recommend-only; deterministic policy
# ladder, NOT a demand forecast). A full admin-managed MarkdownPolicy model lands
# with A5.2 (the approval-gated writeback); these defaults drive the suggestion.
MARKDOWN_MIN_MARGIN_PCT = 5.0     # never recommend below cost + this margin
MARKDOWN_MAX_PCT        = 40.0    # hard cap on any recommended discount
# (days-to-expiry upper bound, discount %) — first band that fits wins.
MARKDOWN_LADDER = [(30, 25.0), (60, 15.0), (90, 10.0), (180, 5.0)]


def _markdown_reco(unit_cost, pack_price, days_to_expiry):
    """
    Deterministic near-expiry markdown suggestion. Picks a discount from the
    policy ladder by days-to-expiry, then CLAMPS it so the net price never drops
    below cost × (1 + MARKDOWN_MIN_MARGIN_PCT) — i.e. we never recommend selling
    at a loss. Recommend-only; no price is changed here.
    Returns {markdown_discount_pct, markdown_net_price, markdown_margin_pct} (all
    None when a markdown doesn't apply / can't stay above the margin floor).
    """
    blank = {'markdown_discount_pct': None, 'markdown_net_price': None,
             'markdown_margin_pct': None}
    if not pack_price or pack_price <= 0 or days_to_expiry is None or days_to_expiry <= 0:
        return blank                       # expired/no price → not a markdown case
    base = 0.0
    for bound, disc in MARKDOWN_LADDER:
        if days_to_expiry <= bound:
            base = disc
            break
    if base <= 0:
        return blank                       # expiry too far out — no markdown yet
    cost = unit_cost or 0
    if cost > 0:
        floor_price = cost * (1 + MARKDOWN_MIN_MARGIN_PCT / 100.0)
        max_allowed = (1 - floor_price / pack_price) * 100.0 if pack_price > floor_price else 0.0
    else:
        max_allowed = MARKDOWN_MAX_PCT     # unknown cost → cap only
    disc = min(base, max_allowed, MARKDOWN_MAX_PCT)
    if disc <= 0.5:
        return blank                       # can't discount without breaching the floor
    disc = round(disc, 1)
    net = round(pack_price * (1 - disc / 100.0), 2)
    margin = round((net - cost) / net * 100.0, 1) if net > 0 else None
    return {'markdown_discount_pct': disc, 'markdown_net_price': net,
            'markdown_margin_pct': margin}

# Sybase IN-list cap and PG bulk-insert batch size.
_SUPPLIER_CHUNK = 400
_BULK_BATCH     = 1000
# Heavy multi-year scan: override the default 30s interactive query timeout.
_QUERY_TIMEOUT  = 300


# ── Small helpers ─────────────────────────────────────────────────────────────

def _to_date(val):
    if val is None:
        return None
    if isinstance(val, _dt.datetime):
        return val.date()
    if isinstance(val, _dt.date):
        return val
    try:
        return _dt.datetime.fromisoformat(str(val)[:10]).date()
    except Exception:
        return None


def _to_dec(val, default=Decimal('0')):
    if val is None:
        return default
    try:
        return Decimal(str(val)).quantize(Decimal('0.001'))
    except (InvalidOperation, ValueError):
        return default


def _str(val, default=''):
    return default if val is None else str(val).strip()


def _valid_expiry(d):
    return bool(d) and _MIN_EXPIRY_YEAR <= d.year <= _MAX_EXPIRY_YEAR


def _clean_docnumber(raw):
    """jConnect returns docnumber as float-ish '64550.0' — strip the '.0'."""
    s = _str(raw)
    return s[:-2] if s.endswith('.0') else s


def _month_chunks(date_from, date_to):
    """
    Yield (start_iso, end_iso) monthly [inclusive, exclusive) windows covering
    [date_from, date_to]. Bounds memory and keeps each Sybase scan short.
    """
    y, m = date_from.year, date_from.month
    while (y, m) <= (date_to.year, date_to.month):
        start = _dt.date(y, m, 1)
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        end = _dt.date(ny, nm, 1)
        # Clamp to the requested window edges.
        chunk_start = max(start, date_from)
        chunk_end   = min(end, date_to + _dt.timedelta(days=1))
        if chunk_start < chunk_end:
            yield chunk_start.isoformat(), chunk_end.isoformat()
        y, m = ny, nm


def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


# ── Main-supplier resolution (from procurement taxonomy) ─────────────────────

def resolve_main_suppliers(categories=None):
    """
    Return {supplier_code: {'name': str, 'category': str}} for every supplier
    classified into one of the "main" categories in SupplierSegmentation.

    categories: iterable of category codes; defaults to MAIN_SUPPLIER_CATEGORIES.
    """
    from apps.procurement.models import SupplierSegmentation

    cats = list(categories) if categories else list(MAIN_SUPPLIER_CATEGORIES)
    rows = SupplierSegmentation.objects.filter(
        supplier_category__in=cats,
    ).values_list('supplier_code', 'supplier_name', 'supplier_category')

    out = {}
    for code, name, cat in rows:
        code = _str(code)
        if code:
            out[code] = {'name': _str(name), 'category': _str(cat)}
    return out


# ── Backfill (SOFTECH → PurchaseExpiryEntry) ─────────────────────────────────

def run_backfill(run, window_from, window_to, branch=None, categories=None,
                 timeout=_QUERY_TIMEOUT):
    """
    Mirror doccode-10 purchase-with-expiry lines from main suppliers into
    PurchaseExpiryEntry for [window_from, window_to] — ACROSS ALL BRANCHES.

    run       : PurchaseExpiryAuditRun (updated with counters; caller finishes it)
    branch    : DEPRECATED / ignored. The mirror MUST hold every branch's purchase
                entries, because purchases are received centrally (HQ store 100)
                and then distributed — a per-branch report reads the chain-wide
                mirror and intersects with that branch's stock. Restricting
                ingestion to one branch would leave the mirror incomplete and
                silently break other branches' reports, so we always mirror all.
    categories: main-supplier category codes (defaults to the two main ones)

    Returns a stats dict. Idempotent — safe to re-run (unique key skips dupes).
    """
    from config.sybase import get_sybase_connection
    from apps.catalog.models import Item
    from apps.branches.models import Branch
    from .models import PurchaseExpiryEntry
    from .queries import QUERY_PURCHASE_EXPIRY_WINDOW

    if branch:
        logger.warning('[PurchaseExpiry] --branch=%s ignored — always mirroring ALL '
                       'branches so every branch report stays complete.', branch)

    suppliers = resolve_main_suppliers(categories)
    if not suppliers:
        raise ValueError(
            'لا يوجد موردون مصنّفون كموزّعين رئيسيين/مصانع. '
            'شغّل محرك المشتريات (run_procurement_engine) لتصنيف الموردين أولاً، '
            'أو صنّفهم يدويًا في تصنيفات الموردين.'
        )

    supplier_codes = list(suppliers.keys())
    run.suppliers_count = len(supplier_codes)

    # PG lookup maps (avoid per-row queries; mirror the procurement pattern).
    item_map   = {i.softech_id: i for i in Item.objects.only('id', 'softech_id', 'name')}
    branch_map = {b.softech_branch_id: b for b in Branch.objects.only('id', 'softech_branch_id')}

    branch_filter = ''   # always all branches — see docstring

    pre_count = PurchaseExpiryEntry.objects.count()
    fetched = 0

    conn = get_sybase_connection()
    try:
        for start_iso, end_iso in _month_chunks(window_from, window_to):
            for sup_chunk in _chunks(supplier_codes, _SUPPLIER_CHUNK):
                in_list = ', '.join(f"'{c}'" for c in sup_chunk)
                sql = QUERY_PURCHASE_EXPIRY_WINDOW.format(
                    start=start_iso, end=end_iso,
                    suppliers=in_list, branch_filter=branch_filter,
                )
                cur = conn.cursor()
                try:
                    cur.execute(sql, timeout=timeout)
                    rows = cur.fetchall()
                finally:
                    cur.close()

                buffer = []
                for r in rows:
                    fetched += 1
                    expiry = _to_date(r[5])
                    if not _valid_expiry(expiry):
                        continue
                    supplier_code = _str(r[0])
                    branch_code   = _str(r[1])
                    item_code     = _str(r[4])
                    if not (supplier_code and branch_code and item_code):
                        continue
                    doc_date = _to_date(r[3])
                    if doc_date is None:
                        continue
                    try:
                        dblflag = int(float(r[7])) if r[7] is not None else 1
                    except (ValueError, TypeError):
                        dblflag = 1

                    meta = suppliers.get(supplier_code, {})
                    item_obj = item_map.get(item_code)
                    buffer.append(PurchaseExpiryEntry(
                        branch_code       = branch_code,
                        supplier_code     = supplier_code,
                        supplier_name     = meta.get('name', ''),
                        supplier_category = meta.get('category', ''),
                        doc_number        = _clean_docnumber(r[2]),
                        doc_date          = doc_date,
                        item_code         = item_code,
                        item_name         = item_obj.name if item_obj else '',
                        dblitemflag       = dblflag,
                        entered_expiry    = expiry,
                        qty               = _to_dec(r[6]),
                        store_code        = _str(r[8]),
                        item              = item_obj,
                        branch            = branch_map.get(branch_code),
                    ))

                if buffer:
                    PurchaseExpiryEntry.objects.bulk_create(
                        buffer, batch_size=_BULK_BATCH, ignore_conflicts=True,
                    )
                logger.info('[PurchaseExpiry] %s..%s suppliers[%d]: fetched=%d',
                            start_iso, end_iso, len(sup_chunk), len(rows))
    finally:
        conn.close()

    post_count = PurchaseExpiryEntry.objects.count()
    upserted = max(0, post_count - pre_count)

    # C1: alert on freshly-received SHORT-DATED deliveries from main suppliers.
    short_dated = 0
    try:
        entries = detect_short_dated(since_dt=run.started_at)
        short_dated = _notify_short_dated(entries)
    except Exception:
        logger.exception('[PurchaseExpiry] short-dated alert step failed')

    run.lines_fetched  = fetched
    run.lines_upserted = upserted
    return {
        'suppliers':   len(supplier_codes),
        'fetched':     fetched,
        'upserted':    upserted,
        'short_dated': short_dated,
    }


# ── Current-stock resolver (live SOFTECH) ────────────────────────────────────

def _stock_in_arrivals(branch_codes, item_codes, timeout=_QUERY_TIMEOUT):
    """
    Return {(branch_code, item_code): [(date, qty), ...] sorted NEWEST first}
    for every stock-IN movement (ARRIVAL_DOCCODES) at the given branches.
    Used to compute how long the oldest on-hand unit has been sitting (FIFO).
    """
    from config.sybase import get_sybase_connection
    from .queries import QUERY_STOCK_IN_MOVEMENTS

    if not branch_codes or not item_codes:
        return {}

    out = {}
    doccodes = ', '.join(f"'{d}'" for d in ARRIVAL_DOCCODES)
    branches = ', '.join(f"'{b}'" for b in branch_codes)
    conn = get_sybase_connection()
    try:
        for chunk in _chunks(list(item_codes), _SUPPLIER_CHUNK):
            items = ', '.join(f"'{c}'" for c in chunk)
            sql = QUERY_STOCK_IN_MOVEMENTS.format(
                doccodes=doccodes, branches=branches, items=items)
            cur = conn.cursor()
            try:
                cur.execute(sql, timeout=timeout)
                rows = cur.fetchall()
            finally:
                cur.close()
            for r in rows:
                ic = _str(r[0]); bc = _str(r[1])
                d = _to_date(r[2]); q = _to_dec(r[3])
                if ic and bc and d:
                    out.setdefault((bc, ic), []).append((d, q))
    finally:
        conn.close()

    for key in out:
        out[key].sort(key=lambda t: t[0], reverse=True)   # newest first
    return out


def _fifo_oldest_date(arrivals, current_qty):
    """
    Given arrivals [(date, qty)] NEWEST-first and the current on-hand qty, return
    the arrival date of the OLDEST unit still on hand (FIFO: newest sells last,
    so what remains is the most-recent arrivals summing to current_qty). This is
    robust to small recent top-ups sitting on top of a large old batch.
    """
    if not arrivals or current_qty is None or current_qty <= 0:
        return None
    cum = Decimal('0')
    oldest = arrivals[-1][0]   # fallback: earliest, if arrivals < current_qty
    for d, q in arrivals:      # newest → oldest
        cum += q
        oldest = d
        if cum >= Decimal(str(current_qty)):
            break
    return oldest


def _current_stock(branch_codes, item_codes):
    """
    Return {(branch_code, item_code): Decimal(qty)} for on-hand stock
    (nowqty > 0, quarantine stores excluded) across the given branches.

    Reuses apps/stockcount/engine.fetch_stock_balance (same stkbal pattern).
    """
    from apps.stockcount.engine import fetch_stock_balance
    result = {}
    for bc in branch_codes:
        balances = fetch_stock_balance(bc, item_codes)   # {item_code: Decimal}
        for code, qty in balances.items():
            if qty and qty > 0:
                result[(bc, code)] = qty
    return result


# ── The report: audit candidates ─────────────────────────────────────────────

# Whitelisted sort keys → (row-key, reverse). None values always sort last.
_SORT_KEYS = {
    'value_at_risk':  ('value_at_risk',           True),   # biggest potential loss first
    'qty':            ('current_qty',             True),   # largest quantity first
    'unit_cost':      ('unit_cost',               True),   # most expensive first
    'retail_value':   ('retail_value',            True),
    'entry_count':    ('entry_count',             True),
    'stock_age':      ('stock_age_days',          True),   # longest sitting in branch first
    'expected_loss':  ('expected_loss',           True),   # biggest projected write-off first
    'days_to_expiry': ('days_to_expiry',          False),  # soonest to expire first
    'expiry':         ('earliest_entered_expiry', False),  # soonest entered expiry first
    'name':           ('item_name',               False),
}


def _velocity_map(item_codes, branch_codes):
    """
    Return ({(item_code, branch_code): monthly_qty_90d_rate}, have_metrics: bool)
    from the latest demand-engine run (purchasing.ItemDemandMetrics — a PG mirror,
    no SOFTECH hit). qty_90d is the net 90-day sales quantity; velocity/day is
    derived by the caller (qty_90d / 90). have_metrics=False means the demand
    engine has never run → risk scoring is left blank rather than assumed.
    """
    from django.db.models import Max
    from apps.purchasing.models import ItemDemandMetrics

    latest = ItemDemandMetrics.objects.aggregate(m=Max('calc_date'))['m']
    if latest is None:
        return {}, False
    rows = (ItemDemandMetrics.objects
            .filter(calc_date=latest,
                    item__softech_id__in=item_codes,
                    branch__softech_branch_id__in=branch_codes)
            .values_list('item__softech_id', 'branch__softech_branch_id', 'qty_90d'))
    out = {}
    for ic, bc, q90 in rows:
        out[(str(ic), str(bc))] = float(q90 or 0)
    return out, True


def _compute_risk(qty, unit_cost, days_to_expiry, velocity_per_day):
    """
    Deterministic expiry-risk for one item: will the on-hand qty sell before it
    expires, and what's the expected write-off if not?

    velocity_per_day : units sold per day (None = demand engine hasn't run).
    Returns dict of risk fields (all None when inputs are insufficient).
    """
    blank = dict(days_to_expiry=days_to_expiry, velocity_per_day=velocity_per_day,
                 days_to_sellout=None, expected_unsold_qty=None,
                 expected_loss=None, risk_tier=None)
    if qty is None or days_to_expiry is None:
        return blank
    uc = unit_cost or 0
    if days_to_expiry <= 0:                       # already past its recorded expiry
        return dict(days_to_expiry=days_to_expiry, velocity_per_day=velocity_per_day,
                    days_to_sellout=None, expected_unsold_qty=round(qty, 2),
                    expected_loss=round(qty * uc, 2) if uc else None,
                    risk_tier='expired')
    if velocity_per_day is None:
        return blank
    projected_sold = velocity_per_day * days_to_expiry
    unsold = max(0.0, qty - projected_sold)
    sellout = (qty / velocity_per_day) if velocity_per_day > 0 else None
    frac = (unsold / qty) if qty > 0 else 0
    tier = ('low' if frac <= 0.001 else
            'critical' if frac >= 0.75 else
            'high' if frac >= 0.40 else 'medium')
    return dict(
        days_to_expiry=days_to_expiry,
        velocity_per_day=round(velocity_per_day, 3),
        days_to_sellout=round(sellout, 1) if sellout is not None else None,
        expected_unsold_qty=round(unsold, 2),
        expected_loss=round(unsold * uc, 2) if uc else None,
        risk_tier=tier,
    )


def audit_candidates(period_from, period_to, branch_codes=None, categories=None,
                     only_in_stock=True, min_qty=Decimal('0'), stock_fetcher=None,
                     sort=None, imported_only=False, min_value_at_risk=None,
                     with_stock_age=True, arrivals_fetcher=None):
    """
    Physical near-expiry audit worklist.

    Trigger set: distinct items that have a PurchaseExpiryEntry (main supplier,
    entered expiry) whose ENTERED EXPIRY ∈ [period_from, period_to] — CHAIN-WIDE,
    since purchases are received centrally then distributed. The purchase itself
    may have happened at any time. Then (if only_in_stock) intersect with items
    on-hand right now AT THE BRANCHES IN SCOPE.

    period_from / period_to : date objects (inclusive) — the ENTERED-EXPIRY window
                              (batches a trusted supplier logged as expiring here).
                              Purchase date (doc_date) is NOT constrained.
    branch_codes            : SOFTECH branch codes whose CURRENT STOCK to audit
                              (None = all active branches). Does NOT filter the
                              expiry trigger (which is chain-wide) — only the
                              on-hand stock intersection.
    categories              : main-supplier categories (defaults to the two main).
    stock_fetcher           : callable(branch_codes, item_codes) → {(bc,ic): qty};
                              defaults to live SOFTECH lookup (injectable for tests).
    sort                    : one of _SORT_KEYS (default: 'value_at_risk' when
                              only_in_stock else 'expiry').
    imported_only           : keep only items flagged imported (catalog.is_imported).
    min_value_at_risk       : drop items whose value-at-risk (qty×cost) is below this.

    Each row is enriched with economics + attributes so the UI can filter/sort
    ("expensive", "imported", "biggest loss if expired", "large qty"):
      {item_code, item_name, current_qty, branches_in_stock, entry_count,
       suppliers, first_entry_date, last_entry_date, earliest_entered_expiry,
       latest_entered_expiry, has_entered_expiry_passed,
       unit_cost, pack_price, value_at_risk, retail_value, is_imported,
       origin, medicine_type, producer, family, store_classif, pack_qty,
       stock_age_days, oldest_arrival_date, oldest_arrival_branch}

    stock_age_days = how long the OLDEST on-hand unit has sat at the branch (FIFO
    over ARRIVAL_DOCCODES: purchase/transfer-in/return/surplus) — a higher value
    means it's been sitting long unsold ⇒ higher near-expiry tendency. Best-effort
    (None if the ERP lookup fails or only_in_stock is False). Sort key 'stock_age'.
    """
    from django.db.models import Count, Min, Max
    from .models import PurchaseExpiryEntry

    cats = list(categories) if categories else list(MAIN_SUPPLIER_CATEGORIES)

    # The period selects on the ENTERED EXPIRY date — i.e. "batches that a trusted
    # supplier's data entry says expire within [period_from, period_to]". The
    # purchase (doc_date) may have happened at ANY time in the synced mirror.
    #
    # NB: the expiry trigger is CHAIN-WIDE, deliberately NOT filtered by
    # branch_codes. Purchases are received centrally (HQ store 100) and then
    # distributed, so an item's expiring batch is recorded at HQ even though the
    # stock sits at a selling branch. branch_codes filters CURRENT STOCK only
    # (below) — filtering the mirror by the stock branch would wrongly drop every
    # centrally-purchased item.
    qs = PurchaseExpiryEntry.objects.filter(
        entered_expiry__gte=period_from,
        entered_expiry__lte=period_to,
        supplier_category__in=cats,
    )

    # Aggregate per item across the window/scope.
    agg = (
        qs.values('item_code')
          .annotate(
              entry_count      = Count('id'),
              first_entry_date = Min('doc_date'),
              last_entry_date  = Max('doc_date'),
              earliest_expiry  = Min('entered_expiry'),
              latest_expiry    = Max('entered_expiry'),
          )
    )
    per_item = {row['item_code']: row for row in agg}
    if not per_item:
        return []

    item_codes = list(per_item.keys())

    # Names + supplier lists (one extra pass, cheap on the indexed mirror).
    names = dict(
        qs.exclude(item_name='')
          .values_list('item_code', 'item_name')
          .distinct()
    )
    suppliers_by_item = {}
    for ic, sname in qs.values_list('item_code', 'supplier_name').distinct():
        if sname:
            suppliers_by_item.setdefault(ic, set()).add(sname)

    # Resolve which branches to check CURRENT stock in.
    #
    # IMPORTANT: purchases are received centrally (e.g. HQ store 100) and then
    # distributed to the selling branches, so the mirror's purchase branch is NOT
    # where the stock ends up. For "all branches" we must scan every active
    # branch's stock — not just the branches that appear on the purchase entries —
    # or distributed stock is missed.
    if branch_codes:
        scope_branches = list(branch_codes)
    else:
        from apps.branches.models import Branch
        scope_branches = list(
            Branch.objects.filter(is_active=True)
            .values_list('softech_branch_id', flat=True)
        )
        if not scope_branches:   # fallback (e.g. tests without Branch rows)
            scope_branches = list(qs.values_list('branch_code', flat=True).distinct())

    stock_map = {}
    if only_in_stock:
        fetch = stock_fetcher or _current_stock
        stock_map = fetch(scope_branches, item_codes)

    # Economics + attributes from the PG catalog mirror (one query, no SOFTECH).
    item_map = _item_attr_map(item_codes)

    # Sales velocity (for expiry-risk scoring) from the latest demand-engine run.
    vel_map, vel_known = ({}, False)
    if only_in_stock:
        vel_map, vel_known = _velocity_map(item_codes, scope_branches)

    today = _dt.date.today()
    results = []
    for ic, row in per_item.items():
        if only_in_stock:
            branches_in_stock = sorted(
                {bc for (bc, code) in stock_map if code == ic and stock_map[(bc, code)] > 0}
            )
            current_qty = sum(
                (stock_map[(bc, code)] for (bc, code) in stock_map if code == ic),
                Decimal('0'),
            )
            if current_qty <= min_qty:
                continue
        else:
            branches_in_stock = []
            current_qty = None

        attr = item_map.get(ic, {})
        if imported_only and not attr.get('is_imported'):
            continue

        unit_cost   = attr.get('unit_cost')      # cost/purchase price per pack
        pack_price  = attr.get('pack_price')     # retail price per pack
        qf = float(current_qty) if current_qty is not None else None
        value_at_risk = (qf * unit_cost)  if (qf is not None and unit_cost)  else None
        retail_value  = (qf * pack_price) if (qf is not None and pack_price) else None

        if min_value_at_risk is not None and (value_at_risk or 0) < float(min_value_at_risk):
            continue

        # Expiry-risk score: will it sell before the (earliest in-window) expiry?
        velocity = None
        if vel_known and qf is not None:
            velocity = sum(vel_map.get((ic, bc), 0.0) for bc in branches_in_stock) / 90.0
        d2e = (row['earliest_expiry'] - today).days if row['earliest_expiry'] else None
        risk = _compute_risk(qf, unit_cost, d2e, velocity)
        markdown = _markdown_reco(unit_cost, pack_price, d2e)   # A5.1 recommend-only

        results.append({
            'item_code':                ic,
            'item_name':                names.get(ic, '') or attr.get('name', ''),
            'current_qty':              qf,
            'branches_in_stock':        branches_in_stock,
            'entry_count':              row['entry_count'],
            'suppliers':                sorted(suppliers_by_item.get(ic, [])),
            'first_entry_date':         row['first_entry_date'].isoformat() if row['first_entry_date'] else None,
            'last_entry_date':          row['last_entry_date'].isoformat() if row['last_entry_date'] else None,
            'earliest_entered_expiry':  row['earliest_expiry'].isoformat() if row['earliest_expiry'] else None,
            'latest_entered_expiry':    row['latest_expiry'].isoformat() if row['latest_expiry'] else None,
            'has_entered_expiry_passed': bool(row['earliest_expiry'] and row['earliest_expiry'] < today),
            # ── economics + attributes (for filter/sort) ──────────────────────
            'unit_cost':      unit_cost,
            'pack_price':     pack_price,
            'value_at_risk':  round(value_at_risk, 2) if value_at_risk is not None else None,
            'retail_value':   round(retail_value, 2) if retail_value is not None else None,
            'is_imported':    attr.get('is_imported', False),
            'is_fridge':      attr.get('is_fridge', False),
            'origin':         attr.get('origin', ''),
            'medicine_type':  attr.get('medicine_type', ''),
            'shape':          attr.get('shape', ''),
            'effect':         attr.get('effect', ''),
            'producer':       attr.get('producer', ''),
            'family':         attr.get('family', ''),
            'store_classif':  attr.get('store_classif', ''),
            'pack_qty':       attr.get('pack_qty'),
            # ── expiry-risk score (A2) ─────────────────────────────────────────
            'days_to_expiry':      risk['days_to_expiry'],
            'velocity_per_day':    risk['velocity_per_day'],
            'days_to_sellout':     risk['days_to_sellout'],
            'expected_unsold_qty': risk['expected_unsold_qty'],
            'expected_loss':       risk['expected_loss'],
            'risk_tier':           risk['risk_tier'],
            # ── markdown recommendation (A5.1, recommend-only) ─────────────────
            'markdown_discount_pct': markdown['markdown_discount_pct'],
            'markdown_net_price':    markdown['markdown_net_price'],
            'markdown_margin_pct':   markdown['markdown_margin_pct'],
            # ── stock age in branch (filled below when only_in_stock) ──────────
            'stock_age_days':       None,
            'oldest_arrival_date':  None,
            'oldest_arrival_branch': None,
        })

    # ── "Age in branch" — how long the oldest on-hand unit has sat (FIFO) ──────
    # An old arrival still on the shelf ⇒ higher near-expiry tendency. Best-effort:
    # a flaky ERP moment leaves stock_age_days=None rather than failing the report.
    # Only auto-hit SOFTECH for arrivals on the production path (no injected stock
    # source); a caller that injected its own stock_fetcher must inject an
    # arrivals_fetcher too, otherwise age is left blank (keeps tests offline).
    if arrivals_fetcher is not None:
        _fetch_arr = arrivals_fetcher
    elif stock_fetcher is None:
        _fetch_arr = _stock_in_arrivals
    else:
        _fetch_arr = None

    if only_in_stock and with_stock_age and results and _fetch_arr is not None:
        surviving = [r['item_code'] for r in results]
        scope = sorted({bc for r in results for bc in r['branches_in_stock']}) or scope_branches
        try:
            arrivals = _fetch_arr(scope, surviving)
        except Exception:
            logger.exception('[PurchaseExpiry] stock-age lookup failed — leaving age blank')
            arrivals = None
        if arrivals:
            for r in results:
                best = None   # (age_days, date, branch)
                for bc in r['branches_in_stock']:
                    q = stock_map.get((bc, r['item_code']))
                    d = _fifo_oldest_date(arrivals.get((bc, r['item_code'])), q)
                    if d is None:
                        continue
                    age = (today - d).days
                    if best is None or age > best[0]:
                        best = (age, d, bc)
                if best:
                    r['stock_age_days']        = best[0]
                    r['oldest_arrival_date']   = best[1].isoformat()
                    r['oldest_arrival_branch'] = best[2]

    _sort_results(results, sort, only_in_stock)
    return results


# ── B2: Supplier dating scorecard ─────────────────────────────────────────────

def supplier_scorecard(categories=None, months_back=None, short_dated_months=6):
    """
    Per main-supplier: how well-dated is the stock they deliver? Pure PG
    aggregation over PurchaseExpiryEntry (shelf-life-at-receipt = entered_expiry −
    purchase date). A negotiation lever — suppliers who consistently ship
    short-dated goods drive avoidable expiry loss.

    months_back        : only count purchases from the last N months (None = all mirror).
    short_dated_months : a line is "short-dated" if shelf life at receipt < this.

    Returns list[dict] sorted worst-first (highest % short-dated), each:
      {supplier_code, supplier_name, category, lines, items, avg_shelf_months,
       min_shelf_months, short_dated_lines, pct_short_dated}
    """
    import datetime as _d
    from django.db.models import (F, ExpressionWrapper, DurationField, Count, Avg,
                                  Min, Q)
    from .models import PurchaseExpiryEntry

    cats = list(categories) if categories else list(MAIN_SUPPLIER_CATEGORIES)
    qs = PurchaseExpiryEntry.objects.filter(supplier_category__in=cats)
    if months_back:
        cutoff = _d.date.today() - _d.timedelta(days=int(months_back) * 30)
        qs = qs.filter(doc_date__gte=cutoff)

    shelf = ExpressionWrapper(F('entered_expiry') - F('doc_date'),
                              output_field=DurationField())
    short_cut = _d.timedelta(days=int(short_dated_months) * 30)
    qs = qs.annotate(shelf=shelf)

    agg = (qs.values('supplier_code', 'supplier_name', 'supplier_category')
             .annotate(
                 lines=Count('id'),
                 items=Count('item_code', distinct=True),
                 avg_shelf=Avg('shelf'),
                 min_shelf=Min('shelf'),
                 short_dated_lines=Count('id', filter=Q(shelf__lt=short_cut)),
             ))

    def _months(td):
        return round(td.days / 30.0, 1) if td is not None else None

    out = []
    for r in agg:
        lines = r['lines'] or 0
        short = r['short_dated_lines'] or 0
        out.append({
            'supplier_code':    r['supplier_code'],
            'supplier_name':    r['supplier_name'],
            'category':         r['supplier_category'],
            'lines':            lines,
            'items':            r['items'],
            'avg_shelf_months': _months(r['avg_shelf']),
            'min_shelf_months': _months(r['min_shelf']),
            'short_dated_lines': short,
            'pct_short_dated':  round(100.0 * short / lines, 1) if lines else 0.0,
        })
    out.sort(key=lambda x: (-x['pct_short_dated'], x['avg_shelf_months'] or 999))
    return out


# ── A4: Inter-branch rebalancing suggestion ───────────────────────────────────

def rebalance_suggest(item_code, from_branch, days_to_expiry,
                      stock_fetcher=None, velocity_map=None):
    """
    For a near-expiry item that will expire unsold at `from_branch`, recommend
    moving the surplus to branches that sell it fast enough to clear it before it
    expires. Deterministic:

      surplus at source   = max(0, source_qty − source_velocity × days_to_expiry)
      headroom at target  = max(0, target_velocity × days_to_expiry − target_qty)
      allocate surplus across targets, highest-headroom first, in whole units.

    Velocity = ItemDemandMetrics.qty_90d ÷ 90 (PG, latest run). Stock = live
    SOFTECH stkbal per branch. Both are injectable for tests.

    Returns {item_code, item_id, item_name, from_branch*, source_qty,
             source_velocity_per_day, source_surplus, days_to_expiry,
             velocity_known, plan:[{to_branch, to_branch_id, to_branch_name, qty,
             target_qty, velocity_per_day, headroom}]}.
    The plan feeds apps/transfers create (requesting_branch=target, supplying=source).
    """
    from apps.catalog.models import Item
    from apps.branches.models import Branch

    item = Item.objects.filter(softech_id=item_code).only('id', 'name', 'cost_price').first()
    bmeta = {}
    for bc, bid, nar, nm in Branch.objects.filter(is_active=True).values_list(
            'softech_branch_id', 'id', 'name_ar', 'name'):
        bmeta[str(bc)] = {'id': bid, 'name': nar or nm or str(bc)}
    branch_codes = list(bmeta.keys())

    fetch = stock_fetcher or _current_stock
    stock_map = fetch(branch_codes, [item_code])
    stock = {bc: float(stock_map.get((bc, item_code), 0) or 0) for bc in branch_codes}

    if velocity_map is None:
        velocity_map, vknown = _velocity_map([item_code], branch_codes)
    else:
        vknown = True
    vel = {bc: float(velocity_map.get((item_code, bc), 0.0)) / 90.0 for bc in branch_codes}

    d2e = max(0, int(days_to_expiry or 0))

    src = str(from_branch) if from_branch else None
    if not src or src not in bmeta:
        surpluses = {bc: max(0.0, stock[bc] - vel[bc] * d2e) for bc in branch_codes}
        src = max(surpluses, key=surpluses.get) if surpluses else None

    source_qty = stock.get(src, 0.0)
    source_vel = vel.get(src, 0.0)
    surplus = max(0.0, source_qty - source_vel * d2e)

    targets = []
    for bc in branch_codes:
        if bc == src:
            continue
        headroom = vel[bc] * d2e - stock[bc]
        if headroom > 0.5 and vel[bc] > 0:
            targets.append((bc, headroom, vel[bc], stock[bc]))
    targets.sort(key=lambda t: -t[1])

    plan, remaining = [], surplus
    for bc, headroom, v, tq in targets:
        if remaining <= 0.5:
            break
        qty = int(round(min(remaining, headroom)))
        if qty <= 0:
            continue
        plan.append({
            'to_branch': bc, 'to_branch_id': bmeta[bc]['id'],
            'to_branch_name': bmeta[bc]['name'], 'qty': qty,
            'target_qty': round(tq, 2), 'velocity_per_day': round(v, 3),
            'headroom': round(headroom, 1),
        })
        remaining -= qty

    return {
        'item_code': item_code,
        'item_id': item.id if item else None,
        'item_name': item.name if item else item_code,
        'from_branch': src,
        'from_branch_id': bmeta.get(src, {}).get('id'),
        'from_branch_name': bmeta.get(src, {}).get('name', src),
        'source_qty': round(source_qty, 2),
        'source_velocity_per_day': round(source_vel, 3),
        'source_surplus': round(surplus, 2),
        'days_to_expiry': d2e,
        'velocity_known': vknown,
        'plan': plan,
    }


# ── C1: short-dated-at-receipt detection + alert ──────────────────────────────

def detect_short_dated(since_dt=None, threshold_months=SHORT_DATED_MONTHS,
                       recent_days=RECENT_RECEIPT_DAYS, categories=None):
    """
    Recently-received purchase lines from main suppliers whose shelf life at
    receipt (entered_expiry − purchase date) is below threshold_months.

    since_dt : only rows mirrored at/after this time (i.e. new in this sync) —
               so re-runs don't re-alert; None = ignore (used by tests/manual).
    recent_days : only deliveries whose purchase date is within this window, so a
               3-year backfill doesn't alert on ancient short-dated purchases.
    """
    import datetime as _d
    from django.db.models import F, ExpressionWrapper, DurationField
    from .models import PurchaseExpiryEntry

    cats = list(categories) if categories else list(MAIN_SUPPLIER_CATEGORIES)
    recent_cut = _d.date.today() - _d.timedelta(days=int(recent_days))
    short_cut = _d.timedelta(days=int(threshold_months) * 30)
    qs = (PurchaseExpiryEntry.objects
          .filter(supplier_category__in=cats, doc_date__gte=recent_cut)
          .annotate(shelf=ExpressionWrapper(F('entered_expiry') - F('doc_date'),
                                            output_field=DurationField()))
          .filter(shelf__lt=short_cut))
    if since_dt is not None:
        qs = qs.filter(synced_at__gte=since_dt)
    return list(qs.values('branch_code', 'supplier_code', 'supplier_name',
                          'doc_number', 'doc_date', 'item_code', 'item_name',
                          'entered_expiry', 'qty').order_by('entered_expiry'))


def _notify_short_dated(entries, threshold_months=SHORT_DATED_MONTHS):
    """Send one summary alert to purchasing/admin about short-dated receipts."""
    import datetime as _d
    if not entries:
        return 0
    try:
        from apps.notifications.models import Notification
        from apps.users.models import StaffProfile
    except Exception:
        return len(entries)

    n_items = len({e['item_code'] for e in entries})
    lines = [f"{e['item_name'] or e['item_code']} — انتهاء {e['entered_expiry']} — "
             f"{e['supplier_name']} (فاتورة {e['doc_number']}، فرع {e['branch_code']})"
             for e in entries[:15]]
    body = (f"استُلمت {len(entries)} دفعة قصيرة الأجل (أقل من {threshold_months} أشهر "
            f"صلاحية عند الاستلام) من موردين رئيسيين، تخص {n_items} صنفًا:\n\n"
            + "\n".join(lines))
    if len(entries) > 15:
        body += f"\n… و{len(entries) - 15} أخرى."

    recipients = StaffProfile.objects.filter(role__in=['purchasing', 'admin'], is_active=True)
    dedup = f"short_dated_receipt_{_d.date.today().isoformat()}"
    for r in recipients:
        try:
            Notification.objects.create(
                recipient=r, notification_type='system',
                title=f"⚠️ {len(entries)} دفعة قصيرة الأجل عند الاستلام",
                body=body, dedup_key=dedup,
            )
        except Exception:
            logger.exception('short-dated notify failed for %s', getattr(r, 'pk', '?'))
    return len(entries)


# ── C2: expiry-prone items (procurement feedback) ─────────────────────────────

def expiry_prone_items(months_back=12, short_dated_months=SHORT_DATED_MONTHS,
                       categories=None, min_short_pct=30.0, limit=500):
    """
    Items that are chronically bought short-dated (a high share of their main-
    supplier purchases arrive with < short_dated_months shelf life) — the buyer
    should reduce reorder qty, negotiate dating, or switch source. Combined with
    sales velocity (ItemDemandMetrics) so slow + short-dated items rise to the top.

    Returns list[dict] sorted worst-first (by % short-dated, then volume):
      {item_code, item_name, lines, short_dated_lines, pct_short_dated,
       suppliers, monthly_velocity, first_date, last_date, reorder_review}
    """
    import datetime as _d
    from django.db.models import (F, ExpressionWrapper, DurationField, Count, Q,
                                  Min, Max)
    from apps.branches.models import Branch
    from .models import PurchaseExpiryEntry

    cats = list(categories) if categories else list(MAIN_SUPPLIER_CATEGORIES)
    cut = _d.date.today() - _d.timedelta(days=int(months_back) * 30)
    short_cut = _d.timedelta(days=int(short_dated_months) * 30)

    qs = (PurchaseExpiryEntry.objects
          .filter(supplier_category__in=cats, doc_date__gte=cut)
          .annotate(shelf=ExpressionWrapper(F('entered_expiry') - F('doc_date'),
                                            output_field=DurationField())))
    agg = (qs.values('item_code')
             .annotate(lines=Count('id'),
                       short_dated_lines=Count('id', filter=Q(shelf__lt=short_cut)),
                       suppliers=Count('supplier_code', distinct=True),
                       first_date=Min('doc_date'), last_date=Max('doc_date')))
    per = {r['item_code']: r for r in agg}
    if not per:
        return []

    codes = list(per.keys())
    names = dict(qs.exclude(item_name='').values_list('item_code', 'item_name').distinct())
    branch_codes = list(Branch.objects.filter(is_active=True)
                        .values_list('softech_branch_id', flat=True))
    vel_map, _ = _velocity_map(codes, branch_codes)

    out = []
    for ic, r in per.items():
        lines = r['lines'] or 0
        short = r['short_dated_lines'] or 0
        pct = round(100.0 * short / lines, 1) if lines else 0.0
        q90 = sum(vel_map.get((ic, bc), 0.0) for bc in branch_codes)
        monthly_velocity = round(q90 / 3.0, 1)   # qty_90d → monthly
        out.append({
            'item_code':        ic,
            'item_name':        names.get(ic, ''),
            'lines':            lines,
            'short_dated_lines': short,
            'pct_short_dated':  pct,
            'suppliers':        r['suppliers'],
            'monthly_velocity': monthly_velocity,
            'first_date':       r['first_date'].isoformat() if r['first_date'] else None,
            'last_date':        r['last_date'].isoformat() if r['last_date'] else None,
            'reorder_review':   pct >= float(min_short_pct),
        })
    out.sort(key=lambda x: (-x['pct_short_dated'], -x['lines']))
    return out[:int(limit)]


# ── D4: scheduled per-branch expiry worklist → notifications ───────────────────

def generate_branch_worklists(back_days=30, ahead_days=90, top_n=25,
                              categories=None, notify=True):
    """
    For each active/operational branch, build a near-term expiry worklist (items
    expiring from `back_days` ago through `ahead_days` ahead, still in stock,
    ranked by expected loss) and push ONE summary in-app notification to that
    branch's managers (pharmacist/supervisor). Resilient per branch (a flaky ERP
    link on one branch never blocks the others). Deduped per (branch, ISO week).

    Returns a summary dict. WhatsApp delivery can be layered on top (omni/whatsapp)
    once staff numbers/opt-in are configured — deliberately not auto-sent here.
    """
    import datetime as _d
    from apps.branches.models import Branch

    today = _d.date.today()
    frm = today - _d.timedelta(days=int(back_days))
    to = today + _d.timedelta(days=int(ahead_days))
    summary = {'branches_scanned': 0, 'branches_with_items': 0,
               'notified': 0, 'errors': 0}

    for b in Branch.objects.filter(is_active=True, is_operational=True):
        bc = b.softech_branch_id
        try:
            rows = audit_candidates(frm, to, branch_codes=[bc], only_in_stock=True,
                                    categories=categories, sort='expected_loss',
                                    with_stock_age=False)
        except Exception:
            logger.exception('[PurchaseExpiry] worklist failed for branch %s', bc)
            summary['errors'] += 1
            continue
        summary['branches_scanned'] += 1
        if not rows:
            continue
        summary['branches_with_items'] += 1
        if notify:
            summary['notified'] += _notify_branch_worklist(b, rows, top_n, today)
    return summary


def _notify_branch_worklist(branch, rows, top_n, today):
    try:
        from apps.notifications.models import Notification
        from apps.users.models import StaffProfile
    except Exception:
        return 0

    bname = getattr(branch, 'name_ar', '') or branch.softech_branch_id
    total_var = sum(r.get('value_at_risk') or 0 for r in rows)
    total_loss = sum(r.get('expected_loss') or 0 for r in rows)
    lines = [f"{r['item_name'] or r['item_code']} — كمية {r['current_qty']} — "
             f"انتهاء {r['earliest_entered_expiry']}" for r in rows[:15]]
    body = (f"{len(rows)} صنف قارب على انتهاء الصلاحية بفرع {bname} — "
            f"قيمة معرّضة {round(total_var):,} ج"
            + (f"، خسارة متوقعة {round(total_loss):,} ج" if total_loss else "")
            + ":\n\n" + "\n".join(lines))
    if len(rows) > 15:
        body += f"\n… و{len(rows) - 15} أخرى — افتح «تدقيق صلاحيات الشراء»."

    iso = today.isocalendar()
    dedup = f"expiry_worklist_{branch.softech_branch_id}_{iso[0]}W{iso[1]}"
    recipients = StaffProfile.objects.filter(
        branch=branch, role__in=['pharmacist', 'supervisor'], is_active=True)
    n = 0
    for r in recipients:
        try:
            Notification.objects.create(
                recipient=r, notification_type='system',
                title=f"🗓️ قائمة صلاحيات الأسبوع — {bname} ({len(rows)})",
                body=body, dedup_key=dedup)
            n += 1
        except Exception:
            logger.exception('worklist notify failed for %s', getattr(r, 'pk', '?'))
    return n


def _item_attr_map(item_codes):
    """{itemcode: {economics + attributes}} from the PG catalog.Item mirror."""
    from apps.catalog.models import Item
    out = {}
    fields = ('softech_id', 'name', 'cost_price', 'pack_price', 'is_imported',
              'origin_name_ar', 'origin_name', 'medicine_type_name_ar',
              'producer_name', 'family_name_ar', 'family_name', 'store_classif', 'pack_qty',
              'requires_fridge', 'shape_name_ar', 'shape_name',
              'effect_name_ar', 'effect_name')
    for it in Item.objects.filter(softech_id__in=item_codes).only(*fields):
        out[it.softech_id] = {
            'name':          it.name,
            'unit_cost':     float(it.cost_price) if it.cost_price is not None else None,
            'pack_price':    float(it.pack_price) if it.pack_price is not None else None,
            'is_imported':   bool(it.is_imported),
            'is_fridge':     bool(getattr(it, 'requires_fridge', False)),
            'origin':        it.origin_name_ar or it.origin_name or '',
            'medicine_type': it.medicine_type_name_ar or '',      # التصنيف العام
            'shape':         it.shape_name_ar or it.shape_name or '',   # الشكل الصيدلي
            'effect':        it.effect_name_ar or it.effect_name or '', # دواعي الاستعمال
            'producer':      it.producer_name or '',
            'family':        it.family_name_ar or it.family_name or '',
            'store_classif': it.store_classif or '',
            'pack_qty':      int(it.pack_qty) if getattr(it, 'pack_qty', None) else None,
        }
    return out


def _sort_results(results, sort, only_in_stock):
    """In-place sort by a whitelisted key; missing values always sort last."""
    key = sort if sort in _SORT_KEYS else ('value_at_risk' if only_in_stock else 'expiry')
    field, reverse = _SORT_KEYS[key]
    if reverse:
        # Numeric, biggest first; None → last.
        results.sort(key=lambda x: (x.get(field) is None, -(x.get(field) or 0), x['item_code']))
    else:
        # String / date, smallest first; empty/None → last.
        default = '9999-12-31' if field == 'earliest_entered_expiry' else '￿'
        results.sort(key=lambda x: (not x.get(field), x.get(field) or default, x['item_code']))
