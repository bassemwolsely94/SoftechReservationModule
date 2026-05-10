"""
apps/sync/sybase_queries.py
ALL column names verified from live SOFTECHDB9 schema.
ABSOLUTE RULE: SELECT only. Never INSERT/UPDATE/DELETE.
"""

# ── BRANCHES ──────────────────────────────────────────────────────────────────
QUERY_BRANCHES = """
    SELECT b.branchcode, b.branchname, b.branchename, b.branchaddress, b.branchphones
    FROM SOFTECHDB9.dbo.branches b
"""

# ── ITEM CATEGORIES ───────────────────────────────────────────────────────────
QUERY_CATEGORIES = """
    SELECT ic.itemsclassifcode, ic.itemsclassifname, ic.classifnamearabic
    FROM SOFTECHDB9.dbo.itemsclassif ic
"""

# ── ITEMS CATALOG ─────────────────────────────────────────────────────────────
# NOTE: phcode does not exist on the SOFTECHDB9.dbo.items table.
#       Chronic-medication detection is done via itemsclassif category names.
QUERY_ITEMS = """
    SELECT
        i.itemcode, i.itemname, i.itemname_scientific, i.itembarcode,
        i.itemclassifcode, i.suppcode, i.itemsaleprice, i.unitsaleprice,
        i.itemnomoreuse, i.itemarchive, i.familycode, i.fridgeitem,
        i.itemmedicine, i.itemcomment, i.itemlastupdate
    FROM SOFTECHDB9.dbo.items i
    WHERE i.itemnomoreuse != '1' AND i.itemarchive = 0
"""

# ── STOCK BALANCES ────────────────────────────────────────────────────────────
QUERY_STOCK = """
    SELECT sb.itemcode, sb.branchcode, sb.storecode, sb.nowqty,
           sb.monthlyqty, sb.onorderqty, sb.modif_lastupdate
    FROM SOFTECHDB9.dbo.stkbal sb WHERE sb.nowqty > 0
"""

# ── CUSTOMERS (PIC — localcustomers table) ───────────────────────────────────
# Real column names discovered via syscolumns on 2026-05-09.
# PK: (branchcode, branchcustcode).
# Phones are ON localcustomers (mobileno = mobile, branchcustphone = landline).
# ischronic flag is SOFTECH-native — sync it directly onto the Customer record.
# branchcustclassif: classification code (varchar 2).
QUERY_CUSTOMERS = """
    SELECT
        lc.branchcode, lc.branchcustcode, lc.branchcustname,
        lc.branchcustaddress1, lc.branchcustaddress2,
        lc.custdofbirth, lc.mobileno, lc.branchcustphone,
        lc.branchcustclassif, lc.ischronic
    FROM SOFTECHDB9.dbo.localcustomers lc
"""

# ── CUSTOMER PHONES ───────────────────────────────────────────────────────────
# Phones are embedded on localcustomers (mobileno / branchcustphone).
# personphones table uses ptcode which does not exist on localcustomers.
# This query is kept as a stub so call-sites don't break; it returns nothing.
QUERY_CUSTOMER_PHONES = None  # not used — phones fetched in QUERY_CUSTOMERS

# ── SALES LINES — incremental (last 10 min) ───────────────────────────────────
QUERY_CUSTOMER_SALES_LINES_RECENT = """
    SELECT
        st.personcode, st.branchcode, st.doccode, st.docnumber, st.docdate,
        st.itemcode, st.transqty, st.transprice, st.transprice_total, st.storecode
    FROM SOFTECHDB9.dbo.stktrans st
    WHERE st.docdate >= DATEADD(minute, -10, GETDATE())
    AND st.doccode IN ('115', '30')
    AND st.personcode IS NOT NULL AND st.personcode != ''
    ORDER BY st.docdate DESC
"""

# ── SALES LINES — full backfill (last 90 days) ────────────────────────────────
QUERY_CUSTOMER_SALES_LINES_FULL = """
    SELECT
        st.personcode, st.branchcode, st.doccode, st.docnumber, st.docdate,
        st.itemcode, st.transqty, st.transprice, st.transprice_total, st.storecode
    FROM SOFTECHDB9.dbo.stktrans st
    WHERE st.docdate >= DATEADD(day, -90, GETDATE())
    AND st.doccode IN ('115', '30')
    AND st.personcode IS NOT NULL AND st.personcode != ''
    ORDER BY st.docdate DESC
"""

