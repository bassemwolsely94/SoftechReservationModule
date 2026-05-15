"""
apps/incentives/engine.py  —  v3

Item-Based Incentive Calculation Engine
=========================================
Main entry points:
  calculate(program_id, period_start, period_end, *, user_ids=None, simulate=False, force=False)
  simulate_only(program_id, period_start, period_end, *, user_ids=None)   ← convenience wrapper

Changes in v3 vs v2:
  ─────────────────────────────────────────────────────────────────────────────
  • Removed `i.groupcode` from the SQL query — this column does not exist in the
    SOFTECH `items` table and caused:
      com.sybase.jdbc3.jdbc.SybSQLException: Invalid column name 'groupcode'
    Category-code matching has been removed from the engine; the `category_code`
    field on IncentiveRule is kept on the model for informational/labelling use
    only and is no longer evaluated by the engine.

  • Multi-item rule support via IncentiveRuleItem:
    A rule can now target either:
      (a) A single item_code stored directly on IncentiveRule.item_code (legacy /
          backward-compatible), OR
      (b) Any number of items stored in IncentiveRuleItem linked to the rule.
    Both are evaluated; (a) takes precedence over (b) in matching order.

  • Per-item incentive override:
    IncentiveRuleItem.incentive_override, when set, overrides the rule's global
    incentive_value for that specific item code.

  • Rule items are prefetched ONCE before the hot loop (not per-row).

  All v2 design decisions (returns = negative, no double-counting, finalization
  lock, idempotency, bulk_create) are preserved unchanged.
  ─────────────────────────────────────────────────────────────────────────────
"""
import logging
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

logger = logging.getLogger('elrezeiky.incentives')

# ── Column indices — SELECT order MUST match _SALES_SQL_TEMPLATE ──────────────
_COL_DOCNUMBER   = 0
_COL_PHCODE      = 1
_COL_DOCDATE     = 2
_COL_BRANCHCODE  = 3
_COL_R_DOCNUMBER = 4
_COL_ITEMCODE    = 5
_COL_ITEMNAME    = 6
# NOTE: groupcode (was col 7) removed — column does not exist in SOFTECH items
_COL_TRANSQTY    = 7   # was 8
_COL_PRICE       = 8   # was 9

_SALES_DOCCODE   = '115'
_RETURNS_DOCCODE = '30'

_SALES_SQL_TEMPLATE = """\
SELECT
    m.docnumber,
    m.phcode,
    m.docdate,
    m.branchcode,
    m.r_docnumber,
    d.itemcode,
    i.itemname,
    d.transqty,
    d.itemsaleprice
FROM SOFTECHDB9.dbo.stktransm m
JOIN SOFTECHDB9.dbo.stktrans d
    ON d.doccode = m.doccode AND d.docnumber = m.docnumber
JOIN SOFTECHDB9.dbo.items i ON i.itemcode = d.itemcode
WHERE m.doccode = '{doc_code}'
  AND CONVERT(DATE, m.docdate) >= '{start}'
  AND CONVERT(DATE, m.docdate) <= '{end}'
  {person_filter}
ORDER BY m.docdate, m.docnumber, d.itemcode"""


# ── Sybase helpers ────────────────────────────────────────────────────────────

