"""
apps/procurement/queries.py

SOFTECH Sybase SQL for the Procurement Intelligence Platform.

ABSOLUTE RULES:
  - SELECT ONLY. Never INSERT / UPDATE / DELETE on SOFTECHDB9.
  - doccode '10'  = purchase from supplier  → +qty, +value
  - doccode '120' = return to supplier       → negate qty and value in Python
  - transqty is always stored positive in stktrans; direction is doccode-driven.

v2 additions (Procurement Intelligence v2):
  QUERY_SUPPLIERS_SEGMENTED — all person types (no ptcode filter) for segmentation

Tax columns confirmed present in this SOFTECH Sybase 12.5 instance
(discovered via inspect_tax_columns management command):
  stktrans.itemsalestax  — absolute tax amount per line (EGP value, e.g. 14.00)
  stktrans.origintaxp    — tax rate percentage applied to this line (e.g. 14.00 = 14%)
  stktransm.origintaxp   — same rate at document/header level
  items.itemsalestaxp    — item master tax rate %
  items.taxcode          — e-invoice tax code
NOT present: stktransm.docvat, stktransm.docextra (do not use)

Column indices for QUERY_PURCHASES_INCREMENTAL:
  [0]  supplier_code    (stktransm.cust_branch_code)
  [1]  branch_code      (stktransm.branchcode)
  [2]  doccode          '10' or '120'
  [3]  doc_number       (stktransm.docnumber)
  [4]  doc_date         (stktransm.docdate)
  [5]  item_code        (stktrans.itemcode)
  [6]  paid_qty         SUM(transqty) over PAID lines only (excludes free lines);
                        always ≥ 0; negate for doccode 120
  [7]  paid_value       SUM(transprice_total) over PAID lines only; negate for 120
  [8]  unit_price       AVG(transprice) over PAID lines only – nominal price/pack
  [9]  cost_price       AVG(newcostprice) – weighted-avg cost at transaction
  [10] buyer_code       (stktransm.usercode)
  [11] doc_value        (stktransm.docvalue) – total invoice header value
  [12] store_code       (stktrans.storecode)
  [13] line_tax_amount  SUM(stktrans.itemsalestax) – absolute VAT on this line
  [14] tax_rate_pct     AVG(stktrans.origintaxp)   – tax rate % (e.g. 14.00)
  [15] free_qty         SUM(transqty) over FREE lines (pharmacydiscp>=100 OR
                        transprice=0).  THIS is the true FOC signal — free goods
                        are booked as separate 100%-discount lines that the old
                        GROUP BY merged into the paid line and hid.
"""

