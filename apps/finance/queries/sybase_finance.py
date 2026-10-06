"""
apps/finance/queries/sybase_finance.py

Phase 1–9 — Financial data extraction from SOFTECH (Sybase ASE 12.5).

ALL queries are SELECT-only.
ABSOLUTE RULE: never INSERT / UPDATE / DELETE on any Sybase connection.

Coverage
────────
1. stktrans-based journal extraction  (purchases, returns, sales by doccode)
2. Period-level revenue / COGS aggregates per branch  (signed — returns negated)
3. Payment / cash movement extraction
4. Expense records (from purchase cost, salary, overheads where available)
5. Balance-sheet-adjacent: inventory value per branch per period
6. Helper: list of active branches and items from SOFTECH

Sybase ASE 12.5 quirks
──────────────────────
- No CTEs.  All subqueries inline.
- Use CONVERT(type, expr) for casts.
- String concat: expr + expr (not CONCAT).
- Date range: docdate >= '2024-01-01' AND docdate <= '2024-01-31'
- No SELECT TOP n — use SET ROWCOUNT n before SELECT instead.
- SOFTECHDB9.dbo prefix for every table.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DEVELOPER GUIDE — STKTRANS DOCCODE REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SOURCE OF TRUTH
───────────────
All 27 doccode definitions live in SOFTECHDB9.dbo.transdoc (columns: doccode,
docdescr [Arabic], docallow, docorder).  Counts below are from stktrans as of
2026-05.  Codes with allow=0 or 0 rows in stktrans are effectively obsolete.

IMPORTANT: transqty and transprice_total are ALWAYS POSITIVE in stktrans.
The doccode itself determines direction — never a negative sign on the row.
Reversal doccodes must be NEGATED in code when computing net totals.

SIGN CONVENTION (see DOCCODE_PNL_SIGN / DOCCODE_INVENTORY_SIGN below)
──────────────────────────────────────────────────────────────────────
  +1  the transaction INCREASES the measure  (sale → revenue up; purchase → cost up)
  -1  the transaction DECREASES the measure  (return → revenue down; write-off → stock down)
   0  no direct impact on the measure        (reservation is a commitment, not a movement)

P&L CALCULATION PATTERN (external / cash-affecting transactions only)
──────────────────────────────────────────────────────────────────────
  net_revenue   = SUM( CASE WHEN doccode='115' THEN  transprice_total
                             WHEN doccode='30'  THEN -transprice_total END )
  net_purchases = SUM( CASE WHEN doccode='10'  THEN  transprice_total
                             WHEN doccode='120' THEN -transprice_total END )
  gross_profit  = net_revenue - net_purchases

  *** NEVER add doccode '30' to the positive side of a revenue SUM.      ***
  *** NEVER add doccode '110','125','130' to purchases — they are INTERNAL ***
  *** stock movements between branches, not supplier-facing transactions.  ***

INVENTORY STOCK MOVEMENT PATTERN (all branches, per branch)
────────────────────────────────────────────────────────────
  net_stock_delta = SUM( CASE WHEN doccode IN ('10','15','25','40','30','50','70','81')
                               THEN  transprice_total
                               WHEN doccode IN ('115','120','110','125','130','140',
                                                '150','160','170','180')
                               THEN -transprice_total
                               ELSE 0 END )

  Codes '80','181','20' have zero stock impact (commitments / cancellations only).

TRANSACTION PAIRS — INCLUDING BOTH SIDES IN ONE QUERY
──────────────────────────────────────────────────────
Always include BOTH codes of a pair in the WHERE doccode IN (...) filter,
then use signed CASE WHEN to net them.  Do NOT query the two codes separately
and subtract in application code — you lose atomicity and risk double-counting.

  Pair                  Primary  Reversal  Notes
  ──────────────────────────────────────────────────────────────────────────
  Sales ↔ Cust. Return   115      30       Revenue pair. 30 negates revenue.
  Purchase ↔ Supp. Ret.   10     120       Cost pair. 120 negates cost.
  HQ Dispatch ↔ Receive  110      15       Internal. 110 = HQ OUT, 15 = branch IN.
  Branch Xfer ↔ Receive  125      25       Internal. 125 = sender OUT, 25 = receiver IN.
  Branch Xfer ↔ Cancel   125      20       20 reverses 125 (adds qty back to sender).
  Branch → HQ Dispatch   130      --       No confirmed receive pair in stktrans.
  Warehouse Dispatch↔Rx  140      40       Perfectly balanced (12,033 each).
  Inv. Surplus ↔ Deficit  50     150       Stock-count pair. 150 negates.
  Reservation ↔ Deliver   80     180       80 = commitment only; 180 = actual OUT.
  Deliver ↔ Return Deliv 180      81       81 brings item back (reverses 180).
  Reservation ↔ Cancel    80     181       181 cancels 80 commitment. No stock.

COMMON MISTAKES TO AVOID
─────────────────────────
  ✗  Using '30' as a sales code   → 30 = CUSTOMER RETURN, not a sale
  ✗  Using '130' as sales return  → 130 = BRANCH→HQ internal dispatch
  ✗  Using '125' as purch. return → 125 = INTER-BRANCH transfer (not supplier)
  ✗  Using '110' as purchases     → 110 = HQ→BRANCH internal dispatch
  ✗  Using '80' as transfer OUT   → 80 = RESERVATION (no physical movement)
  ✗  Querying pair sides separately then subtracting in Python
  ✗  Forgetting to include the reversal code in the WHERE IN (...) filter

ADDING NEW MODULES / FUTURE USE
────────────────────────────────
  1. Import the constants you need:
       from apps.finance.queries.sybase_finance import (
           DOCCODE_SALES, DOCCODE_CUSTOMER_RETURN,
           DOCCODE_PNL_SIGN, DOCCODE_INVENTORY_SIGN,
           DOCCODE_PAIRS,
       )
  2. For SQL aggregations, use the _signed_sum_sql() helper:
       from apps.finance.queries.sybase_finance import _signed_sum_sql
       net_rev_col = _signed_sum_sql('transprice_total',
                                     pos=DOCCODE_SALES,
                                     neg=DOCCODE_CUSTOMER_RETURN,
                                     alias='net_revenue')
  3. For Python post-processing, apply DOCCODE_PNL_SIGN or
     DOCCODE_INVENTORY_SIGN to each row's transqty / transprice_total
     to get a signed value before aggregating.
  4. Always add any new doccode to BOTH sign tables and DOCCODE_PAIRS
     when it becomes relevant — do not leave it undocumented.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import datetime
from typing import Any

from config.sybase import get_sybase_connection

DB = "SOFTECHDB9.dbo"

# ── doc-code constants (verified from live SOFTECHDB9.dbo.transdoc table) ──────
#
# Full reference — all 27 codes from transdoc (Arabic descriptions decoded):
#
# ┌─ CUSTOMER-FACING ──────────────────────────────────────────────────────────┐
#   115  مبيعات لعميل                 Sales to customer             7,902,502 rows
#    30  مرتجع من عميل                Customer return (reduces rev)   264,389 rows
#   121  مبيعات أصول ثابتة            Sales of fixed assets                 0 (UNUSED)
# ├─ SUPPLIER-FACING ──────────────────────────────────────────────────────────┤
#    10  مشتريات من مورد              Purchases from supplier         955,277 rows
#   120  مرتجع لمورد                  Return to supplier               65,120 rows
#    11  مشتريات أصول ثابتة           Fixed assets purchase                 0 (UNUSED)
# ├─ INTER-BRANCH TRANSFERS (paired) ─────────────────────────────────────────┤
#   110  صرف من الرئيسي إلى الفرع    HQ dispatch → branch          1,336,242 rows
#    15  إستلام في الفرع من الرئيسي   Branch receive ← HQ           1,336,154 rows
#   125  صرف - تبادل بين الفروع       Branch A dispatch → Branch B    486,347 rows
#    25  إستلام - تبادل بين الفروع    Branch B receive ← Branch A    486,347 rows
#    20  إلغاء صرف - تبادل بين الفروع Cancel inter-branch dispatch    113,223 rows
#   130  صرف من الفرع إلى الرئيسي    Branch dispatch → HQ            107,484 rows
#   140  صرف - تحويل إلى مخزن        Dispatch to warehouse            12,033 rows
#    40  إستلام - تحويل من مخزن       Receive from warehouse           12,033 rows
# ├─ RESERVATIONS (out-of-stock system) ───────────────────────────────────────┤
#    80  حجز بضاعة غير موجودة         Reserve out-of-stock item        38,843 rows
#   180  تسليم حجز بضاعة غير موجودة   Deliver reserved item            35,606 rows
#   181  إلغاء حجز بضاعة              Cancel reservation                4,570 rows
#    81  مرتجع تسليم حجز بضاعة        Return reserved delivery             494 rows
# ├─ INVENTORY ADJUSTMENTS ────────────────────────────────────────────────────┤
#    50  فائض جرد                     Inventory surplus (count)        62,965 rows
#   150  عجز جرد                      Inventory deficit (count)       136,871 rows
#   160  صرف هالك                     Write-off: damaged/expired        1,625 rows
# ├─ EXPENSE ITEMS ────────────────────────────────────────────────────────────┤
#   170  صرف أصناف مصروفات            Dispatch expense items           44,108 rows
#    70  إستلام أصناف مصروفات          Receive expense items                60 rows
# ├─ MANUFACTURING (all unused) ───────────────────────────────────────────────┤
#    95  صنف مُصنَّع                    Manufactured item                     0 (UNUSED)
#   195  إذن صرف مواد خام للتصنيع      Raw materials for mfg                 0 (UNUSED)
# ├─ DISABLED (allow=0, never in stktrans) ────────────────────────────────────┤
#    90  فائض فرق رصيد بين فرع والرئيسي  Surplus balance reconciliation (DISABLED)
#   190  عجز فرق رصيد بين فرع والرئيسي   Deficit balance reconciliation (DISABLED)
# └────────────────────────────────────────────────────────────────────────────┘

# ── P&L-relevant codes ───────────────────────────────────────────────────────
DOCCODE_SALES           = "115"   # مبيعات لعميل     — Sales to customer
DOCCODE_CUSTOMER_RETURN = "30"    # مرتجع من عميل    — Customer return (reduces revenue)
DOCCODE_PURCHASE        = "10"    # مشتريات من مورد  — Purchases from supplier
DOCCODE_SUPPLIER_RETURN = "120"   # مرتجع لمورد      — Return to supplier (reduces purchases)

# ── Inter-branch transfer codes ──────────────────────────────────────────────
DOCCODE_HQ_DISPATCH     = "110"   # صرف من الرئيسي إلى الفرع    — HQ → Branch (stock OUT of HQ)
DOCCODE_BRANCH_RECEIVE  = "15"    # إستلام في الفرع من الرئيسي   — Branch ← HQ (stock IN to branch)
DOCCODE_XFER_OUT        = "125"   # صرف - تبادل بين الفروع       — Branch → Branch (stock OUT)
DOCCODE_XFER_IN         = "25"    # إستلام - تبادل بين الفروع    — Branch → Branch (stock IN)
DOCCODE_XFER_CANCEL     = "20"    # إلغاء صرف - تبادل            — Cancel inter-branch dispatch
DOCCODE_BRANCH_TO_HQ    = "130"   # صرف من الفرع إلى الرئيسي    — Branch → HQ (stock OUT of branch)
DOCCODE_WH_DISPATCH     = "140"   # صرف - تحويل إلى مخزن         — Dispatch to warehouse (OUT)
DOCCODE_WH_RECEIVE      = "40"    # إستلام - تحويل من مخزن       — Receive from warehouse (IN)

# ── Inventory adjustment codes ───────────────────────────────────────────────
DOCCODE_INV_SURPLUS     = "50"    # فائض جرد   — Stock-count surplus (adds to stock)
DOCCODE_INV_DEFICIT     = "150"   # عجز جرد    — Stock-count deficit (removes from stock)
DOCCODE_WRITE_OFF       = "160"   # صرف هالك   — Damaged / expired write-off

# ── Reservation codes ────────────────────────────────────────────────────────
DOCCODE_RESERVATION     = "80"    # حجز بضاعة غير موجودة
DOCCODE_RES_DELIVER     = "180"   # تسليم حجز بضاعة
DOCCODE_RES_CANCEL      = "181"   # إلغاء حجز بضاعة
DOCCODE_RES_RETURN      = "81"    # مرتجع تسليم حجز

# ── Expense item codes ───────────────────────────────────────────────────────
DOCCODE_EXPENSE_OUT     = "170"   # صرف أصناف مصروفات    — Dispatch expense items (internal use)
DOCCODE_EXPENSE_IN      = "70"    # إستلام أصناف مصروفات — Receive expense items (rare / near-obsolete)

# ── Combined sets for SQL IN() clauses ───────────────────────────────────────
# P&L (always include BOTH the primary AND its reversal in one query)
SALES_DOCCODES          = f"'{DOCCODE_SALES}'"
CUSTOMER_RETURN_CODES   = f"'{DOCCODE_CUSTOMER_RETURN}'"
PURCHASE_DOCCODES       = f"'{DOCCODE_PURCHASE}'"
SUPPLIER_RETURN_CODES   = f"'{DOCCODE_SUPPLIER_RETURN}'"

# Combined pairs for WHERE IN() — use these so both sides are fetched together
PNL_ALL_CODES           = (
    f"'{DOCCODE_SALES}', '{DOCCODE_CUSTOMER_RETURN}', "
    f"'{DOCCODE_PURCHASE}', '{DOCCODE_SUPPLIER_RETURN}'"
)

# Inventory IN movements (stock increases at the receiving branch)
INVENTORY_IN_CODES      = (
    f"'{DOCCODE_PURCHASE}', '{DOCCODE_BRANCH_RECEIVE}', '{DOCCODE_XFER_IN}', "
    f"'{DOCCODE_WH_RECEIVE}', '{DOCCODE_CUSTOMER_RETURN}', '{DOCCODE_INV_SURPLUS}'"
)
# Inventory OUT movements (stock decreases at the dispatching branch)
INVENTORY_OUT_CODES     = (
    f"'{DOCCODE_SALES}', '{DOCCODE_SUPPLIER_RETURN}', '{DOCCODE_HQ_DISPATCH}', "
    f"'{DOCCODE_XFER_OUT}', '{DOCCODE_BRANCH_TO_HQ}', '{DOCCODE_WH_DISPATCH}', "
    f"'{DOCCODE_INV_DEFICIT}', '{DOCCODE_WRITE_OFF}'"
)

# ── Sign tables ───────────────────────────────────────────────────────────────
# Import these in any module that processes stktrans rows in Python.
# Apply to transprice_total (or transqty) before summing.
# transqty / transprice_total are ALWAYS positive in the DB — sign comes from here.

# P&L perspective: +1 = increases the metric, -1 = decreases it
DOCCODE_PNL_SIGN: dict[str, int] = {
    DOCCODE_SALES:           +1,   # 115 — revenue IN
    DOCCODE_CUSTOMER_RETURN: -1,   # 30  — revenue OUT  (reversal of 115)
    DOCCODE_PURCHASE:        +1,   # 10  — cost incurred
    DOCCODE_SUPPLIER_RETURN: -1,   # 120 — cost reversed (reversal of 10)
}

# Inventory / stock-on-hand perspective: +1 = stock added, -1 = stock removed, 0 = no movement
DOCCODE_INVENTORY_SIGN: dict[str, int] = {
    # ── Stock IN (+1) ──────────────────────────────────────────────────────
    DOCCODE_PURCHASE:        +1,   # 10  — buy from supplier
    DOCCODE_BRANCH_RECEIVE:  +1,   # 15  — receive at branch from HQ
    DOCCODE_XFER_IN:         +1,   # 25  — receive from another branch
    DOCCODE_WH_RECEIVE:      +1,   # 40  — receive from warehouse
    DOCCODE_CUSTOMER_RETURN: +1,   # 30  — customer gives item back
    DOCCODE_INV_SURPLUS:     +1,   # 50  — stock-count found more than system
    DOCCODE_EXPENSE_IN:      +1,   # 70  — receive expense items (rare)
    DOCCODE_RES_RETURN:      +1,   # 81  — reserved delivery returned to shelf
    # ── Stock OUT (-1) ─────────────────────────────────────────────────────
    DOCCODE_SALES:           -1,   # 115 — sold to customer
    DOCCODE_SUPPLIER_RETURN: -1,   # 120 — item sent back to supplier
    DOCCODE_HQ_DISPATCH:     -1,   # 110 — HQ sends stock to branch (HQ stock ↓)
    DOCCODE_XFER_OUT:        -1,   # 125 — branch sends stock to another branch
    DOCCODE_BRANCH_TO_HQ:    -1,   # 130 — branch returns stock to HQ
    DOCCODE_WH_DISPATCH:     -1,   # 140 — branch sends stock to warehouse
    DOCCODE_INV_DEFICIT:     -1,   # 150 — stock-count found less than system
    DOCCODE_WRITE_OFF:       -1,   # 160 — damaged / expired goods destroyed
    DOCCODE_EXPENSE_OUT:     -1,   # 170 — items consumed internally
    DOCCODE_RES_DELIVER:     -1,   # 180 — reserved item physically leaves shelf
    # ── Zero impact (0) — commitments / cancellations only ─────────────────
    DOCCODE_RESERVATION:      0,   # 80  — reserve promise; stock moves later at 180
    DOCCODE_RES_CANCEL:       0,   # 181 — cancel reservation; no physical movement
    DOCCODE_XFER_CANCEL:      0,   # 20  — cancel inter-branch dispatch commitment
}

# ── Transaction pairs registry ────────────────────────────────────────────────
# Maps (primary_doccode, reversal_doccode) → human description.
# Use this when building queries that must cover both sides of a transaction.
# The reversal code should always be negated (-1) in aggregations.
DOCCODE_PAIRS: dict[tuple[str, str], str] = {
    (DOCCODE_SALES,        DOCCODE_CUSTOMER_RETURN): "Sales ↔ Customer Return (P&L revenue pair)",
    (DOCCODE_PURCHASE,     DOCCODE_SUPPLIER_RETURN): "Purchase ↔ Supplier Return (P&L cost pair)",
    (DOCCODE_HQ_DISPATCH,  DOCCODE_BRANCH_RECEIVE):  "HQ Dispatch ↔ Branch Receive (internal IN/OUT)",
    (DOCCODE_XFER_OUT,     DOCCODE_XFER_IN):         "Branch Dispatch ↔ Branch Receive (inter-branch)",
    (DOCCODE_XFER_OUT,     DOCCODE_XFER_CANCEL):     "Branch Dispatch ↔ Cancel Dispatch (reversal)",
    (DOCCODE_WH_DISPATCH,  DOCCODE_WH_RECEIVE):      "Warehouse Dispatch ↔ Receive (balanced)",
    (DOCCODE_INV_SURPLUS,  DOCCODE_INV_DEFICIT):     "Stock-Count Surplus ↔ Deficit (adjustment pair)",
    (DOCCODE_RESERVATION,  DOCCODE_RES_DELIVER):     "Reservation ↔ Delivery (commitment → fulfilment)",
    (DOCCODE_RES_DELIVER,  DOCCODE_RES_RETURN):      "Delivery ↔ Return of Delivery (reversal)",
    (DOCCODE_RESERVATION,  DOCCODE_RES_CANCEL):      "Reservation ↔ Cancellation (no stock movement)",
}


# ── helpers ──────────────────────────────────────────────────────────────────

def _rows_as_dicts(cursor, rows: list) -> list[dict]:
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in rows]


def _safe(v: Any) -> Any:
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode("utf-8", errors="replace")
        except Exception:
            return repr(v)
    if isinstance(v, datetime.datetime):
        return v.isoformat()
    if isinstance(v, datetime.date):
        return v.isoformat()
    return v


def _clean(row: dict) -> dict:
    return {k: _safe(v) for k, v in row.items()}


def _period_clause(date_col: str, year: int, month: int) -> str:
    """Build a Sybase-safe date-range WHERE fragment for a given year/month."""
    from calendar import monthrange
    last_day = monthrange(year, month)[1]
    start    = f"{year}-{month:02d}-01"
    end      = f"{year}-{month:02d}-{last_day:02d}"
    return f"{date_col} >= '{start}' AND {date_col} <= '{end}'"


def _signed_sum_sql(
    amount_col: str,
    pos: str,
    neg: str,
    alias: str,
) -> str:
    """
    Generate a signed SUM CASE WHEN expression for Sybase SQL.

    Produces:
        SUM(CASE WHEN doccode IN (<pos>) THEN  <amount_col>
                 WHEN doccode IN (<neg>) THEN -<amount_col>
                 ELSE 0 END) AS <alias>

    Parameters
    ──────────
    amount_col : column name, e.g. 'transprice_total'
    pos        : SQL IN-list string for codes whose value adds positively,
                 e.g. "'115'"  or  "'10', '15'"
    neg        : SQL IN-list string for codes whose value is negated (reversals),
                 e.g. "'30'"   or  "'120'"
    alias      : output column alias

    Usage example
    ─────────────
        sql_col = _signed_sum_sql(
            'transprice_total',
            pos="'115'",
            neg="'30'",
            alias='net_revenue',
        )
        # → SUM(CASE WHEN doccode IN ('115') THEN transprice_total
        #            WHEN doccode IN ('30')  THEN -transprice_total
        #            ELSE 0 END) AS net_revenue
    """
    return (
        f"SUM(CASE WHEN doccode IN ({pos}) THEN  {amount_col}\n"
        f"              WHEN doccode IN ({neg}) THEN -{amount_col}\n"
        f"              ELSE 0 END) AS {alias}"
    )


def apply_doccode_sign(rows: list[dict], sign_table: dict[str, int]) -> list[dict]:
    """
    Post-process a list of stktrans row-dicts by applying signs from a sign table.

    Mutates (and returns) each row, adding:
      signed_qty   = transqty        × sign
      signed_total = transprice_total × sign

    Rows whose doccode is not in sign_table are left with sign=+1 (unchanged).
    Rows with sign=0 get signed_qty=0, signed_total=0.

    Parameters
    ──────────
    rows       : list of dicts from any stktrans query (must have 'doccode',
                 'transqty', 'transprice_total')
    sign_table : one of DOCCODE_PNL_SIGN or DOCCODE_INVENTORY_SIGN

    Usage example
    ─────────────
        from apps.finance.queries.sybase_finance import (
            get_purchases_by_month, get_purchase_returns_by_month,
            apply_doccode_sign, DOCCODE_PNL_SIGN,
        )
        rows = get_purchases_by_month(2025, 12) + get_purchase_returns_by_month(2025, 12)
        rows = apply_doccode_sign(rows, DOCCODE_PNL_SIGN)
        net_cost = sum(r['signed_total'] for r in rows)
    """
    import decimal
    for row in rows:
        sign = sign_table.get(str(row.get("doccode", "")), 1)
        qty   = row.get("transqty")
        total = row.get("transprice_total") or row.get("gross_amount") or row.get("gross_revenue")
        try:
            row["signed_qty"]   = decimal.Decimal(str(qty))   * sign if qty   is not None else None
            row["signed_total"] = decimal.Decimal(str(total)) * sign if total is not None else None
        except (decimal.InvalidOperation, TypeError):
            row["signed_qty"]   = None
            row["signed_total"] = None
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# 1. PURCHASES  (doccode = '10' — مشتريات من مورد)
# ══════════════════════════════════════════════════════════════════════════════

def get_purchases_by_month(
    year: int,
    month: int,
    branch_id: str | None = None,
    conn=None,
) -> list[dict]:
    """
    Return all purchase-from-supplier transaction lines for the given month.
    One row per stktrans line (item × document × branch).

    doccode '10' = مشتريات من مورد (Purchases from supplier) — 955K rows.
    NOTE: doccode '110' (HQ dispatch to branch) is an INTERNAL stock movement,
    not an external purchase — it is intentionally excluded here.

    Pass ``conn`` to reuse an existing Sybase connection (avoids the JPype
    JVM connection overhead when called in a multi-month loop).  When None,
    a new connection is opened and closed automatically.
    """
    where = _period_clause("t.docdate", year, month)
    where += f" AND t.doccode = '{DOCCODE_PURCHASE}'"
    if branch_id:
        where += f" AND t.branchcode = '{branch_id}'"

    sql = f"""
        SELECT
            t.docnumber,
            t.docdate,
            t.branchcode,
            t.itemcode,
            t.transqty,
            t.transprice,
            t.itemsalestax,
            t.origintaxp,
            t.transprice_total                                      AS gross_amount,
            t.transprice_total - ISNULL(t.itemsalestax, 0)         AS net_amount
        FROM   {DB}.stktrans t
        WHERE  {where}
        ORDER  BY t.docdate, t.docnumber
    """
    _own = conn is None
    if _own:
        conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        return [_clean(r) for r in _rows_as_dicts(cur, rows)]
    finally:
        if _own:
            conn.close()


def get_purchase_returns_by_month(
    year: int,
    month: int,
    branch_id: str | None = None,
    conn=None,
) -> list[dict]:
    """
    Return-to-supplier lines (doccode '120' = مرتجع لمورد).
    These reduce net purchases and should be deducted from COGS.
    NOTE: doccode '125' is inter-branch transfer (not purchase returns).

    Pass ``conn`` to reuse an existing Sybase connection.
    """
    where = _period_clause("t.docdate", year, month)
    where += f" AND t.doccode = '{DOCCODE_SUPPLIER_RETURN}'"
    if branch_id:
        where += f" AND t.branchcode = '{branch_id}'"

    sql = f"""
        SELECT
            t.docnumber,
            t.docdate,
            t.branchcode,
            t.itemcode,
            t.transqty,
            t.transprice,
            t.itemsalestax,
            t.transprice_total                                  AS gross_amount,
            t.transprice_total - ISNULL(t.itemsalestax, 0)     AS net_amount
        FROM   {DB}.stktrans t
        WHERE  {where}
        ORDER  BY t.docdate, t.docnumber
    """
    _own = conn is None
    if _own:
        conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        return [_clean(r) for r in _rows_as_dicts(cur, rows)]
    finally:
        if _own:
            conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# 2. SALES  (doccode = '115') / CUSTOMER RETURNS (doccode = '30')
# ══════════════════════════════════════════════════════════════════════════════

def get_sales_by_month(
    year: int,
    month: int,
    branch_id: str | None = None,
    conn=None,
) -> list[dict]:
    """
    Sales-to-customer transaction lines for the month.
    doccode '115' = مبيعات لعميل (Sales to customer) — 7.9M rows — the ONLY sales code.
    NOTE: doccode '30' is customer RETURNS (مرتجع من عميل), not sales — excluded here.
    Use get_sales_returns_by_month() for customer returns.

    Pass ``conn`` to reuse an existing Sybase connection.
    """
    where = _period_clause("t.docdate", year, month)
    where += f" AND t.doccode = '{DOCCODE_SALES}'"
    if branch_id:
        where += f" AND t.branchcode = '{branch_id}'"

    sql = f"""
        SELECT
            t.docnumber,
            t.docdate,
            t.branchcode,
            t.itemcode,
            t.transqty,
            t.transprice,
            t.itemsalestax,
            t.origintaxp,
            t.transprice_total                                  AS gross_revenue,
            ISNULL(t.itemsalestax, 0)                           AS tax_amount,
            t.transprice_total - ISNULL(t.itemsalestax, 0)     AS net_revenue
        FROM   {DB}.stktrans t
        WHERE  {where}
        ORDER  BY t.docdate, t.docnumber
    """
    _own = conn is None
    if _own:
        conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        return [_clean(r) for r in _rows_as_dicts(cur, rows)]
    finally:
        if _own:
            conn.close()


def get_sales_returns_by_month(
    year: int,
    month: int,
    branch_id: str | None = None,
    conn=None,
) -> list[dict]:
    """
    Customer return lines (doccode '30' = مرتجع من عميل).
    Items returned BY the customer TO the pharmacy — reduces net revenue.
    NOTE: doccode '130' is branch→HQ internal transfer (not sales returns).

    Pass ``conn`` to reuse an existing Sybase connection.
    """
    where = _period_clause("t.docdate", year, month)
    where += f" AND t.doccode = '{DOCCODE_CUSTOMER_RETURN}'"
    if branch_id:
        where += f" AND t.branchcode = '{branch_id}'"

    sql = f"""
        SELECT
            t.docnumber,
            t.docdate,
            t.branchcode,
            t.itemcode,
            t.transqty,
            t.transprice,
            t.transprice_total  AS return_value
        FROM   {DB}.stktrans t
        WHERE  {where}
        ORDER  BY t.docdate, t.docnumber
    """
    _own = conn is None
    if _own:
        conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        return [_clean(r) for r in _rows_as_dicts(cur, rows)]
    finally:
        if _own:
            conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# 3. AGGREGATED MONTHLY SNAPSHOT  (fast, branch-level P&L totals)
# ══════════════════════════════════════════════════════════════════════════════

def get_monthly_branch_snapshot(
    year: int,
    month: int,
    conn=None,
) -> list[dict]:
    """
    Return one row per branch with aggregated monthly P&L data from stktrans.

    Only external (cash-affecting) transactions are included:
      - Purchases from supplier  : doccode '10'  (مشتريات من مورد)
      - Returns to supplier      : doccode '120' (مرتجع لمورد)
      - Sales to customer        : doccode '115' (مبيعات لعميل)
      - Customer returns         : doccode '30'  (مرتجع من عميل)

    Inter-branch transfers (15, 25, 110, 125, 130, etc.) are intentionally
    excluded — they are internal stock movements with no P&L impact.

    Returned columns
    ─────────────────
    Gross (unsigned) columns — raw values before netting:
      total_purchases_gross  — gross purchase value (doccode 10, excl. returns)
      total_purchases_net    — same but after tax deduction
      total_purchase_returns — supplier returns value (doccode 120, positive)
      total_sales_gross      — gross sales value (doccode 115, excl. returns)
      total_sales_net        — same but after tax deduction
      total_sales_returns    — customer returns value (doccode 30, positive)
      total_tax              — total itemsalestax on sales rows

    Signed (netted) columns — returns already subtracted, ready for display:
      net_revenue    = total_sales_gross   - total_sales_returns
      net_purchases  = total_purchases_gross - total_purchase_returns
      gross_profit   = net_revenue - net_purchases  (Python-derived, appended post-query)
    """
    period = _period_clause("docdate", year, month)
    sql = f"""
        SELECT
            branchcode,
            -- ── Gross unsigned columns (individual legs) ──────────────────────
            SUM(CASE WHEN doccode = '{DOCCODE_PURCHASE}'
                     THEN transprice_total ELSE 0 END)                   AS total_purchases_gross,
            SUM(CASE WHEN doccode = '{DOCCODE_PURCHASE}'
                     THEN transprice_total - ISNULL(itemsalestax, 0)
                     ELSE 0 END)                                          AS total_purchases_net,
            SUM(CASE WHEN doccode = '{DOCCODE_SUPPLIER_RETURN}'
                     THEN transprice_total ELSE 0 END)                   AS total_purchase_returns,
            SUM(CASE WHEN doccode = '{DOCCODE_SALES}'
                     THEN transprice_total ELSE 0 END)                   AS total_sales_gross,
            SUM(CASE WHEN doccode = '{DOCCODE_SALES}'
                     THEN transprice_total - ISNULL(itemsalestax, 0)
                     ELSE 0 END)                                          AS total_sales_net,
            SUM(CASE WHEN doccode = '{DOCCODE_CUSTOMER_RETURN}'
                     THEN transprice_total ELSE 0 END)                   AS total_sales_returns,
            SUM(CASE WHEN doccode = '{DOCCODE_SALES}'
                     THEN ISNULL(itemsalestax, 0) ELSE 0 END)            AS total_tax,
            -- ── Signed net columns (pair netted in one SUM, returns negated) ──
            {_signed_sum_sql('transprice_total',
                             pos=f"'{DOCCODE_SALES}'",
                             neg=f"'{DOCCODE_CUSTOMER_RETURN}'",
                             alias='net_revenue')},
            {_signed_sum_sql('transprice_total - ISNULL(itemsalestax, 0)',
                             pos=f"'{DOCCODE_SALES}'",
                             neg=f"'{DOCCODE_CUSTOMER_RETURN}'",
                             alias='net_revenue_excl_tax')},
            {_signed_sum_sql('transprice_total',
                             pos=f"'{DOCCODE_PURCHASE}'",
                             neg=f"'{DOCCODE_SUPPLIER_RETURN}'",
                             alias='net_purchases')}
        FROM   {DB}.stktrans
        WHERE  {period}
        AND    doccode IN (
                   '{DOCCODE_PURCHASE}',
                   '{DOCCODE_SUPPLIER_RETURN}',
                   '{DOCCODE_SALES}',
                   '{DOCCODE_CUSTOMER_RETURN}'
               )
        GROUP  BY branchcode
        ORDER  BY branchcode
    """
    _own = conn is None
    if _own:
        conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        result = [_clean(r) for r in _rows_as_dicts(cur, rows)]
    finally:
        if _own:
            conn.close()

    # Derive gross_profit in Python (Sybase cannot reference column aliases in same SELECT)
    import decimal
    D = decimal.Decimal
    for r in result:
        rev  = D(str(r.get("net_revenue")  or 0))
        cost = D(str(r.get("net_purchases") or 0))
        r["gross_profit"]     = rev - cost
        r["gross_margin_pct"] = (
            (r["gross_profit"] / rev * D("100")).quantize(D("0.01"))
            if rev > 0 else D("0")
        )
    return result


# ══════════════════════════════════════════════════════════════════════════════
# 4. INVENTORY VALUE (approximation via stktrans cumulative balance)
# ══════════════════════════════════════════════════════════════════════════════

def get_inventory_value_snapshot(
    year: int,
    month: int,
    branch_id: str | None = None,
    conn=None,
) -> list[dict]:
    """
    Estimate closing inventory value per branch at end of given month.

    Logic (per branch, cumulative from all time to period_end):
      + Stock IN  : purchases (10), branch-receive-from-HQ (15),
                    inter-branch receive (25), warehouse receive (40),
                    customer returns (30), inventory surplus (50)
      - Stock OUT : sales (115), return-to-supplier (120),
                    HQ dispatch (110), inter-branch dispatch (125),
                    branch-to-HQ (130), warehouse dispatch (140),
                    inventory deficit (150), write-off (160)

    All values use transprice_total (cost price × qty for IN; sale price × qty
    for sales OUT — so the result is a mix of cost and selling price).
    For a proper FIFO/AVCO valuation, use the newqty × costprice approach.

    Returns: [{branchcode, est_inventory_value}]
    """
    from calendar import monthrange
    last_day   = monthrange(year, month)[1]
    period_end = f"{year}-{month:02d}-{last_day:02d}"

    branch_filter = f" AND branchcode = '{branch_id}'" if branch_id else ""

    sql = f"""
        SELECT
            branchcode,
            SUM(CASE WHEN doccode IN ({INVENTORY_IN_CODES})
                     THEN transprice_total - ISNULL(itemsalestax, 0)
                     ELSE 0 END)
            - SUM(CASE WHEN doccode IN ({INVENTORY_OUT_CODES})
                       THEN transprice_total ELSE 0 END)   AS est_inventory_value
        FROM   {DB}.stktrans
        WHERE  docdate <= '{period_end}'
        AND    doccode IN ({INVENTORY_IN_CODES}, {INVENTORY_OUT_CODES})
        {branch_filter}
        GROUP  BY branchcode
        ORDER  BY branchcode
    """
    _own = conn is None
    if _own:
        conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        return [_clean(r) for r in _rows_as_dicts(cur, rows)]
    finally:
        if _own:
            conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# 5. SIGNED PERIOD TOTALS — clean P&L roll-up for dashboards / APIs
# ══════════════════════════════════════════════════════════════════════════════

def get_signed_period_totals(
    year: int,
    month: int,
    branch_id: str | None = None,
) -> dict:
    """
    Return a single signed P&L summary dict for the given month.

    Both the primary and reversal doccode are fetched in ONE query pass,
    with reversals negated inline via CASE WHEN (see DEVELOPER GUIDE above).

    Returned keys
    ─────────────
      net_revenue         — sales(115) minus customer_returns(30)
      net_revenue_excl_tax— net_revenue excluding itemsalestax
      net_purchases       — purchases(10) minus supplier_returns(120)
      gross_profit        — net_revenue - net_purchases
      gross_margin_pct    — gross_profit / net_revenue × 100

      sales_gross         — raw 115 total (before subtracting returns)
      sales_returns       — raw 30 total  (positive — the amount returned)
      purchases_gross     — raw 10 total  (before subtracting returns)
      purchase_returns    — raw 120 total (positive — the amount returned)
      total_tax           — tax on sales rows

      branches            — number of distinct branches in the period
      doccode_breakdown   — dict {doccode: {"count": n, "total": v}} for audit

    Usage
    ─────
        from apps.finance.queries.sybase_finance import get_signed_period_totals
        summary = get_signed_period_totals(2025, 12)
        print(summary["net_revenue"], summary["gross_margin_pct"])
    """
    period = _period_clause("docdate", year, month)
    branch_filter = f" AND branchcode = '{branch_id}'" if branch_id else ""

    sql = f"""
        SELECT
            COUNT(DISTINCT branchcode)                                    AS branches,
            -- ── Gross unsigned ─────────────────────────────────────────────
            SUM(CASE WHEN doccode = '{DOCCODE_SALES}'
                     THEN transprice_total ELSE 0 END)                   AS sales_gross,
            SUM(CASE WHEN doccode = '{DOCCODE_CUSTOMER_RETURN}'
                     THEN transprice_total ELSE 0 END)                   AS sales_returns,
            SUM(CASE WHEN doccode = '{DOCCODE_PURCHASE}'
                     THEN transprice_total ELSE 0 END)                   AS purchases_gross,
            SUM(CASE WHEN doccode = '{DOCCODE_SUPPLIER_RETURN}'
                     THEN transprice_total ELSE 0 END)                   AS purchase_returns,
            SUM(CASE WHEN doccode = '{DOCCODE_SALES}'
                     THEN ISNULL(itemsalestax, 0) ELSE 0 END)            AS total_tax,
            -- ── Signed net (pair+reversal in one SUM) ─────────────────────
            {_signed_sum_sql('transprice_total',
                             pos=f"'{DOCCODE_SALES}'",
                             neg=f"'{DOCCODE_CUSTOMER_RETURN}'",
                             alias='net_revenue')},
            {_signed_sum_sql('transprice_total - ISNULL(itemsalestax, 0)',
                             pos=f"'{DOCCODE_SALES}'",
                             neg=f"'{DOCCODE_CUSTOMER_RETURN}'",
                             alias='net_revenue_excl_tax')},
            {_signed_sum_sql('transprice_total',
                             pos=f"'{DOCCODE_PURCHASE}'",
                             neg=f"'{DOCCODE_SUPPLIER_RETURN}'",
                             alias='net_purchases')}
        FROM   {DB}.stktrans
        WHERE  {period}
        AND    doccode IN ({PNL_ALL_CODES})
        {branch_filter}
    """

    # Breakdown query: count + sum per doccode for audit trail
    sql_breakdown = f"""
        SELECT
            doccode,
            COUNT(*)                       AS row_count,
            SUM(transprice_total)          AS total_value
        FROM   {DB}.stktrans
        WHERE  {period}
        AND    doccode IN ({PNL_ALL_CODES})
        {branch_filter}
        GROUP  BY doccode
        ORDER  BY doccode
    """

    import decimal
    D = decimal.Decimal

    conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        row = cur.fetchone()
        cols = [d[0] for d in cur.description]
        totals = _clean(dict(zip(cols, row))) if row else {}

        cur.execute(sql_breakdown)
        bdown_rows = cur.fetchall()
        bdown_cols = [d[0] for d in cur.description]
    finally:
        conn.close()

    breakdown = {
        str(r[0]): {"count": r[1], "total": _safe(r[2])}
        for r in bdown_rows
    }

    rev  = D(str(totals.get("net_revenue")  or 0))
    cost = D(str(totals.get("net_purchases") or 0))
    profit = rev - cost
    margin = (
        (profit / rev * D("100")).quantize(D("0.01"))
        if rev > 0 else D("0")
    )

    return {
        **totals,
        "gross_profit":       str(profit),
        "gross_margin_pct":   str(margin),
        "doccode_breakdown":  breakdown,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 7. PAYMENT / CASH MOVEMENTS
# ══════════════════════════════════════════════════════════════════════════════

def get_payment_transactions(
    year: int,
    month: int,
    branch_id: str | None = None,
    table_name: str | None = None,
) -> list[dict]:
    """
    Extract payment / receipt records from a SOFTECH payments table.

    `table_name` should be set after Phase-0 discovers the correct table
    (e.g. 'receipts', 'payments', 'cashbook').  If None, returns empty list
    with a guidance message so the caller knows discovery is required.

    Returns: [{docno, docdate, branchid, direction, amount, payment_method,
               party_code, party_name, reference, notes}]
    """
    if not table_name:
        return []   # caller must first discover the payments table via Phase 0

    where = _period_clause("docdate", year, month)
    if branch_id:
        where += f" AND branchid = '{branch_id}'"

    sql = f"SELECT * FROM {DB}.{table_name} WHERE {where} ORDER BY docdate, docno"
    conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        return [_clean(r) for r in _rows_as_dicts(cur, rows)]
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# 8. BRANCHES & ITEMS (reference data)
# ══════════════════════════════════════════════════════════════════════════════

def get_softech_branches() -> list[dict]:
    """
    Return branch reference data from SOFTECH.
    Table/column names from existing sync task (apps/sync/tasks.py).
    Returns: [{branchid, nameen, namear, address, phone}]
    """
    sql = f"""
        SELECT
            branchcode,
            branchname,
            branchename,
            branchaddress,
            branchphones
        FROM   {DB}.branches
        ORDER  BY branchcode
    """
    conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute('SET ROWCOUNT 200')
        try:
            cur.execute(sql)
            rows = cur.fetchall()
            return [_clean(r) for r in _rows_as_dicts(cur, rows)]
        finally:
            try:
                cur.execute('SET ROWCOUNT 0')
            except Exception:
                pass
    except Exception:
        return []
    finally:
        conn.close()


def get_stktrans_doccodes() -> list[dict]:
    """
    Return distinct doccodes present in stktrans with counts.
    Useful for verifying which transaction types exist.
    """
    sql = f"""
        SELECT doccode, COUNT(*) AS cnt
        FROM   {DB}.stktrans
        GROUP  BY doccode
        ORDER  BY cnt DESC
    """
    conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        return [_clean(r) for r in _rows_as_dicts(cur, rows)]
    finally:
        conn.close()


def get_date_range_in_stktrans() -> dict:
    """Return the earliest and latest docdate in stktrans."""
    sql = f"SELECT MIN(docdate) AS min_date, MAX(docdate) AS max_date FROM {DB}.stktrans"
    conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        row = cur.fetchone()
        return {
            "min_date": _safe(row[0]) if row else None,
            "max_date": _safe(row[1]) if row else None,
        }
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# 9. TOP ITEMS BY VALUE  (useful for expense / COGS breakdown)
# ══════════════════════════════════════════════════════════════════════════════

def get_top_items_by_purchase_value(
    year: int,
    month: int,
    limit: int = 50,
    branch_id: str | None = None,
    conn=None,
) -> list[dict]:
    """Top N items by gross purchase value for a given month (doccode '10' only).

    Pass ``conn`` to reuse an existing Sybase connection.
    """
    where = _period_clause("t.docdate", year, month)
    where += f" AND t.doccode = '{DOCCODE_PURCHASE}'"
    if branch_id:
        where += f" AND t.branchcode = '{branch_id}'"

    sql = f"""
        SELECT
            t.itemcode,
            SUM(t.transprice_total)                                    AS gross_value,
            SUM(t.transprice_total - ISNULL(t.itemsalestax,0))        AS net_value,
            SUM(t.transqty)                                            AS total_qty,
            COUNT(DISTINCT t.docnumber)                                AS doc_count
        FROM   {DB}.stktrans t
        WHERE  {where}
        GROUP  BY t.itemcode
        ORDER  BY gross_value DESC
    """
    _own = conn is None
    if _own:
        conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute(f'SET ROWCOUNT {limit}')
        try:
            cur.execute(sql)
            rows = cur.fetchall()
            return [_clean(r) for r in _rows_as_dicts(cur, rows)]
        finally:
            # Reset ROWCOUNT so shared connections are not left with a row limit
            try:
                cur.execute('SET ROWCOUNT 0')
            except Exception:
                pass
    finally:
        if _own:
            conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# 10. YEAR-TO-DATE SUMMARY (for executive dashboard)
# ══════════════════════════════════════════════════════════════════════════════

def get_ytd_summary(year: int, conn=None) -> list[dict]:
    """
    Monthly P&L aggregates for every month in `year`, all branches combined.
    Returns up to 12 rows (one per month with data).

    Uses only external cash-affecting transactions:
      purchases_gross  : doccode '10'  (purchases from supplier)
      purchase_returns : doccode '120' (returns to supplier, positive value)
      sales_gross      : doccode '115' (sales to customer)
      sales_returns    : doccode '30'  (customer returns, positive value)
      total_tax        : itemsalestax on sales rows only

    Signed net columns (returns already negated — use these for P&L display):
      net_revenue    = sales_gross   - sales_returns
      net_purchases  = purchases_gross - purchase_returns
      gross_profit   = net_revenue   - net_purchases  (Python-derived)
    """
    sql = f"""
        SELECT
            MONTH(docdate)                                                AS month_num,
            -- ── Gross unsigned ─────────────────────────────────────────────
            SUM(CASE WHEN doccode = '{DOCCODE_PURCHASE}'
                     THEN transprice_total ELSE 0 END)                  AS purchases_gross,
            SUM(CASE WHEN doccode = '{DOCCODE_SUPPLIER_RETURN}'
                     THEN transprice_total ELSE 0 END)                  AS purchase_returns,
            SUM(CASE WHEN doccode = '{DOCCODE_SALES}'
                     THEN transprice_total ELSE 0 END)                  AS sales_gross,
            SUM(CASE WHEN doccode = '{DOCCODE_CUSTOMER_RETURN}'
                     THEN transprice_total ELSE 0 END)                  AS sales_returns,
            SUM(CASE WHEN doccode = '{DOCCODE_SALES}'
                     THEN ISNULL(itemsalestax, 0) ELSE 0 END)           AS total_tax,
            -- ── Signed net (pair netted, reversals negated) ────────────────
            {_signed_sum_sql('transprice_total',
                             pos=f"'{DOCCODE_SALES}'",
                             neg=f"'{DOCCODE_CUSTOMER_RETURN}'",
                             alias='net_revenue')},
            {_signed_sum_sql('transprice_total',
                             pos=f"'{DOCCODE_PURCHASE}'",
                             neg=f"'{DOCCODE_SUPPLIER_RETURN}'",
                             alias='net_purchases')}
        FROM   {DB}.stktrans
        WHERE  YEAR(docdate) = {year}
        AND    doccode IN (
                   '{DOCCODE_PURCHASE}',
                   '{DOCCODE_SUPPLIER_RETURN}',
                   '{DOCCODE_SALES}',
                   '{DOCCODE_CUSTOMER_RETURN}'
               )
        GROUP  BY MONTH(docdate)
        ORDER  BY month_num
    """
    _own = conn is None
    if _own:
        conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        result = [_clean(r) for r in _rows_as_dicts(cur, rows)]
    finally:
        if _own:
            conn.close()

    # Derive gross_profit per month in Python
    import decimal
    D = decimal.Decimal
    for r in result:
        rev  = D(str(r.get("net_revenue")  or 0))
        cost = D(str(r.get("net_purchases") or 0))
        r["gross_profit"]     = rev - cost
        r["gross_margin_pct"] = (
            (r["gross_profit"] / rev * D("100")).quantize(D("0.01"))
            if rev > 0 else D("0")
        )
    return result
