"""
apps/insurance/sybase_queries.py

Softech queries for the Insurance Claims module.
ABSOLUTE RULE: SELECT only. Never INSERT/UPDATE/DELETE.

Confirmed schema (from inspect_insurance_schema 2026-06-02):

  motalbas   — Motalba HEADER (one row per motalba)
    personcode, motalbano, motalbadate, personbranchcode,
    motfromdate, mottodate, motissuedate, motnumber, motnoofpages,
    motnoofpatients, docvaluetotal, docvaluenet, motalbadel,
    motalbacomment, mottotsupp, mottotcontract, mottotapproved,
    mottotcust, mottotpatient

  motalba    — Motalba DETAIL (one row per prescription/invoice)
    personcode, motalbano, branchcode, docnumber, motalbasdate,
    motalbafdate, docdate, docvaluerequired, docvalue_grandtotal,
    motalba_docorder, doccode, patientcode, ppersoncode, invdel,
    custbranchcode

  custdiscpclassif — Contract discount tiers (confirmed codes):
    [22] اصناف ترسية   → TARSIA
    [23] اصناف اورام   → TARSIA (oncology)
    [10] Med: Local    → LOCAL
    [13..15] Imported  → IMPORTED

  itemsorigin — importedorigin flag:
    '1' = imported: codes 40,50,60,310,320,7
    '0' = local: all others

NOTE: Sybase ASE 12.5 via jConnect does NOT support IN ('x','y') with
string literals — use explicit OR conditions instead.
"""

# ── LIST ALL SOFTECH TABLES ────────────────────────────────────────────────────
QUERY_LIST_ALL_TABLES = """
    SELECT o.name
    FROM   SOFTECHDB9.dbo.sysobjects o
    WHERE  o.type = 'U'
    ORDER  BY o.name
"""

# ── INSURANCE-RELATED TABLE DISCOVERY ─────────────────────────────────────────
QUERY_INSURANCE_TABLES = """
    SELECT o.name
    FROM   SOFTECHDB9.dbo.sysobjects o
    WHERE  o.type = 'U'
      AND (
           LOWER(o.name) LIKE '%hi%'
        OR LOWER(o.name) LIKE '%health%'
        OR LOWER(o.name) LIKE '%insur%'
        OR LOWER(o.name) LIKE '%motalb%'
        OR LOWER(o.name) LIKE '%taamin%'
        OR LOWER(o.name) LIKE '%claim%'
        OR LOWER(o.name) LIKE '%tamin%'
      )
    ORDER  BY o.name
"""

# ── TABLE COLUMNS (template — inject table name via .format()) ─────────────────
QUERY_TABLE_COLUMNS_TEMPLATE = """
    SELECT c.name, t.name AS type, c.length
    FROM   SOFTECHDB9.dbo.syscolumns c
    JOIN   SOFTECHDB9.dbo.sysobjects o ON c.id = o.id
    JOIN   SOFTECHDB9.dbo.systypes   t ON c.usertype = t.usertype
    WHERE  o.name = '{table}'
    ORDER  BY c.colid
"""

# ── STKTRANSM COLUMNS ─────────────────────────────────────────────────────────
QUERY_STKTRANSM_COLUMNS = """
    SELECT c.name, t.name AS type, c.length
    FROM   SOFTECHDB9.dbo.syscolumns c
    JOIN   SOFTECHDB9.dbo.sysobjects o ON c.id = o.id
    JOIN   SOFTECHDB9.dbo.systypes   t ON c.usertype = t.usertype
    WHERE  o.name = 'stktransm'
    ORDER  BY c.colid
"""

# ── CUSTDISCPCLASSIF — Contract discount tier reference ───────────────────────
QUERY_CUSTDISCPCLASSIF_ALL = """
    SELECT c.custdiscpcode, c.custdiscpdescr
    FROM   SOFTECHDB9.dbo.custdiscpclassif c
    ORDER  BY c.custdiscpcode
"""

# ── ITEMSORIGIN — Origin + import flag ────────────────────────────────────────
QUERY_ITEMSORIGIN_ALL = """
    SELECT io.itemorigincode, io.itemoriginname, io.originnamearabic, io.importedorigin
    FROM   SOFTECHDB9.dbo.itemsorigin io
"""

