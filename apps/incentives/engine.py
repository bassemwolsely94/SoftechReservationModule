"""
apps/incentives/engine.py  —  v6

Item-Based Incentive Calculation Engine
=========================================
Main entry point:
  calculate(program_id, period_start, period_end, *, user_ids=None,
            simulate=False, force=False, triggered_by=None)

New in v5 vs v4 (Near Expiry Incentive Extension):
  ─────────────────────────────────────────────────────────────────────────────
  • itemexpirydate added to stktrans SQL (column [9]).
    The existing IncentiveRule.expiry_within_days field is now WIRED into the
    engine — rules with this set only match sales where the batch expiry date
    is within N days of the sale date.

  • r_docnumber BUG FIX: stktrans.r_docnumber EXISTS (confirmed from live schema).
    The sales SQL still uses NULL (backward-compatible) but returns SQL now
    correctly fetches r_docnumber so is_reversed is properly set on sales.

  • Origin filter:
    IncentiveRule.is_imported_filter ('any' | 'local' | 'imported') and
    IncentiveRule.origin_codes (list of origin_code strings) are evaluated
    against catalog.Item pulled from PostgreSQL in a single bulk query.

  • Margin filter:
    IncentiveRule.margin_min / margin_max applied as:
    margin_pct = (pack_price - cost_price) / pack_price * 100

  • Pack price filter:
    IncentiveRule.pack_price_min / pack_price_max applied against
    catalog.Item.pack_price.

  • Item attribute map:
    Built ONCE after SOFTECH fetch; only loaded when any active rule needs it.
    Single PostgreSQL query for all item codes seen in the sales window.

  • IncentiveTransaction.expiry_date + expiry_days_remaining:
    Stored for every qualifying sale that has expiry data — enables the
    near-expiry dashboard without re-querying SOFTECH.
  ─────────────────────────────────────────────────────────────────────────────

Near-expiry data source:
  stktrans.itemexpirydate — the batch expiry date stamped on each sale line
  by SOFTECH at transaction time (confirmed live: column index 10 in stktrans,
  but we SELECT it explicitly so it's always at our defined _COL_EXPIRY_DATE).

  stkbalexpiry — used by the separate near-expiry STOCK report (views.py).
  Not used inside calculate() — the engine relies only on stktrans.
"""
import logging
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

logger = logging.getLogger('elrezeiky.incentives')

# ── Column indices — SELECT order MUST match _SALES_SQL_TEMPLATE ──────────────
_COL_DOCNUMBER   = 0
_COL_USERCODE    = 1   # m.usercode — cashier/employee
_COL_DOCDATE     = 2   # full datetime — used for time_window + near-expiry filtering
_COL_BRANCHCODE  = 3
_COL_R_DOCNUMBER = 4   # sales SQL: NULL placeholder; returns SQL: actual r_docnumber
_COL_ITEMCODE    = 5
_COL_ITEMNAME    = 6
_COL_TRANSQTY    = 7
_COL_PRICE       = 8
_COL_EXPIRY_DATE = 9   # d.itemexpirydate — batch expiry date (NEW in v5)

_SALES_DOCCODE   = '115'
_RETURNS_DOCCODE = '30'

# Cross-period look-forward window (days after period_end)
_CROSS_PERIOD_DAYS = 90

# ── Sales SQL ─────────────────────────────────────────────────────────────────
# Column [4] is NULL for sales — r_docnumber is only meaningful on returns.
# Column [9] is d.itemexpirydate — the batch expiry date of each sale line.
# NOTE: stktrans has individual batch-split rows (dblitemflag differentiates them).
#       We do NOT aggregate — each batch line is processed individually.
_SALES_SQL_TEMPLATE = """\
SELECT
    m.docnumber,
    m.usercode,
    m.docdate,
    m.branchcode,
    NULL                AS r_docnumber,
    d.itemcode,
    i.itemname,
    d.transqty,
    d.itemsaleprice,
    d.itemexpirydate
FROM SOFTECHDB9.dbo.stktransm m
JOIN SOFTECHDB9.dbo.stktrans d
    ON d.doccode    = m.doccode
   AND d.docnumber  = m.docnumber
   AND d.branchcode = m.branchcode
   AND d.docdate    = m.docdate
JOIN SOFTECHDB9.dbo.items i ON i.itemcode = d.itemcode
WHERE m.doccode = '{doc_code}'
  AND m.docdate >= '{start} 00:00:00'
  AND m.docdate <  DATEADD(day, 1, CONVERT(DATETIME, '{end}'))
  {person_filter}
ORDER BY m.docdate, m.docnumber, d.itemcode"""

# ── Returns SQL ───────────────────────────────────────────────────────────────
# r_docnumber IS a real column on stktrans (confirmed live schema).
# We now select it properly so returned_qty_map correctly keys by
# (original_sale_doc_no, item_code) and is_reversed is set accurately.
_RETURNS_SQL_TEMPLATE = """\
SELECT
    m.docnumber,
    m.usercode,
    m.docdate,
    m.branchcode,
    d.r_docnumber,
    d.itemcode,
    i.itemname,
    d.transqty,
    d.itemsaleprice,
    d.itemexpirydate
FROM SOFTECHDB9.dbo.stktransm m
JOIN SOFTECHDB9.dbo.stktrans d
    ON d.doccode    = m.doccode
   AND d.docnumber  = m.docnumber
   AND d.branchcode = m.branchcode
   AND d.docdate    = m.docdate
JOIN SOFTECHDB9.dbo.items i ON i.itemcode = d.itemcode
WHERE m.doccode = '{doc_code}'
  AND m.docdate >= '{start} 00:00:00'
  AND m.docdate <  DATEADD(day, 1, CONVERT(DATETIME, '{end}'))
  {person_filter}
ORDER BY m.docdate, m.docnumber, d.itemcode"""

