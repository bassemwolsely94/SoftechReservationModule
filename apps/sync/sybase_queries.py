"""
apps/sync/sybase_queries.py
ALL column names verified from live SOFTECHDB9 schema.
ABSOLUTE RULE: SELECT only. Never INSERT/UPDATE/DELETE.

Full reference for all 69 columns of SOFTECHDB9.dbo.items, their confirmed meanings,
Django model mappings, filter params, and known TODOs:
    docs/softech_items_reference.md
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
# Row layout (index-mapped in sync_items):
#  [0]  i.itemcode              PK varchar(6)
#  [1]  i.itemname              main name
#  [2]  i.itemname_scientific   scientific / generic name
#  [3]  i.itembarcode           barcode (used for item search)
#  [4]  i.itemclassifcode       FK → itemsclassif (therapeutic category)
#  [5]  i.suppcode              fallback supplier code (itemssuppliers.main_supp='1' is authoritative)
#  [6]  i.itemsaleprice         full-pack retail price
#  [7]  i.unitsaleprice         per-unit / per-strip price
#  [8]  i.itemnomoreuse         '1' = discontinued
#  [9]  i.itemarchive           1 = archived
#  [10] i.familycode            FK → itemsfamily.familycode
#  [11] i.fridgeitem            '1' = requires refrigeration
#  [12] i.itemmedicine          FK → itemstree.cdlcode (general medicine category)
#  [13] i.itemcomment           free-text comment
#  [14] i.itemlastupdate        last catalog update timestamp
#  [15] i.itemcostprice         CURRENT catalog cost price (updated on every stock receive)
#  [16] i.itemproducercode      FK → itemsproducers.itemproducercode (manufacturer)
#  [17] i.unitcode              FK → itemsunits.unitcode (pack sub-unit type e.g. strip, vial)
#  [18] i.itemshapecode         FK → itemshape.itemshapecode (dosage form e.g. tablet, syrup)
#  [19] i.itemorigincode        FK → itemsorigin.itemorigincode (country of origin)
#  [20] i.itemeffectcode        FK → itemseffect.itemeffectcode (primary disease / indication)
#  [21] i.itemeffectcode2       FK → itemseffect2.itemeffectcode2 (secondary indication)
#  [22] i.itemtrans             1=stockable, 0=non-stockable
#  [23] i.hi_typecode           insurance type: 0=none,1=Talbia,2=TPA,3=Takaful,4=Other
#  [24] i.itemslevel            0=standard, 1=premium
#  [25] i.itempointsys          0=no points, 1=points-eligible
#  [26] i.packqty               units (strips/vials) per pack
#  [27] i.itemtrans1            branch permissions: 0=full,1=dispatch only,2=return only,3=stop
#  [28] i.itemtrans2            supplier permissions: 0=full,1=buy only,2=return only,3=stop
#  [29] i.itemtrans3            customer permissions: 0=full,1=sell only,2=return only,3=stop
#  [30] i.itemnosaleclassif     dispensing/contract restriction code (10=normal,20=#2,30=#3,31=#4)
#  [31] i.fmi                   fast-moving item flag (1=FMI)
#  [32] i.itemstoreclassif      FK → custdiscpclassif.custdiscpcode (contract discount tier)
QUERY_ITEMS = """
    SELECT
        i.itemcode, i.itemname, i.itemname_scientific, i.itembarcode,
        i.itemclassifcode, i.suppcode, i.itemsaleprice, i.unitsaleprice,
        i.itemnomoreuse, i.itemarchive, i.familycode, i.fridgeitem,
        i.itemmedicine, i.itemcomment, i.itemlastupdate,
        i.itemcostprice,
        i.itemproducercode,
        i.unitcode,
        i.itemshapecode,
        i.itemorigincode,
        i.itemeffectcode,
        i.itemeffectcode2,
        i.itemtrans,
        i.hi_typecode,
        i.itemslevel,
        i.itempointsys,
        i.packqty,
        i.itemtrans1,
        i.itemtrans2,
        i.itemtrans3,
        i.itemnosaleclassif,
        i.fmi,
        i.itemstoreclassif,
        i.pharmacydiscp,
        i.additionaldiscp,
        i.specialdiscp,
        i.posdiscp,
        i.itemsaleprice_tax,
        i.itemsalestaxp
    FROM SOFTECHDB9.dbo.items i
"""
# NOTE: no WHERE filter — the FULL master is synced. Discontinued
# (itemnomoreuse='1') AND archived (itemarchive=1) items are BOTH included, each
# synced with is_active=False plus its own flag (no_more_use / item_archive; see
# sync_items). This lets purchasing surface & avoid them flagged, while other
# modules (which filter is_active) keep hiding them.

# ── ITEM ENRICHMENT LOOKUPS ───────────────────────────────────────────────────

# custdiscpclassif — contract discount classification reference table.
# items.itemstoreclassif (FK) → custdiscpclassif.custdiscpcode (PK).
# Used by SOFTECH to assign items to contract pricing tiers.
# See docs/softech_items_reference.md for full code map.
QUERY_CUSTDISCPCLASSIF = """
    SELECT c.custdiscpcode, c.custdiscpdescr
    FROM SOFTECHDB9.dbo.custdiscpclassif c
    WHERE c.custdiscpdescr IS NOT NULL AND c.custdiscpdescr != ''