# ── PERSONSDATA — Look up insurance company name from personcode ──────────────
QUERY_PERSONSDATA_BY_CODE = """
    SELECT pd.personcode, pd.personname, pd.ptcode, pd.ptclassifcode
    FROM   SOFTECHDB9.dbo.personsdata pd
    WHERE  pd.personcode = ?
"""

# ── ALL INSURANCE/CONTRACT PERSONS ────────────────────────────────────────────
# NOTE: Sybase ASE 12.5 does not support IN ('10','15') with jConnect.
# Must use explicit OR conditions.
QUERY_INSURANCE_PERSONS = """
    SELECT pd.personcode, pd.personname, pd.ptcode, pd.ptclassifcode
    FROM   SOFTECHDB9.dbo.personsdata pd
    WHERE  (pd.ptclassifcode = '10' OR pd.ptclassifcode = '15')
      AND  pd.personname IS NOT NULL
      AND  pd.personname != ''
    ORDER  BY pd.personname
"""

# ── ALL PERSONNAMES (no classification filter) ─────────────────────────────────
# Used to resolve company names for motalba personcodes that are NOT yet
# configured as subclients.  Motalba personcodes may carry any ptclassifcode,
# so we must NOT filter by 10/15 here — fetch every person that has a name.
QUERY_ALL_PERSONNAMES = """
    SELECT pd.personcode, pd.personname
    FROM   SOFTECHDB9.dbo.personsdata pd
    WHERE  pd.personname IS NOT NULL
      AND  pd.personname != ''
"""

# ═══════════════════════════════════════════════════════════════════════════════
# MOTALBA QUERIES (confirmed table structure 2026-06-02)
# ═══════════════════════════════════════════════════════════════════════════════

# ── DISCOVER motalbas across ALL personcodes within a date range ──────────────
# Returns one aggregate row per (personcode, motalbano) combination.
# motalbasdate = claim period start, motalbafdate = claim period end.
# Used by the discover-motalbas API endpoint.
# Params: period_from (YYYY-MM-DD), period_to (YYYY-MM-DD)
QUERY_DISCOVER_MOTALBAS_BY_DATERANGE = """
    SELECT
        m.personcode,
        m.motalbano,
        MIN(m.motalbasdate)      AS motalbasdate,
        MAX(m.motalbafdate)      AS motalbafdate,
        COUNT(*)                 AS rxcount,
        SUM(m.docvalue_grandtotal) AS docvaluetotal
    FROM SOFTECHDB9.dbo.motalba m
    WHERE m.motalbasdate >= ?
      AND m.motalbafdate <= ?
      AND m.invdel = 1
    GROUP BY m.personcode, m.motalbano
    ORDER BY m.motalbano DESC
"""

# Variant: single personcode within date range (for per-client discovery)
# Params: personcode, period_from, period_to
QUERY_DISCOVER_MOTALBAS_BY_PC_DATERANGE = """
    SELECT
        m.personcode,
        m.motalbano,
        MIN(m.motalbasdate)      AS motalbasdate,
        MAX(m.motalbafdate)      AS motalbafdate,
        COUNT(*)                 AS rxcount,
        SUM(m.docvalue_grandtotal) AS docvaluetotal
    FROM SOFTECHDB9.dbo.motalba m
    WHERE m.personcode  = ?
      AND m.motalbasdate >= ?
      AND m.motalbafdate <= ?
      AND m.invdel = 1
    GROUP BY m.personcode, m.motalbano
    ORDER BY m.motalbano DESC
"""

# ── MOTALBA SUMMARY — list motalbas for a personcode from the DETAIL table ────
#
# IMPORTANT (confirmed 2026-06-02):
#   motalbas (header) table = EMPTY — never used by this pharmacy.
#   All motalba data comes from the `motalba` detail table.
#   motalbano is shared across personcodes — always filter by BOTH.
#
# Returns one row per motalbano for the given personcode.
# motalbasdate = start of claim period; motalbafdate = end of claim period.
# Param: personcode
QUERY_MOTALBAS_BY_PERSONCODE = """
    SELECT
        m.motalbano,
        MIN(m.motalbasdate) AS motalbasdate,
        MAX(m.motalbafdate) AS motalbafdate,
        COUNT(*) AS rxcount,
        SUM(m.docvalue_grandtotal) AS docvaluetotal
    FROM SOFTECHDB9.dbo.motalba m
    WHERE m.personcode = ?
      AND m.invdel = 1
    GROUP BY m.motalbano
    ORDER BY m.motalbano DESC
"""

