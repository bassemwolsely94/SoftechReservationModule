# SOFTECH Purchase Save — EXACT native DML (captured 2026-07-03)

Captured via `monSysSQLText` (after installing MDA + a restart to activate
`max SQL text monitored`) while the operator saved a real purchase on the native
`مشتريات من الموردين` screen. SPID 40, branch 100, supplier 30, **docnumber 63667**,
item 404 (UROSOLVINE), qty 10, public 38, net 28.5, total 285. This is the
byte-exact sequence the client sends — the source of truth for the writer.

## The sequence (spid 40)
```
begin tran                                            -- (batch 54)
  ... prereq reads: dup-guard on stktransm; select count(*) from stkbal (item 404);
      select sum(itemqty) from stkbalexpiry (item 404) ...
  INSERT INTO stktransm (...)                         -- (batch 133) header
  INSERT INTO stktrans  (...)                         -- (batch 134) one per line
  insert into temp_r_stk (...doctext blob...)         -- (batch 135) on-screen cache
commit tran                                           -- (batch 138)
begin tran                                            -- (batch 139)
  update lastdocnumbers set lastdocnumberin_supp=63667,
         lastdocnumberout_supp=11030 where branchcode='100'   -- (batch 142) COUNTER
commit tran                                           -- (batch 143)
```

## Header INSERT (exact — 32 columns)
```sql
INSERT INTO stktransm (
  branchcode, doccode, docnumber, docdate, specialdiscp, origintaxp, storecode,
  fatstatuscode, ptcode, ptclassifcode, fatcurrentstatus, docwritedate, custdiscp,
  usercode, cust_branch_store, cust_professional, saleprice_extrap, docvalue,
  docvaluepay, docvaluereturn, patientpayment, docvalue1, docvalue2, docvalue3,
  bcurrency, docvaluebc, docvaluepaybc, bcrate, supp_main_code, cust_branch_code,
  origdoc, docnumber2 )
VALUES ( '100','10',63667,'7-3-2026 0:0:0.000', 0.00, 0.00, '100',
  '10','20','60','15','7-3-2026 0:0:0.000', 0.00,
  '1509','100','0', 0.00, 285.0000,
  0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000,
  1, 285.00, 0.0000, 1.0000, '00', '30',
  0, 3072026 )
```
Notes vs our earlier writer:
- **`docwritedate` IS set** (= docdate/today). We had NULL.
- **OMITS** `trans_time`, `table_dumped`, `phcode`, `personnewbal`, `mitemsys`,
  `cashiercode`, `vf2` (let them default/NULL). We were setting several of these.
