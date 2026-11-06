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
    """Vouchers whose due date (cheqdate) OR issue date (cheqregisterdate) falls in [d1, d2].
    tf_type = banktype of tf_bankcode (outer join: NULL when unset or unknown, Ruling P31)."""
    return (
        "SELECT c.cheqsno, c.branchcode, c.financialdoccode, c.cheqtype, c.cheqno, c.cheqdate, "  # nosec B608 - only date.isoformat() values and module constants are interpolated
        "c.cheqregisterdate, c.bankcode, c.personcode, CONVERT(varchar(10), c.ptcode) ptcode, c.cheqvalue, "
        "c.chequenote, c.tf_branchcode, c.tf_bankcode, c.tf_cheqsno, "
        # jConnect drops the alias of a plain column (tb.banktype would come back as 'banktype' and
        # overwrite b.banktype): select both as expressions so the aliases survive
        "CONVERT(varchar(2), b.banktype) banktype, CONVERT(varchar(2), tb.banktype) tf_type, "
        f"(SELECT COUNT(*) FROM {DB}.dailyexpenses e WHERE {_expense_link('e.expensedate')}) has_expense "
        f"FROM {DB}.cheques c, {DB}.banks b, {DB}.banks tb "
        "WHERE b.bankcode = c.bankcode AND c.tf_bankcode *= tb.bankcode "
        f"AND (({_bounds('c.cheqdate', d1, d2)}) OR ({_bounds('c.cheqregisterdate', d1, d2)}))"
    )


HQ_BRANCH = '100'
TRANSFER_BOX_PERSON = '-180'
TRANSFER_BANK_PERSON = '-181'
TRANSFER_PAIR_DAYS = 31   # Ruling P30: cheqsno repeats across years, so the other leg must be near in time
_DIGITS = re.compile(r'^\d{1,20}$')


def _digits(v) -> str:
    """A SOFTECH code made of digits only (leading zeros kept, e.g. bank '04'), else ValueError."""
    s = str(v).strip()
    if not _DIGITS.match(s):
        raise ValueError(f'not a digit code: {v!r}')
    return s


def _near(d: date) -> str:
    return f"ABS(DATEDIFF(day, c.cheqdate, '{d.isoformat()}')) <= {TRANSFER_PAIR_DAYS}"


_PAIR_COLS = ("SELECT c.branchcode, c.cheqsno, c.personcode, c.bankcode, c.tf_branchcode, c.tf_bankcode, "
              "c.tf_cheqsno, c.cheqdate ")
BANK_TYPE_BOX = '0'


def sql_transfer_legs_pointing_at(legs) -> str:
    """Ruling P28/P30: branch legs of box->box transfers pointing back at HQ vouchers
    (tf_branchcode = HQ, tf_cheqsno = the HQ cheqsno) dated within TRANSFER_PAIR_DAYS of the HQ leg.
    ``legs`` = [(cheqsno, cheqdate)]; codes must be digits and dates ``date``, so only digit codes,
    isoformat dates and module constants are interpolated."""
    conds = [f"(CONVERT(varchar(20), c.tf_cheqsno) = '{_digits(sno)}' AND {_near(d)})"
             for sno, d in sorted(set(legs))]
    if not conds:
        raise ValueError('no legs')
    return (
        _PAIR_COLS + f"FROM {DB}.cheques c "  # nosec B608 - only digit codes, date.isoformat() values and module constants are interpolated
        f"WHERE c.personcode = '{TRANSFER_BOX_PERSON}' "
        f"AND CONVERT(varchar(10), c.tf_branchcode) = '{HQ_BRANCH}' "
        f"AND ({' OR '.join(conds)})"
    )