# ── MOTALBA HEADER INFO (from detail table) — for a specific personcode+motalbano
# Used by importer to get period dates when importing by motalbano.
# Params: personcode, motalbano
QUERY_MOTALBA_HEADER_FROM_DETAIL = """
    SELECT
        m.personcode,
        m.motalbano,
        MIN(m.motalbasdate) AS period_from,
        MAX(m.motalbafdate) AS period_to,
        COUNT(*) AS rxcount,
        SUM(m.docvalue_grandtotal) AS total_value
    FROM SOFTECHDB9.dbo.motalba m
    WHERE m.personcode = ?
      AND m.motalbano  = ?
      AND m.invdel = 1
    GROUP BY m.personcode, m.motalbano
"""

# ── MOTALBA DETAIL LINES — all prescriptions in a motalba ────────────────────
# CRITICAL: motalbano is NOT unique — always filter by BOTH personcode AND motalbano.
# (confirmed: multiple personcodes share same motalbano number)
#
# Params: personcode, motalbano (int)
#
# Columns:
#  [0]  m.personcode
#  [1]  m.motalbano
#  [2]  m.branchcode
#  [3]  m.docnumber      (invoice number → joins stktransm/stktrans)
#  [4]  m.docdate        (invoice date)
#  [5]  m.doccode        (115=sale, 30=return)
#  [6]  m.motalba_docorder (sequence within motalba)
#  [7]  m.docvalue_grandtotal  (gross public price — POSITIVE even for returns)
#  [8]  m.patientcode    (patient identifier — int)
#  [9]  m.ppersoncode    (patient personcode → localcustomers.phcode)
#  [10] m.custbranchcode
#  [11] m.docvaluerequired     (net after contract discount — POSITIVE even for returns)
#
#  CRITICAL: for doccode='30' (returns), SOFTECH stores both values as POSITIVE
#  but prints them as NEGATIVE.  The importer must negate both when doccode='30'.
QUERY_MOTALBA_LINES_BY_NO = """
    SELECT
        m.personcode,
        m.motalbano,
        m.branchcode,
        m.docnumber,
        m.docdate,
        m.doccode,
        m.motalba_docorder,
        m.docvalue_grandtotal,
        m.patientcode,
        m.ppersoncode,
        m.custbranchcode,
        m.docvaluerequired
    FROM SOFTECHDB9.dbo.motalba m
    WHERE m.personcode = ?
      AND m.motalbano  = ?
      AND m.invdel = 1
    ORDER BY m.motalba_docorder, m.docdate, m.docnumber
"""

# ── MOTALBA LINES — by personcode + date range (fallback) ────────────────────
# Used when motalbano is not known.
# Params: personcode, period_from (YYYY-MM-DD), period_to (YYYY-MM-DD)
QUERY_MOTALBA_LINES_BY_PERSONCODE_DATERANGE = """
    SELECT
        m.personcode,
        m.motalbano,
        m.branchcode,
        m.docnumber,
        m.docdate,
        m.doccode,
        m.motalba_docorder,
        m.docvalue_grandtotal,
        m.patientcode,
        m.ppersoncode,
        m.custbranchcode,
        m.docvaluerequired
    FROM SOFTECHDB9.dbo.motalba m
    WHERE m.personcode = ?
      AND m.docdate >= ?
      AND m.docdate <= ?
      AND m.invdel = 1
    ORDER BY m.docdate, m.motalba_docorder, m.docnumber
"""

# Variant: multiple personcodes via 2-code OR (extend as needed)
# The caller should build the WHERE clause dynamically for >2 codes.
QUERY_MOTALBA_LINES_TWO_PERSONCODES_DATERANGE = """
    SELECT
        m.personcode,
        m.motalbano,
        m.branchcode,
        m.docnumber,
        m.docdate,
        m.doccode,
        m.motalba_docorder,
        m.docvalue_grandtotal,
        m.patientcode,
        m.ppersoncode,
        m.custbranchcode
    FROM SOFTECHDB9.dbo.motalba m
    WHERE (m.personcode = ? OR m.personcode = ?)
      AND m.docdate >= ?
      AND m.docdate <= ?
      AND m.invdel = 1
    ORDER BY m.docdate, m.motalba_docorder, m.docnumber
"""