- `docvalue1/2/3 = 0` (confirmed — purchases don't populate them).
- `ptcode='20'`, `ptclassifcode='60'` (the supplier's class), `cust_branch_code='30'`
  (supplier personcode), `docnumber2=3072026` (supplier invoice no), `usercode='1509'`,
  `cust_professional='0'`, `origdoc=0`, `supp_main_code='00'`, `docvaluepay=0`.

## Line INSERT (exact — 27 columns) — THE FIX
```sql
INSERT INTO stktrans (
  branchcode, doccode, docnumber, docdate, storecode, itemcode, itemsalestax,
  itemsaleprice_tax, pharmacydiscp, additionaldiscp, itemexpirydate, transprice,
  transprice_total, origintaxp, custdiscp, specialdiscp, saleprice_extrap, usercode,
  bonusqty, dblitemflag, storecode2, transqty, newqty, retqty, suppliercode,
  personcode, itemsaleprice, promtype )
VALUES ( '100','10',63667,'7-3-2026 0:0:0.000','100','404', 0.0000,
  38.0000, 25.0000, 0.00, '9-9-2028 0:0:0.000', 28.5000,
  285.0000, 0.00, 1.00, 0.00, 0.00, '1509',
  0.00000, 1, '0', 10.00000, 47.00000, 0.00000, '30',
  '30', 38.000, 1 )
```
**Critical differences (why `tr_stktrans` rejected our insert with error 2732):**
1. **`newqty = 47.0` = the RESULTING running stock balance** (previous 37 + transqty 10).
   NOT the line qty. The trigger validates newqty against `stkbal.nowqty ± transqty`;
   a wrong value → `rollback trigger with raiserror` (2732). ⇒ we MUST read live
   `stkbal.nowqty` at push time and set `newqty = nowqty + transqty` (purchase) /
   `nowqty − transqty` (return). *This is also why a verbatim clone failed — the copied
   newqty was stale once stock had moved.*
2. **`newcostprice` is OMITTED** — the client does not send it; the trigger computes the
   weighted-avg cost. ⇒ we must NOT set newcostprice.
3. **Minimal columns** — no `trans_time`, `r_docnumber`, `r_docdate`, `r_doccode`,
   `s_doccode`, `s_docnumber`, `s_docdate`, `item_partno`, `costcentercode`,
   `rcostprice`, `vf1..vf4`. Extra columns we were sending are dropped.
4. `custdiscp = 1.00` (small non-zero on this line — reproduce the client's value; likely a
   per-item margin/deal field, not a discount %), `storecode2='0'`, `promtype=1`,
   `bonusqty=0`, `dblitemflag=1`.
5. `pharmacydiscp = 25` (public 38 → net 28.5), `itemsaleprice=38`, `itemsaleprice_tax=38`,
   `itemsalestax=0`, `transprice=28.5`, `transprice_total=285`, `retqty=0`.

## Counter UPDATE (exact) — client does it explicitly, NOT via trigger
```sql
update lastdocnumbers set lastdocnumberin_supp = 63667,
       lastdocnumberout_supp = 11030 where branchcode = '100'
```
- Runs in its OWN transaction AFTER the doc commit.
- Sets `lastdocnumberin_supp` = the docnumber just used (63667), and writes back the
  current `lastdocnumberout_supp` (11030) unchanged. ⇒ our writer must, after inserting,
  `UPDATE lastdocnumbers SET {in_supp|out_supp} = <docnumber> WHERE branchcode=<branch>`
  (allocation = read current + 1; do NOT rely on a trigger to bump it — the FINAL
  `tr_stktransm` does not, unlike the staging `tr_stktransm5`).

## RETURN TO SUPPLIER (doccode 120) — EXACT native DML (captured 2026-07-03)
Return of purchase 63669 (RAMCO PHARM, item 404 ×10) → return doc **11035**
(`lastdocnumberout_supp`). Built via the screen's "Select From Original Purchases" (reads
the original stktrans line to copy cost/price/expiry). Differs from a purchase:

### Return header — 31 cols (NO docwritedate)
```sql
INSERT INTO stktransm ( branchcode, doccode, docnumber, docdate, specialdiscp, origintaxp,
  storecode, fatstatuscode, ptcode, ptclassifcode, fatcurrentstatus, custdiscp, usercode,
  cust_branch_store, cust_professional, saleprice_extrap, docvalue, docvaluepay,
  docvaluereturn, patientpayment, docvalue1, docvalue2, docvalue3, bcurrency, docvaluebc,
  docvaluepaybc, bcrate, supp_main_code, cust_branch_code, origdoc, docnumber2 )
VALUES ( '100','120',11035,'7-3-2026 0:0:0.000',0.00,0.00,'100','10','20','60','15',0.00,
  '1509','100','0',0.00, 285.0000, 0.0000, 0.0000, 63669.0000, 0.0000,0.0000,0.0000,
  1, 285.00, 0.0000, 1.0000, '00', '30', 0, 4 )
```
- **`patientpayment` = the ORIGINAL purchase docnumber** (63669) — the رقم مرجعي reference.
- **`docnumber2` = the return-REASON code** (4 = "مرتجع لعمل إدخال إصحيح"), NOT the supplier invoice no.
- `docvaluereturn = 0`; **no `docwritedate`**; else same sentinels as the purchase header.

### Return line — 32 cols (INCLUDES newcostprice + r_* linkage)
```sql
INSERT INTO stktrans ( branchcode, doccode, docnumber, docdate, storecode, itemsalestax,
  itemsaleprice_tax, pharmacydiscp, additionaldiscp, itemexpirydate, transprice, newcostprice,
  transprice_total, origintaxp, custdiscp, specialdiscp, saleprice_extrap, usercode, bonusqty,
  dblitemflag, storecode2, r_docnumber, r_docdate, transqty, newqty, retqty, itemcode,
  suppliercode, personcode, itemsaleprice, r_doccode, promtype )
VALUES ( '100','120',11035,'7-3-2026 0:0:0.000','100', 0.0000, 38.0000, 25.0000, 0.00,
  '9-9-2028 0:0:0.000', 28.5000, 28.4557, 285.0000, 0.00, 0.00, 0.00, 0.00, '1509', 0.00000,
  1, '0', 63669, '7-3-2026 0:0:0.000', 10.00000, 37.00000, 0.00000, '404', '30', '30',
  38.000, '10', 1 )
```
- **INCLUDES `newcostprice`** (28.4557) = the ORIGINAL purchase line's weighted-avg cost (read
  from stktrans doccode=10 docnumber=`r_docnumber`). Purchases OMIT newcostprice; returns SEND it.