# ── SOFTECH RESERVATIONS ──────────────────────────────────────────────────────
QUERY_SOFTECH_RESERVATIONS = """
    SELECT
        sm.branchcode, sm.doccode, sm.docnumber, sm.docdate,
        sm.cust_branch_code, sm.docvalue, sm.storecode, sm.usercode,
        st.itemcode, st.transqty, st.transprice
    FROM SOFTECHDB9.dbo.stktransm sm
    JOIN SOFTECHDB9.dbo.stktrans st
        ON sm.branchcode = st.branchcode AND sm.doccode = st.doccode
        AND sm.docnumber = st.docnumber AND sm.docdate = st.docdate
    WHERE sm.doccode IN ('80', '180')
    ORDER BY sm.docdate DESC
"""

# ── USERS ─────────────────────────────────────────────────────────────────────
QUERY_USERS = """
    SELECT u.userid, u.usercode, u.usergroup, u.user_nomore, u.branchcode, u.storecode
    FROM SOFTECHDB9.dbo.users u WHERE u.user_nomore = '0'
"""

QUERY_EXISTING_RESERVATIONS = None

# ── STKTRANS REFERENCE VALIDATION ─────────────────────────────────────────────
# Used when the supplying branch enters an ERP transaction number on a transfer.
# Validates that the docnumber exists in stktrans for the given branch and doccode.
QUERY_VALIDATE_STKTRANS = """
    SELECT sm.docnumber, sm.doccode, sm.branchcode, sm.docdate, sm.docvalue,
           sm.usercode, sm.storecode
    FROM SOFTECHDB9.dbo.stktransm sm
    WHERE sm.docnumber = ?
      AND sm.branchcode = ?
      AND sm.doccode IN ('110', '115', '501', '502')
"""

# ── ITEM SEARCH (live from SOFTECH, includes public price) ────────────────────
# Used by transfer/reservation create screens to search items with real-time price.
QUERY_ITEM_SEARCH = """
    SELECT TOP 30
        i.itemcode, i.itemname, i.itemname_scientific, i.itembarcode,
        i.itemclassifcode, i.itemsaleprice, i.unitsaleprice,
        i.itemnomoreuse, i.itemarchive, i.fridgeitem, i.itemmedicine
    FROM SOFTECHDB9.dbo.items i
    WHERE i.itemnomoreuse != '1'
      AND i.itemarchive = 0
      AND (
          i.itemcode LIKE ?
          OR i.itemname LIKE ?
          OR i.itembarcode LIKE ?
      )
    ORDER BY i.itemname
"""

# ── CHRONIC MEDICATIONS (classification-name-based) ──────────────────────────
# SOFTECH items table has no phcode / ATC column.
# We identify chronic items via Arabic and English keywords in the
# therapeutic-category name (itemsclassif.classifnamearabic / itemsclassifname).
QUERY_CHRONIC_ITEMS = """
    SELECT i.itemcode, i.itemname, ic.itemsclassifname, ic.classifnamearabic
    FROM SOFTECHDB9.dbo.items i
    LEFT JOIN SOFTECHDB9.dbo.itemsclassif ic
           ON i.itemclassifcode = ic.itemsclassifcode
    WHERE i.itemnomoreuse != '1'
      AND i.itemarchive = 0
      AND (
            ic.classifnamearabic LIKE N'%ضغط%'
         OR ic.classifnamearabic LIKE N'%سكر%'
         OR ic.classifnamearabic LIKE N'%كوليسترول%'
         OR ic.classifnamearabic LIKE N'%الغدة الدرقية%'
         OR ic.classifnamearabic LIKE N'%قلب%'
         OR ic.classifnamearabic LIKE N'%ربو%'
         OR ic.classifnamearabic LIKE N'%تخثر%'
         OR ic.classifnamearabic LIKE N'%الصرع%'
         OR ic.classifnamearabic LIKE N'%باركنسون%'
         OR ic.classifnamearabic LIKE N'%اكتئاب%'
         OR ic.classifnamearabic LIKE N'%مناعة%'
         OR ic.classifnamearabic LIKE N'%هشاشة%'
         OR ic.itemsclassifname LIKE '%hypertens%'
         OR ic.itemsclassifname LIKE '%diabet%'
         OR ic.itemsclassifname LIKE '%cardiovasc%'
         OR ic.itemsclassifname LIKE '%cholesterol%'
         OR ic.itemsclassifname LIKE '%thyroid%'
         OR ic.itemsclassifname LIKE '%asthma%'
         OR ic.itemsclassifname LIKE '%anticoagul%'
         OR ic.itemsclassifname LIKE '%epilep%'
         OR ic.itemsclassifname LIKE '%parkinson%'
         OR ic.itemsclassifname LIKE '%depress%'
         OR ic.itemsclassifname LIKE '%immunosuppress%'
         OR ic.itemsclassifname LIKE '%osteoporos%'
      )
    ORDER BY ic.itemsclassifname, i.itemname
"""