"""

# itemsproducers — simple code→name lookup for manufacturers.
# itemproducercode is the PK; items.itemproducercode is the FK.
QUERY_ITEMSPRODUCERS = """
    SELECT ip.itemproducercode, ip.itemproducername
    FROM SOFTECHDB9.dbo.itemsproducers ip
    WHERE ip.itemproducername IS NOT NULL AND ip.itemproducername != ''
"""

# itemsunits — pack sub-unit type (strip, vial, ampoule, etc.)
QUERY_ITEMSUNITS = """
    SELECT iu.unitcode, iu.unitname
    FROM SOFTECHDB9.dbo.itemsunits iu
    WHERE iu.unitname IS NOT NULL
"""

# itemshape — dosage form (tablet, capsule, syrup, injection, etc.)
QUERY_ITEMSHAPE = """
    SELECT ish.itemshapecode, ish.itemshapename, ish.shapenamearabic
    FROM SOFTECHDB9.dbo.itemshape ish
"""

# itemsorigin — country of origin + import flag
QUERY_ITEMSORIGIN = """
    SELECT io.itemorigincode, io.itemoriginname, io.originnamearabic, io.importedorigin
    FROM SOFTECHDB9.dbo.itemsorigin io
"""

# itemseffect — primary disease / therapeutic indication
QUERY_ITEMSEFFECT = """
    SELECT ie.itemeffectcode, ie.itemeffectname, ie.effectnamearabic
    FROM SOFTECHDB9.dbo.itemseffect ie
"""

# itemseffect2 — secondary disease / therapeutic indication
QUERY_ITEMSEFFECT2 = """
    SELECT ie2.itemeffectcode2, ie2.itemeffectname2, ie2.effectnamearabic2
    FROM SOFTECHDB9.dbo.itemseffect2 ie2
"""

# activeingredients — master table: aicode → ainame
QUERY_ACTIVE_INGREDIENTS = """
    SELECT ai.aicode, ai.ainame
    FROM SOFTECHDB9.dbo.activeingredients ai
    WHERE ai.ainame IS NOT NULL AND ai.ainame != ''
"""

# itemsai — junction: one item can have multiple active ingredients
QUERY_ITEMSAI = """
    SELECT ia.itemcode, ia.aicode
    FROM SOFTECHDB9.dbo.itemsai ia
    WHERE ia.aiblock IS NULL OR ia.aiblock != '1'
"""

# ── STOCK BALANCES ────────────────────────────────────────────────────────────
QUERY_STOCK = """
    SELECT sb.itemcode, sb.branchcode, sb.storecode, sb.nowqty,
           sb.monthlyqty, sb.onorderqty, sb.modif_lastupdate
    FROM SOFTECHDB9.dbo.stkbal sb WHERE sb.nowqty > 0
"""

# ── PERSON TYPES — lookup table ───────────────────────────────────────────────
# ptcode is the person-class code (e.g. '01'=عميل, '02'=مورد, '03'=مصنع …).
# ptdescr = Arabic name, ptedescr = English name.
QUERY_PERSONTYPES = """
    SELECT pt.ptcode, pt.ptdescr, pt.ptedescr
    FROM SOFTECHDB9.dbo.persontypes pt
"""

# ── PERSONSDATA CHANNEL MAP (institutional accounts only) ────────────────────
# NOTE: stktransm.phcode = customer PIC (same as localcustomers.phcode, e.g. '01HD1').
# However, personsdata uses a completely different code scheme for its ~405 institutional
# accounts (hospitals, insurance cos), so phcode → personsdata yields 0 matches for
# retail customers.
# The AUTHORITATIVE channel per invoice is stktransm.ptclassifcode, read directly.
# This query is kept as a reference but is no longer called from sync_sales.
QUERY_PERSONSDATA_CHANNELS = """
    SELECT pd.personcode, pd.ptclassifcode
    FROM SOFTECHDB9.dbo.personsdata pd
    WHERE pd.ptclassifcode IS NOT NULL
      AND pd.ptclassifcode != ''
      AND pd.ptcode = '10'
"""

# ── PERSON TYPE CLASSIFICATIONS — sub-classif lookup ─────────────────────────
# Each (ptcode, ptclassifcode) pair maps to a display label (ptclassifdescr).
# For customers: e.g. ('01','90')='توصيل', ('01','91')='كاش', ('01','15')='تأمين'.
# For suppliers: e.g. ('02','WH')='موزع', ('02','MF')='مصنع'  … etc.
QUERY_PERSONTYPESCLASSIF = """
    SELECT pc.ptcode, pc.ptclassifcode, pc.ptclassifdescr
    FROM SOFTECHDB9.dbo.persontypesclassif pc
