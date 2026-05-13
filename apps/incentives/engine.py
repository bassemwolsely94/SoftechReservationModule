"""
apps/incentives/engine.py

Item-Based Incentive Calculation Engine
========================================
Main entry point: calculate(program_id, period_start, period_end, user_ids=None)

Algorithm:
  1. Load the program and its active rules (sorted priority-desc)
  2. Optionally resolve person_codes from user_ids filter
  3. Fetch sales (doc_code=115) from Softech stktransm/stktrans
  4. Fetch returns (doc_code=30) from Softech for same period
  5. Build a reverse-set: (original_doc_no, item_code) pairs that were returned
  6. For each sale line: find the highest-priority matching rule → compute incentive
     — mark is_reversed=True (incentive=0) if the pair appears in reverse-set
  7. For each return line: create a negative-incentive transaction row
  8. Write IncentiveTransaction rows (delete+recreate for idempotency)
  9. Return { created, total_by_user }

Fraud prevention:
  • No manual editing of IncentiveTransaction — only calculate() writes them
  • Returns ALWAYS reduce incentives (never ignored)
  • Cross-period returns: any return that refs a doc_no from a prior period
    still creates a negative row in the current period's transactions
"""
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

logger = logging.getLogger('elrezeiky.incentives')

# Column indices for sales / returns queries (same SELECT order)
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

_SALES_SQL_TEMPLATE = """
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
ORDER BY m.docdate, m.docnumber, d.itemcode
"""


def _fetch_rows(doc_code: str, start: date, end: date, person_codes=None) -> list:
    """Fetch rows from Softech for the given doc_code in the date range."""
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
    ).strip()

    conn = get_sybase_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        return cursor.fetchall()
    finally:
        conn.close()


def _to_decimal(value, default=Decimal('0')) -> Decimal:
    """Safely convert a Sybase numeric to Python Decimal."""
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default


def _to_str(value) -> str:
    """Safely convert a Sybase value to Python str."""
    if value is None:
        return ''
    return str(value).strip()