- **`r_docnumber` = original purchase docnumber (63669)**, **`r_docdate` = its docdate**,
  **`r_doccode` = '10'** — the linkage to the original.
- **`newqty` = stkbal.nowqty − transqty** (47 − 10 = 37) — return DECREASES stock.
- `transqty` positive; `retqty=0`; `dblitemflag` = line index.

### Counter
```sql
update lastdocnumbers set lastdocnumberout_supp = 11035 where branchcode = '100'
```

### Writer implications (return path)
1. Header: 31 cols, `patientpayment=<original docnumber>`, `docnumber2=<reason code>`, no docwritedate.
2. Line: 32 cols, INCLUDE `newcostprice` (read from the original purchase's stktrans line by
   `r_docnumber`), `r_docnumber`/`r_docdate`/`r_doccode='10'`; `newqty = nowqty − transqty`.
3. Counter: `lastdocnumberout_supp = docnumber`.
4. Requires the original purchase to exist in SOFTECH (read its line newcostprice + docdate).

## On-screen doc cache — `temp_r_stk` (and why the "Temporarily Save" draft is NOT replicable)
During a **full Save**, the client also writes `insert into temp_r_stk (branchcode, doccode,
docnumber, docdate, doctext)` — an opaque ~80-byte encoded `doctext` blob keyed by the **final
docnumber**. This is a per-saved-document on-screen cache (for fast re-open/reprint), NOT the
stock record. We skip it (stktransm/stktrans + counter are authoritative; our pushed docs still
browse and are returnable natively — proven).

### The "Temporarily Save On-Screen Data" draft is CLIENT-LOCAL (confirmed 3 ways, 2026-07-03)
Requested feature: push an invoice as a temporary draft that the operator "retrieves" in SofTech,
reviews, then Saves. **Not achievable** — the temp draft is stored on the **workstation**, not the
HQ database:
1. Original table search after a temp-save found no server row.
2. `watch_temp_rstk` polled `temp_r_stk` docnumber=0 directly (0.3s) through **5 controlled
   temp-saves** → **zero** server changes.
3. Broad scan: the only `docnumber=0` row anywhere is an old Feb-2025 leftover; today's temp_r_stk
   rows are all keyed by **final** docnumbers (full-save caches), none from the temp-saves.
The native "retrieve temporarily saved" reads the local workstation store; nothing is written
server-side, so there is no blob to reverse-engineer / reproduce. ⇒ "review before it lands" is
delivered by OUR flow instead: OCR → validate (SofTech rules) → preview modal → push final.
Command: `apps/sync/management/commands/watch_temp_rstk.py`.

## ✅ SOLVED (2026-07-03) — the bottleneck was CHAINED vs UNCHAINED transaction mode
After the analysis below, the actual root cause was found: **jConnect `setAutoCommit(false)`
puts the session in CHAINED transaction mode**; SofTech's `sp_expirytrans` (called by
`tr_stktrans`) has internal `begin tran`/`@@trancount` logic that misbehaves under chained
mode and hits its error path → invalid `raiserror` → **err 2732**. The native client runs
**UNCHAINED** (explicit `begin tran`/`commit tran`, autocommit on).

**Fix:** run the whole document as ONE batch in unchained mode:
`set chained off; begin tran; INSERT stktransm; INSERT stktrans…; UPDATE lastdocnumbers;
verify; commit/rollback tran`. Implemented in `apps/invoices/writer.py::_run_write_batch`.

**PROVEN** via the rollback probe (`clone_purchase --branch 100 --docnumber 63667`):
`PROBE ok=True docnumber=63668 lines=1/1 err=0` — header + line inserted, verified, rolled
back (zero residue). Multi-line docs work too; the only extra care is items appearing on
multiple batches (unique index `stktrans_x`) → give each a distinct key (dblitemflag/expiry).

Direct-DML supplier-invoice writeback is therefore **FEASIBLE**. The writer:
live `newqty` from `stkbal`; omit `newcostprice`; exact 32/28 column sets; `docwritedate`;
explicit counter update; **unchained single-batch**; SofTech-style dup guard (supplier+doccode+
docnumber2) for idempotency; gated by `INVOICE_WRITER_ENABLED`.

## (superseded) earlier "blocked" analysis — direct insert appeared blocked by encrypted `sp_expirytrans`
After replicating the exact captured DML (live `newqty`, omit `newcostprice`, exact 32/28
column sets, `docwritedate`, explicit counter update, `set quoted_identifier on` + other
session options), from our jConnect connection:
- The **header** (`stktransm`) insert **succeeds** (`tr_stktransm` accepts it).
- **Every** `stktrans` line insert **fails with error 2732** (`tr_stktrans` does
  `rollback trigger with raiserror <invalid#>` → 2732 = "user error number invalid").