# ── MAIN PURCHASE LINES — incremental fetch ───────────────────────────────────
#
# Groups by (supplier, branch, doccode, docnumber, date, item) to collapse
# expiry-batch splits (dblitemflag > 1) into a single line — same technique
# as QUERY_SALES_INCREMENTAL for sales.
#
# Parameter: ? = integer lookback days (e.g. 30, 90, 365)
#
#
# FOC (بونص / free-goods) handling — CRITICAL:
#   In SOFTECH, free goods are entered as a SEPARATE stktrans line for the same
#   item (distinct batch/dblitemflag) carrying a 100% pharmacy discount
#   (pharmacydiscp = 100).  The free line may be zero-priced OR carry only VAT
#   (transprice = the tax amount).  Confirmed on real invoices 64550 / 64544:
#     item 4179 : paid line qty 100 @ 396 (phdisc 12) + FREE line qty 20 (phdisc 100)
#     item 91338: paid line qty 5  @ 70.18 (phdisc 20) + FREE line qty 1  (phdisc 100)
#   The old GROUP BY collapsed the paid + free lines together and AVG'd the price
#   away, so the free units were invisible.  We now split each (invoice × item)
#   group into PAID vs FREE with CASE aggregates so the free quantity survives.
#
#   free_line := (pharmacydiscp >= 100)  OR  (transprice = 0)
#     paid_qty   / paid_value / unit_price  → computed over NON-free lines only
#     free_qty                              → sum of transqty on free lines
#     line_tax_amount                       → summed over ALL lines (VAT is due on
#                                             free goods too)
#
QUERY_PURCHASES_INCREMENTAL = """
    SELECT
        sm.cust_branch_code                              AS supplier_code,
        sm.branchcode                                    AS branch_code,
        sm.doccode,
        sm.docnumber                                     AS doc_number,
        sm.docdate                                       AS doc_date,
        st.itemcode                                      AS item_code,
        SUM(CASE WHEN COALESCE(st.pharmacydiscp,0) >= 100 OR st.transprice = 0
                 THEN 0 ELSE st.transqty END)            AS paid_qty,
        SUM(CASE WHEN COALESCE(st.pharmacydiscp,0) >= 100 OR st.transprice = 0
                 THEN 0 ELSE COALESCE(st.transprice_total,0) END) AS paid_value,
        AVG(CASE WHEN COALESCE(st.pharmacydiscp,0) >= 100 OR st.transprice = 0
                 THEN NULL ELSE st.transprice END)       AS unit_price,
        AVG(st.newcostprice)                             AS cost_price,
        sm.usercode                                      AS buyer_code,
        sm.docvalue                                      AS doc_value,
        st.storecode                                     AS store_code,
        SUM(COALESCE(st.itemsalestax, 0))                AS line_tax_amount,
        AVG(COALESCE(st.origintaxp,   0))                AS tax_rate_pct,
        SUM(CASE WHEN COALESCE(st.pharmacydiscp,0) >= 100 OR st.transprice = 0
                 THEN st.transqty ELSE 0 END)            AS free_qty
    FROM SOFTECHDB9.dbo.stktransm sm
    JOIN SOFTECHDB9.dbo.stktrans  st
        ON  st.branchcode = sm.branchcode
        AND st.doccode    = sm.doccode
        AND st.docnumber  = sm.docnumber
        AND st.docdate    = sm.docdate
    WHERE sm.docdate >= DATEADD(day, -?, GETDATE())
      AND sm.doccode IN ('10', '120')
      AND st.itemcode   IS NOT NULL
      AND st.itemcode   != ''
      AND st.transqty   >  0
    GROUP BY
        sm.cust_branch_code, sm.branchcode, sm.doccode, sm.docnumber,
        sm.docdate, st.itemcode, sm.usercode, sm.docvalue, st.storecode
"""


# ── SUPPLIER MASTER from personsdata ─────────────────────────────────────────
#
# ptcode = '02' → supplier / distributor
# Column indices:
#   [0] personcode   supplier code (FK matches stktransm.personcode on purchase docs)
#   [1] personname   Arabic supplier name
#   [2] ptclassifcode  sub-classification (e.g. 'WH'=warehouse, 'MF'=manufacturer)
#
QUERY_SUPPLIERS = """
    SELECT
        pd.personcode,
        pd.personname,
        pd.ptclassifcode
    FROM SOFTECHDB9.dbo.personsdata pd
    WHERE pd.ptcode = '20'
      AND pd.personname IS NOT NULL
      AND pd.personname != ''
"""


# ── CURRENT STOCK BALANCES ────────────────────────────────────────────────────
#
# Reused from purchasing/queries.py pattern.
# Used in the procurement engine to measure current stock vs purchase history.
#
QUERY_PROCUREMENT_STKBAL = """
    SELECT
        sb.itemcode,
        sb.branchcode,
        SUM(sb.nowqty) AS nowqty
    FROM SOFTECHDB9.dbo.stkbal sb
    WHERE sb.nowqty    >  0
      AND sb.branchcode IS NOT NULL
      AND sb.itemcode   IS NOT NULL
      AND sb.itemcode   != ''
      AND sb.storecode  NOT IN ('102', '103', '105')
    GROUP BY sb.itemcode, sb.branchcode
"""