def sql_bank_transfer_partners(legs) -> str:
    """Ruling P30: box-side legs of -181 box<->bank transfers for bank-side rows. The bank-side row
    points at its box leg (live SOFTECH: 100/16119 -> 100/16118; the box leg has no tf_cheqsno):
    same branch, cheqsno = the bank row's tf_cheqsno, bankcode = its tf_bankcode, tf_bankcode = its
    bankcode, dated within TRANSFER_PAIR_DAYS, own box a cash box (banktype 0, Ruling P31).
    ``legs`` = [(branchcode, tf_cheqsno, tf_bankcode, bankcode, cheqdate)]; same guards."""
    conds = [f"(CONVERT(varchar(10), c.branchcode) = '{_digits(b)}' "
             f"AND CONVERT(varchar(20), c.cheqsno) = '{_digits(tf_sno)}' "
             f"AND CONVERT(varchar(10), c.bankcode) = '{_digits(tf_bank)}' "
             f"AND CONVERT(varchar(10), c.tf_bankcode) = '{_digits(bank)}' AND {_near(d)})"
             for b, tf_sno, tf_bank, bank, d in sorted(set(legs))]
    if not conds:
        raise ValueError('no legs')
    return (
        _PAIR_COLS + f", CONVERT(varchar(2), pb.banktype) banktype FROM {DB}.cheques c, {DB}.banks pb "  # nosec B608 - only digit codes, date.isoformat() values and module constants are interpolated
        f"WHERE c.personcode = '{TRANSFER_BANK_PERSON}' AND pb.bankcode = c.bankcode "
        f"AND CONVERT(varchar(5), pb.banktype) = '{BANK_TYPE_BOX}' AND ({' OR '.join(conds)})"
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


# ── Stock at cost (Plan 3, Task 3): SOFTECH's own "stock at date" report tables ───────────────────────
STOCK_TIMEOUT = 600   # one deadline over the whole read; storebal_date has ~one row per product per store


def _select(sql: str, params: tuple = ()) -> list[dict]:
    """One SELECT on a fresh HQ connection with the stock timeout; same guard as ``open_fetch``."""
    if not isinstance(sql, str) or not _SELECT_ONLY.match(sql) or ';' in sql or _INTO.search(sql):
        raise ValueError('GL readers may only run a single SELECT statement')
    conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, list(params), timeout=STOCK_TIMEOUT)
        cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        conn.close()


def storebal_rows(as_of: date) -> list[dict]:
    """(storecode, nowqty, nowcostprice) of every product line SOFTECH's stock-at-date report holds for ``as_of``."""
    return _select(
        f"SELECT storecode, nowqty, nowcostprice FROM {DB}.storebal_date WHERE storebaldate = ?",  # nosec B608 - only module constants are interpolated
        (as_of.isoformat(),))


def storebal_snapshots(d1: date | None = None, d2: date | None = None) -> list[dict]:
    """(storebaldate, storecode) pairs of ``storebal_datem``: the stores the report was run for, per date.
    Both bounds optional (inclusive)."""
    sql = f"SELECT storebaldate, storecode FROM {DB}.storebal_datem"  # nosec B608 - only module constants are interpolated
    conds, params = [], []
    if d1 is not None:
        conds.append("storebaldate >= ?")
        params.append(d1.isoformat())
    if d2 is not None:
        conds.append("storebaldate <= ?")
        params.append(d2.isoformat())
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    return _select(sql, tuple(params))


def store_names() -> list[dict]:
    """(storecode, storename) from the SOFTECH ``stores`` master."""
    return _select(f"SELECT storecode, storename FROM {DB}.stores")  # nosec B608 - only module constants are interpolated


# ── Ledger-vs-SOFTECH comparison (Plan 3, Task 4) ─────────────────────────────────────────────────────
def sales_net_by_day(d1: date, d2: date) -> list[dict]:
    """(branchcode, docdate, net): Σ paymentvalue of sales (doccode 115) minus returns (30) per branch and day,
    every tender except 60 (change discount, which the ledger books as a pair that nets to nothing in the sales
    group). Aggregated in SOFTECH: the plain month read of ``branchesales`` is ~100K rows and times out."""
    return _select(
        "SELECT branchcode, docdate, "  # nosec B608 - only date.isoformat() values and module constants are interpolated
        "SUM(CASE WHEN doccode = '30' THEN -paymentvalue ELSE paymentvalue END) net "
        f"FROM {DB}.branchesales "
        f"WHERE doccode IN ('115','30') AND paymenttype <> '60' AND {_bounds('docdate', d1, d2)} "
        "GROUP BY branchcode, docdate")


def expense_rows(d1: date, d2: date) -> list[dict]:
    """(branchcode, expensedate, expcode, expvalue, expcomment) of every ``dailyexpenses`` row in [d1, d2]."""
    return _select(
        "SELECT branchcode, expensedate, expcode, expvalue, expcomment "  # nosec B608 - only date.isoformat() values and module constants are interpolated
        f"FROM {DB}.dailyexpenses WHERE {_bounds('expensedate', d1, d2)}")