# ── CUSTDISCOUNTS — per-client per-category discount rates ───────────────────
# Returns all custdiscpcode/rate rows for a personcode.
# Used during import to auto-populate applied_local/imported/tarsia_disc_pct.
#
# custdiscptype='p' means percentage discount.
# custdiscpcode mapping (confirmed from live data):
#   Local   : 10,11,12,19,25  (rate = local discount %)
#   Imported: 13,14,15,26,27,28,50,90  (rate = imported discount %)
#   Tarsia  : 22,23  (rate = 0 for tendered/oncology items)
#
# Param: personcode
QUERY_CUSTDISCOUNTS_BY_PERSONCODE = """
    SELECT
        cd.custdiscpcode,
        cd.custdiscp,
        cd.custdiscp2,
        cd.custdiscp3,
        cd.custdiscp4,
        cd.custdiscptype,
        cd.allow_sell
    FROM SOFTECHDB9.dbo.custdiscounts cd
    WHERE cd.personcode = ?
    ORDER BY cd.custdiscpcode
"""

# ── CONTRACTSTYPES — payment type reference ───────────────────────────────────
# 16 rows describing how payment is split (employee vs company).
# Used as a display reference when showing contract terms.
QUERY_CONTRACTSTYPES_ALL = """
    SELECT ct.paytypecode, ct.paytypedescr
    FROM   SOFTECHDB9.dbo.contractstypes ct
    ORDER  BY ct.paytypecode
"""

# ── CUSTDISCOUNTSTRANS — contract amendment history ──────────────────────────
# Tracks changes to discount rates and payment terms over time per personcode.
# Most recent row = current contract terms.
# Param: personcode
QUERY_CUSTDISCOUNTSTRANS_BY_PERSONCODE = """
    SELECT
        cdt.custdiscp,
        cdt.origintaxp,
        cdt.transdate,
        cdt.patient_paypercent,
        cdt.patient_paytype,
        cdt.patient_maxfatora,
        cdt.personname,
        cdt.personmaxbal,
        cdt.pcategorycode
    FROM SOFTECHDB9.dbo.custdiscountstrans cdt
    WHERE cdt.personcode = ?
    ORDER BY cdt.transdate DESC
"""

# ── PATIENT NAME FROM LOCALCUSTOMERS via ppersoncode ─────────────────────────
# motalba.ppersoncode → localcustomers.phcode
# Param: ppersoncode (patient personcode)
QUERY_PATIENT_NAME_BY_PHCODE = """
    SELECT lc.branchcustname
    FROM   SOFTECHDB9.dbo.localcustomers lc
    WHERE  RTRIM(lc.phcode) = ?
"""

# ── PATIENT NAME FROM PERSONSDATA via ppersoncode ─────────────────────────────
# Fallback if not in localcustomers
QUERY_PATIENT_NAME_FROM_PERSONSDATA = """
    SELECT pd.personname
    FROM   SOFTECHDB9.dbo.personsdata pd
    WHERE  pd.personcode = ?
"""

# ── PRESCRIPTION HEADER + PATIENT NAME ────────────────────────────────────────
# Fetches patient name via stktransm.phcode → localcustomers.branchcustname.
# Used when ppersoncode lookup fails.
# Params: docnumber, branchcode
#
# Columns:
#  [0]  sm.phcode
#  [1]  lc.branchcustname   (patient name — may be NULL if not retail customer)
QUERY_PRESCRIPTION_PATIENT_NAME = """
    SELECT sm.phcode, lc.branchcustname
    FROM SOFTECHDB9.dbo.stktransm sm
    LEFT JOIN SOFTECHDB9.dbo.localcustomers lc ON lc.phcode = sm.phcode
    WHERE sm.docnumber       = CONVERT(numeric(6), ?)
      AND RTRIM(sm.branchcode) = ?
"""

