"""
Call-center returns attribution from SOFTECH  (doc 16, Phase 5 — penny-exact)
============================================================================
SOFTECH does not stamp the CC agent on a return, nor does the PG mirror link a
return to its original sale. But stktrans returns DO carry `r_docnumber` (the
original SALE's document number). So a return is attributed to the call center
when its linked original doc-115 sale was placed by a CC sales agent.

  CC return amount = Σ transprice_total  over doc-30 return lines whose
                     r_docnumber → a doc-115 sale by a CC agent  (EXISTS, no join fan-out)
  CC return profit = Σ (transprice_total − transqty·newcostprice) over the same lines

Used by build_call_center_rollups to turn gross CC sales/profit into NET.
Validated Jun-2026: returns 5,745 (sheet 5,105) → net 827,988 vs 828,628 (≈0.08%).
"""
from decimal import Decimal


def _month_bounds_str(year, month):
    ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
    return f'{year}{month:02d}01', f'{ny}{nm:02d}01'


def cc_returns_from_softech(year, month, agent_usercodes):
    """Return {'amount': Decimal, 'profit': Decimal, 'docs': int} for CC returns."""
    if not agent_usercodes:
        return {'amount': Decimal('0'), 'profit': Decimal('0'), 'docs': 0}
    from config.sybase import get_sybase_connection
    start, end = _month_bounds_str(year, month)
    agents = ','.join("'%s'" % str(a).replace("'", "") for a in agent_usercodes)
    sql = f"""
        SELECT
            SUM(r.transprice_total) AS amt,
            SUM(r.transprice_total - r.transqty * r.newcostprice) AS profit,
            COUNT(DISTINCT r.docnumber) AS docs
        FROM stktrans r
        WHERE r.doccode = '30'
          AND r.docdate >= '{start}' AND r.docdate < '{end}'
          AND EXISTS (
              SELECT 1 FROM stktrans o
              WHERE o.branchcode = r.branchcode AND o.doccode = '115'
                AND o.docnumber = r.r_docnumber AND o.usercode IN ({agents})
          )
    """
    conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        row = cur.fetchone()
    finally:
        conn.close()
    amt = Decimal(str(row[0] or 0))
    profit = Decimal(str(row[1] or 0))
    return {'amount': amt, 'profit': profit, 'docs': int(row[2] or 0)}