"""

# ── CUSTOMERS (localcustomers LEFT JOIN personsdata) ──────────────────────────
# Row layout — index-mapped in sync_customers:
#  [0]  lc.branchcode
#  [1]  lc.branchcustcode          (softech_id / sequential per-branch number)
#  [2]  lc.branchcustname
#  [3]  lc.branchcustaddress1
#  [4]  lc.branchcustaddress2
#  [5]  lc.custdofbirth
#  [6]  lc.mobileno
#  [7]  lc.branchcustphone
#  [8]  lc.branchcustclassif       (branch-level classif, used as fallback)
#  [9]  lc.ischronic
#  [10] lc.phcode                  (PIC — global unique customer code)
#  [11] lc.orderbranchcode         (default delivery/order branch for this customer)
#  [12] pd.ptcode                  (person type code, from personsdata)
#  [13] pd.ptclassifcode           (person classif code — AUTHORITATIVE channel)
#  [14] pd.personglobalcode        (global person code, from personsdata)
#
# personsdata is LEFT JOINed on phcode = personcode, so rows without a PIC still
# appear but pd.* columns will be NULL.
QUERY_CUSTOMERS = """
    SELECT
        lc.branchcode, lc.branchcustcode, lc.branchcustname,
        lc.branchcustaddress1, lc.branchcustaddress2,
        lc.custdofbirth, lc.mobileno, lc.branchcustphone,
        lc.branchcustclassif, lc.ischronic,
        lc.phcode,
        lc.orderbranchcode,
        pd.ptcode,
        pd.ptclassifcode,
        pd.personglobalcode
    FROM SOFTECHDB9.dbo.localcustomers lc
    LEFT JOIN SOFTECHDB9.dbo.personsdata pd
        ON pd.personcode = lc.phcode
"""

# ── CUSTOMER PHONES ───────────────────────────────────────────────────────────
# personphones.personcode = lc.phcode (the PIC, e.g. "01HD14").
# One PIC can have multiple phone rows. We pull all non-blocked entries and
# pick up to 2 phones per PIC in sync_customers (phone + phone_alt).
# stckorderallow='1' marks the preferred ordering/contact phone — order by it
# DESC so the primary phone sorts first.
QUERY_CUSTOMER_PHONES = """
    SELECT pp.personcode, pp.phoneno, pp.stckorderallow
    FROM SOFTECHDB9.dbo.personphones pp
    WHERE pp.phoneblock = 0
      AND pp.phoneno IS NOT NULL
    ORDER BY pp.personcode, pp.stckorderallow DESC, pp.phoneno
"""

# ── SALES LINES — incremental (last 10 min) ───────────────────────────────────
# Row layout (index-mapped in sync_sales):
#  [0]  st.personcode         (customer code — maps to Customer.softech_id)
#  [1]  st.branchcode         (transaction branch)
#  [2]  st.doccode            ('115'=sale, '30'=return)
#  [3]  st.docnumber          (invoice number; may come as float, normalised to int string)
#  [4]  st.docdate            (invoice date/datetime)
#  [5]  st.itemcode           (item code — maps to Item.softech_id)
#  [6]  st.transqty           (quantity)
#  [7]  st.transprice         (unit price)
#  [8]  st.transprice_total   (line total)
#  [9]  st.storecode          (warehouse/store code within branch → PurchaseHistory.store_code)
#  [10] sm.usercode           (cashier ERP usercode → PurchaseHistory.softech_user)
#  [11] sm.phcode             (customer PIC — same format as localcustomers.phcode, e.g. '01HD1'.
#                              personsdata uses a different code scheme so the phcode→personsdata
#                              join yields 0 matches; channel comes from sm.ptclassifcode [14].)
#  [12] sm.cust_branch_code   (customer ordering/delivery branch → PurchaseHistory.cust_branch_code)
#  [13] sm.ptcode             (customer person-type code on this invoice → PurchaseHistory.sales_person_type)
#                              e.g. '10'='عـمـيــل' (Corporate), '11'='عميل فرد' (Individual)
#  [14] sm.ptclassifcode      (AUTHORITATIVE sales channel on this invoice → PurchaseHistory.sales_channel)
#                              e.g. '91'='عميل نقدى', '90'='عميل Delivery', '10'='تعاقدات/آجل',
#                                   '15'='تأمين صحي', '11'='موظفيين', '99'='Vip'
#  [15] st.newcostprice      (running weighted-average cost per unit at time of transaction →
#                              PurchaseHistoryLine.cost_at_sale.
#                              This is the AUTHORITATIVE cost for COGS calculation.
#                              Item.cost_price is the CURRENT catalog cost (updated every sync)
#                              and diverges from historic transaction costs.)
#  [16] st.trans_time        (actual transaction clock datetime — used for hour-of-day filtering.
#                              stktransm.docdate is date-only (always midnight) so hour filtering
#                              must use stktrans.trans_time which carries the real clock time.)
# ── SALES LINES — incremental (today + yesterday) ─────────────────────────────
# CRITICAL: stktrans.docdate is DATE-ONLY (always midnight) — the real clock time
# lives in st.trans_time. A `docdate >= DATEADD(minute,-10,GETDATE())` filter
# therefore matches ZERO rows for all but the first 10 minutes after midnight,
# so the 5-minute incremental silently synced no sales. trans_time carries the
# clock time but is UNINDEXED, so filtering on it forces a multi-minute table
# scan. The correct, indexed, selective predicate is a DAY boundary on docdate.
# We include yesterday (not just today) so late-posted documents and the midnight
# rollover are never missed; re-processing overlapping days is idempotent because
# sync_sales upserts by softech_invoice_id. ~1-2k rows/day → returns instantly.
QUERY_CUSTOMER_SALES_LINES_RECENT = """
    SELECT
        st.personcode, st.branchcode, st.doccode, st.docnumber, st.docdate,
        st.itemcode, st.transqty, st.transprice, st.transprice_total, st.storecode,
        sm.usercode, sm.phcode, sm.cust_branch_code,
        sm.ptcode, sm.ptclassifcode,
        st.newcostprice,
        st.trans_time,
        st.itemsaleprice, st.pharmacydiscp, st.additionaldiscp,
        st.custdiscp, st.specialdiscp
    FROM SOFTECHDB9.dbo.stktrans st
    JOIN SOFTECHDB9.dbo.stktransm sm
        ON  sm.branchcode = st.branchcode
        AND sm.doccode    = st.doccode
        AND sm.docnumber  = st.docnumber
        AND sm.docdate    = st.docdate
    WHERE st.docdate >= DATEADD(day, -1, CONVERT(datetime, CONVERT(char(8), GETDATE(), 112)))
    AND st.doccode IN ('115', '30')
    AND st.personcode IS NOT NULL AND st.personcode != ''
    ORDER BY st.docdate DESC