# ── ITEM PUBLIC PRICES — for margin computation ───────────────────────────────
#
# Fetches current public (retail) price per item.
# Used to compute purchase margin = (public_price - purchase_cost) / public_price.
#
# Column indices:
#   [0] itemcode
#   [1] itemsaleprice  — full-pack retail price (public price)
#   [2] itemcostprice  — current catalog cost (updated on each stock-receive)
#
QUERY_ITEM_PRICES = """
    SELECT
        i.itemcode,
        i.itemsaleprice,
        i.itemcostprice
    FROM SOFTECHDB9.dbo.items i
    WHERE i.itemnomoreuse != '1'
      AND i.itemarchive = 0
"""


# ── ITEM ↔ SUPPLIER MAPPING from items master ─────────────────────────────────
#
# itemssuppliers table maps each item to its supplier(s).
# main_supp='1' = primary supplier; others are secondary.
#
# Column indices:
#   [0] itemcode
#   [1] suppcode   — supplier code
#   [2] main_supp  — '1' if primary supplier
#   [3] supprice   — supplier's unit price (if stored)
#
QUERY_ITEM_SUPPLIERS = """
    SELECT
        iss.itemcode,
        iss.suppcode,
        iss.main_supp,
        COALESCE(iss.supprice, 0) AS supprice
    FROM SOFTECHDB9.dbo.itemssuppliers iss
    WHERE iss.suppcode IS NOT NULL AND iss.suppcode != ''
"""


# ── PURCHASE SUMMARY PER SUPPLIER (aggregate, last N days) ───────────────────
#
# Pre-aggregated summary directly from Sybase — used for quick KPI cards.
# Negates doccode 120 (returns) in SQL.
#
# Parameter: ? = lookback days
#
QUERY_SUPPLIER_SUMMARY = """
    SELECT
        sm.cust_branch_code                          AS supplier_code,
        COUNT(DISTINCT sm.docnumber)           AS invoice_count,
        SUM(CASE sm.doccode
            WHEN '10'  THEN  sm.docvalue
            WHEN '120' THEN -sm.docvalue
            ELSE 0 END)                        AS net_invoice_value,
        SUM(CASE sm.doccode
            WHEN '10'  THEN  st.transqty
            WHEN '120' THEN -st.transqty
            ELSE 0 END)                        AS net_qty,
        COUNT(DISTINCT st.itemcode)            AS distinct_items,
        MIN(sm.docdate)                        AS first_purchase,
        MAX(sm.docdate)                        AS last_purchase,
        COUNT(DISTINCT sm.branchcode)          AS branches_supplied
    FROM SOFTECHDB9.dbo.stktransm sm
    JOIN SOFTECHDB9.dbo.stktrans  st
        ON  st.branchcode = sm.branchcode
        AND st.doccode    = sm.doccode
        AND st.docnumber  = sm.docnumber
        AND st.docdate    = sm.docdate
    WHERE sm.docdate >= DATEADD(day, -?, GETDATE())
      AND sm.doccode IN ('10', '120')
      AND st.itemcode IS NOT NULL
      AND st.transqty >  0
    GROUP BY sm.cust_branch_code
"""


# ── PURCHASE TOTALS PER BRANCH (aggregate, last N days) ──────────────────────
#
# Used for branch procurement analysis (Module 11).
# Parameter: ? = lookback days
#
QUERY_BRANCH_PURCHASE_SUMMARY = """
    SELECT
        sm.branchcode,
        COUNT(DISTINCT sm.docnumber)           AS invoice_count,
        COUNT(DISTINCT sm.personcode)          AS supplier_count,
        COUNT(DISTINCT st.itemcode)            AS item_count,
        SUM(CASE sm.doccode
            WHEN '10'  THEN  sm.docvalue
            WHEN '120' THEN -sm.docvalue
            ELSE 0 END)                        AS net_value
    FROM SOFTECHDB9.dbo.stktransm sm
    JOIN SOFTECHDB9.dbo.stktrans  st
        ON  st.branchcode = sm.branchcode
        AND st.doccode    = sm.doccode
        AND st.docnumber  = sm.docnumber
        AND st.docdate    = sm.docdate
    WHERE sm.docdate >= DATEADD(day, -?, GETDATE())
      AND sm.doccode IN ('10', '120')
      AND st.transqty >  0
    GROUP BY sm.branchcode
"""


