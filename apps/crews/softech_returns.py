"""
apps/crews/softech_returns.py

A call-center crew's returns from SOFTECH (piece 2b Part B, owner ruling B + the date match,
2026-11-18). The rule is apps/forecasting/cc_softech.cc_returns_from_softech's, plus one condition:

  a doc-30 return line in the month is the crew's when an original doc-115 sale exists at the same
  branch with docnumber = r.r_docnumber, made by one of the crew's seller codes active in the
  month, AND — when r.r_docdate is set — on that date (o.docdate = r.r_docdate; SOFTECH docdate is
  date-only). A return without r_docdate falls back to the number-only match.

The date match keeps a reused (old) document number from crediting a return to the crew; there is
no look-back limit and no membership date on the original sale (a member's 2-year-old sale still
counts). cc_softech keeps the number-only rule: the comparison's "old rule" column needs it.

Read-only. Usercodes and month bounds are `?` parameters; dates are 'YYYYMMDD' strings (jConnect
rejects Python datetimes).
"""
from datetime import date
from decimal import Decimal

from config.sybase import get_sybase_connection

_SQL = """
    SELECT
        SUM(r.transprice_total) AS amt,
        SUM(r.transprice_total - r.transqty * r.newcostprice) AS profit,
        COUNT(DISTINCT r.docnumber) AS docs
    FROM stktrans r
    WHERE r.doccode = '30'
      AND r.docdate >= ? AND r.docdate < ?
      AND EXISTS (
          SELECT 1 FROM stktrans o
          WHERE o.branchcode = r.branchcode AND o.doccode = '115'
            AND o.docnumber = r.r_docnumber AND o.usercode IN ({codes})
            AND (r.r_docdate IS NULL OR o.docdate = r.r_docdate)
      )
"""

ZERO = {'amount': Decimal('0'), 'profit': Decimal('0'), 'docs': 0}


def _month_bounds(year: int, month: int) -> tuple:
    ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
    return date(year, month, 1).strftime('%Y%m%d'), date(ny, nm, 1).strftime('%Y%m%d')


def returns_sql(year: int, month: int, usercodes) -> tuple:
    """(sql, params). Codes: quotes stripped (as cc_softech does), de-duplicated, sorted."""
    codes = sorted({str(c).replace("'", '') for c in usercodes} - {''})
    return _SQL.format(codes=','.join('?' * len(codes))), [*_month_bounds(year, month), *codes]


def returns_for_codes(year: int, month: int, usercodes) -> dict:
    """{'amount', 'profit', 'docs'} of the month's returns linked (number + date) to a sale by one
    of these seller codes. No codes → zero, SOFTECH not asked. Raises when SOFTECH is
    unreachable — the caller marks it, never zeroes."""
    sql, params = returns_sql(year, month, usercodes)
    if len(params) == 2:
        return dict(ZERO)
    conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
    finally:
        conn.close()
    return {'amount': Decimal(str(row[0] or 0)), 'profit': Decimal(str(row[1] or 0)),
            'docs': int(row[2] or 0)}