"""

# ── SALES LINES — full backfill (last 90 days) ────────────────────────────────
QUERY_CUSTOMER_SALES_LINES_FULL = """
    SELECT
        st.personcode, st.branchcode, st.doccode, st.docnumber, st.docdate,
        st.itemcode, st.transqty, st.transprice, st.transprice_total, st.storecode,
        sm.usercode, sm.phcode, sm.cust_branch_code,
        sm.ptcode, sm.ptclassifcode,
        st.newcostprice,
        st.trans_time,
        st.itemsaleprice, st.pharmacydiscp, st.additionaldiscp,
        st.custdiscp, st.specialdiscp
    FROM SOFTECHDB9.dbo.stktrans st
    JOIN SOFTECHDB9.dbo.stktransm sm
        ON  sm.branchcode = st.branchcode
        AND sm.doccode    = st.doccode
        AND sm.docnumber  = st.docnumber
        AND sm.docdate    = st.docdate
    WHERE st.docdate >= DATEADD(day, -90, GETDATE())
    AND st.doccode IN ('115', '30')
    AND st.personcode IS NOT NULL AND st.personcode != ''
    ORDER BY st.docdate DESC
"""

# ── SALES LINES — bounded window backfill (doc 16, Phase 3.5) ─────────────────
# Same shape as _FULL but with explicit [start, end) docdate bounds ('YYYYMMDD'),
# so the historical backfill can march month-by-month (bounded memory, resumable).
QUERY_CUSTOMER_SALES_LINES_WINDOW = """
    SELECT
        st.personcode, st.branchcode, st.doccode, st.docnumber, st.docdate,
        st.itemcode, st.transqty, st.transprice, st.transprice_total, st.storecode,
        sm.usercode, sm.phcode, sm.cust_branch_code,
        sm.ptcode, sm.ptclassifcode,
        st.newcostprice,
        st.trans_time,
        st.itemsaleprice, st.pharmacydiscp, st.additionaldiscp,
        st.custdiscp, st.specialdiscp
    FROM SOFTECHDB9.dbo.stktrans st
    JOIN SOFTECHDB9.dbo.stktransm sm
        ON  sm.branchcode = st.branchcode
        AND sm.doccode    = st.doccode
        AND sm.docnumber  = st.docnumber
        AND sm.docdate    = st.docdate
    WHERE st.docdate >= '{start}' AND st.docdate < '{end}'
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
    FROM SOFTECHDB9.dbo.users u
"""
# NOTE: ALL users (active + inactive) — departed staff still own historical sales, so we
# need their names for analytics/insights. is_active is derived from user_nomore in sync_users;
# account-creation still validates is_active=True (see users/serializers.py), so inactive
# users can't get local accounts.

QUERY_EXISTING_RESERVATIONS = None

# ── STKTRANS REFERENCE VALIDATION ─────────────────────────────────────────────
# Two-pass strategy for maximum robustness:
#
#   Pass 1 (QUERY_VALIDATE_STKTRANS):
#     Match by docnumber + branchcode, ANY doccode.
#     No doccode whitelist — "تبادل بين الفرع" and other inter-branch doc types
#     vary by SOFTECH installation and should not block a valid match.
#     The found doccode is returned and shown to the admin.
#
#   Pass 2 (QUERY_VALIDATE_STKTRANS_ANY):
#     Match by docnumber only, ANY branch, ANY doccode.
#     Fallback for documents entered centrally (HQ) or under a different branch.
#
# NOTE: stktransm.branchcode = the branch that ENTERED the document.
# This may differ from supplying_branch.softech_branch_id when documents
# are entered centrally. ERPMatcher reports the actual branchcode found.

# doccode 125 = صرف تبادل بين الفروع (supplying branch sends to requesting branch)
# This is the ONLY valid doccode for inter-branch transfer verification.

# doccode 125 = صرف تبادل بين الفروع (supplying branch sends to requesting branch)

# Pass 1: stktransm — docnumber + branchcode + doccode=125
QUERY_VALIDATE_STKTRANS = """
    SELECT sm.docnumber, sm.doccode, sm.branchcode, sm.docdate, sm.docvalue,
           sm.usercode, sm.storecode
    FROM SOFTECHDB9.dbo.stktransm sm
    WHERE sm.docnumber = ?
      AND sm.branchcode = ?
      AND sm.doccode = '125'