- **Cloning the client's OWN successful item-404 save (docnumber 63667) ALSO fails** from
  our connection — byte-identical item/values that the native client committed seconds earlier.
  ⇒ it is **NOT the data / newqty / columns** — it is the **connection/session**.
- `tr_stktrans` calls **`sp_expirytrans`** (params: storecode, itemcode, itemexpirydate,
  transqty, transtype, batchno, item_nowqty, item_newqty; touches only `stkbalexpiry`).
  **Both `tr_stktrans` and `sp_expirytrans` are ENCRYPTED** (`syscomments.text` NULL) — the
  validation that fails cannot be read, and it depends on native-client session context we
  cannot reproduce (not a discoverable temp table; not simple `set` options).

**Conclusion: SUPPLIER-INVOICE DIRECT-DML WRITEBACK IS NOT FEASIBLE** without the vendor
(SofTech) providing the `tr_stktrans`/`sp_expirytrans` source or an official import API. This
is the hard read-only ceiling. Pivot to: (a) prefill the native on-screen doc in `temp_r_stk`
so the operator reviews + clicks Save (SofTech does its own trigger-safe insert) — needs
decoding the `doctext` blob; or (b) ship Track-A OCR + export to speed manual entry.

## Writer changes (implemented — kept for a future vendor-import path; NOT usable via direct DML)
1. Read live `stkbal.nowqty` per (branchcode, storecode, itemcode) at push time →
   `newqty = nowqty + transqty` (doccode 10) / `nowqty − transqty` (120).
2. OMIT `newcostprice` from the stktrans insert.
3. Use the EXACT captured column sets above (header 32 / line 27); set `docwritedate=docdate`.
4. Allocate `docnumber = read({counter}) + 1`; insert header+lines; then a separate
   `UPDATE lastdocnumbers SET {counter}=docnumber WHERE branchcode=<branch>`.
5. Re-verify with the rollback probe — expect it to LAND now (no 2732).

## Tax, total and free-goods columns (decoded 2026-10-31)

Read-only comparison of hand-entered PharmaOverseas purchases (branch 100: 66176, 66175, 66173,
65966) with our doc 66177, which had posted VAT-less totals. With «الضريبة من التكلفة» UNticked
(the house standard — VAT outside the unit cost):

| Where | Column | Value |
|---|---|---|
| taxed line | `saleprice_extrap` | the line VAT % (14). `origintaxp` stays 0. Untaxed lines 0. |
| header | `docvalue3` | Σ `itemsalestax × transqty` («خارج التكلفة») |
| header | `docvalue` / `docvaluebc` | Σ `transprice_total` + `docvalue3` (what the supplier is owed) |
| free line | `bonusqty` | value of the free goods = paid unit cost × free qty (e.g. 56.2) |
| header | `docvalue1` | Σ `bonusqty` (NOT added to `docvalue`) |
| line | `custdiscp` | 1.0 on purchase lines |

With the box TICKED (doc 65708): VAT is inside `transprice`, `saleprice_extrap` = 0, `docvalue3` = 0,
`docvalue` = Σ line totals.

The writer (`writer._finish_purchase_line`, `writer._native_purchase_totals`) sets these from the
FINAL line rows, after per-line overrides (replacement buy-backs zero VAT → no VAT %). Rollback probe of
invoice 224: docvalue 4234.68, docvalue3 325.16, extrap 14 on the 5 taxed lines, zero residue.
Still unknown: where «نوع الضريبة = قيمة» (VAT entered as an amount) is stored — needs a hand-entered sample.

### Golden comparison with the hand entry of the same invoice (66178 vs our 66177), 2026-10-31

The owner entered invoice 224 by hand (doc 100/10/66178, user 1509) with «الضريبة من التكلفة»
TICKED on the taxed lines. Owner decision: the module posts this way (`writer.VAT_IN_COST`).