# Future returns referencing in-period sales.
_CROSS_PERIOD_RETURNS_SQL = """\
SELECT
    m.docnumber,
    m.usercode,
    m.docdate,
    m.branchcode,
    d.r_docnumber,
    d.itemcode,
    i.itemname,
    d.transqty,
    d.itemsaleprice,
    d.itemexpirydate
FROM SOFTECHDB9.dbo.stktransm m
JOIN SOFTECHDB9.dbo.stktrans d
    ON d.doccode    = m.doccode
   AND d.docnumber  = m.docnumber
   AND d.branchcode = m.branchcode
   AND d.docdate    = m.docdate
JOIN SOFTECHDB9.dbo.items i ON i.itemcode = d.itemcode
WHERE m.doccode = '30'
  AND m.docdate >  '{period_end} 23:59:59'
  AND m.docdate <  DATEADD(day, 1, CONVERT(DATETIME, '{lookforward_end}'))
  {person_filter}
ORDER BY m.docdate, m.docnumber, d.itemcode"""


# ── Sybase helpers ────────────────────────────────────────────────────────────

def _fetch_rows(doc_code: str, start: date, end: date,
                person_codes=None, use_returns_template=False) -> list:
    """Open one Sybase connection, run the query, return all rows, close."""
    from config.sybase import get_sybase_connection

    person_filter = ''
    if person_codes:
        quoted = ', '.join(f"'{c}'" for c in person_codes)
        person_filter = f'AND m.usercode IN ({quoted})'

    template = _RETURNS_SQL_TEMPLATE if use_returns_template else _SALES_SQL_TEMPLATE
    sql = template.format(
        doc_code=doc_code,
        start=start.strftime('%Y-%m-%d'),
        end=end.strftime('%Y-%m-%d'),
        person_filter=person_filter,
    )

    conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        return cur.fetchall()
    finally:
        conn.close()


def _fetch_cross_period_returns(period_end: date, person_codes=None) -> list:
    """Fetch return transactions dated AFTER period_end (up to +90 days)."""
    from config.sybase import get_sybase_connection

    lookforward_end = period_end + timedelta(days=_CROSS_PERIOD_DAYS)
    person_filter = ''
    if person_codes:
        quoted = ', '.join(f"'{c}'" for c in person_codes)
        person_filter = f'AND m.usercode IN ({quoted})'

    sql = _CROSS_PERIOD_RETURNS_SQL.format(
        period_end=period_end.strftime('%Y-%m-%d'),
        lookforward_end=lookforward_end.strftime('%Y-%m-%d'),
        person_filter=person_filter,
    )

    conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        return cur.fetchall()
    finally:
        conn.close()


# ── Type-conversion helpers ───────────────────────────────────────────────────

def _to_decimal(value, default=Decimal('0')) -> Decimal:
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default


def _to_str(value) -> str:
    return '' if value is None else str(value).strip()


def _to_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
    except Exception:
        return None


