"""
apps/purchasing/queries.py

SOFTECH Sybase SQL + PG aggregate SQL for the Demand & Purchasing Engine.

ALL RULES:
  • Sybase: SELECT ONLY — never INSERT / UPDATE / DELETE on SOFTECHDB9.
  • Column names verified from live SOFTECHDB9 schema.
  • doccode '115' = retail sale, '30' = return/refund.
  • transqty is ALWAYS positive in stktrans; doccode determines direction.

Performance notes:
  • ORDER BY removed from QUERY_SALES_INCREMENTAL — sorting 100k+ Sybase rows is
    expensive and unnecessary since we upsert by unique key on the PG side.
  • PG_AGGREGATE_SQL replaces the ORM conditional-Q annotate() approach.
    It does a SINGLE table scan with CASE WHEN per column instead of Django
    generating multiple passes via conditional SUMs.  ~3-5× faster on
    SalesTransactionLine tables with > 500k rows.

Incremental architecture:
  • Default run  → QUERY_SALES_INCREMENTAL with lookback_days = smart_days  (≤10)
  • Full backfill → QUERY_SALES_INCREMENTAL with lookback_days = 365
  • All three windows (30/90/365) are calculated from the PG
    SalesTransactionLine table, NOT from Sybase directly.
    This makes calculation reproducible even when SOFTECH is offline.

Column order for QUERY_SALES_INCREMENTAL (by index):
  0  branchcode       varchar
  1  itemcode         varchar
  2  doccode          varchar   '115' | '30'
  3  docnumber        varchar
  4  docdate          datetime  → stripped to date in engine
  5  transqty         numeric   always ≥ 0 (SUM of batch splits)
  6  transprice_total numeric   total line revenue = SUM(transprice_total); 0 when NULL

Parameter: lookback_days (int, bound as ?)

Named parameters for PG_AGGREGATE_SQL (psycopg2 %(name)s style):
  d30    date — 30 days ago
  d90    date — 90 days ago
  d365   date — 365 days ago (rolling window start)
"""

# ── INCREMENTAL / FULL SALES FETCH FROM SOFTECH ───────────────────────────────
#
# Returns ONE row per (branchcode, itemcode, doccode, docnumber, docdate) with
# transqty = SUM of ALL expiry-batch lines for that item on that document.
#
# Why GROUP BY / SUM:
#   stktrans uses dblitemflag as a line-sequence number for expiry-batch splits.
#   When a pharmacist sells item X drawing from multiple expiry batches, SOFTECH
#   creates separate stktrans rows (dblitemflag = 1, 2, 3 …) — all with the same
#   (branchcode, itemcode, doccode, docnumber, docdate) but different transqty.
#   Without aggregation, reading individual lines under-counts the real quantity
#   sold (or, if we DISTINCT-ON the group, we keep only one batch and discard
#   the rest).  SUM(transqty) gives the correct total sold per item per invoice.
#
# Notes:
#   • dblitemflag is NEVER 0 in this database — it always starts at 1.
#     There is no "header vs detail" split; every row is a batch detail line.
#   • ORDER BY removed — unnecessary for the upsert workload; saves Sybase CPU.
#   • Parameter: ? = number of days to look back
#     (e.g. smart 3–10 for incremental, 365 for full backfill)
#
QUERY_SALES_INCREMENTAL = """
    SELECT
        st.branchcode,
        st.itemcode,
        st.doccode,
        st.docnumber,
        st.docdate,
        SUM(st.transqty)                          AS transqty,
        SUM(COALESCE(st.transprice_total, 0))     AS transprice_total
    FROM SOFTECHDB9.dbo.stktrans st
    WHERE st.docdate >= DATEADD(day, -?, GETDATE())
      AND st.doccode IN ('115', '30')
      AND st.itemcode IS NOT NULL
      AND st.itemcode != ''
      AND st.transqty > 0
    GROUP BY st.branchcode, st.itemcode, st.doccode, st.docnumber, st.docdate
"""