"""

# Pass 2: stktransm — docnumber + doccode=125, any branch
QUERY_VALIDATE_STKTRANS_ANY = """
    SELECT sm.docnumber, sm.doccode, sm.branchcode, sm.docdate, sm.docvalue,
           sm.usercode, sm.storecode
    FROM SOFTECHDB9.dbo.stktransm sm
    WHERE sm.docnumber = ?
      AND sm.doccode = '125'
"""

# Pass 3: stktransm — docnumber only, zero filters (diagnostic / last resort)
QUERY_VALIDATE_STKTRANS_RAW = """
    SELECT sm.docnumber, sm.doccode, sm.branchcode, sm.docdate, sm.docvalue,
           sm.usercode, sm.storecode
    FROM SOFTECHDB9.dbo.stktransm sm
    WHERE sm.docnumber = ?
"""

# Pass 4: stktrans direct — if stktransm has nothing at all for this docnumber,
# fall back to the line-items table itself.  Returns one representative row so
# ERPMatcher can confirm existence and proceed to item matching.
# Columns: docnumber, branchcode, doccode (NULL), docdate (NULL), storecode, usercode (NULL)
QUERY_STKTRANS_DIRECT_HEADER = """
    SELECT TOP 1
           st.docnumber, NULL AS doccode, st.branchcode,
           NULL AS docdate, NULL AS docvalue,
           NULL AS usercode, st.storecode
    FROM SOFTECHDB9.dbo.stktrans st
    WHERE st.docnumber = ?
"""

# ── STKTRANS LINE ITEMS — ERP transfer match verification ─────────────────────
# Returns all item lines for a specific document number + branch.
# Used by ERPMatcher to cross-reference what was actually transferred in SOFTECH
# against the items requested in a TransferRequest.
# Verified stktrans columns: docnumber, branchcode, itemcode, transqty, transprice_total, storecode
# NOTE: stktrans has NO itemname column — confirmed by InvalidColumn error. Item name from items table or local catalog.
#
# Pass 1: lines for specific branch (matches primary header pass)
# stktrans columns: itemcode, transqty, transprice_total, storecode, trans_time
# NOTE: stktrans has NO itemname column — item name is resolved from the local catalog.
# Column order: [0]=itemcode, [1]=transqty, [2]=transprice_total, [3]=storecode, [4]=trans_time
QUERY_STKTRANS_LINES = """
    SELECT st.itemcode, st.transqty, st.transprice_total, st.storecode, st.trans_time
    FROM SOFTECHDB9.dbo.stktrans st
    WHERE st.docnumber = ?
      AND st.branchcode = ?
    ORDER BY st.itemcode
"""

# Pass 2: all lines for this docnumber across any branch
# Column order: [0]=itemcode, [1]=transqty, [2]=transprice_total, [3]=storecode, [4]=trans_time
QUERY_STKTRANS_LINES_ANY = """
    SELECT st.itemcode, st.transqty, st.transprice_total, st.storecode, st.trans_time
    FROM SOFTECHDB9.dbo.stktrans st
    WHERE st.docnumber = ?
    ORDER BY st.itemcode
"""

# ── ERP USER LOOKUP — resolve usercode → userid (login name) ─────────────────
# stktransm stores usercode (numeric code). The SOFTECH users table maps it
# to the actual login userid and full display name.
# Column order: [0]=userid, [1]=username (may be NULL — handle gracefully)
QUERY_ERP_USER_LOOKUP = """
    SELECT u.userid, u.username
    FROM SOFTECHDB9.dbo.users u
    WHERE u.usercode = ?
"""

# ── ITEM SEARCH (live from SOFTECH, includes public price) ────────────────────
# Used by transfer/reservation create screens to search items with real-time price.
# Supports wildcard patterns: the caller converts user "*" → SQL "%" before binding.
# Two variants:
#   QUERY_ITEM_SEARCH     — exact / partial match (caller wraps q with %)
#   QUERY_ITEM_SEARCH_TOP — configurable TOP N (use Python .format(top=N) before execute)
QUERY_ITEM_SEARCH = """
    SELECT TOP 50
        i.itemcode, i.itemname, i.itemname_scientific, i.itembarcode,
        i.itemclassifcode, i.itemsaleprice, i.unitsaleprice,
        i.itemnomoreuse, i.itemarchive, i.fridgeitem, i.itemmedicine
    FROM SOFTECHDB9.dbo.items i
    WHERE i.itemnomoreuse != '1'
      AND i.itemarchive = 0
      AND (
          i.itemcode LIKE ?
          OR i.itemname LIKE ?
          OR i.itemname_scientific LIKE ?
          OR i.itembarcode LIKE ?
      )
    ORDER BY i.itemname
"""

# ── ITEM BARCODES (itembarcode table) ────────────────────────────────────────
# SOFTECHDB9.dbo.itembarcode — real schema (verified via sp_help / inspect_softech_schema):
#   itemcode        char(6)    FK → items.itemcode
#   itembarcode     char(15)   the EAN-13 / international barcode value
#   usercode        char(5)    who entered it
#   modif_lastupdate datetime  last modified
#   mainbarcode     char(1)    '1' = primary barcode for this item
#   blockbarcode    char(1)    '1' = blocked/obsolete; '0'/NULL = active
#   delusercode     char(5)    who deleted it
#   deltrans_time   datetime   when deleted
#
# Row layout: [0] itemcode, [1] itembarcode, [2] blockbarcode
QUERY_ITEM_BARCODES = """
    SELECT ib.itemcode, ib.itembarcode, ISNULL(ib.blockbarcode, '0') AS blockbarcode
    FROM SOFTECHDB9.dbo.itembarcode ib
    INNER JOIN SOFTECHDB9.dbo.items i ON ib.itemcode = i.itemcode
    WHERE i.itemnomoreuse != '1'
      AND i.itemarchive = 0
      AND ib.itembarcode IS NOT NULL
      AND ib.itembarcode != ''
    ORDER BY ib.itemcode, ib.mainbarcode DESC
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