# ── PRESCRIPTION LINES WITH ITEM CLASSIFICATION ───────────────────────────────
# Returns item lines + patient name for one prescription (docnumber + branchcode).
# Joins stktransm for phcode, localcustomers for name,
#       items → itemsorigin → custdiscpclassif for classification.
#
# Params: docnumber, branchcode
#
# Columns:
#  [0]  st.itemcode
#  [1]  i.itemname
#  [2]  st.transqty
#  [3]  st.transprice        (unit price)
#  [4]  st.transprice_total  (line total)
#  [5]  io.importedorigin    ('1'=imported, '0'=local, NULL=local)
#  [6]  i.itemstoreclassif   (contract discount code → tarsia if 22/23)
#  [7]  i.itemorigincode
#  [8]  cc.custdiscpdescr    (discount tier description for audit)
#  [9]  sm.phcode            (patient PIC → localcustomers)
# [10]  lc.branchcustname    (patient name — may be NULL)
QUERY_PRESCRIPTION_LINES_CLASSIFIED = """
    SELECT
        st.itemcode,
        i.itemname,
        st.transqty,
        st.transprice,
        st.transprice_total,
        io.importedorigin,
        i.itemstoreclassif,
        i.itemorigincode,
        cc.custdiscpdescr,
        sm.phcode,
        st.itemsaleprice,
        ci.patientname
    FROM SOFTECHDB9.dbo.stktrans st
    JOIN SOFTECHDB9.dbo.stktransm sm
        ON  sm.docnumber  = st.docnumber
        AND sm.branchcode = st.branchcode
        AND sm.doccode    = st.doccode
    JOIN SOFTECHDB9.dbo.items i
        ON  i.itemcode = st.itemcode
    LEFT JOIN SOFTECHDB9.dbo.itemsorigin io
        ON  io.itemorigincode = i.itemorigincode
    LEFT JOIN SOFTECHDB9.dbo.custdiscpclassif cc
        ON  cc.custdiscpcode = i.itemstoreclassif
    LEFT JOIN SOFTECHDB9.dbo.companiesitems ci
        ON  ci.docnumber  = st.docnumber
        AND ci.branchcode = st.branchcode
        AND ci.doccode    = st.doccode
    WHERE st.docnumber  = CONVERT(numeric(6), ?)
      AND st.branchcode = ?
    ORDER BY st.itemcode
"""

# Patient name source (confirmed 2026-06-02):
# companiesitems.patientname joined via (docnumber, branchcode, doccode).
# Gives 100% coverage (546/546) for motalba 117 — exact match to Softech HTM report.
# This table is populated manually at POS for every insurance prescription.
# Also contains: patientno, membershipno, roshettano, deptname, relativedegree.

# ── SINGLE PRESCRIPTION LOOKUP (for manual add by receipt number) ─────────────
# Param: docnumber
QUERY_PRESCRIPTION_HEADER_BY_DOCNO = """
    SELECT
        sm.branchcode,
        sm.doccode,
        sm.docnumber,
        sm.docdate,
        sm.docvalue,
        sm.phcode,
        sm.ptclassifcode
    FROM SOFTECHDB9.dbo.stktransm sm
    WHERE sm.docnumber = CONVERT(numeric(6), ?)
      AND (sm.doccode = '115' OR sm.doccode = '30')
"""

# Branch-scoped variant — MUCH faster: docnumber alone is not the leading index
# column on stktransm, so filtering by docnumber only forces a full-table scan.
# Adding branchcode (Sybase '=' is trailing-space-insensitive, so '160' matches
# the char column) lets the engine seek the (branch, docnumber) index.
# Params: docnumber, branchcode
QUERY_PRESCRIPTION_HEADER_BY_DOCNO_BRANCH = """
    SELECT
        sm.branchcode,
        sm.doccode,
        sm.docnumber,
        sm.docdate,
        sm.docvalue,
        sm.phcode,
        sm.ptclassifcode
    FROM SOFTECHDB9.dbo.stktransm sm
    WHERE sm.docnumber  = CONVERT(numeric(6), ?)
      AND sm.branchcode = ?
      AND (sm.doccode = '115' OR sm.doccode = '30')
"""

# ── VERIFY DOCNUMBER EXISTS IN MOTALBA ────────────────────────────────────────
# Check if a docnumber is already assigned to a motalba.
# Returns [0]=motalbano, [1]=personcode (child/billing code),
#         [2]=ppersoncode (PARENT / group code — عميل أب, e.g. '4999').
# Param: docnumber
QUERY_CHECK_DOC_IN_MOTALBA = """
    SELECT m.motalbano, m.personcode, m.ppersoncode
    FROM SOFTECHDB9.dbo.motalba m
    WHERE m.docnumber = CONVERT(numeric(6), ?)
"""

