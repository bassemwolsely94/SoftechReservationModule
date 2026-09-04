"""
apps/batches/queries.py

SOFTECH Sybase SQL for the Purchase-Expiry Physical Audit engine.

ABSOLUTE RULES:
  - SELECT ONLY. Never INSERT / UPDATE / DELETE on SOFTECHDB9.
  - doccode '10' = purchase from supplier (the ONLY doccode this engine cares
    about — it wants the ORIGINAL data-entry of an expiry, not returns/transfers).

Why we read stktrans.itemexpirydate
-----------------------------------
`stktrans.itemexpirydate` is the batch expiry date the operator KEYS at
data-entry time on every stktrans line, including purchase-invoice lines
(confirmed live; also used by apps/incentives/engine.py). That keyed value —
scoped to purchases from trusted "main" suppliers inside a chosen window — is
the signal this engine mirrors.

Supplier code on purchase docs
------------------------------
On purchase documents the supplier's personcode is stored in
`stktransm.cust_branch_code` (SOFTECH quirk). The shipped procurement engine
already treats `cust_branch_code` as the supplier key and joins it to
`personsdata.personcode`-keyed SupplierProfile/SupplierSegmentation, so the
two are the same code space in this instance.

ASE-safety
----------
Sybase ASE 12.5 has no DATE type and flaky CONVERT styles. We use direct
DATETIME range comparison (`docdate >= 'YYYY-MM-DD 00:00:00' AND docdate <
'YYYY-MM-DD 00:00:00'`), the same proven pattern as apps/stockcount/engine.py.
The window end is EXCLUSIVE (pass the first day of the month AFTER the range).
"""

# ── Purchase lines carrying an entered expiry, for a supplier set + window ────
#
# Placeholders are formatted in Python (not bound params) because the supplier
# IN-list and the optional branch filter are dynamic. All interpolated values
# are server-controlled (dates we build, supplier codes from our own mirror),
# never raw user text.
#
# Column indices:
#   [0] supplier_code   stktransm.cust_branch_code
#   [1] branch_code     stktransm.branchcode
#   [2] doc_number      stktransm.docnumber
#   [3] doc_date        stktransm.docdate      (data-entry / invoice date)
#   [4] item_code       stktrans.itemcode
#   [5] entered_expiry  stktrans.itemexpirydate
#   [6] qty             stktrans.transqty
#   [7] dblitemflag     stktrans.dblitemflag   (expiry-batch split discriminator)
#   [8] store_code      stktrans.storecode
#
QUERY_PURCHASE_EXPIRY_WINDOW = """
    SELECT
        sm.cust_branch_code   AS supplier_code,
        sm.branchcode         AS branch_code,
        sm.docnumber          AS doc_number,
        sm.docdate            AS doc_date,
        st.itemcode           AS item_code,
        st.itemexpirydate     AS entered_expiry,
        st.transqty           AS qty,
        st.dblitemflag        AS dblitemflag,
        st.storecode          AS store_code
    FROM SOFTECHDB9.dbo.stktransm sm
    JOIN SOFTECHDB9.dbo.stktrans  st
        ON  st.branchcode = sm.branchcode
        AND st.doccode    = sm.doccode
        AND st.docnumber  = sm.docnumber
        AND st.docdate    = sm.docdate
    WHERE sm.doccode = '10'
      AND sm.docdate >= '{start} 00:00:00'
      AND sm.docdate <  '{end} 00:00:00'
      AND st.itemexpirydate IS NOT NULL
      AND st.itemcode   IS NOT NULL
      AND st.itemcode   != ''
      AND st.transqty   >  0
      AND sm.cust_branch_code IN ({suppliers})
      {branch_filter}
"""