| Column | Native (66178) | Rule now in the writer |
|---|---|---|
| `stktransm.docwritedate` | 2026-10-29 | «تاريخ مستند المورد» = the supplier invoice date (`invoice_date`); `docdate` = receipt day |
| `usercode`, `cashiercode` | 1509 / 1509 | the SofTech code of the staff member who posts (`StaffProfile.softech_user_id`); posting refuses without one |
| `docvalue`, `docvaluebc` | 4234.68 | Σ `transprice_total` + `docvalue3` |
| `docvalue3` | 0 | Σ VAT only on lines with VAT outside the cost (`storecode2 ≠ '1'`) |
| line `storecode2` | '1' on taxed lines | the «الضريبة من التكلفة» box |
| line `transprice` | 104.0022 (= 91.23 × 1.14) | Pb·(1−d1)(1−d2)(1−d3)·(1+rate), rounded once to 4 places |
| line `pharmacydiscp` | 19.9983 | back-solved from the net and rounded to 4 places; the cost is then derived FROM it |
| line `itemsaleprice_tax` | 114.0351 | public / (1+rate), 4 places |
| line `itemsalestax` | 12.7722 | unrounded net × rate, 4 places |
| line `saleprice_extrap` | 14 | VAT % on taxed lines |
| line `itemexpirydate` | 2028-05-05 | month/year expiry → day = month |

Other tables: the native save also writes one `temp_r_stk` row per document (199 characters: a 20-byte
opaque value + padding, apparently a checksum by the client); we cannot reproduce it and SofTech opens our
documents without it. `stkbal` (`nowqty`, `nowcostprice`, `usercode`), `stkbalexpiry` (one bucket per
expiry date, `batchno` = `item_partno`) and `personsdata` (`personcredit`, `personfdate`) are updated by the
SofTech triggers for both. `items` and `itemssuppliers` are not touched by either.

Rollback probe of invoice 224 after the fix, as user 1509: every header and line money column equal to
66178; the only differences are line data (4 OCR'd batches, 2 hand-typed expiries).

## Returns (doccode 120) mirror the original purchase — decoded 2026-10-31

Hand-entered HQ returns 11319–11323 («Select From Original Purchases»): every return line copies
the original purchase line — `transprice`, discounts, `itemsalestax`, `itemsaleprice(_tax)`,
`storecode2`, `saleprice_extrap`, `custdiscp`, `bonusqty`, `itemexpirydate`, `item_partno` — plus
`r_docnumber` / `r_docdate`; only `transqty` (and so `transprice_total`) is the returned quantity.
`newcostprice` is set by the SofTech trigger to the item's CURRENT average cost (rollback probe).
The writer now does the same (`writer._mirror_original`), reading the original lines from SofTech
at posting; the return header counts VAT outside the cost only when the original header did.

Triggers (rollback probes): UPDATEs on `stktrans`/`stktransm` fire NO side effects (stock, expiry
buckets, cost and supplier balance unchanged); header inserts don't move `personsdata` either.
The supplier balance (`personsdata.personcredit`/`persondebit`/`personfdate`) is changed by the
native client on save — documents posted by the module have never updated it (open item).

Return 11324 (module, 2026-10-31) was corrected in place by owner exception: 13 lines + header
mirrored to 66177, 7 `stkbalexpiry` rows moved to the hand entry 66178's dates/batches, 5 `stkbal`
average costs set to 66178's VAT-inclusive cost; 27/27 rows, audited (AuditLog #66370).

## Native save, captured (purchase 66179, return 11325 — 2026-10-31)

MDA capture of the owner's own saves (excerpt: `softech_native_save_sql_66179_11325.txt`). After the
document rows, the native client itself (no trigger does this — rollback probes of full inserts left
`personsdata` untouched) runs, in the same transaction:

| Document | Statement |
|---|---|
| purchase | `update personsdata set personcredit = personcredit + docvalue where personcode = supplier` |
| purchase | per item: `select count(*) from itemssuppliers …` and, when 0, `insert into itemssuppliers` (d1, d2, d3, public price, pre-tax cost, VAT per unit, VAT %) |
| return | `update personsdata set personcredit = personcredit − docvalue …` |
| return | original header `docvaluereturn += ` the return's value; original line `retqty += qty` (by `dblitemflag`) |
| both | `insert into temp_r_stk` (20-byte opaque value — not reproduced) |
| both | separate transaction: `update lastdocnumbers set lastdocnumberin_supp = max(10), lastdocnumberout_supp = max(120)` |

The writer now runs the same statements (`writer._native_after_save`) inside the document's
transaction and commits only when each hit its rows. Rollback probes: purchase 224 → balance
+4234.68; return 231 → −3909.52 and 66177 marked returned; zero residue.

The 18 documents the module had posted before were corrected the same way by owner decision
(AuditLog #66372): supplier 1268 +400,000.00, supplier 30 +570.00, PharmaOverseas net 0; purchases
63670, 65912 and 66177 marked returned (quantities and value). Return 11324 itself: AuditLog #66370.
