"""SELECT-only SOFTECH SQL for the GL drafting readers (Plan 2).

Sybase ASE 12.5: no CTEs, no TOP, CONVERT for varchar<->int comparisons. One query per calendar month
(a cold first query can take ~150 s, warm ~2.5 s). ``open_fetch()`` yields ``fetch(sql) -> list[dict]`` on one
connection and refuses anything that is not a single SELECT, on top of SOFTECH_READ_ONLY.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import date, timedelta

from config.sybase import get_sybase_connection

from .sybase_accounting import DB, _fetch


def month_chunks(d1: date, d2: date):
    """Yield (first, last) inclusive sub-ranges of [d1, d2], one per calendar month."""
    cur = d1
    while cur <= d2:
        nxt = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        end = min(d2, nxt - timedelta(days=1))
        yield cur, end
        cur = nxt


def _bounds(col: str, d1: date, d2: date) -> str:
    return f"{col} >= '{d1.isoformat()}' AND {col} < '{(d2 + timedelta(days=1)).isoformat()}'"


# Ruling P20: a dailyexpenses row is paid by a voucher (cheques) only when it is on the same branch,
# the voucher is an expense voucher (personcode '-120') and the expense date is within 31 days of
# the voucher date. At HQ cheqsno is not a voucher link, and cheqsno repeats across years.
EXPENSE_VOUCHER_PERSON = '-120'
EXPENSE_LINK_DAYS = 31


def _expense_link(expensedate: str) -> str:
    """WHERE fragment joining expense rows ``e`` to voucher ``c`` (both aliases fixed)."""
    return (
        "e.branchcode = c.branchcode "
        "AND CONVERT(varchar(20), e.cheqsno) = CONVERT(varchar(20), c.cheqsno) "
        f"AND c.personcode = '{EXPENSE_VOUCHER_PERSON}' "
        f"AND ABS(DATEDIFF(day, {expensedate}, c.cheqdate)) <= {EXPENSE_LINK_DAYS}"
    )


def expense_voucher_linked(voucher_personcode, voucher_date, expense_date) -> bool:
    """Python mirror of ``_expense_link`` (applied again by the readers on the returned columns)."""
    if voucher_date is None or expense_date is None:
        return False
    return (str(voucher_personcode or '').strip() == EXPENSE_VOUCHER_PERSON
            and abs((voucher_date - expense_date).days) <= EXPENSE_LINK_DAYS)


def sql_branchesales(d1: date, d2: date) -> str:
    return (
        "SELECT branchcode, doccode, docdate, paymenttype, SUM(paymentvalue) s "  # nosec B608 - only date.isoformat() values and module constants are interpolated
        f"FROM {DB}.branchesales "
        f"WHERE doccode IN ('115','30') AND paymenttype <> '10' AND {_bounds('docdate', d1, d2)} "
        "GROUP BY branchcode, doccode, docdate, paymenttype"
    )


def sql_credit_docs(d1: date, d2: date) -> str:
    return (
        "SELECT m.branchcode, m.doccode, m.docnumber, m.docdate, MIN(b.personcode) pmin, MAX(b.personcode) pmax, "  # nosec B608 - only date.isoformat() values and module constants are interpolated
        "SUM(b.paymentvalue) credit, m.docvalue, m.docvalue1, m.docvalue3 "
        f"FROM {DB}.stktransm m, {DB}.branchesales b "
        "WHERE m.branchcode = b.branchcode AND m.doccode = b.doccode "
        "AND CONVERT(varchar(20), m.docnumber) = CONVERT(varchar(20), b.docnumber) "
        "AND m.docdate = b.docdate "
        "AND m.doccode IN ('115','30') AND b.paymenttype = '10' "
        f"AND {_bounds('m.docdate', d1, d2)} "
        "GROUP BY m.branchcode, m.doccode, m.docnumber, m.docdate, "
        "m.docvalue, m.docvalue1, m.docvalue3"
    )


def sql_cheques(d1: date, d2: date) -> str:
    """Vouchers whose due date (cheqdate) OR issue date (cheqregisterdate) falls in [d1, d2]."""
    return (
        "SELECT c.cheqsno, c.branchcode, c.financialdoccode, c.cheqtype, c.cheqno, c.cheqdate, "  # nosec B608 - only date.isoformat() values and module constants are interpolated
        "c.cheqregisterdate, c.bankcode, c.personcode, CONVERT(varchar(10), c.ptcode) ptcode, c.cheqvalue, "
        "c.chequenote, c.tf_branchcode, c.tf_bankcode, c.tf_cheqsno, b.banktype, "
        f"(SELECT COUNT(*) FROM {DB}.dailyexpenses e WHERE {_expense_link('e.expensedate')}) has_expense "
        f"FROM {DB}.cheques c, {DB}.banks b "
        "WHERE b.bankcode = c.bankcode "
        f"AND (({_bounds('c.cheqdate', d1, d2)}) OR ({_bounds('c.cheqregisterdate', d1, d2)}))"
    )


HQ_BRANCH = '100'
TRANSFER_BOX_PERSON = '-180'


def sql_transfer_legs_pointing_at(cheqsnos) -> str:
    """Ruling P28: branch legs of box->box transfers that point back at the given HQ vouchers
    (tf_branchcode = HQ, tf_cheqsno IN ...). No date bound: the other leg may sit in another range.
    ``cheqsnos`` are coerced to int, so only integers and module constants are interpolated."""
    keys = sorted({int(str(s).strip()) for s in cheqsnos})
    if not keys:
        raise ValueError('no cheqsnos')
    in_list = ', '.join(f"'{k}'" for k in keys)
    return (
        "SELECT c.branchcode, c.cheqsno, c.personcode, c.tf_branchcode, c.tf_cheqsno "  # nosec B608 - only int() values and module constants are interpolated
        f"FROM {DB}.cheques c "
        f"WHERE c.personcode = '{TRANSFER_BOX_PERSON}' "
        f"AND CONVERT(varchar(10), c.tf_branchcode) = '{HQ_BRANCH}' "
        f"AND CONVERT(varchar(20), c.tf_cheqsno) IN ({in_list})"
    )


def sql_expenses(d1: date, d2: date) -> str:
    """dailyexpenses rows plus the paying box from the linked voucher (Ruling P20 link, see
    ``_expense_link``). No linked voucher -> NULL bankcode -> the engine raises unmapped_account."""
    link = _expense_link('d.expensedate').replace('e.', 'd.')
    return (
        "SELECT d.branchcode, d.expensedate, d.intervalcode, d.day_sno, d.expcode, d.expvalue, d.expcomment, "  # nosec B608 - only date.isoformat() values and module constants are interpolated
        "d.cheqsno, "
        f"(SELECT MAX(c.bankcode) FROM {DB}.cheques c WHERE {link}) bankcode, "
        f"(SELECT MAX(c.personcode) FROM {DB}.cheques c WHERE {link}) v_personcode, "
        f"(SELECT MAX(c.cheqdate) FROM {DB}.cheques c WHERE {link}) v_cheqdate "
        f"FROM {DB}.dailyexpenses d WHERE {_bounds('d.expensedate', d1, d2)}"
    )


_SELECT_ONLY = re.compile(r'^\s*select\b', re.I)
_INTO = re.compile(r'\binto\b', re.I)


@contextmanager
def open_fetch():
    """Yield ``fetch(sql) -> list[dict]`` bound to one SOFTECH connection, closed on exit."""
    conn = get_sybase_connection()

    def fetch(sql: str) -> list[dict]:
        if not isinstance(sql, str) or not _SELECT_ONLY.match(sql) or ';' in sql or _INTO.search(sql):
            raise ValueError('GL readers may only run a single SELECT statement')
        rows, cols = _fetch(conn, sql)
        return [dict(zip(cols, r)) for r in rows]

    try:
        yield fetch
    finally:
        conn.close()