def _to_datetime(value):
    """Keep as datetime (for time_window filtering)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    try:
        return datetime.strptime(str(value)[:19], '%Y-%m-%d %H:%M:%S')
    except Exception:
        try:
            return datetime.strptime(str(value)[:10], '%Y-%m-%d')
        except Exception:
            return None


# ── Rule item helpers ─────────────────────────────────────────────────────────

def _build_rule_item_sets(rules) -> tuple[dict, dict]:
    rule_item_sets: dict[int, frozenset] = {}
    rule_item_map:  dict[tuple, object]  = {}
    for rule in rules:
        items = list(rule.rule_items.all())
        rule_item_sets[rule.id] = frozenset(ri.item_code for ri in items)
        for ri in items:
            rule_item_map[(rule.id, ri.item_code)] = ri
    return rule_item_sets, rule_item_map


# ── Tiered slab helpers ───────────────────────────────────────────────────────

def _find_slab(slabs: list, total_qty: Decimal) -> dict | None:
    for slab in slabs:
        min_q = _to_decimal(slab.get('min_qty', 0))
        max_q_raw = slab.get('max_qty')
        max_q = None if max_q_raw is None else _to_decimal(max_q_raw)
        if total_qty >= min_q and (max_q is None or total_qty <= max_q):
            return slab
    return None


def _calc_tiered_incentive(rule, qty: Decimal, unit_price: Decimal,
                            total_period_qty: Decimal) -> Decimal:
    config = rule.slab_config or {}
    slabs  = config.get('slabs', [])
    slab_type = config.get('type', 'percent')
    slab = _find_slab(slabs, total_period_qty)
    if slab is None:
        return Decimal('0')
    rate = _to_decimal(slab.get('rate', 0))
    if slab_type == 'percent':
        return (qty * unit_price * rate / Decimal('100')).quantize(Decimal('0.0001'))
    return (qty * rate).quantize(Decimal('0.0001'))


def _calc_target_based_incentive(rule, qty: Decimal, unit_price: Decimal,
                                  total_period_qty: Decimal) -> Decimal:
    """
    Feature 2 — Target-Based Incentive.

    achievement_pct = total_period_qty / target_qty * 100
    Find matching tier by [min_pct, max_pct) range.
    Apply tier rate to this transaction's qty.

    target_tiers JSON: {
      "tiers": [
        {"min_pct": 0,   "max_pct": 79,  "rate": 0.0,  "type": "fixed_per_unit"},
        {"min_pct": 80,  "max_pct": 99,  "rate": 5.0,  "type": "fixed_per_unit"},
        {"min_pct": 100, "max_pct": 119, "rate": 10.0, "type": "fixed_per_unit"},
        {"min_pct": 120, "max_pct": null,"rate": 15.0, "type": "fixed_per_unit"}
      ]
    }
    """
    target_qty = _to_decimal(getattr(rule, 'target_qty', None))
    if target_qty <= 0:
        return Decimal('0')

    config = getattr(rule, 'target_tiers', None) or {}
    tiers = config.get('tiers', [])
    if not tiers:
        return Decimal('0')

    achievement_pct = total_period_qty / target_qty * Decimal('100')

    # Find matching tier
    matched_tier = None
    for tier in tiers:
        min_p = _to_decimal(tier.get('min_pct', 0))
        max_p_raw = tier.get('max_pct')
        max_p = None if max_p_raw is None else _to_decimal(max_p_raw)
        if achievement_pct >= min_p and (max_p is None or achievement_pct <= max_p):
            matched_tier = tier
            break

    if matched_tier is None:
        return Decimal('0')

    rate = _to_decimal(matched_tier.get('rate', 0))
    tier_type = matched_tier.get('type', 'fixed_per_unit')

    if tier_type == 'percent':
        return (qty * unit_price * rate / Decimal('100')).quantize(Decimal('0.0001'))
    return (qty * rate).quantize(Decimal('0.0001'))


# ── Item attribute map ────────────────────────────────────────────────────────

def _rules_need_item_attrs(rules) -> bool:
    """
    Return True if any active rule requires catalog.Item attribute lookups.
    Covers: origin filters, margin, pack price, and category_code wiring (Feature 7).
    """
    for rule in rules:
        if (rule.is_imported_filter != 'any'
                or rule.origin_codes
                or rule.margin_min is not None
                or rule.margin_max is not None
                or rule.pack_price_min is not None
                or rule.pack_price_max is not None
                # Category wiring: rule has category_code but no item_code and no rule_items
                or (rule.category_code and not rule.item_code)):
            return True
    return False


def _build_item_attr_map(item_codes: set) -> dict:
    """
    One PostgreSQL query for all item codes seen in the sales window.
    Returns {softech_id: {is_imported, origin_code, pack_price, cost_price,
                          category_softech_id}}.
    Now includes category for Feature 7 (category_code wiring).
    """
    from apps.catalog.models import Item
    if not item_codes:
        return {}
    rows = Item.objects.filter(softech_id__in=item_codes).select_related('category').values(
        'softech_id', 'is_imported', 'origin_code', 'pack_price', 'cost_price',
        'category__softech_id',
    )
    return {
        r['softech_id']: {
            **r,
            'category_softech_id': r['category__softech_id'] or '',
        }
        for r in rows
    }


# ── Rule matching ─────────────────────────────────────────────────────────────

def _find_matching_rule(
    rules,
    rule_item_sets,
    item_code:         str,
    person_code:       str,
    branch_code:       str,
    qty:               Decimal,
    erp_dt:            datetime | None,
    total_period_qty:  Decimal,
    item_expiry_date:  date | None    = None,
    item_attr_map:     dict           = None,
):
    """
    Return the highest-priority matching IncentiveRule for one ERP sale line.

    Filter order (lower priority number = higher priority):
      1.  person_code_filter      (optional, existing)
      2.  branch_filter           (optional, existing)
      3.  time_window             (optional, existing)
      4.  item scope              (item_code OR rule_item_sets, existing)
      5.  min_qty gate            (per-transaction, existing)
      6.  min_total_qty_in_period (aggregate gate, existing)
      7.  expiry_within_days      (near-expiry filter — was stored but never applied, NOW WIRED)
      8.  is_imported_filter      (origin local/imported, NEW)
      9.  origin_codes            (specific country codes, NEW)
      10. margin filter           (margin_min / margin_max, NEW)
      11. pack price filter       (pack_price_min / pack_price_max, NEW)

    Returns None if no rule matches.
    """
    for rule in rules:
        # ── 1. Person code filter ─────────────────────────────────────────────
        if rule.person_code_filter and rule.person_code_filter != person_code:
            continue

        # ── 2. Branch filter ──────────────────────────────────────────────────
        if rule.branch_filter and rule.branch_filter != branch_code:
            continue

        # ── 3. Time window ────────────────────────────────────────────────────
        if rule.time_window_start and rule.time_window_end and erp_dt:
            t = erp_dt.time()
            if not (rule.time_window_start <= t <= rule.time_window_end):
                continue

        # ── 4. Item scope ─────────────────────────────────────────────────────
        # Priority order: single item_code > rule_items list > category_code > wildcard
        if rule.item_code:
            if rule.item_code != item_code:
                continue
        elif rule_item_sets.get(rule.id):
            if item_code not in rule_item_sets[rule.id]:
                continue
        elif rule.category_code:
            # Feature 7: category-level rule — wire category_code (was "informational only")
            attrs = (item_attr_map or {}).get(item_code)
            if attrs is None or attrs.get('category_softech_id', '') != rule.category_code:
                continue
        # else: no targeting = wildcard (applies to all items that pass other filters)

        # ── 5. Per-transaction qty gate ───────────────────────────────────────
        if qty < rule.min_qty:
            continue

        # ── 6. Period aggregate qty gate ──────────────────────────────────────
        if rule.min_total_qty_in_period and total_period_qty < rule.min_total_qty_in_period:
            continue

        # ── 7. Near-expiry filter (expiry_within_days) ────────────────────────
        if rule.expiry_within_days:
            if item_expiry_date is None:
                # No expiry info on this transaction line — cannot qualify
                continue
            sale_date = erp_dt.date() if erp_dt else None
            if sale_date is None:
                continue
            days_remaining = (item_expiry_date - sale_date).days
            # Must be non-negative (not already expired) and within threshold
            if not (0 <= days_remaining <= rule.expiry_within_days):
                continue

        # ── 8. Origin: local / imported filter ───────────────────────────────
        if rule.is_imported_filter != 'any':
            attrs = (item_attr_map or {}).get(item_code)
            if attrs is not None:
                is_imp = bool(attrs['is_imported'])
                if rule.is_imported_filter == 'local' and is_imp:
                    continue
                if rule.is_imported_filter == 'imported' and not is_imp:
                    continue
            # If attrs missing, we allow (fail-open) to avoid silently dropping
            # transactions when catalog is incomplete

        # ── 9. Origin codes whitelist ─────────────────────────────────────────
        if rule.origin_codes:
            attrs = (item_attr_map or {}).get(item_code)
            if attrs is not None:
                origin = _to_str(attrs['origin_code'])
                if origin not in rule.origin_codes:
                    continue

        # ── 10. Margin filter ─────────────────────────────────────────────────
        if rule.margin_min is not None or rule.margin_max is not None:
            attrs = (item_attr_map or {}).get(item_code)
            if attrs is not None:
                pack_price = _to_decimal(attrs['pack_price'])
                cost_price = _to_decimal(attrs['cost_price'])
                if pack_price > 0:
                    margin_pct = (pack_price - cost_price) / pack_price * Decimal('100')
                    if rule.margin_min is not None and margin_pct < rule.margin_min:
                        continue
                    if rule.margin_max is not None and margin_pct > rule.margin_max:
                        continue
                else:
                    # Cannot calculate margin (zero price) — skip this rule
                    continue

        # ── 11. Pack price filter ─────────────────────────────────────────────
        if rule.pack_price_min is not None or rule.pack_price_max is not None:
            attrs = (item_attr_map or {}).get(item_code)
            if attrs is not None:
                pack_price = _to_decimal(attrs['pack_price'])
                if rule.pack_price_min is not None and pack_price < rule.pack_price_min:
                    continue
                if rule.pack_price_max is not None and pack_price > rule.pack_price_max:
                    continue

        return rule

    return None


# ── Incentive calculation ─────────────────────────────────────────────────────

def _calc_incentive(rule, qty: Decimal, unit_price: Decimal,
                    item_code: str, rule_item_map: dict,
                    total_period_qty: Decimal,
                    doc_no: str,
                    processed_transactions: set) -> Decimal:
    """Compute the positive incentive amount for one qualifying sale line."""
    effective_value = rule.incentive_value
    effective_type  = rule.incentive_type

    ri = rule_item_map.get((rule.id, item_code))
    if ri is not None and ri.incentive_override is not None:
        effective_value = ri.incentive_override

    if effective_type == 'target_based':
        return _calc_target_based_incentive(rule, qty, unit_price, total_period_qty)

    if effective_type == 'tiered':
        return _calc_tiered_incentive(rule, qty, unit_price, total_period_qty)

    if effective_type == 'fixed_per_transaction':
        key = (doc_no, rule.id)
        if key in processed_transactions:
            return Decimal('0')
        processed_transactions.add(key)
        return effective_value.quantize(Decimal('0.0001'))

    if effective_type == 'percent':
        return (qty * unit_price * effective_value / Decimal('100')
                ).quantize(Decimal('0.0001'))

    return (qty * effective_value).quantize(Decimal('0.0001'))


# ── Person-code ↔ StaffProfile map ───────────────────────────────────────────

def _build_person_code_map(user_ids=None) -> dict:
    from apps.users.models import StaffProfile
    qs = StaffProfile.objects.select_related('user').exclude(softech_user_id='')
    if user_ids:
        qs = qs.filter(id__in=user_ids)
    return {p.softech_user_id.strip(): p
            for p in qs
            if p.softech_user_id.strip()}


# ── CalculationResult ─────────────────────────────────────────────────────────

class CalculationResult(NamedTuple):
    created:              int
    total_by_user:        dict   # {str(staff_id): float}
    user_summaries:       list   # [{user_id, user_name, person_code, total}]
    skipped_person_codes: list
    simulated:            bool
    log_id:               int | None
    # Only populated in simulate mode with write_log=False (for get_my_progress)
    raw_transactions:     list  = []   # list of pending transaction dicts
    total_qty_map:        dict  = {}   # {(staff_id, item_code): Decimal}


# ── Near-expiry stock query (for dashboard — uses stkbalexpiry) ───────────────
#
# IMPORTANT data facts (verified against live SOFTECHDB9):
#   • stkbalexpiry.branchcode is ALWAYS 0 — it is NOT populated. The real
#     physical location is stkbalexpiry.storecode (100,101,102,103,104,105,110,160).
#   • storecodes 102, 103, 105 are quarantine / expired-stock holding stores
#     (catalog.EXCLUDED_STORE_CODES). Stock there is NOT sellable, so it is
#     excluded by default — a near-expiry SELLING incentive only cares about
#     stock still on the sellable shelf.
#   • The table also retains already-expired rows (itemexpirydate < today) and
#     zero-qty rows — both filtered out by default.
#
# This dashboard is purely informational. The incentive ENGINE itself does not
# use this table — it reads stktrans.itemexpirydate directly.

# Hard cap on rows returned to protect the API / frontend from unbounded payloads.
_NEAR_EXPIRY_STOCK_LIMIT = 2000


def _expiry_bucket(days_rem):
    """Map days-remaining to a bucket label.  Single source of truth."""
    if days_rem is None:
        return 'unknown'
    if days_rem <= 30:
        return '0-30'
    if days_rem <= 60:
        return '31-60'
    if days_rem <= 90:
        return '61-90'
    if days_rem <= 180:
        return '91-180'
    return '181+'


def fetch_near_expiry_stock(
    expiry_within_days: int,
    store_codes: list | None = None,
    item_codes: list | None  = None,
    include_quarantine: bool = False,
    include_zero_qty: bool   = False,
    limit: int               = _NEAR_EXPIRY_STOCK_LIMIT,
) -> list:
    """
    Query stkbalexpiry for items expiring within N days.

    Parameters
    ----------
    expiry_within_days : only rows expiring within this many days from today
    store_codes        : optional list of storecode values to include
    item_codes         : optional list of itemcode values to include
    include_quarantine : if False (default), exclude quarantine stores 102/103/105
    include_zero_qty   : if False (default), exclude rows with itemqty <= 0
    limit              : max rows returned (most-urgent first)

    Returns list of dicts:
      {itemcode, item_name, itemexpirydate, itemqty, storecode, branchcode,
       batchno, days_remaining, expiry_bucket, is_quarantine}
    """
    from config.sybase import get_sybase_connection
    from apps.catalog.models import EXCLUDED_STORE_CODES

    today = date.today()
    cutoff_date = today + timedelta(days=expiry_within_days)

    # ── Location filter — use storecode (branchcode is always 0) ──────────────
    store_filter = ''
    if store_codes:
        quoted = ', '.join(f"'{c}'" for c in store_codes)
        store_filter = f"AND sbe.storecode IN ({quoted})"

    # ── Quarantine exclusion (default) ────────────────────────────────────────
    quarantine_filter = ''
    if not include_quarantine:
        quoted = ', '.join(f"'{c}'" for c in sorted(EXCLUDED_STORE_CODES))
        quarantine_filter = f"AND sbe.storecode NOT IN ({quoted})"

    item_filter = ''
    if item_codes:
        quoted = ', '.join(f"'{c}'" for c in item_codes)
        item_filter = f"AND sbe.itemcode IN ({quoted})"

    qty_filter = '' if include_zero_qty else 'AND sbe.itemqty > 0'

    safe_limit = max(1, min(int(limit or _NEAR_EXPIRY_STOCK_LIMIT), 10000))

    sql = f"""
        SET ROWCOUNT {safe_limit}
        SELECT
            sbe.itemcode,
            sbe.itemexpirydate,
            sbe.itemqty,
            sbe.branchcode,
            sbe.storecode,
            sbe.batchno,
            i.itemname
        FROM SOFTECHDB9.dbo.stkbalexpiry sbe
        JOIN SOFTECHDB9.dbo.items i ON i.itemcode = sbe.itemcode
        WHERE sbe.itemexpirydate >= '{today.strftime('%Y-%m-%d')} 00:00:00'
          AND sbe.itemexpirydate <= '{cutoff_date.strftime('%Y-%m-%d')} 23:59:59'
          {qty_filter}
          {store_filter}
          {quarantine_filter}
          {item_filter}
        ORDER BY sbe.itemexpirydate ASC, sbe.itemcode
        SET ROWCOUNT 0
    """

    conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
    finally:
        conn.close()

    quarantine_set = set(EXCLUDED_STORE_CODES)
    results = []
    for row in rows:
        item_code     = _to_str(row[0])
        expiry_dt     = _to_date(row[1])
        item_qty      = _to_decimal(row[2])
        branch_code   = _to_str(row[3])
        store_code    = _to_str(row[4])
        batch_no      = _to_str(row[5])
        item_name     = _to_str(row[6])

        days_rem = (expiry_dt - today).days if expiry_dt else None

        results.append({
            'itemcode':        item_code,
            'item_name':       item_name,
            'itemexpirydate':  expiry_dt.isoformat() if expiry_dt else None,
            'itemqty':         float(item_qty),
            'storecode':       store_code,
            'branchcode':      branch_code,   # kept for reference (always '0')
            'batchno':         batch_no,
            'days_remaining':  days_rem,
            'expiry_bucket':   _expiry_bucket(days_rem),
            'is_quarantine':   store_code in quarantine_set,
        })

    return results


# ── Main engine ───────────────────────────────────────────────────────────────

def calculate(
    program_id: int,
    period_start: date,
    period_end:   date,
    *,
    user_ids:     list | None  = None,
    simulate:     bool         = False,
    force:        bool         = False,
    triggered_by = None,
    write_log:    bool         = True,   # False for silent progress checks
) -> CalculationResult:
    """
    Run (or simulate) the incentive calculation.

    Parameters
    ----------
    program_id   : IncentiveProgram.pk
    period_start : inclusive start date
    period_end   : inclusive end date
    user_ids     : optional list of StaffProfile PKs to restrict processing
    simulate     : if True, compute results without writing to DB
    force        : if True, recalculate even if settlements are finalized
    triggered_by : StaffProfile running this (written to CalcLog)
    """
    from .models import (
        IncentiveProgram, IncentiveTransaction, IncentiveSettlement,
        IncentiveCalculationLog,
    )

    t_start = time.monotonic()

    program = IncentiveProgram.objects.get(pk=program_id)

    # ── Guard: finalization lock ──────────────────────────────────────────────
    if not simulate:
        locked = IncentiveSettlement.objects.filter(
            program=program,
            period_start=period_start,
            period_end=period_end,
            is_finalized=True,
        )
        if locked.exists() and not force:
            raise ValueError(
                f'Period {period_start}→{period_end} has finalized settlements for '
                f'"{program.name}". Pass force=True to recalculate.'
            )
        if locked.exists() and force:
            logger.warning(
                'calculate: force-recalculating finalized period %s->%s for program %d',
                period_start, period_end, program_id,
            )
            locked.update(is_finalized=False, finalized_at=None, finalized_by=None)

    # ── Load active rules (sorted by priority ASC, prefetch rule_items) ───────
    rules = list(
        program.rules
        .filter(is_active=True)
        .prefetch_related('rule_items')
        .order_by('priority', 'item_code')
    )
    if not rules:
        logger.warning('calculate: program %d has no active rules', program_id)
        return CalculationResult(0, {}, [], [], simulate, None)

    rule_item_sets, rule_item_map = _build_rule_item_sets(rules)

    # ── Build person_code map ONCE ────────────────────────────────────────────
    person_map = _build_person_code_map(user_ids)
    person_codes = list(person_map.keys()) if user_ids else None

    if not person_map:
        logger.warning('calculate: no StaffProfiles with softech_user_id found')
        return CalculationResult(0, {}, [], [], simulate, None)

    # ── Fetch ERP data ────────────────────────────────────────────────────────
    try:
        sales_rows = _fetch_rows(
            _SALES_DOCCODE, period_start, period_end, person_codes,
            use_returns_template=False,
        )
        returns_rows = _fetch_rows(
            _RETURNS_DOCCODE, period_start, period_end, person_codes,
            use_returns_template=True,   # use template with real r_docnumber
        )
        future_return_rows = _fetch_cross_period_returns(period_end, person_codes)
    except Exception as exc:
        logger.error('calculate: Softech fetch failed -- %s', exc, exc_info=True)
        raise

    logger.info(
        'calculate: program=%d period=%s->%s sales=%d returns=%d future_returns=%d',
        program_id, period_start, period_end,
        len(sales_rows), len(returns_rows), len(future_return_rows),
    )

    # ── Build item attribute map (for origin / margin / price filters) ────────
    needs_attrs = _rules_need_item_attrs(rules)
    if needs_attrs:
        all_item_codes = {
            _to_str(row[_COL_ITEMCODE])
            for row in sales_rows
            if _to_str(row[_COL_ITEMCODE])
        }
        item_attr_map = _build_item_attr_map(all_item_codes)
        logger.info('calculate: loaded item_attrs for %d items', len(item_attr_map))
    else:
        item_attr_map = {}

    # ── Pre-aggregate: total qty per (staff_id, item_code) for tiered rules ───
    total_qty_by_user_item: dict[tuple, Decimal] = defaultdict(Decimal)
    for row in sales_rows:
        person_code = _to_str(row[_COL_USERCODE])
        item_code   = _to_str(row[_COL_ITEMCODE])
        qty         = _to_decimal(row[_COL_TRANSQTY])
        staff       = person_map.get(person_code)
        if staff and qty > 0 and item_code:
            total_qty_by_user_item[(staff.id, item_code)] += qty

    # ── Build in-period return quantity map ───────────────────────────────────
    # Key: (ref_doc_no, item_code) → total returned qty (positive)
    # Now using REAL r_docnumber from returns SQL (bug fix in v5).
    returned_qty_map: dict[tuple, Decimal] = defaultdict(Decimal)
    for row in returns_rows:
        ref_doc = _to_str(row[_COL_R_DOCNUMBER])
        icode   = _to_str(row[_COL_ITEMCODE])
        qty     = _to_decimal(row[_COL_TRANSQTY])
        if ref_doc and icode and qty > 0:
            returned_qty_map[(ref_doc, icode)] += qty

    # ── Build sale doc_no set for cross-period filtering ──────────────────────
    sale_doc_nos: set = {
        _to_str(row[_COL_DOCNUMBER])
        for row in sales_rows
        if _to_str(row[_COL_DOCNUMBER])
    }

    cross_period_returns = [
        row for row in future_return_rows
        if _to_str(row[_COL_R_DOCNUMBER]) in sale_doc_nos
    ]

    # ── Build transactions (in-memory) ────────────────────────────────────────
    to_create:   list = []
    total_by_user: dict  = {}
    skipped_codes: list  = []
    processed_transactions: set = set()

    # ─── Pass 1: in-period sales ──────────────────────────────────────────────
    for row in sales_rows:
        doc_no      = _to_str(row[_COL_DOCNUMBER])
        person_code = _to_str(row[_COL_USERCODE])
        item_code   = _to_str(row[_COL_ITEMCODE])
        qty         = _to_decimal(row[_COL_TRANSQTY])
        price       = _to_decimal(row[_COL_PRICE])
        branch_code = _to_str(row[_COL_BRANCHCODE])
        erp_dt      = _to_datetime(row[_COL_DOCDATE])
        erp_date    = erp_dt.date() if erp_dt else None

        # Near-expiry: extract itemexpirydate from column [9]
        item_expiry_date = (
            _to_date(row[_COL_EXPIRY_DATE])
            if len(row) > _COL_EXPIRY_DATE else None
        )

        if qty <= 0 or not item_code or not person_code:
            continue

        staff = person_map.get(person_code)
        if staff is None:
            if person_code not in skipped_codes:
                skipped_codes.append(person_code)
            continue

        total_period_qty = total_qty_by_user_item.get((staff.id, item_code), Decimal('0'))

        rule = _find_matching_rule(
            rules, rule_item_sets, item_code, person_code, branch_code,
            qty, erp_dt, total_period_qty,
            item_expiry_date=item_expiry_date,
            item_attr_map=item_attr_map,
        )
        if rule is None:
            continue

        returned = returned_qty_map.get((doc_no, item_code), Decimal('0'))
        is_reversed = (returned >= qty)

        incentive_amt = _calc_incentive(
            rule, qty, price, item_code, rule_item_map,
            total_period_qty, doc_no, processed_transactions,
        )

        # Calculate expiry_days_remaining for audit trail
        expiry_days_remaining = None
        if item_expiry_date and erp_date:
            expiry_days_remaining = (item_expiry_date - erp_date).days

        to_create.append(dict(
            program=program, rule=rule, user=staff,
            item_code=item_code, item_name=_to_str(row[_COL_ITEMNAME]),
            doc_no=doc_no, doc_type='sale', ref_doc_no='',
            quantity=qty, unit_price=price,
            incentive_amount=incentive_amt,
            is_reversed=is_reversed,
            is_cross_period_return=False,
            period_start=period_start, period_end=period_end,
            erp_date=erp_date, branch_code=branch_code,
            expiry_date=item_expiry_date,
            expiry_days_remaining=expiry_days_remaining,
        ))
        total_by_user.setdefault(staff.id, Decimal('0'))
        total_by_user[staff.id] += incentive_amt

    # ─── Pass 2: in-period returns (negative) ────────────────────────────────
    for row in returns_rows:
        doc_no      = _to_str(row[_COL_DOCNUMBER])
        person_code = _to_str(row[_COL_USERCODE])
        item_code   = _to_str(row[_COL_ITEMCODE])
        qty         = _to_decimal(row[_COL_TRANSQTY])
        price       = _to_decimal(row[_COL_PRICE])
        ref_doc_no  = _to_str(row[_COL_R_DOCNUMBER])
        branch_code = _to_str(row[_COL_BRANCHCODE])
        erp_dt      = _to_datetime(row[_COL_DOCDATE])
        erp_date    = erp_dt.date() if erp_dt else None

        item_expiry_date = (
            _to_date(row[_COL_EXPIRY_DATE])
            if len(row) > _COL_EXPIRY_DATE else None
        )

        if qty <= 0 or not item_code or not person_code:
            continue

        staff = person_map.get(person_code)
        if staff is None:
            continue

        total_period_qty = total_qty_by_user_item.get((staff.id, item_code), Decimal('0'))

        rule = _find_matching_rule(
            rules, rule_item_sets, item_code, person_code, branch_code,
            qty, erp_dt, total_period_qty,
            item_expiry_date=item_expiry_date,
            item_attr_map=item_attr_map,
        )
        if rule is None:
            continue

        incentive_amt = -_calc_incentive(
            rule, qty, price, item_code, rule_item_map,
            total_period_qty, doc_no, set(),
        )

        expiry_days_remaining = None
        if item_expiry_date and erp_date:
            expiry_days_remaining = (item_expiry_date - erp_date).days

        to_create.append(dict(
            program=program, rule=rule, user=staff,
            item_code=item_code, item_name=_to_str(row[_COL_ITEMNAME]),
            doc_no=doc_no, doc_type='return', ref_doc_no=ref_doc_no,
            quantity=-qty, unit_price=price,
            incentive_amount=incentive_amt,
            is_reversed=False,
            is_cross_period_return=False,
            period_start=period_start, period_end=period_end,
            erp_date=erp_date, branch_code=branch_code,
            expiry_date=item_expiry_date,
            expiry_days_remaining=expiry_days_remaining,
        ))
        total_by_user.setdefault(staff.id, Decimal('0'))
        total_by_user[staff.id] += incentive_amt

    # ─── Pass 3: cross-period returns ────────────────────────────────────────
    for row in cross_period_returns:
        doc_no      = _to_str(row[_COL_DOCNUMBER])
        person_code = _to_str(row[_COL_USERCODE])
        item_code   = _to_str(row[_COL_ITEMCODE])
        qty         = _to_decimal(row[_COL_TRANSQTY])
        price       = _to_decimal(row[_COL_PRICE])
        ref_doc_no  = _to_str(row[_COL_R_DOCNUMBER])
        branch_code = _to_str(row[_COL_BRANCHCODE])
        erp_dt      = _to_datetime(row[_COL_DOCDATE])
        erp_date    = erp_dt.date() if erp_dt else None

        item_expiry_date = (
            _to_date(row[_COL_EXPIRY_DATE])
            if len(row) > _COL_EXPIRY_DATE else None
        )

        if qty <= 0 or not item_code or not person_code:
            continue

        staff = person_map.get(person_code)
        if staff is None:
            continue

        total_period_qty = total_qty_by_user_item.get((staff.id, item_code), Decimal('0'))

        rule = _find_matching_rule(
            rules, rule_item_sets, item_code, person_code, branch_code,
            qty, None,
            total_period_qty,
            item_expiry_date=item_expiry_date,
            item_attr_map=item_attr_map,
        )
        if rule is None:
            continue

        incentive_amt = -_calc_incentive(
            rule, qty, price, item_code, rule_item_map,
            total_period_qty, doc_no, set(),
        )

        expiry_days_remaining = None
        if item_expiry_date and erp_date:
            expiry_days_remaining = (item_expiry_date - erp_date).days

        to_create.append(dict(
            program=program, rule=rule, user=staff,
            item_code=item_code, item_name=_to_str(row[_COL_ITEMNAME]),
            doc_no=doc_no, doc_type='return', ref_doc_no=ref_doc_no,
            quantity=-qty, unit_price=price,
            incentive_amount=incentive_amt,
            is_reversed=False,
            is_cross_period_return=True,
            period_start=period_start, period_end=period_end,
            erp_date=erp_date, branch_code=branch_code,
            expiry_date=item_expiry_date,
            expiry_days_remaining=expiry_days_remaining,
        ))
        total_by_user.setdefault(staff.id, Decimal('0'))
        total_by_user[staff.id] += incentive_amt

    # ── Build user_summaries ──────────────────────────────────────────────────
    id_to_profile = {p.id: p for p in person_map.values()}
    user_summaries = []
    for uid, total in sorted(total_by_user.items(), key=lambda x: -x[1]):
        profile = id_to_profile.get(uid)
        name  = profile.full_name if profile else f'#{uid}'
        pcode = profile.softech_user_id if profile else ''
        user_summaries.append({
            'user_id':     uid,
            'user_name':   name,
            'person_code': pcode,
            'total':       float(total),
        })

    # ── Simulation mode ───────────────────────────────────────────────────────
    if simulate:
        logger.info(
            'simulate: program=%d would create %d transactions',
            program_id, len(to_create),
        )
        duration = time.monotonic() - t_start
        log_id = None
        if write_log:
            from django.utils import timezone
            log_entry = IncentiveCalculationLog.objects.create(
                program=program,
                triggered_by=triggered_by,
                period_start=period_start,
                period_end=period_end,
                mode='simulate',
                status='done',
                transactions_created=len(to_create),
                skipped_person_codes=skipped_codes,
                user_summaries={str(s['user_id']): s for s in user_summaries},
                duration_seconds=round(duration, 2),
                finished_at=timezone.now(),
            )
            log_id = log_entry.id
        return CalculationResult(
            created=len(to_create),
            total_by_user={str(uid): float(v) for uid, v in total_by_user.items()},
            user_summaries=user_summaries,
            skipped_person_codes=skipped_codes,
            simulated=True,
            log_id=log_id,
            # pass through the in-memory to_create for get_my_progress detail
            raw_transactions=to_create,
            total_qty_map=dict(total_qty_by_user_item),
        )

    # ── Persist ───────────────────────────────────────────────────────────────
    deleted, _ = IncentiveTransaction.objects.filter(
        program=program,
        period_start=period_start,
        period_end=period_end,
    ).delete()
    if deleted:
        logger.info('calculate: deleted %d stale transactions', deleted)

    IncentiveTransaction.objects.bulk_create(
        [IncentiveTransaction(**kw) for kw in to_create],
        batch_size=500,
    )

    duration = time.monotonic() - t_start
    from django.utils import timezone
    log_entry = IncentiveCalculationLog.objects.create(
        program=program,
        triggered_by=triggered_by,
        period_start=period_start,
        period_end=period_end,
        mode='calculate',
        status='done',
        transactions_created=len(to_create),
        skipped_person_codes=skipped_codes,
        user_summaries={str(s['user_id']): s for s in user_summaries},
        finished_at=timezone.now(),
        duration_seconds=round(duration, 2),
    )

    logger.info(
        'calculate: DONE program=%d period=%s->%s created=%d skipped=%s duration=%.1fs',
        program_id, period_start, period_end, len(to_create),
        skipped_codes or 'none', duration,
    )

    return CalculationResult(
        created=len(to_create),
        total_by_user={str(uid): float(v) for uid, v in total_by_user.items()},
        user_summaries=user_summaries,
        skipped_person_codes=skipped_codes,
        simulated=False,
        log_id=log_entry.id,
    )


def simulate_only(
    program_id: int,
    period_start: date,
    period_end: date,
    *,
    user_ids=None,
    triggered_by=None,
) -> CalculationResult:
    """Convenience wrapper — preview without any DB transaction writes."""
    return calculate(
        program_id, period_start, period_end,
        user_ids=user_ids, simulate=True, triggered_by=triggered_by,
    )


# ── Employee Progress Dashboard  (Feature 1) ─────────────────────────────────

def get_my_progress(staff_profile) -> list:
    """
    Feature 1 — Employee Live Progress Dashboard.

    For each active IncentiveProgram that covers today, run a silent simulation
    scoped to this employee (period_start → today).

    Returns list of program_progress dicts:
    {
      program_id, program_name,
      period_start, period_end,
      period_days_total, period_days_elapsed, period_days_remaining,
      earned_to_date,        -- actual incentive from start to today
      projected_total,       -- linear projection to period_end
      top_items,             -- [{item_code, item_name, incentive, qty}]
      slab_progress,         -- [{rule_id, rule_name, current_qty, next_slab_at,
                                  units_needed, current_rate, next_rate}] for tiered/target
      rule_breakdown,        -- [{rule_id, rule_name, incentive}]
    }
    """
    from .models import IncentiveProgram

    today = date.today()

    # All active programs where today falls within the period
    active_programs = IncentiveProgram.objects.filter(
        is_active=True,
        start_date__lte=today,
        end_date__gte=today,
    ).prefetch_related('rules__rule_items')

    results = []

    for program in active_programs:
        rules = list(program.rules.filter(is_active=True))
        if not rules:
            continue

        period_start = program.start_date
        period_end   = program.end_date

        # Simulate from period_start to today (not full period)
        try:
            result = calculate(
                program.id,
                period_start,
                today,   # simulate only up to today
                user_ids=[staff_profile.id],
                simulate=True,
                write_log=False,  # silent — don't pollute the audit log
            )
        except Exception as exc:
            logger.warning('get_my_progress: program %d failed — %s', program.id, exc)
            continue

        earned = float(result.total_by_user.get(str(staff_profile.id), 0.0))

        # Linear projection to period_end
        days_total   = (period_end   - period_start).days + 1
        days_elapsed = (today        - period_start).days + 1
        days_remaining = (period_end - today).days

        if days_elapsed > 0:
            projected = earned / days_elapsed * days_total
        else:
            projected = 0.0

        # Top items by incentive amount
        item_map: dict = defaultdict(lambda: {'item_code': '', 'item_name': '', 'incentive': 0.0, 'qty': 0.0})
        rule_map: dict = defaultdict(lambda: {'rule_id': 0, 'rule_name': '', 'incentive': 0.0})

        for txn in result.raw_transactions:
            if txn['doc_type'] == 'sale':
                k = txn['item_code']
                item_map[k]['item_code']  = txn['item_code']
                item_map[k]['item_name']  = txn['item_name']
                item_map[k]['incentive'] += float(txn['incentive_amount'])
                item_map[k]['qty']       += float(txn['quantity'])
            if txn.get('rule'):
                rid = txn['rule'].id
                rule_map[rid]['rule_id']   = rid
                rule_map[rid]['rule_name'] = txn['rule'].rule_name or txn['item_name']
                rule_map[rid]['incentive'] += float(txn['incentive_amount'])

        top_items = sorted(item_map.values(), key=lambda x: -x['incentive'])[:5]
        rule_breakdown = sorted(rule_map.values(), key=lambda x: -x['incentive'])

        # Slab/target progress — for tiered and target_based rules
        slab_progress = []
        total_qty_map = result.total_qty_map  # {(staff_id, item_code): Decimal}

        for rule in rules:
            if rule.incentive_type not in ('tiered', 'target_based'):
                continue

            # Get all item codes for this rule
            if rule.item_code:
                target_codes = [rule.item_code]
            else:
                target_codes = [ri.item_code for ri in rule.rule_items.all()]

            for item_code in target_codes:
                current_qty = float(
                    total_qty_map.get((staff_profile.id, item_code), Decimal('0'))
                )

                if rule.incentive_type == 'tiered':
                    config = rule.slab_config or {}
                    slabs  = config.get('slabs', [])
                    current_rate = 0.0
                    next_rate    = None
                    next_at      = None
                    units_needed = None

                    for i, slab in enumerate(slabs):
                        min_q = float(slab.get('min_qty', 0))
                        max_q = slab.get('max_qty')
                        if current_qty >= min_q and (max_q is None or current_qty <= float(max_q)):
                            current_rate = float(slab.get('rate', 0))
                            if i + 1 < len(slabs):
                                next_slab = slabs[i + 1]
                                next_at = float(next_slab.get('min_qty', 0))
                                next_rate = float(next_slab.get('rate', 0))
                                units_needed = max(0.0, next_at - current_qty)
                            break

                    slab_progress.append({
                        'rule_id':     rule.id,
                        'rule_name':   rule.rule_name or item_code,
                        'item_code':   item_code,
                        'current_qty': current_qty,
                        'current_rate': current_rate,
                        'next_slab_at': next_at,
                        'next_rate':   next_rate,
                        'units_needed': units_needed,
                        'type':        'tiered',
                    })

                elif rule.incentive_type == 'target_based':
                    target_qty = float(getattr(rule, 'target_qty', 0) or 0)
                    if target_qty > 0:
                        achievement_pct = current_qty / target_qty * 100
                        units_needed_100 = max(0.0, target_qty - current_qty)

                        slab_progress.append({
                            'rule_id':        rule.id,
                            'rule_name':      rule.rule_name or item_code,
                            'item_code':      item_code,
                            'current_qty':    current_qty,
                            'target_qty':     target_qty,
                            'achievement_pct': round(achievement_pct, 1),
                            'units_to_100pct': units_needed_100,
                            'type':           'target_based',
                        })

        results.append({
            'program_id':       program.id,
            'program_name':     program.name,
            'period_start':     period_start.isoformat(),
            'period_end':       period_end.isoformat(),
            'period_days_total':     days_total,
            'period_days_elapsed':   days_elapsed,
            'period_days_remaining': days_remaining,
            'earned_to_date':    round(earned, 2),
            'projected_total':   round(projected, 2),
            'top_items':         top_items,
            'slab_progress':     slab_progress,
            'rule_breakdown':    rule_breakdown,
        })

    return results