# ── BRANCH DATABASE PICCRMORDERS — Branch POS Delivery Orders ────────────────
#
# Each branch has its own Sybase database (e.g. 192.168.1.5 = branch 160).
# Branch piccrmorders contains TWO types of records:
#
#   1. crmbranchcode = branchcode:
#      Branch POS-created orders (source_type='branch_pos').
#      These ONLY exist in the branch DB — NOT on HQ.
#      Branch 130 has 105K such orders, latest: today.
#
#   2. crmbranchcode = '100':
#      Call center orders assigned to this branch — replicated from HQ.
#      Already synced via QUERY_PICCRMORDERS_* from HQ. Skip to avoid duplicates.
#
# The branch piccrmorders uses the SAME schema as HQ piccrmorders.
# Status tracking is via piccrmorderstatus at the branch DB level.
# Branch 130 has 27K status records, 12 x st=44 today (live activity!).
#
# Column layout: identical to QUERY_PICCRMORDERS_ACTIVE (same schema).
# Use same index mapping [0..19] as HQ queries.
#
# Unique key across all sources: (crmbranchcode, crmorderno)
# This prevents duplicate imports when a CC order (crmBr='100') appears on both HQ and branch.

QUERY_BRANCH_PICCRMORDERS_ACTIVE = """
    SELECT
        crmbranchcode, crmorderno, branchcode, doccode,
        orderdatetime, orderusercode, ordervalue,
        phcode, drivercode,
        driveroutdatetime, driveroutvalue, driverindatetime, drivertime,
        orderdatetimes, ordertobr, ordertobrtaken,
        orderinvoice, delivertocust,
        orderstatus, orderstatustime,
        docnumber5, docdate5, docnumber
    FROM piccrmorders
    WHERE crmbranchcode = branchcode
      AND orderdatetime >= DATEADD(day, -{days}, GETDATE())
    ORDER BY orderdatetime DESC
"""

# Incremental: branch POS orders modified in last N minutes.
# Caller uses .format(minutes=N).
QUERY_BRANCH_PICCRMORDERS_RECENT = """
    SELECT
        crmbranchcode, crmorderno, branchcode, doccode,
        orderdatetime, orderusercode, ordervalue,
        phcode, drivercode,
        driveroutdatetime, driveroutvalue, driverindatetime, drivertime,
        orderdatetimes, ordertobr, ordertobrtaken,
        orderinvoice, delivertocust,
        orderstatus, orderstatustime,
        docnumber5, docdate5, docnumber
    FROM piccrmorders
    WHERE crmbranchcode = branchcode
      AND (
          orderstatustime >= DATEADD(minute, -{minutes}, GETDATE())
          OR orderdatetime >= DATEADD(minute, -{minutes}, GETDATE())
      )
    ORDER BY orderdatetime DESC
"""

# Status history for a specific branch POS order.
QUERY_BRANCH_PICCRMORDERS_STATUS_HISTORY = """
    SELECT orderstatus, usercode, trans_time
    FROM piccrmorderstatus
    WHERE crmbranchcode = ? AND crmorderno = ?
    ORDER BY trans_time
"""

# ── PICCRMORDERS5 — Live Pending Orders Queue ─────────────────────────────────
#
# This is the ACTUAL live pending queue at each branch.
# Key distinction from piccrmorders:
#   piccrmorders  = full history (all completed + in-progress orders)
#   piccrmorders5 = ONLY currently pending orders (docnumber=0, never invoiced)
#
# An order appears in piccrmorders5 when:
#   - It has been prepared at the branch (status 44)
#   - It has been dispatched to driver (status 50)
#   - It has been sent to branch but branch hasn't invoiced yet (status 30)
#   - docnumber = 0 means it has NOT been invoiced / fulfilled yet
#
# When an order is invoiced (delivered), docnumber gets filled and it
# is REMOVED from piccrmorders5 (hence the small counts per branch).
#
# piccrmorders5 is EXCLUSIVE — rows do NOT appear in piccrmorders.
# It contains BOTH CC orders (crmbranchcode='100') AND branch POS orders.
#
# Live counts per branch (2026-06-01):
#   Branch 130: 35 pending (1 CC, 34 POS) — status 30/44/50
#   Branch 140: 3 pending
#   Branch 150: 5 pending (all CC)
#   Branch 160: 5 pending (2 CC, 3 POS)
#   Branch 170: 84 pending (2 CC, 82 POS) — 77 at st=50 (out for delivery)
#
# Column layout: IDENTICAL to piccrmorders (same columns, same index mapping).

