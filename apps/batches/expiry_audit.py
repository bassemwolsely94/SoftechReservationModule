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
    PurchaseExpiryEntry for [window_from, window_to].

    run       : PurchaseExpiryAuditRun (updated with counters; caller finishes it)
    branch    : SOFTECH branch code to restrict to, or None/'' for all branches
    categories: main-supplier category codes (defaults to the two main ones)

    Returns a stats dict. Idempotent — safe to re-run (unique key skips dupes).
    """
    from config.sybase import get_sybase_connection
    from apps.catalog.models import Item
    from apps.branches.models import Branch
    from .models import PurchaseExpiryEntry
    from .queries import QUERY_PURCHASE_EXPIRY_WINDOW

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

    branch_filter = ''
    if branch:
        branch_filter = f"AND sm.branchcode = '{branch}'"

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

    run.lines_fetched  = fetched
    run.lines_upserted = upserted
    return {
        'suppliers': len(supplier_codes),
        'fetched':   fetched,
        'upserted':  upserted,
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
    'expiry':         ('earliest_entered_expiry', False),  # soonest entered expiry first
    'name':           ('item_name',               False),
}


def audit_candidates(period_from, period_to, branch_codes=None, categories=None,
                     only_in_stock=True, min_qty=Decimal('0'), stock_fetcher=None,
                     sort=None, imported_only=False, min_value_at_risk=None,
                     with_stock_age=True, arrivals_fetcher=None):
    """
    Physical near-expiry audit worklist.

    Trigger set: distinct items that have a PurchaseExpiryEntry (main supplier,
    entered expiry) whose ENTERED EXPIRY ∈ [period_from, period_to] and whose
    branch is in scope. The purchase itself may have happened at any time in the
    synced mirror. Then (if only_in_stock) intersect with items on-hand right now.

    period_from / period_to : date objects (inclusive) — the ENTERED-EXPIRY window
                              (batches a trusted supplier logged as expiring here).
                              Purchase date (doc_date) is NOT constrained.
    branch_codes            : list of SOFTECH branch codes, or None for all
                              branches that appear in the mirror for this window.
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
    qs = PurchaseExpiryEntry.objects.filter(
        entered_expiry__gte=period_from,
        entered_expiry__lte=period_to,
        supplier_category__in=cats,
    )
    if branch_codes:
        qs = qs.filter(branch_code__in=branch_codes)

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
            'origin':         attr.get('origin', ''),
            'medicine_type':  attr.get('medicine_type', ''),
            'producer':       attr.get('producer', ''),
            'family':         attr.get('family', ''),
            'store_classif':  attr.get('store_classif', ''),
            'pack_qty':       attr.get('pack_qty'),
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


def _item_attr_map(item_codes):
    """{itemcode: {economics + attributes}} from the PG catalog.Item mirror."""
    from apps.catalog.models import Item
    out = {}
    fields = ('softech_id', 'name', 'cost_price', 'pack_price', 'is_imported',
              'origin_name_ar', 'origin_name', 'medicine_type_name_ar',
              'producer_name', 'family_name_ar', 'family_name', 'store_classif', 'pack_qty')
    for it in Item.objects.filter(softech_id__in=item_codes).only(*fields):
        out[it.softech_id] = {
            'name':          it.name,
            'unit_cost':     float(it.cost_price) if it.cost_price is not None else None,
            'pack_price':    float(it.pack_price) if it.pack_price is not None else None,
            'is_imported':   bool(it.is_imported),
            'origin':        it.origin_name_ar or it.origin_name or '',
            'medicine_type': it.medicine_type_name_ar or '',
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
