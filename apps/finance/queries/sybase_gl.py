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


def sql_branchesales(d1: date, d2: date) -> str:
    return (
        "SELECT branchcode, doccode, docdate, paymenttype, SUM(paymentvalue) s "
        f"FROM {DB}.branchesales "
        f"WHERE doccode IN ('115','30') AND paymenttype <> '10' AND {_bounds('docdate', d1, d2)} "
        "GROUP BY branchcode, doccode, docdate, paymenttype"
    )


def sql_credit_docs(d1: date, d2: date) -> str:
    return (
        "SELECT m.branchcode, m.doccode, m.docnumber, m.docdate, MIN(b.personcode) pmin, MAX(b.personcode) pmax, "
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