QUERY_BRANCH_PICCRMORDERS5_ALL = """
    SELECT
        crmbranchcode, crmorderno, branchcode, doccode,
        orderdatetime, orderusercode, ordervalue,
        phcode, drivercode,
        driveroutdatetime, driveroutvalue, driverindatetime, drivertime,
        orderdatetimes, ordertobr, ordertobrtaken,
        orderinvoice, delivertocust,
        orderstatus, orderstatustime,
        docnumber5, docdate5, docnumber
    FROM piccrmorders5
    WHERE docnumber = 0
    ORDER BY orderdatetime DESC
"""

# Incremental: piccrmorders5 changes in last N minutes.
# ── PICCRMITEMS — Order Line Items ───────────────────────────────────────────
#
# Fetches all items for a specific CRM order from HQ piccrmitems.
# Parameters: branchcode (e.g. '100'), crmorderno (int)
#
# Column layout:
#  [0] itemcode       — SOFTECH item code → Item.softech_id
#  [1] itemqty        — quantity ordered
#  [2] itemsaleprice  — full-pack retail price
#  [3] unitsaleprice  — per-unit / per-strip price
#  [4] transprice     — actual transaction price (after discount)
#  [5] custdiscp      — customer discount %
#  [6] itemsalestax   — tax amount
#  [7] sitemqty       — quantity fulfilled / supplied

QUERY_PICCRMITEMS_FOR_ORDER = """
    SELECT i.itemcode, i.itemqty, i.itemsaleprice, i.unitsaleprice,
           i.transprice, i.custdiscp, i.itemsalestax, i.sitemqty
    FROM SOFTECHDB9.dbo.piccrmitems i
    WHERE i.branchcode = ? AND i.crmorderno = ?
    ORDER BY i.trans_time
"""

QUERY_BRANCH_PICCRMORDERS5_RECENT = """
    SELECT
        crmbranchcode, crmorderno, branchcode, doccode,
        orderdatetime, orderusercode, ordervalue,
        phcode, drivercode,
        driveroutdatetime, driveroutvalue, driverindatetime, drivertime,
        orderdatetimes, ordertobr, ordertobrtaken,
        orderinvoice, delivertocust,
        orderstatus, orderstatustime,
        docnumber5, docdate5, docnumber
    FROM piccrmorders5
    WHERE docnumber = 0
      AND (
          orderstatustime >= DATEADD(minute, -{minutes}, GETDATE())
          OR orderdatetime >= DATEADD(minute, -{minutes}, GETDATE())
      )
    ORDER BY orderdatetime DESC
"""

# All piccrmorderstatus changes in last N minutes (for batch status updates).
# Used to catch status updates on BOTH CC orders AND branch POS orders at the branch.
QUERY_BRANCH_STATUS_UPDATES_RECENT = """
    SELECT crmbranchcode, crmorderno, branchcode, orderstatus, usercode, trans_time
    FROM piccrmorderstatus
    WHERE trans_time >= DATEADD(minute, -{minutes}, GETDATE())
    ORDER BY trans_time DESC
"""

# ── PICCRMORDERS — Call Center / Delivery Order Queue ────────────────────────
#
# Table: SOFTECHDB9.dbo.piccrmorders
# This is the LIVE transient order table for all delivery / call-center orders.
#
# All orders originate from crmbranchcode='100' (the central call center رئيسى branch).
# branchcode = the fulfilling pharmacy branch.
#
# Status lifecycle (orderstatus):
#   NULL / 10  → created              (orderdatetime set)
#   20         → pending_review        (sent to fulfilling branch)
#   30         → preparing             (branch acknowledged, ordertobr/ordertobrtaken set)
#   44         → ready                 (branch prepared/invoiced, orderinvoice set)
#   50         → out_for_delivery      (driver left, driveroutdatetime set)
#   90         → delivered             (driverindatetime + delivertocust set)
#   100        → cancelled / closed
#
# Join path for customer:  phcode → localcustomers.phcode / personsdata.personcode
# Join path for line items: docnumber (invoice) → stktrans.docnumber + branchcode
# Note: docnumber5 = pre-invoice staging document; docnumber = final invoice (set after delivery).
#
# Column index map (QUERY_PICCRMORDERS_ACTIVE):
#  [0]  crmbranchcode    — always '100' (call center branch)
#  [1]  crmorderno       — PK: unique order number (int)
#  [2]  branchcode       — fulfilling branch
#  [3]  doccode          — always '115' (sale)
#  [4]  orderdatetime    — when order was placed by CC agent
#  [5]  orderusercode    — CC agent user code
#  [6]  ordervalue       — order value (total)
#  [7]  phcode           — customer PIC → Customer.softech_pic
#  [8]  drivercode       — assigned driver user code (may be NULL)
#  [9]  driveroutdatetime — when driver left (status 50)
#  [10] driveroutvalue   — value driver carries
#  [11] driverindatetime — when driver returned (status 90)
#  [12] drivertime       — delivery minutes
#  [13] orderdatetimes   — order datetime stamp copy
#  [14] ordertobr        — when sent to branch (status 20)
#  [15] ordertobrtaken   — when branch acknowledged (status 30)
#  [16] orderinvoice     — when branch invoiced/prepared (status 44)
#  [17] delivertocust    — when delivered to customer (status 90)
#  [18] orderstatus      — current status code (see above)
#  [19] orderstatustime  — when status last changed