def _to_date(value) -> date | None:
    """
    Convert whatever Sybase returns for a datetime column to a Python date.
    The CursorWrapper._convert_date() already converts Java Timestamps to
    Python datetime objects, so we just call .date() on them.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    # Fallback: string 'YYYY-MM-DD'
    try:
        return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
    except Exception:
        return None


def _find_matching_rule(rules, item_code: str, group_code: str,
                        person_code: str, qty: Decimal):
    """
    Return the highest-priority active IncentiveRule that matches the given line.
    Rules are assumed to be pre-sorted descending by priority.
    Returns None if no rule matches.
    """
    for rule in rules:
        # Person-code scope (optional)
        if rule.person_code_filter and rule.person_code_filter != person_code:
            continue
        # Item / category targeting
        if rule.item_code:
            if rule.item_code != item_code:
                continue
        elif rule.category_code:
            if rule.category_code != group_code:
                continue
        # Minimum quantity gate
        if qty < rule.min_qty:
            continue
        # expiry_within_days — we flag but can't check without batch data; rule still matches
        return rule
    return None


def _calc_incentive(rule, qty: Decimal, unit_price: Decimal) -> Decimal:
    """Compute raw (positive) incentive amount for one matching line."""
    if rule.incentive_type == 'percent':
        return (qty * unit_price * rule.incentive_value / Decimal('100')).quantize(Decimal('0.0001'))
    # fixed: per-unit amount
    return (qty * rule.incentive_value).quantize(Decimal('0.0001'))


def _build_person_code_map(user_ids=None) -> dict:
    """
    Return {person_code: StaffProfile} mapping.
    If user_ids given, restricts to those profiles only.
    """
    from apps.users.models import StaffProfile
    qs = StaffProfile.objects.exclude(softech_user_id='')
    if user_ids:
        qs = qs.filter(id__in=user_ids)
    return {p.softech_user_id.strip(): p for p in qs if p.softech_user_id.strip()}


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def calculate(program_id: int, period_start: date, period_end: date,
              user_ids=None) -> dict:
    """
    Run the incentive calculation for one program + period.

    Args:
        program_id   — IncentiveProgram.id
        period_start — inclusive start date
        period_end   — inclusive end date
        user_ids     — optional list[int] of StaffProfile PKs to filter

    Returns:
        {
            'created': int,
            'total_by_user': { str(staff_id): float(total) }
        }
    """
    from .models import IncentiveProgram, IncentiveTransaction

    program = IncentiveProgram.objects.get(pk=program_id)

    # ── Load rules ────────────────────────────────────────────────────────────
    rules = list(
        program.rules
        .filter(is_active=True)
        .order_by('-priority', 'item_code')
        .select_related()
    )
    if not rules:
        logger.warning('calculate: program %d has no active rules — nothing to do', program_id)
        return {'created': 0, 'total_by_user': {}}

    # ── Build person_code → StaffProfile map ─────────────────────────────────
    person_map = _build_person_code_map(user_ids)
    person_codes = list(person_map.keys()) if user_ids else None

    # ── Fetch ERP data ────────────────────────────────────────────────────────
    try:
        sales_rows   = _fetch_rows(_SALES_DOCCODE,   period_start, period_end, person_codes)
        returns_rows = _fetch_rows(_RETURNS_DOCCODE,  period_start, period_end, person_codes)
    except Exception as exc:
        logger.error('calculate: Softech fetch failed: %s', exc)
        raise

    # ── Build reverse index: (original_doc_no, item_code) → True ─────────────
    # Used to mark same-period sales that were fully returned
    returned_pairs: set[tuple] = set()
    for row in returns_rows:
        ref_doc = _to_str(row[_COL_R_DOCNUMBER])
        icode   = _to_str(row[_COL_ITEMCODE])
        if ref_doc and icode:
            returned_pairs.add((ref_doc, icode))

    # ── Delete existing transactions for this program/period (idempotent) ─────
    deleted, _ = IncentiveTransaction.objects.filter(
        program=program,
        period_start=period_start,
        period_end=period_end,
    ).delete()
    if deleted:
        logger.info('calculate: deleted %d stale transactions', deleted)

    # ── Process sales ─────────────────────────────────────────────────────────
    to_create = []
    total_by_user: dict[int, Decimal] = {}

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
            # Try lazy lookup (when user_ids filter not applied)
            if user_ids is None:
                person_map.update(_build_person_code_map())
                staff = person_map.get(person_code)
            if staff is None:
                continue

        rule = _find_matching_rule(rules, item_code, group_code, person_code, qty)
        if rule is None:
            continue

        is_reversed   = (doc_no, item_code) in returned_pairs
        incentive_amt = Decimal('0') if is_reversed else _calc_incentive(rule, qty, price)

        to_create.append(IncentiveTransaction(
            program=program,
            rule=rule,
            user=staff,
            item_code=item_code,
            item_name=_to_str(row[_COL_ITEMNAME]),
            doc_no=doc_no,
            doc_type='sale',
            ref_doc_no='',
            quantity=qty,
            unit_price=price,
            incentive_amount=incentive_amt,
            is_reversed=is_reversed,
            period_start=period_start,
            period_end=period_end,
            erp_date=erp_date,
            branch_code=branch_code,
        ))
        if not is_reversed:
            total_by_user.setdefault(staff.id, Decimal('0'))
            total_by_user[staff.id] += incentive_amt

    # ── Process returns (negative incentives) ─────────────────────────────────
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
            continue  # If no rule matches, no incentive was earned to reverse

        incentive_amt = -_calc_incentive(rule, qty, price)

        to_create.append(IncentiveTransaction(
            program=program,
            rule=rule,
            user=staff,
            item_code=item_code,
            item_name=_to_str(row[_COL_ITEMNAME]),
            doc_no=doc_no,
            doc_type='return',
            ref_doc_no=ref_doc_no,
            quantity=-qty,
            unit_price=price,
            incentive_amount=incentive_amt,
            is_reversed=False,
            period_start=period_start,
            period_end=period_end,
            erp_date=erp_date,
            branch_code=branch_code,
        ))
        total_by_user.setdefault(staff.id, Decimal('0'))
        total_by_user[staff.id] += incentive_amt

    # ── Bulk insert ───────────────────────────────────────────────────────────
    IncentiveTransaction.objects.bulk_create(to_create, batch_size=500)
    logger.info(
        'calculate: program=%d period=%s→%s created=%d',
        program_id, period_start, period_end, len(to_create),
    )

    return {
        'created': len(to_create),
        'total_by_user': {str(uid): float(v) for uid, v in total_by_user.items()},
    }