def _fetch_rows(doc_code: str, start: date, end: date, person_codes=None) -> list:
    """Open one Sybase connection, run the query, return all rows, close."""
    from config.sybase import get_sybase_connection

    person_filter = ''
    if person_codes:
        quoted = ', '.join(f"'{c}'" for c in person_codes)
        person_filter = f'AND m.phcode IN ({quoted})'

    sql = _SALES_SQL_TEMPLATE.format(
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


# ── Rule item helpers ─────────────────────────────────────────────────────────

def _build_rule_item_sets(rules) -> tuple[dict, dict]:
    """
    Returns two dicts built from pre-fetched rule_items:
      rule_item_sets  : {rule.id: frozenset of item_codes}
      rule_item_map   : {(rule.id, item_code): IncentiveRuleItem}  — for override lookup
    """
    rule_item_sets: dict[int, frozenset] = {}
    rule_item_map:  dict[tuple, object]  = {}
    for rule in rules:
        items = list(rule.rule_items.all())   # already prefetched
        rule_item_sets[rule.id] = frozenset(ri.item_code for ri in items)
        for ri in items:
            rule_item_map[(rule.id, ri.item_code)] = ri
    return rule_item_sets, rule_item_map


# ── Rule matching ─────────────────────────────────────────────────────────────

def _find_matching_rule(rules, rule_item_sets, item_code: str,
                        person_code: str, qty: Decimal):
    """
    Return the highest-priority matching rule for an ERP line.

    Matching logic (in order of precedence):
      1. rule.item_code (single legacy field) — exact match
      2. item_code in rule_item_sets[rule.id] (multi-item set)
      3. If neither is configured the rule is skipped (no catch-all).

    Rules MUST be sorted by (-priority, item_code) before passing in.
    Returns None if nothing matches.
    """
    for rule in rules:
        # Scope: person_code filter (optional — blank = all)
        if rule.person_code_filter and rule.person_code_filter != person_code:
            continue

        # Item scope
        if rule.item_code:
            # Legacy single-item match
            if rule.item_code != item_code:
                continue
        else:
            item_set = rule_item_sets.get(rule.id)
            if not item_set:
                # Rule has no items configured at all — skip
                continue
            if item_code not in item_set:
                continue

        # Minimum quantity gate
        if qty < rule.min_qty:
            continue

        return rule
    return None


def _calc_incentive(rule, qty: Decimal, unit_price: Decimal,
                    item_code: str = '', rule_item_map: dict = None) -> Decimal:
    """
    Compute the positive incentive amount for one qualifying line.
    Applies IncentiveRuleItem.incentive_override when available.
    """
    effective_value = rule.incentive_value
    effective_type  = rule.incentive_type

    if item_code and rule_item_map:
        ri = rule_item_map.get((rule.id, item_code))
        if ri is not None and ri.incentive_override is not None:
            effective_value = ri.incentive_override
            # type stays the same (percent or fixed) — override changes value only

    if effective_type == 'percent':
        return (qty * unit_price * effective_value / Decimal('100')
                ).quantize(Decimal('0.0001'))
    return (qty * effective_value).quantize(Decimal('0.0001'))


# ── Person-code ↔ StaffProfile map ───────────────────────────────────────────

def _build_person_code_map(user_ids=None) -> dict:
    """
    Return {softech_user_id.strip(): StaffProfile}.
    Built ONCE before the hot loop — never call inside a row-processing loop.
    """
    from apps.users.models import StaffProfile
    qs = StaffProfile.objects.select_related('user').exclude(softech_user_id='')
    if user_ids:
        qs = qs.filter(id__in=user_ids)
    return {p.softech_user_id.strip(): p
            for p in qs
            if p.softech_user_id.strip()}


# ── CalculationResult ─────────────────────────────────────────────────────────

class CalculationResult(NamedTuple):
    created: int
    total_by_user: dict          # {str(staff_id): float}
    skipped_person_codes: list   # person_codes with no StaffProfile
    simulated: bool


# ── Main engine ───────────────────────────────────────────────────────────────

def calculate(
    program_id: int,
    period_start: date,
    period_end: date,
    *,
    user_ids=None,
    simulate: bool = False,
    force: bool = False,
) -> CalculationResult:
    """
    Run (or simulate) the incentive calculation.

    Parameters
    ----------
    program_id   : IncentiveProgram.pk
    period_start : inclusive start date
    period_end   : inclusive end date
    user_ids     : optional list of StaffProfile PKs to restrict processing
    simulate     : if True, compute results without writing to the database
    force        : if True, recalculate even if settlements are finalized
                   (reopens/deletes finalized settlements for the period)

    Returns
    -------
    CalculationResult(created, total_by_user, skipped_person_codes, simulated)
    """
    from .models import IncentiveProgram, IncentiveTransaction, IncentiveSettlement

    program = IncentiveProgram.objects.get(pk=program_id)

    # ── Guard: finalization lock ───────────────────────────────────────────────
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
                f'"{program.name}". Pass force=True to recalculate and reopen them, '
                'or use simulate=True to preview.'
            )
        if locked.exists() and force:
            logger.warning(
                'calculate: force-recalculating finalized period %s→%s for program %d',
                period_start, period_end, program_id,
            )
            locked.update(is_finalized=False, finalized_at=None, finalized_by=None)

    # ── Load active rules (prefetch rule_items) ────────────────────────────────
    rules = list(
        program.rules
        .filter(is_active=True)
        .prefetch_related('rule_items')
        .order_by('-priority', 'item_code')
    )
    if not rules:
        logger.warning('calculate: program %d has no active rules', program_id)
        return CalculationResult(0, {}, [], simulate)

    # ── Build rule item helpers ONCE ──────────────────────────────────────────
    rule_item_sets, rule_item_map = _build_rule_item_sets(rules)

    # ── Build person_code map ONCE ─────────────────────────────────────────────
    person_map = _build_person_code_map(user_ids)
    person_codes = list(person_map.keys()) if user_ids else None

    if not person_map:
        logger.warning('calculate: no StaffProfiles with softech_user_id found')
        return CalculationResult(0, {}, [], simulate)

    # ── Fetch ERP data ─────────────────────────────────────────────────────────
    try:
        sales_rows   = _fetch_rows(_SALES_DOCCODE,   period_start, period_end, person_codes)
        returns_rows = _fetch_rows(_RETURNS_DOCCODE, period_start, period_end, person_codes)
    except Exception as exc:
        logger.error('calculate: Softech fetch failed — %s', exc, exc_info=True)
        raise

    logger.info(
        'calculate: program=%d period=%s→%s sales=%d returns=%d',
        program_id, period_start, period_end, len(sales_rows), len(returns_rows),
    )

    # ── Build return quantity map ──────────────────────────────────────────────
    returned_qty_map: dict[tuple, Decimal] = defaultdict(Decimal)
    for row in returns_rows:
        ref_doc = _to_str(row[_COL_R_DOCNUMBER])
        icode   = _to_str(row[_COL_ITEMCODE])
        qty     = _to_decimal(row[_COL_TRANSQTY])
        if ref_doc and icode and qty > 0:
            returned_qty_map[(ref_doc, icode)] += qty

    # ── Build transactions (in-memory) ────────────────────────────────────────
    to_create:      list  = []
    total_by_user:  dict  = {}
    skipped_codes:  list  = []

    # ─── Pass 1: sales ────────────────────────────────────────────────────────
    for row in sales_rows:
        doc_no      = _to_str(row[_COL_DOCNUMBER])
        person_code = _to_str(row[_COL_PHCODE])
        item_code   = _to_str(row[_COL_ITEMCODE])
        qty         = _to_decimal(row[_COL_TRANSQTY])
        price       = _to_decimal(row[_COL_PRICE])
        erp_date    = _to_date(row[_COL_DOCDATE])
        branch_code = _to_str(row[_COL_BRANCHCODE])

        if qty <= 0 or not item_code or not person_code:
            continue

        staff = person_map.get(person_code)
        if staff is None:
            if person_code not in skipped_codes:
                skipped_codes.append(person_code)
            continue

        rule = _find_matching_rule(rules, rule_item_sets, item_code, person_code, qty)
        if rule is None:
            continue

        returned = returned_qty_map.get((doc_no, item_code), Decimal('0'))
        is_reversed = (returned >= qty)

        incentive_amt = _calc_incentive(rule, qty, price, item_code, rule_item_map)

        to_create.append(dict(
            program=program, rule=rule, user=staff,
            item_code=item_code, item_name=_to_str(row[_COL_ITEMNAME]),
            doc_no=doc_no, doc_type='sale', ref_doc_no='',
            quantity=qty, unit_price=price,
            incentive_amount=incentive_amt,
            is_reversed=is_reversed,
            period_start=period_start, period_end=period_end,
            erp_date=erp_date, branch_code=branch_code,
        ))
        total_by_user.setdefault(staff.id, Decimal('0'))
        total_by_user[staff.id] += incentive_amt

    # ─── Pass 2: returns (always negative) ────────────────────────────────────
    for row in returns_rows:
        doc_no      = _to_str(row[_COL_DOCNUMBER])
        person_code = _to_str(row[_COL_PHCODE])
        item_code   = _to_str(row[_COL_ITEMCODE])
        qty         = _to_decimal(row[_COL_TRANSQTY])
        price       = _to_decimal(row[_COL_PRICE])
        ref_doc_no  = _to_str(row[_COL_R_DOCNUMBER])
        erp_date    = _to_date(row[_COL_DOCDATE])
        branch_code = _to_str(row[_COL_BRANCHCODE])

        if qty <= 0 or not item_code or not person_code:
            continue

        staff = person_map.get(person_code)
        if staff is None:
            continue

        rule = _find_matching_rule(rules, rule_item_sets, item_code, person_code, qty)
        if rule is None:
            continue

        incentive_amt = -_calc_incentive(rule, qty, price, item_code, rule_item_map)

        to_create.append(dict(
            program=program, rule=rule, user=staff,
            item_code=item_code, item_name=_to_str(row[_COL_ITEMNAME]),
            doc_no=doc_no, doc_type='return', ref_doc_no=ref_doc_no,
            quantity=-qty, unit_price=price,
            incentive_amount=incentive_amt,
            is_reversed=False,
            period_start=period_start, period_end=period_end,
            erp_date=erp_date, branch_code=branch_code,
        ))
        total_by_user.setdefault(staff.id, Decimal('0'))
        total_by_user[staff.id] += incentive_amt

    # ── Simulation mode: return results without touching DB ───────────────────
    if simulate:
        logger.info('simulate: program=%d would create %d transactions', program_id, len(to_create))
        return CalculationResult(
            created=len(to_create),
            total_by_user={str(uid): float(v) for uid, v in total_by_user.items()},
            skipped_person_codes=skipped_codes,
            simulated=True,
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

    logger.info(
        'calculate: DONE program=%d period=%s→%s created=%d skipped_codes=%s',
        program_id, period_start, period_end, len(to_create), skipped_codes or 'none',
    )

    return CalculationResult(
        created=len(to_create),
        total_by_user={str(uid): float(v) for uid, v in total_by_user.items()},
        skipped_person_codes=skipped_codes,
        simulated=False,
    )


def simulate_only(
    program_id: int,
    period_start: date,
    period_end: date,
    *,
    user_ids=None,
) -> CalculationResult:
    """Convenience wrapper — preview without any DB writes."""
    return calculate(
        program_id, period_start, period_end,
        user_ids=user_ids, simulate=True,
    )