# ── PURCHASE MONTHLY TREND (last 12 months) ───────────────────────────────────
#
# Groups by year + month for trend charts.
# No parameter — always last 12 months.
#
QUERY_PURCHASE_MONTHLY_TREND = """
    SELECT
        YEAR(sm.docdate)                       AS yr,
        MONTH(sm.docdate)                      AS mo,
        COUNT(DISTINCT sm.docnumber)           AS invoice_count,
        SUM(CASE sm.doccode
            WHEN '10'  THEN  sm.docvalue
            WHEN '120' THEN -sm.docvalue
            ELSE 0 END)                        AS net_value,
        COUNT(DISTINCT sm.personcode)          AS supplier_count,
        COUNT(DISTINCT st.itemcode)            AS item_count
    FROM SOFTECHDB9.dbo.stktransm sm
    JOIN SOFTECHDB9.dbo.stktrans  st
        ON  st.branchcode = sm.branchcode
        AND st.doccode    = sm.doccode
        AND st.docnumber  = sm.docnumber
        AND st.docdate    = sm.docdate
    WHERE sm.docdate >= DATEADD(month, -12, GETDATE())
      AND sm.doccode IN ('10', '120')
      AND st.transqty >  0
    GROUP BY YEAR(sm.docdate), MONTH(sm.docdate)
    ORDER BY yr, mo
"""


# ── PRICE HISTORY PER ITEM (last N days) ──────────────────────────────────────
#
# Tracks purchase price evolution per item × supplier to detect price drift.
# Parameter: ? = lookback days, ?? = item code
#
QUERY_ITEM_PRICE_HISTORY = """
    SELECT
        sm.personcode                          AS supplier_code,
        sm.docdate                             AS doc_date,
        AVG(st.transprice)                     AS avg_price,
        MIN(st.transprice)                     AS min_price,
        MAX(st.transprice)                     AS max_price,
        SUM(st.transqty)                       AS total_qty
    FROM SOFTECHDB9.dbo.stktransm sm
    JOIN SOFTECHDB9.dbo.stktrans  st
        ON  st.branchcode = sm.branchcode
        AND st.doccode    = sm.doccode
        AND st.docnumber  = sm.docnumber
        AND st.docdate    = sm.docdate
    WHERE sm.doccode = '10'
      AND sm.docdate >= DATEADD(day, -?, GETDATE())
      AND st.itemcode  = ?
      AND st.transqty  > 0
    GROUP BY sm.personcode, sm.docdate
    ORDER BY sm.docdate DESC
"""


# ── TOP PURCHASED ITEMS (last N days, net qty) ───────────────────────────────
#
# Parameter: ? = lookback days
#
QUERY_TOP_PURCHASED_ITEMS = """
    SELECT TOP 50
        st.itemcode,
        COUNT(DISTINCT sm.docnumber)           AS invoice_count,
        COUNT(DISTINCT sm.personcode)          AS supplier_count,
        SUM(CASE sm.doccode
            WHEN '10'  THEN  st.transqty
            WHEN '120' THEN -st.transqty
            ELSE 0 END)                        AS net_qty,
        SUM(CASE sm.doccode
            WHEN '10'  THEN  st.transprice_total
            WHEN '120' THEN -st.transprice_total
            ELSE 0 END)                        AS net_value,
        MIN(CASE WHEN sm.doccode='10' THEN st.transprice END) AS min_price,
        MAX(CASE WHEN sm.doccode='10' THEN st.transprice END) AS max_price,
        AVG(CASE WHEN sm.doccode='10' THEN st.transprice END) AS avg_price
    FROM SOFTECHDB9.dbo.stktransm sm
    JOIN SOFTECHDB9.dbo.stktrans  st
        ON  st.branchcode = sm.branchcode
        AND st.doccode    = sm.doccode
        AND st.docnumber  = sm.docnumber
        AND st.docdate    = sm.docdate
    WHERE sm.docdate >= DATEADD(day, -?, GETDATE())
      AND sm.doccode IN ('10', '120')
      AND st.itemcode  IS NOT NULL
      AND st.transqty  >  0
    GROUP BY st.itemcode
    ORDER BY net_value DESC
"""