# Branch-scoped (fast, index-seekable) — used to re-verify a receipt's CURRENT
# parent code (ppersoncode) live before hard-blocking a manual add, so a stale
# local cache never produces a false "different parent" rejection.
# Params: docnumber, branchcode
QUERY_CHECK_DOC_IN_MOTALBA_BRANCH = """
    SELECT m.motalbano, m.personcode, m.ppersoncode
    FROM SOFTECHDB9.dbo.motalba m
    WHERE m.docnumber  = CONVERT(numeric(6), ?)
      AND m.branchcode = ?
"""

# ── PROHIBITED ITEMS (contract dispensing restrictions) ───────────────────────
# itemnosaleclassif: '10'=normal, '20'/'30'/'31'=restricted
QUERY_PROHIBITED_ITEMS = """
    SELECT i.itemcode, i.itemname, i.itemnosaleclassif
    FROM   SOFTECHDB9.dbo.items i
    WHERE  i.itemnomoreuse != '1'
      AND  i.itemarchive = 0
      AND  i.itemnosaleclassif IS NOT NULL
      AND  i.itemnosaleclassif != '10'
      AND  i.itemnosaleclassif != ''
    ORDER  BY i.itemnosaleclassif, i.itemname
"""

# ── SAMPLE TRANSACTIONS for a personcode (diagnostic) ────────────────────────
# NOTE: Sybase does NOT support IN ('115','30') — use OR.
# Param: personcode (injected via .format())
QUERY_SAMPLE_TRANSACTIONS_TEMPLATE = """
    SELECT TOP 10
        st.personcode, st.branchcode, st.doccode, st.docnumber, st.docdate,
        st.itemcode, st.transqty, st.transprice_total
    FROM SOFTECHDB9.dbo.stktrans st
    WHERE st.personcode = '{personcode}'
      AND (st.doccode = '115' OR st.doccode = '30')
    ORDER BY st.docdate DESC
"""

# ── SAMPLE INSURANCE TRANSACTIONS (diagnostic) ────────────────────────────────
# Sybase-safe: use OR instead of IN
QUERY_SAMPLE_INSURANCE_TRANSACTIONS = """
    SELECT TOP 10
        sm.ptclassifcode, sm.phcode, sm.docnumber, sm.docdate,
        sm.docvalue, sm.branchcode
    FROM SOFTECHDB9.dbo.stktransm sm
    WHERE (sm.ptclassifcode = '10' OR sm.ptclassifcode = '15')
    ORDER BY sm.docdate DESC
"""

# ── DISTINCT PERSONCODES FOR INSURANCE/CONTRACT DOCS ─────────────────────────
QUERY_DISTINCT_INSURANCE_PERSONCODES = """
    SELECT DISTINCT TOP 30 st.personcode
    FROM SOFTECHDB9.dbo.stktrans st
    JOIN SOFTECHDB9.dbo.stktransm sm
        ON  sm.branchcode = st.branchcode
        AND sm.doccode    = st.doccode
        AND sm.docnumber  = st.docnumber
        AND sm.docdate    = st.docdate
    WHERE (sm.ptclassifcode = '10' OR sm.ptclassifcode = '15')
      AND st.personcode IS NOT NULL
      AND st.personcode != ''
"""