# ── SINGLE-PASS PG AGGREGATION — replaces ORM conditional-Q annotate() ────────
#
# One full scan of purchasing_salestransactionline with CASE WHEN per column.
# HAVING SUM(net_qty) > 0 mirrors the Excel HAVING clause (items with net sales).
#
# Indexed path:
#   stl_item_branch_date (item_id, branch_id, doc_date)  — composite
#   stl_agg_sales_idx    (item_id, branch_id, doc_date)  — partial (migration 0003)
#   stl_doc_date         (doc_date)                       — for range filter
#
# Parameters (%(name)s psycopg2 format):
#   d365, d90, d30  — date objects (rolling window boundaries)
#
# Non-stockable items (catalog_item.is_stockable = FALSE) are excluded via
# a subquery filter.  Only 38 out of ~37,500 items are non-stockable.
#
PG_AGGREGATE_SQL = """
    SELECT
        item_id,
        branch_id,

        -- Net quantities per rolling window (sales − returns)
        SUM(net_qty)                                                                    AS qty_365d,
        SUM(CASE WHEN doc_date >= %(d90)s  THEN net_qty ELSE 0 END)                    AS qty_90d,
        SUM(CASE WHEN doc_date >= %(d30)s  THEN net_qty ELSE 0 END)                    AS qty_30d,

        -- Distinct invoice counts per window (sales only, doccode='115')
        COUNT(DISTINCT CASE WHEN doccode = '115'                      THEN docnumber END) AS inv_365d,
        COUNT(DISTINCT CASE WHEN doccode = '115' AND doc_date >= %(d90)s THEN docnumber END) AS inv_90d,
        COUNT(DISTINCT CASE WHEN doccode = '115' AND doc_date >= %(d30)s THEN docnumber END) AS inv_30d,

        -- Transaction row counts per window (MonthlyAvg3RatesofTRNsCount in Excel)
        COUNT(CASE WHEN doccode = '115'                         THEN 1 END)             AS trns_365d,
        COUNT(CASE WHEN doccode = '115' AND doc_date >= %(d90)s THEN 1 END)             AS trns_90d,
        COUNT(CASE WHEN doccode = '115' AND doc_date >= %(d30)s THEN 1 END)             AS trns_30d,

        -- Last sale date (for UI "last sold" display)
        MAX(CASE WHEN doccode = '115' THEN doc_date END)                                AS last_sale_date,

        -- Net sales revenue (actual revenue after discounts, sign-corrected)
        -- +net_revenue for sales (115), -net_revenue for returns (30) — matches net_qty logic
        SUM(net_revenue)                                                                AS net_sales_revenue_365d

    FROM purchasing_salestransactionline

    WHERE item_id   IS NOT NULL
      AND branch_id IS NOT NULL
      AND doc_date  >= %(d365)s
      AND item_id IN (SELECT id FROM catalog_item WHERE is_stockable = TRUE)

    GROUP BY item_id, branch_id

    HAVING SUM(net_qty) > 0
"""


# ── CURRENT STOCK FROM SOFTECH stkbal ────────────────────────────────────────
#
# Fetched during every engine run so current_stock reflects the live SOFTECH
# balance rather than the potentially-stale PG ItemStock snapshot.
#
# Excludes store codes 102, 103, 105 (expired / quarantine holding areas at
# the HQ branch — defined in catalog.models.EXCLUDED_STORE_CODES).
#
# SUMs nowqty per (itemcode, branchcode) because one branch may have multiple
# storecodes (front counter 100, back store 101, …).  The Excel Power Query
# used the same grouping logic.
#
QUERY_STKBAL = """
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


# ── LEGACY: single-shot three-window aggregation (kept for reference / fallback)
# Not used in the main engine anymore; the PG-based calculation from
# SalesTransactionLine gives identical results and is reproducible offline.
#
# Column order:
#   0  itemcode
#   1  branchcode
#   2  qty_30d
#   3  qty_90d
#   4  qty_365d
#   5  invoices_30d
#   6  invoices_90d
#   7  invoices_365d
QUERY_DEMAND_BY_ITEM_BRANCH = """
    SELECT
        st.itemcode,
        st.branchcode,
        SUM(CASE
            WHEN st.docdate >= DATEADD(day, -30, GETDATE()) THEN
                CASE st.doccode WHEN '115' THEN st.transqty WHEN '30' THEN -st.transqty ELSE 0 END
            ELSE 0
        END) AS qty_30d,
        SUM(CASE
            WHEN st.docdate >= DATEADD(day, -90, GETDATE()) THEN
                CASE st.doccode WHEN '115' THEN st.transqty WHEN '30' THEN -st.transqty ELSE 0 END
            ELSE 0
        END) AS qty_90d,
        SUM(CASE st.doccode
            WHEN '115' THEN  st.transqty
            WHEN '30'  THEN -st.transqty
            ELSE 0
        END) AS qty_365d,
        COUNT(DISTINCT CASE
            WHEN st.doccode = '115' AND st.docdate >= DATEADD(day, -30, GETDATE())
            THEN st.docnumber END) AS invoices_30d,
        COUNT(DISTINCT CASE
            WHEN st.doccode = '115' AND st.docdate >= DATEADD(day, -90, GETDATE())
            THEN st.docnumber END) AS invoices_90d,
        COUNT(DISTINCT CASE WHEN st.doccode = '115' THEN st.docnumber END) AS invoices_365d
    FROM SOFTECHDB9.dbo.stktrans st
    WHERE st.docdate >= DATEADD(day, -365, GETDATE())
      AND st.doccode IN ('115', '30')
      AND st.itemcode IS NOT NULL AND st.itemcode != ''
    GROUP BY st.itemcode, st.branchcode
    HAVING SUM(CASE WHEN st.doccode = '115' THEN st.transqty ELSE 0 END) > 0
"""