# ── SUPPLIER × ITEM FULL HISTORY (for mapping table) ─────────────────────────
#
# Full purchase history per (supplier, item) for the learning table.
# Parameter: ? = lookback days
#
QUERY_SUPPLIER_ITEM_MAPPING = """
    SELECT
        sm.personcode                          AS supplier_code,
        st.itemcode                            AS item_code,
        COUNT(DISTINCT sm.docnumber)           AS purchase_count,
        MAX(sm.docdate)                        AS last_purchase_date,
        MIN(CASE WHEN sm.doccode='10' THEN st.transprice END)  AS min_price,
        MAX(CASE WHEN sm.doccode='10' THEN st.transprice END)  AS max_price,
        AVG(CASE WHEN sm.doccode='10' THEN st.transprice END)  AS avg_price,
        SUM(CASE sm.doccode
            WHEN '10'  THEN  st.transqty
            WHEN '120' THEN -st.transqty
            ELSE 0 END)                        AS net_qty
    FROM SOFTECHDB9.dbo.stktransm sm
    JOIN SOFTECHDB9.dbo.stktrans  st
        ON  st.branchcode = sm.branchcode
        AND st.doccode    = sm.doccode
        AND st.docnumber  = sm.docnumber
        AND st.docdate    = sm.docdate
    WHERE sm.docdate >= DATEADD(day, -?, GETDATE())
      AND sm.doccode IN ('10', '120')
      AND sm.personcode IS NOT NULL AND sm.personcode != ''
      AND st.itemcode   IS NOT NULL AND st.itemcode   != ''
      AND st.transqty   >  0
    GROUP BY sm.personcode, st.itemcode
    HAVING SUM(CASE sm.doccode WHEN '10' THEN st.transqty ELSE 0 END) > 0
"""


# ── SUPPLIER SEGMENTATION — all person types for classification ───────────────
#
# Fetches ALL persons without ptcode restriction so we can classify:
#   Official distributors, Manufacturers, Warehouses, Patients, Internal, Services.
#
# Uses only confirmed SOFTECH Sybase 12.5 columns:
#   personcode, personname, ptcode, ptclassifcode.
# persontype / persontypeclassif are absent in this SOFTECH version — replaced
# with empty-string literals to maintain 6-column API shape.
#
# Column indices:
#   [0] personcode
#   [1] personname
#   [2] ptcode          — primary type code (e.g. '20'=supplier)
#   [3] ptclassifcode   — sub-classification (OD/MF/WH/etc.)
#   [4] persontype      — '' (not available in this Sybase version)
#   [5] persontypeclassif — '' (not available in this Sybase version)
#
QUERY_SUPPLIERS_SEGMENTED = """
    SELECT
        pd.personcode,
        pd.personname,
        COALESCE(pd.ptcode,        '') AS ptcode,
        COALESCE(pd.ptclassifcode, '') AS ptclassifcode,
        ''                             AS persontype,
        ''                             AS persontypeclassif
    FROM SOFTECHDB9.dbo.personsdata pd
    WHERE pd.personname IS NOT NULL
      AND pd.personname != ''
      AND pd.personcode IS NOT NULL
      AND pd.personcode != ''
"""


# NOTE: QUERY_INVOICE_TAX removed — tax is now fetched at the line level via
# stktrans.itemsalestax (cols [13]) and stktrans.origintaxp (col [14]) directly
# inside QUERY_PURCHASES_INCREMENTAL.  No second Sybase round-trip needed.