# ── ALL ITEM LINES FOR ALL PRESCRIPTIONS IN A MOTALBA (batch fetch) ──────────
# Fetches every item line for every prescription in one query.
# Group by docnumber in Python after fetching to eliminate per-prescription queries.
#
# Params: personcode, motalbano
#
# Columns:
#  [0]  m.docnumber
#  [1]  st.itemcode
#  [2]  i.itemname
#  [3]  st.transqty
#  [4]  st.transprice        (unit price)
#  [5]  st.transprice_total  (line total)
#  [6]  io.importedorigin    ('1'=imported, '0'=local, NULL=local)
#  [7]  i.itemstoreclassif   (contract discount code → tarsia if 22/23)
#  [8]  i.itemorigincode
#  [9]  cc.custdiscpdescr    (discount tier description)
# [10]  sm.phcode            (patient PIC → localcustomers)
# [11]  lc.branchcustname    (patient name — may be NULL)
QUERY_ALL_MOTALBA_LINES_CLASSIFIED = """
    SELECT
        m.docnumber,
        st.itemcode,
        i.itemname,
        st.transqty,
        st.transprice,
        st.transprice_total,
        io.importedorigin,
        i.itemstoreclassif,
        i.itemorigincode,
        cc.custdiscpdescr,
        sm.phcode,
        lc.branchcustname
    FROM SOFTECHDB9.dbo.motalba m
    JOIN SOFTECHDB9.dbo.stktrans st
        ON  st.docnumber  = m.docnumber
        AND st.branchcode = m.branchcode
    JOIN SOFTECHDB9.dbo.stktransm sm
        ON  sm.branchcode = st.branchcode
        AND sm.doccode    = st.doccode
        AND sm.docnumber  = st.docnumber
        AND sm.docdate    = st.docdate
    JOIN SOFTECHDB9.dbo.items i
        ON  i.itemcode = st.itemcode
    LEFT JOIN SOFTECHDB9.dbo.itemsorigin io
        ON  io.itemorigincode = i.itemorigincode
    LEFT JOIN SOFTECHDB9.dbo.custdiscpclassif cc
        ON  cc.custdiscpcode = i.itemstoreclassif
    LEFT JOIN SOFTECHDB9.dbo.localcustomers lc
        ON  lc.phcode = sm.phcode
    WHERE m.personcode = ?
      AND m.motalbano  = ?
      AND m.invdel = 1
    ORDER BY m.motalba_docorder, m.docnumber, st.itemcode
"""

# ── ITEM LINES BY DOCNUMBER (fast — no stktransm join, no branchcode in WHERE) ──
# Used by the batch importer.  Returns all item lines for a list of docnumbers.
# stktransm is NOT joined here because:
#   a) its join condition (sm.docdate = st.docdate on DATETIME) is slow
#   b) patient name is resolved from motalba.ppersoncode separately
# branchcode is NOT in the WHERE clause because RTRIM() prevents index use;
# branchcode filtering is done in Python after fetching.
# Columns: [0]=docnumber, [1]=branchcode, [2]=itemcode, [3]=itemname,
#          [4]=transqty, [5]=transprice, [6]=transprice_total,
#          [7]=importedorigin, [8]=itemstoreclassif, [9]=itemorigincode,
#          [10]=custdiscpdescr
# Params: one CONVERT(numeric(6), ?) per docnumber — build dynamically.
QUERY_ITEM_LINES_DOCNOS_TEMPLATE = """
    SELECT
        st.docnumber,
        st.branchcode,
        st.itemcode,
        i.itemname,
        st.transqty,
        st.transprice,
        st.transprice_total,
        io.importedorigin,
        i.itemstoreclassif,
        i.itemorigincode,
        cc.custdiscpdescr,
        st.itemsaleprice,
        ci.patientname
    FROM SOFTECHDB9.dbo.stktrans st
    JOIN SOFTECHDB9.dbo.stktransm sm
        ON  sm.docnumber  = st.docnumber
        AND sm.branchcode = st.branchcode
        AND sm.doccode    = st.doccode
    JOIN SOFTECHDB9.dbo.items i
        ON i.itemcode = st.itemcode
    LEFT JOIN SOFTECHDB9.dbo.itemsorigin io
        ON io.itemorigincode = i.itemorigincode
    LEFT JOIN SOFTECHDB9.dbo.custdiscpclassif cc
        ON cc.custdiscpcode = i.itemstoreclassif
    LEFT JOIN SOFTECHDB9.dbo.companiesitems ci
        ON  ci.docnumber  = st.docnumber
        AND ci.branchcode = st.branchcode
        AND ci.doccode    = st.doccode
    WHERE {docno_filter}
    ORDER BY st.docnumber, st.itemcode
"""

# ── HCICLAIMFORMS — claim form submission tracking ────────────────────────────
# Param: personcode
QUERY_HCICLAIMFORMS_BY_PERSONCODE = """
    SELECT
        h.personcode, h.receivesno, h.receivedate, h.noofforms,
        h.claimsno1, h.claimsno2, h.receivedby, h.claimcomment
    FROM SOFTECHDB9.dbo.hciclaimforms h
    WHERE h.personcode = ?
      AND h.claimdel = 0
    ORDER BY h.receivedate DESC
"""
