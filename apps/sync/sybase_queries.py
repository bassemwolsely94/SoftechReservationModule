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

# ── CUSTOMERS (PIC — Individual Retail Customers Only) ────────────────────────
# ptcode '10' = customer, '11' = potential customer
# ptclassifcode filters:
#   '90' = delivery, '91' = cash retail (PIC), '15' = insurance (excluded)
#   B2B / insurance companies have ptcode '20','30','40' — excluded by ptcode filter
# We keep ptcode IN ('10','11') but exclude insurance ptclassifcodes
QUERY_CUSTOMERS = """
    SELECT
        lc.phcode, lc.branchcustname, lc.branchcustaddress1, lc.branchcustaddress2,
        lc.custdofbirth, lc.branchcode, '' AS personnote, lc.branchcustcode,
        lc.branchcustclassif, 0 AS custdiscp, '' AS personsstatus, lc.custbranchcode
    FROM SOFTECHDB9.dbo.localcustomers lc
    WHERE lc.phcode IS NOT NULL AND lc.phcode != ''
        p.ptcode, p.personname, p.personadd1, p.personadd2,
        p.persondofbirth, p.branchcode, p.personnote, p.ptcode,
        p.ptclassifcode, p.custdiscp, p.personsstatus
    FROM SOFTECHDB9.dbo.localcustomers p
    WHERE p.ptcode IN ('10', '11')
      AND p.ptclassifcode NOT IN ('15', '16', '17', '18', '20', '25', '30')
      AND (p.personsstatus IS NULL OR p.personsstatus != 'X')
"""

# ── CUSTOMER PHONES ───────────────────────────────────────────────────────────
QUERY_CUSTOMER_PHONES = """
    SELECT lc.phcode, lc.mobileno, '40' AS phonetype
    FROM SOFTECHDB9.dbo.localcustomers lc
    WHERE lc.phcode IS NOT NULL AND lc.phcode != ''
      AND lc.mobileno IS NOT NULL AND lc.mobileno != ''

    UNION ALL

    SELECT lc.phcode, lc.branchcustphone, '10' AS phonetype
    FROM SOFTECHDB9.dbo.localcustomers lc
    WHERE lc.phcode IS NOT NULL AND lc.phcode != ''
      AND lc.branchcustphone IS NOT NULL AND lc.branchcustphone != ''

    ORDER BY 1, 3
    SELECT ph.ptcode, ph.phoneno, ph.phonetype
    FROM SOFTECHDB9.dbo.personphones ph
    WHERE ph.ptcode IN ('10', '11') AND ph.phoneblock = 0
    ORDER BY ph.ptcode, ph.phonetype
"""

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
