"""
apps/crews/softech_returns.py

A crew's returns from SOFTECH (piece 2b). Same rule and SQL as
apps/forecasting/cc_softech.cc_returns_from_softech: a doc-30 return line in the month counts when
its r_docnumber links to a doc-115 sale by a crew seller. The one difference: the seller must have
been a member ON THE ORIGINAL SALE'S DATE — `o.usercode IN (...)` becomes an OR of
`(o.usercode = ? AND o.docdate >= ? AND o.docdate < ?)` per identity span. With spans opened long
before the sale (the seed) the result equals the old figure.

Read-only. Usercodes and dates are `?` parameters; dates are 'YYYYMMDD' strings built from date
objects (jConnect rejects Python datetimes).
"""
from datetime import date, timedelta
from decimal import Decimal

from config.sybase import get_sybase_connection

ONE_DAY = timedelta(days=1)

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
            AND o.docnumber = r.r_docnumber
            AND ({spans})
      )
"""
_SPAN = '(o.usercode = ? AND o.docdate >= ? AND o.docdate < ?)'


def _ymd(d: date) -> str:
    return d.strftime('%Y%m%d')


def _month_bounds(year: int, month: int):
    ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
    return date(year, month, 1), date(ny, nm, 1)


def returns_sql(year: int, month: int, spans) -> tuple:
    """(sql, params) for the spans [(usercode, from, to inclusive)]."""
    start, end = _month_bounds(year, month)
    params = [_ymd(start), _ymd(end)]
    for value, frm, to in spans:
        params += [str(value), _ymd(frm), _ymd(to + ONE_DAY)]
    return _SQL.format(spans=' OR '.join([_SPAN] * len(spans))), params


def returns_for_spans(year: int, month: int, spans, lookback_days: int = 400) -> dict:
    """{'amount', 'profit', 'docs'} of returns in the month linked to a sale by a span's seller on
    a span day. Spans are clipped to [month_start - lookback_days, month_end] (an original sale
    older than that is not looked for). Raises when SOFTECH is unreachable — the caller marks it,
    never zeroes."""
    start, end = _month_bounds(year, month)
    lo, hi = start - timedelta(days=lookback_days), end - ONE_DAY
    spans = [(v, max(f, lo), min(t, hi)) for v, f, t in spans if f <= hi and t >= lo]
    if not spans:
        return {'amount': Decimal('0'), 'profit': Decimal('0'), 'docs': 0}
    sql, params = returns_sql(year, month, spans)
    conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
    finally:
        conn.close()
    return {'amount': Decimal(str(row[0] or 0)), 'profit': Decimal(str(row[1] or 0)),
            'docs': int(row[2] or 0)}
