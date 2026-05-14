"""
apps/incentives/engine.py  —  v2 (production-hardened)

Item-Based Incentive Calculation Engine
=========================================
Main entry points:
  calculate(program_id, period_start, period_end, *, user_ids=None, simulate=False, force=False)
  simulate_only(program_id, period_start, period_end, *, user_ids=None)   ← convenience wrapper

Key design decisions (v2):
  ─────────────────────────────────────────────────────────────────────────────
  • Returns are always separate negative transactions.  Sales are always written
    at their FULL quantity with FULL incentive.  Net incentive = sum of all rows.
    This eliminates the v1 double-counting bug (zeroing the sale AND creating
    a negative return = double-deduction).

  • For same-period partial returns (3 of 5 units returned):
      Sale row  : qty=5,  incentive= +25
      Return row: qty=-3, incentive= -15
      Net                            +10  ✓

  • `is_reversed` flag on sale rows is purely informational:
    True means the full sale qty was returned within the same period.
    It does NOT affect incentive_amount computation.

  • Cross-period returns (ref_doc_no from a previous period):
    Always produce a negative transaction in the current period.
    The previous period's sale row is NOT modified (it may be finalized).

  • Finalization lock:
    If ANY finalized IncentiveSettlement exists for this program+period,
    calculate() raises ValueError unless force=True.
    Use simulate=True to preview without writing.

  • Idempotency:
    Non-simulated runs delete existing transactions for the period first,
    then bulk-insert fresh ones (batch_size=500).

  • Performance:
    — person_map built ONCE before the loop (not per-row)
    — returned_qty_map built in a single pass over returns_rows
    — Softech connection opened once (sales+returns in one pass)
    — bulk_create with batch_size=500
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
_COL_GROUPCODE   = 7
_COL_TRANSQTY    = 8
_COL_PRICE       = 9

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
    i.groupcode,
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


# ── Rule matching ─────────────────────────────────────────────────────────────

def _find_matching_rule(rules, item_code: str, group_code: str,
                        person_code: str, qty: Decimal):
    """
    Return the highest-priority matching rule.
    Rules MUST be sorted by (-priority, item_code) before passing in.
    Returns None if nothing matches.
    """
    for rule in rules:
        # Scope: person_code filter (optional — blank = all)
        if rule.person_code_filter and rule.person_code_filter != person_code:
            continue
        # Scope: specific item_code OR category_code (item_code wins)
        if rule.item_code:
            if rule.item_code != item_code:
                continue
        elif rule.category_code:
            if rule.category_code != group_code:
                continue
        # Minimum quantity gate
        if qty < rule.min_qty:
            continue
        return rule
    return None


def _calc_incentive(rule, qty: Decimal, unit_price: Decimal) -> Decimal:
    """Compute the positive incentive amount for one qualifying line."""
    if rule.incentive_type == 'percent':
        return (qty * unit_price * rule.incentive_value / Decimal('100')
                ).quantize(Decimal('0.0001'))
    return (qty * rule.incentive_value).quantize(Decimal('0.0001'))


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
            # Reopen finalized settlements so they can be re-finalized later
            locked.update(is_finalized=False, finalized_at=None, finalized_by=None)

    # ── Load active rules ──────────────────────────────────────────────────────
    rules = list(
        program.rules
        .filter(is_active=True)
        .order_by('-priority', 'item_code')
    )
    if not rules:
        logger.warning('calculate: program %d has no active rules', program_id)
        return CalculationResult(0, {}, [], simulate)

    # ── Build person_code map ONCE ─────────────────────────────────────────────
    # user_ids=None → load ALL staff with Softech IDs
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
    # { (ref_doc_no, item_code): Decimal }  — total returned qty per original doc+item
    # Used to flag same-period fully-returned sales as is_reversed=True (informational).
    #
    # NOTE: is_reversed=True does NOT zero the incentive_amount.
    # Net incentive = sale_incentive + return_incentive (return is negative).
    # This avoids v1 double-counting.
    returned_qty_map: dict[tuple, Decimal] = defaultdict(Decimal)
    for row in returns_rows:
        ref_doc = _to_str(row[_COL_R_DOCNUMBER])
        icode   = _to_str(row[_COL_ITEMCODE])
        qty     = _to_decimal(row[_COL_TRANSQTY])
        if ref_doc and icode and qty > 0:
            returned_qty_map[(ref_doc, icode)] += qty

    # Track which doc_numbers exist in current-period sales
    # (returns referencing other doc_numbers are cross-period returns)
    current_sale_docnos: set[str] = {
        _to_str(row[_COL_DOCNUMBER]) for row in sales_rows
    }

    # ── Build transactions (in-memory) ────────────────────────────────────────
    to_create        = []
    total_by_user:   dict[int, Decimal] = {}
    skipped_codes:   list[str] = []

    # ─── Pass 1: sales ────────────────────────────────────────────────────────
    for row in sales_rows:
        doc_no      = _to_str(row[_COL_DOCNUMBER])
        person_code = _to_str(row[_COL_PHCODE])
        item_code   = _to_str(row[_COL_ITEMCODE])
        group_code  = _to_str(row[_COL_GROUPCODE])
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

        rule = _find_matching_rule(rules, item_code, group_code, person_code, qty)
        if rule is None:
            continue

        # is_reversed = informational flag only (full quantity was returned same-period)
        returned = returned_qty_map.get((doc_no, item_code), Decimal('0'))
        is_reversed = (returned >= qty)

        # incentive_amount is always the FULL sale incentive — returns handled separately
        incentive_amt = _calc_incentive(rule, qty, price)

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
        group_code  = _to_str(row[_COL_GROUPCODE])
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

        rule = _find_matching_rule(rules, item_code, group_code, person_code, qty)
        if rule is None:
            # No rule → no incentive was earned → no reversal needed
            continue

        incentive_amt = -_calc_incentive(rule, qty, price)  # always negative

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