QUERY_PICCRMORDERS_ACTIVE = """
    SELECT
        crmbranchcode, crmorderno, branchcode, doccode,
        orderdatetime, orderusercode, ordervalue,
        phcode, drivercode,
        driveroutdatetime, driveroutvalue, driverindatetime, drivertime,
        orderdatetimes, ordertobr, ordertobrtaken,
        orderinvoice, delivertocust,
        orderstatus, orderstatustime,
        docnumber5, docdate5, docnumber
    FROM SOFTECHDB9.dbo.piccrmorders
    WHERE (orderstatus < 90 OR orderstatus IS NULL)
      AND orderdatetime >= DATEADD(day, -{days}, GETDATE())
    ORDER BY orderdatetime DESC
"""
# Column index additions (appended to original [0..19]):
#  [20] docnumber5  — pre-invoice staging document number (KEY SOFTECH REFERENCE)
#  [21] docdate5    — staging document date
#  [22] docnumber   — final invoice number (0 = still pending)

# Active orders modified in the last N minutes (incremental sync).
# Caller uses .format(minutes=N) to set the lookback window.
QUERY_PICCRMORDERS_RECENT = """
    SELECT
        crmbranchcode, crmorderno, branchcode, doccode,
        orderdatetime, orderusercode, ordervalue,
        phcode, drivercode,
        driveroutdatetime, driveroutvalue, driverindatetime, drivertime,
        orderdatetimes, ordertobr, ordertobrtaken,
        orderinvoice, delivertocust,
        orderstatus, orderstatustime,
        docnumber5, docdate5, docnumber
    FROM SOFTECHDB9.dbo.piccrmorders
    WHERE orderstatustime >= DATEADD(minute, -{minutes}, GETDATE())
    OR orderdatetime >= DATEADD(minute, -{minutes}, GETDATE())
    ORDER BY orderdatetime DESC
"""

# Full status history for a specific order (for audit trail).
QUERY_PICCRMORDERS_STATUS_HISTORY = """
    SELECT orderstatus, usercode, trans_time
    FROM SOFTECHDB9.dbo.piccrmorderstatus
    WHERE crmbranchcode = ? AND crmorderno = ?
    ORDER BY trans_time
"""

# Line items for a delivered order via invoice docnumber + branchcode.
# Used after orderstatus=90 when docnumber is populated.
QUERY_PICCRMORDERS_LINES = """
    SELECT st.itemcode, st.transqty, st.transprice, st.transprice_total, st.storecode
    FROM SOFTECHDB9.dbo.stktrans st
    WHERE st.docnumber = ?
      AND st.branchcode = ?
    ORDER BY st.itemcode
"""



# ── SOFTECH permission model (usergroups / mitems / mglevels) ─────────────────
QUERY_ERP_USERGROUPS = """
    SELECT usergroup, groupdescr, groupblocked
    FROM SOFTECHDB9.dbo.usergroups
"""

QUERY_ERP_SCREENS = """
    SELECT mitemname, mitemdescr, mitemedescr, mitemsys, mitemsubsys, mitemorder
    FROM SOFTECHDB9.dbo.mitems
"""

QUERY_ERP_GROUPPERMS = """
    SELECT usergroup, mitemname,
           mitemenable, mitemshow, mitemretrieve, mitemsave, mitemdatain,
           mitemprint, mitemscan, mitemdata, mitemmoney, mitemcost,
           mitembrmb, mitemscanedit
    FROM SOFTECHDB9.dbo.mglevels
"""

# ── TRANSFERS IN TRANSIT ──────────────────────────────────────────────────────
#
# doccode '125' = صرف تبادل بين الفروع
#   stktransm row on the SUPPLYING branch side.
#   When the same docnumber also appears in stktrans under the RECEIVING branch,
#   the transfer has been received.
#
# Usage: bind (since_date_str,) e.g. '2026-05-01'

QUERY_TRANSIT_HEADERS = """
    SELECT sm.docnumber, sm.doccode, sm.branchcode, sm.docdate,
           sm.docvalue, sm.usercode, sm.storecode
    FROM SOFTECHDB9.dbo.stktransm sm
    WHERE sm.doccode = '125'
      AND sm.docdate >= ?
    ORDER BY sm.docdate DESC
"""

# All distinct branchcodes present in stktrans for a specific docnumber.
# If branches > 1, the extra branch(es) are the receiving side(s).
# Bind: (docnumber_int,)
QUERY_TRANSIT_BRANCHES_PER_DOC = """
    SELECT DISTINCT st.branchcode
    FROM SOFTECHDB9.dbo.stktrans st
    WHERE st.docnumber = ?
"""

# Line items for the supplying-branch side of an inter-branch transfer.
# Bind: (docnumber_int, supplying_branchcode)
# Column layout:
#  [0] itemcode, [1] transqty, [2] transprice_total, [3] storecode, [4] trans_time
QUERY_TRANSIT_ITEMS_FOR_BRANCH = """
    SELECT st.itemcode, st.transqty, st.transprice_total, st.storecode, st.trans_time
    FROM SOFTECHDB9.dbo.stktrans st
    WHERE st.docnumber = ?
      AND st.branchcode = ?
    ORDER BY st.itemcode
"""

# Receipt date from stktransm on the receiving branch side.
# Bind: (docnumber_int, receiving_branchcode)
QUERY_TRANSIT_RECEIPT_DATE = """
    SELECT TOP 1 sm.docdate
    FROM SOFTECHDB9.dbo.stktransm sm
    WHERE sm.docnumber = ?
      AND sm.branchcode = ?
"""

