# SOFTECH Supplier-Invoice (Purchase) Writeback — Investigation & Spec

**Investigation date:** 2026-06-28
**Target:** SOFTECHDB9.dbo (Sybase ASE 12.5 — HQ `192.168.1.8`, branchcode=100; branch data consolidated at HQ)
**Mode:** read-only probes — `apps/sync/management/commands/investigate_purchase_invoice.py` + `…_invoice2.py`
**Raw output:** `docs/architecture/softech_purchase_invoice_investigation.txt` (+ `…2.txt`)
**Objective:** Let our platform turn an **OCR'd supplier invoice** (`apps/invoices.SupplierInvoice`) into a
SOFTECH **purchase document** — supplier purchase = **doccode 10**, return-to-supplier = **doccode 120** —
to collapse manual data-entry time. Two write surfaces, exactly mirroring how the native purchasing screen
works and how `apps/pos_orders` already writes customer sales.

**Sibling that already solved every hard problem (REUSE, don't reinvent):**
[`SOFTECH_INDIRECT_POS_ORDER_WRITEBACK.md`](SOFTECH_INDIRECT_POS_ORDER_WRITEBACK.md) +
[`14_PHASE2_INDIRECT_POS_WRITER_DESIGN.md`](14_PHASE2_INDIRECT_POS_WRITER_DESIGN.md) → built as
`apps/pos_orders/{writer,pricing,reconcile}.py`. Connector transactions live in `config/sybase.py`
(`ConnectionWrapper.begin/commit/rollback`).

---

## 0. Decision context (set by the business owner)
- **Writer lives in `apps/invoices`** (extend it with `writer.py`/`pricing.py`), fed by a confirmed
  `SupplierInvoice` — NOT a separate app. (Sales used a separate `apps/pos_orders`; purchases ride on the
  existing OCR module.)
- **Investigation/spec first** (this doc) before any module code.

---

## 1. CONFIRMED — there is NO dedicated purchase/receiving/staging table
Read-only census of user tables (`%purch%`, `%receiv%`, `%grn%`, `%buy%`, `%draft%`, `%staging%`,
`%hold%`, `%pend%`, `%supp%`, all `…5` twins) found **no purchase-specific document table**:
- `%purch%` → none (only **reporting** procs `sp_purch_classif/_family/_origin1/_shape/_suppclassif…`, the
  purchase analog of `sp_sales_*`; rollups, not writers).
- `%supp%` → only `items_suppliers` / `itemssuppliers` (item↔supplier master).
- The only transaction tables are the **shared** `stktransm`/`stktrans` (final) and their `…5` staging
  twins `stktransm5`/`stktrans5`. Variants `stktransm5_revise`, `stktransm5_ext`, `dm_stktransm5` are
  **empty**; `stktransm5_ot` has a different shape (no `doccode`). **Purchase drafts are NOT in any variant.**

⇒ **Supplier invoices flow through the SAME `stktransm`/`stktrans` family as everything else, distinguished
only by `doccode` (10 / 120).** This is the purchase mirror of the sales finding.

### The "Temporarily Save On-Screen Data" feature is CLIENT-SIDE — NOT a server table (PROVEN)
**Live experiment (2026-06-28):** the operator entered a real purchase (supplier PHARMA OVER SEAS, supplier
doc no `1124578`, total `371.25`, items 404 & 2138) and clicked the screen's **"Temporarily Save On-Screen
Data"** button. We then probed the server for that draft. It appears in **NO server table**:
- `stktransm5` doccode=10 → 0 rows; `lastdocnumbers['000'].lastdocnumberin_supp` **stayed 0** (no allocation).
- `temp_invoices` empty; `stktransm_prep` (0), `stktransm_q` (0), `stktransm_hq` (0), `stktransm9` (41, none
  ours), `imports`/`importsm`/`itemsimports*` (0). No row anywhere has `docnumber2=1124578`.

⇒ **The native purchasing draft is serialized on the WORKSTATION (local "on-screen data"), recoverable only
on that same client — it is never written to SOFTECHDB.** Unlike sales (where `stktransm5` is a genuine
server hand-off to the cashier), **there is NO server-side purchase staging table to mimic.** Although the
readable `tr_stktransm5` trigger *would* route a doccode-10 insert to `lastdocnumberin_supp` (§3), nothing
ever consumes a staged purchase, so `stktransm5` for purchases is a dead end — we do not use it.

**Architectural consequence:** the "save & retrieve later" capability lives in **OUR `SupplierInvoice`**
(OCR'd, multi-user, searchable — strictly better than the native single-machine temp-save). The **only**
SOFTECH write is the **final** document (§2).

---

## ⛔ EMPIRICAL BLOCKER (2026-07-02) — direct final insert is REJECTED by `tr_stktrans`
Tested on prod (HQ) by cloning real purchase 100/10/63662 (rollback probe, zero residue):
- A header-only `stktransm` insert **succeeds** (`@@error=0`, row visible in-txn).
- Adding ANY `stktrans` line — even a **byte-for-byte verbatim copy** of the original line —
  fails: **`@@error=2732`**, `@@rowcount=0`, the hidden `tr_stktrans` trigger does a
  `rollback trigger with raiserror` (invalid msg number → 2732) and the row is discarded
  (no exception surfaces). All 9 verbatim lines rejected identically.
- `tr_stktrans` / `tr_stktransm` bodies are **HIDDEN** (syscomments NULL — vendor-encrypted);
  cannot be read.
- The `imports/importsm/itemsimports/itemsimportsm` tables are a **foreign-import/customs**
  module (customs/cargo/takhlis/insurance/currency), NOT the supplier receival path; nothing
  references them. The screen's "Import From Receival of Stock Items" is that customs flow.

**Conclusion:** the final purchase insert is **not plain bare-DML** — `tr_stktrans` enforces a
rule / needs native-client **session context** (temp tables `temp_sitems`/`temp_snos`, running
`newqty` balance, batch/stkbal state, or a duplicate guard) that a direct connection does not
set up. Unlike POS sales (which had a light-trigger *pending* table `stktransm5` to write), a
purchase has **no server-side staging** and its final insert is gated. **Direct-DML writeback of
supplier invoices is therefore NOT viable as specified below** without either (a) the vendor's
`tr_stktrans` source, or (b) capturing the native client's exact Save-time DML/proc via ASE
monitoring (`monSysSQLText`) and replaying it. See §14 for options. The §2–§9 design remains the
correct target IF that session setup can be reproduced.

## 2. The write surface — FINAL document only (one path)
The native purchasing draft is client-local (§1), so there is exactly **one** server write surface, and it
is what "full entry of the invoice into the ERP" means:

| Surface | Tables | Serial counter (`lastdocnumbers`) | Side-effects on insert |
|---|---|---|---|
| **Final / full entry** | `stktransm` + `stktrans` (doccode 10 / 120) | branch's own row (ver_branch=1, e.g. `'100'`=63546 / `'130'`) `lastdocnumberin_supp` (10) / `lastdocnumberout_supp` (120) | **heavy (hidden triggers)** — stock receive (`stkbal.nowqty +transqty`), weighted-avg **cost recompute** (`nowcostprice`), supplier **account balance** (`personnewbal`), e-invoice. |

- **Draft / "save & retrieve later" = OUR `SupplierInvoice`** (PG). OCR → review/edit/correct → on confirm,
  the writer commits the final document. No SOFTECH write happens until the user commits.
- Allocation = read the branch's own `lastdocnumberin_supp` (HOLDLOCK) **+1**, INSERT, let the trigger bump
  it — same native pattern proven for sales (never pre-UPDATE).
- Because the final insert fires SOFTECH's stock/cost/accounting triggers (which we cannot read), this path
  is **gated (`INVOICE_WRITER_ENABLED`) and validated on `SOFTECH_TEST_HOST` first** — observe before/after
  with the `observe_finalization` pattern, exactly as the sales finalization was de-risked.
- Returns to supplier = same path, doccode **120**, `lastdocnumberout_supp`, with `r_docnumber`/`r_doccode`
  linking the original purchase.

---

## 3. Serial allocation — `tr_stktransm5` routing (CONFIRMED, trigger body readable)
On any `stktransm5` INSERT the trigger stamps `trans_time` then bumps the **`branchcode='000'`** counter by
doccode (read current **+1**, INSERT — do **NOT** pre-UPDATE; same rule proven for sales §3/§6m):

```
@doccode='30'   -> lastdocnumberin_cust     (customer return)
@doccode='115'  -> lastdocnumberout_cust    (customer sale)
@doccode='10'   -> lastdocnumberin_supp     (SUPPLIER PURCHASE)        ← us
@doccode='120'  -> lastdocnumberout_supp    (RETURN TO SUPPLIER)        ← us
else <99        -> lastdocnumberin
else >=99       -> lastdocnumberout
```
Final-table allocation (surface B) uses the **branch's own** `ver_branch=1` row's `lastdocnumberin_supp` /
`lastdocnumberout_supp` (HQ `'100'`: in_supp=63527, out_supp=11014 at probe time), allocated the same way.
No stored procedure creates a purchase — **bare DML + trigger chain** (same philosophy as the discount &
sales writebacks).

---

## 4. Golden template — finalized purchase header (CONFIRMED, real row)
`stktransm` doccode=10, branch 130, docnumber 11946, 2026-06-25 (probe `…invoice2`):
```
branchcode=130  doccode=10  docnumber=11946  docdate=<date-only>
supp_main_code='00'            cust_branch_code=5014   ← SUPPLIER personcode
docnumber2=5623                ← supplier's PRINTED invoice no (→ SupplierInvoice.invoice_number)
docvalue=1350.0  docvaluepay=0.0   ← purchases post to supplier account; NO immediate tender
docvalue1=0  docvalue2=0  docvalue3=0   ← NOT used for purchases (sales used gross/COGS/tax here)
origintaxp=0  custdiscp=0  specialdiscp=0  saleprice_extrap=0  docvaluereturn=0
storecode=130  cust_branch_store=130
ptcode='20'  ptclassifcode='80'   ← supplier type; ptclassif VARIES per supplier (read from personsdata)
fatstatuscode='10'  fatcurrentstatus='15'  cust_professional='2'
usercode=1399  trans_time=<clock>  table_dumped=<clock>
personnewbal=-933081.71   ← supplier running A/C balance (negative=payable); set by finalization
bcurrency=1  docvaluebc=1350.0  docvaluepaybc=0  bcrate=1.0
phcode=NULL  mitemsys=NULL  cashiercode=NULL  origdoc=0  refdoctorcode=NULL  comments=NULL
```
Return-to-supplier header (doccode 120, branch 100, docnumber 11014) is identical shape with
`ptclassifcode=60`, `docvalue=663.52`, `docvaluepay=0`.

### 4b. Native screen confirmation (`مشتريات من الموردين` — screenshots, 2026-06-28)
The native **Purchases-from-Suppliers** screen (SofTech MINI) confirms the mapping end-to-end and exposes
the **"Temporarily Save On-Screen Data"** button = the draft/"save & finalize later" feature (writes the
staging twin, surface A). Two save buttons sit top-left: temporary (draft) vs commit. The screen can also
"Import From 'Receival of Stock Items'" — our OCR import is the same idea (populate the lines
programmatically). Status bar user `291100BASSEM` = branch 100.

| Screen label (AR) | Example | SOFTECH column |
|---|---|---|
| رقم المستند | **63532** | `docnumber` — equals `lastdocnumberin_supp` (was 63527 at the §3 probe → advances per purchase) ✔ |
| رقم مستند المورد | 1122830 | **`docnumber2`** = supplier's printed invoice no ✔ |
| تاريخ مستند المورد | 2026/06/25 | supplier invoice date |
| تاريخ الإستلام | 2026/06/28 | `docdate` (receipt date) |
| المورد | EGY DRUG-ZAYTOUN | supplier → `cust_branch_code` / line `suppliercode` (personcode) |
| لحساب مخزن / لحساب فرع | رئيسي | `storecode` / branch account |
| نوع السداد | Credit | account credit ⇒ `docvaluepay=0`, no `branchesales` ✔ |
| موقف السداد | Open | doc open/editable vs Closed/posted |
| خصم خاص (header) / ضريبة ق.م % | 0.00 / 0.00 | header `specialdiscp` / `origintaxp` |
| إجمالي القيمة | 110.50 | `docvalue` |

Line formula **confirmed on real data** (HALOPERIDOL, code 90792): public `سعر البيع للجمهور`=28.000 ×
(1 − discount `21.0714`%) = unit cost `تكلفة الوحدة`=22.10 = `transprice`=`newcostprice`; × qty 5 =
`إجمالي تكلفة`=110.50 = `transprice_total`. ⇒ **public=`itemsaleprice`, discount%=`pharmacydiscp`,
cost=`transprice`/`newcostprice`, expiry=`itemexpirydate`**. (Screenshot 2 verifies 3 more lines:
99→73.50, 213→159×3, 168→125.50×30.)

### Header mapping (`SupplierInvoice` → `stktransm`/`stktransm5`)
| SOFTECH col | Source |
|---|---|
| `branchcode`,`storecode`,`cust_branch_store` | `SupplierInvoice.branch` (softech code) |
| `doccode` | `'10'` purchase / `'120'` return |
| `docnumber` | allocated (see §3) |
| `docdate` | `invoice_date` (date-only) |
| `docnumber2` | `invoice_number` (supplier's printed no) |
| `cust_branch_code` | supplier personcode (resolve via §6) |
| `supp_main_code` | supplier main-group (from supplier master; `'00'` seen) |
| `ptcode` | `'20'` (constant — supplier) |
| `ptclassifcode` | the supplier's `personsdata.ptclassifcode` (NOT hardcoded) |
| `docvalue`,`docvaluebc` | `total_after_discount` |
| `docvaluepay`,`docvaluepaybc`,`patientpayment` | `0` (account credit) |
| `docvalue1/2/3` | `0` |
| `usercode` | data-entry staff's ERP usercode |
| `trans_time` | `getdate()` (stamped by trigger on staging; set on final) |
| `fatstatuscode`/`fatcurrentstatus`/`bcurrency`/`bcrate` | sentinels `'10'`/`'15'`/`1`/`1.0` |

---

## 5. Line mapping (`InvoiceLine` → `stktrans`/`stktrans5`)
`stktrans` line schema confirmed (45 cols). Semantics cross-checked with the documented read-side in
[`apps/procurement/queries.py`](../../apps/procurement/queries.py) (doccode 10/120; `transprice`=purchase
price/pack, `newcostprice`=weighted-avg cost, `itemsalestax`/`origintaxp`=tax). Key columns:

**CONFIRMED line values** (doc 130/10/11946, item 128695):
```
itemcode=128695  transqty=1  transprice=1350.0008  newqty=1  newcostprice=1350.0008
itemexpirydate=2028-02-01     itemsaleprice=2145.0  itemsaleprice_tax=2145.0  itemsalestax=0
pharmacydiscp=37.0629  additionaldiscp=0  origintaxp=0  custdiscp=0  specialdiscp=0
transprice_total=1350.0008  bonusqty=0  dblitemflag=1  promtype=1
suppliercode=5014  personcode=5014   r_docnumber/r_doccode/s_*=NULL   item_partno=NULL  retqty=0
```
Verified relationship: **`transprice = itemsaleprice × (1 − pharmacydiscp/100)`** → 2145 × (1−0.370629) =
1350.00 ✓. So **the purchase discount lands in `pharmacydiscp`** (public→net), NOT `custdiscp` (that's the
customer-sale column). `newcostprice = transprice` (landed cost) and `newqty = transqty` (qty received).

| SOFTECH col | Source / meaning |
|---|---|
| `itemcode` | `InvoiceLine.item.softech_id` |
| `transqty`, `newqty` | `quantity` (received qty) |
| `transprice`, `transprice_total`, `newcostprice` | net purchase price/pack (= `unit_price`); `_total = ×qty`; cost = net |
| `itemsaleprice` / `itemsaleprice_tax` | public/retail price set at receive (`public_price`) |
| `itemsalestax` / `origintaxp` | line VAT amount / rate (`vat_pct`) — `0` for exempt |
| `pharmacydiscp` / `additionaldiscp` | the purchase discount tiers (`discount_pct` / `extra_discount_pct`) |
| `custdiscp` / `specialdiscp` | `0` for purchases (customer-side columns) |
| `itemexpirydate` | batch **expiry** (`InvoiceLine.expiry_date`) |
| `item_partno` | batch / lot **number** (`InvoiceLine.batch_number`) — optional (was NULL here) |
| `suppliercode`, `personcode` | supplier personcode (= header `cust_branch_code`) |
| `s_doccode`/`s_docnumber`/`s_docdate` | source-doc link — NULL on a plain purchase |
| `dblitemflag` | 1 (batch-split marker; >1 when one item has multiple expiries → multiple lines) |
| `promtype` | 1 (default) |
| `r_docnumber`/`r_doccode`/`r_docdate` | original purchase ref (returns / doccode 120 only) |
| `bonusqty` | free-goods qty (supplier bonus) — map from invoice if present, else 0 |

---

## 6. Supplier resolution (master = `personsdata`, ptcode='20')
`ptcode='20'` = supplier/distributor (confirmed: `apps/procurement/queries.py` `QUERY_SUPPLIERS`).
`ptclassifcode` sub-types observed: **10** (دومينانت — general/official distributor, 1174 rows), 20, 30,
40 (مقاصة/clearing), 50, 60, 70, 80, 96 (طباعة/media). The purchase header's `ptclassifcode` is the
**supplier's own** classification — resolve it from the supplier's `personsdata` row, don't hardcode.
`cust_branch_code` (header) and `suppliercode` (line) = the supplier `personcode`. Map
`VendorProfile`/`SupplierInvoice.supplier_name` → SOFTECH `personcode` (extend `VendorProfile` with a
`softech_personcode`, resolved against `personsdata`/`itemssuppliers`).

---

## 7. Payment / accounting — NO `branchesales` for purchases (CONFIRMED)
Probe: the finalized purchase doc had **zero `branchesales` rows** and `docvaluepay=0`. Purchases post to
the **supplier account** (the finalization sets `personnewbal`), not a POS tender. ⇒ the purchase writer is
**simpler than sales** — `stktransm(5)` + `stktrans(5)` only, **no `branchesales5` table**. (Supplier cash
payments, if ever modeled, are a separate accounting doc — out of scope.)

---

## 8. Finalization side-effects (surface B) — hidden triggers SOFTECH owns
On a **final** `stktransm`/`stktrans` doccode-10 insert, SOFTECH's (vendor-protected) trigger chain does:
stock receive (`stkbal.nowqty +transqty`), **weighted-avg cost recompute** (`stkbal.nowcostprice` →
flows to `newcostprice`), supplier **account balance** (`personnewbal`), e-invoice (`stktransm_inv`).
These are exactly what manual data-entry does today, so they are DESIRED — but because we cannot read the
math, surface B **must be validated on `SOFTECH_TEST_HOST`** before any prod commit (observe before/after
with the existing `observe_finalization` pattern).

---

## 9. BUILT (2026-06-28) — gated, no prod write yet
Track A (OCR) and Track B (writer) are implemented in `apps/invoices`:
- `pricing.py` — `compute_line`/`compute_header` (verified vs the golden row + unit tests).
- `writer.py` — `build_plan` (dry-run preview), `push_final` (gated by `INVOICE_WRITER_ENABLED`,
  default off → returns the dry-run plan; live path writes FINAL `stktransm`/`stktrans` doccode 10/120,
  allocates branch `lastdocnumber{in,out}_supp`+1, verify-readback, idempotent via `vf2='INV<pk>'`),
  `probe_invoice` (rollback probe — real inserts then ROLLBACK; reports `trigger_bumped_counter`).
- Models: `SupplierInvoice` (+doc_kind, softech_branchcode/store_code/docnumber, return_of_docnumber,
  client_token, erp_* audit, statuses queued/pushing/finalized/push_failed; migration 0010);
  `VendorProfile.softech_personcode`.
- API: `POST /api/invoices/{id}/push-preview/` (dry-run plan), `/push/` (gated, RBAC
  admin/purchasing/supervisor), `/probe/` (admin, test-instance rehearsal).
- Settings/env: `INVOICE_WRITER_ENABLED` / `_PROFILE` / `INVOICE_DEFAULT_USERCODE` / `INVOICE_WRITE_CHARSET`.
- Tests: `apps/tests/test_invoice_writer.py` (pricing, plan shape, gate, returns) — green.

### 9a. No test instance → validate by CLONING a real entered purchase
`python manage.py clone_purchase --branch <bc> --docnumber <n>` (read-only by default):
reads a real entered purchase, rebuilds it through our writer, runs the **rollback probe**
(real insert → read back → ROLLBACK, zero residue) and **diffs every column of our
re-insert against the original** (flagging DIFF, OURS-NULL, and `trigger_bumped_counter`).
Add `--commit` (needs `INVOICE_WRITER_ENABLED=True`) to insert ONE real document, which is
then **returned manually** (doccode 120). This is the same clone-and-rollback rehearsal that
de-risked the POS writer (`pos_probe --clone`).

**#1 unknown to settle (now via clone_purchase, no test host needed):** does the FINAL
`stktransm` insert trigger bump
`lastdocnumber*_supp` (native, like the staging path) or must the client `UPDATE` it? `probe_invoice`
returns `trigger_bumped_counter` to answer this with zero residue before any commit.

## 9b. Original design notes (extends `apps/invoices`; mirrors `pos_orders/writer.py`)
```
apps/invoices/
  pricing.py     # pure line/header math (qty × price − discounts, VAT) — already partly in models.compute_total
  writer.py      # transactional writer (FINAL document only):
                 #   push_final(invoice)  → stktransm/stktrans doccode 10 (or 120 return)  [gated]
                 #   probe_invoice(...)   → rollback probe (real INSERTs, always ROLLBACK) — zero residue
                 #   (NO push_draft / cancel_draft — purchase drafts live in SupplierInvoice, not SOFTECH)
  + SupplierInvoice: this IS the draft ("save & retrieve later"). Add status 'finalized',
    softech_branchcode, softech_doccode, softech_docnumber, erp_payload/readback/error (immutable audit),
    client_token (idempotency via vf2/comments)
  + VendorProfile.softech_personcode (supplier resolution)
```
Reused verbatim from `pos_orders`: native serial allocation (read+1, HOLDLOCK), **inline-literal INSERTs**
(param INSERTs silently don't land on this ASE), one statement per cursor, cp1256 write charset,
verify-readback, rollback-probe-as-rehearsal, idempotency tag, queue-on-unreachable, `*_WRITER_ENABLED`
kill-switch. New env: `INVOICE_WRITER_ENABLED=False`, `INVOICE_WRITER_PROFILE=test`.

OCR upgrade (Track A, no SOFTECH risk): structured Gemini JSON (vs pipe-splitting), per-field confidence,
auto-match by `vendor_item_code` against `itemssuppliers`, batch/expiry normalization.

---

## 10. Test-instance / next-read checklist
- [x] Capture line VALUES of a real doccode-10 doc (§5) — done; discount lives in `pharmacydiscp`.
- [x] Determine where the native "Temporarily Save On-Screen Data" draft goes — **client-local, no server
      table** (proven via live save + full server search, §1). ⇒ no staging surface; our SupplierInvoice is the draft.
- [ ] On `SOFTECH_TEST_HOST`: a `push_final` writes `stktransm`/`stktrans` doccode 10 and appears in the
      native purchasing browse; capture exact NOT-NULL sentinels via the rollback probe first.
- [ ] On test: final insert → `stkbal.nowqty +`, `nowcostprice` recompute, `personnewbal` update (observe_finalization).
- [ ] Returns (doccode 120): `_out_supp` counter + `r_docnumber`/`r_doccode` link to original purchase.
- [x] `docnumber2` = supplier printed invoice no — confirmed on the native screen (1122830 / 8815737813 / 1124578).

## 11. Files
| File | Purpose |
|---|---|
| `apps/sync/management/commands/investigate_purchase_invoice.py` | census + counters + tr_stktransm5 body + schemas |
| `apps/sync/management/commands/investigate_purchase_invoice2.py` | golden template (header+lines) + supplier sub-types + variant hunt |
| `apps/sync/management/commands/investigate_purchase_draft.py` | searched for a saved draft in stktransm5 + counters (none) |
| `apps/sync/management/commands/investigate_purchase_draft2.py` | temp_* hunt + every-table-with-docnumber2 census (draft not in DB) |
| `apps/sync/management/commands/investigate_purchase_draft3.py` | scanned stktransm_prep/_q/_hq/9 + imports* (draft not in DB → client-local) |
| `docs/architecture/softech_purchase_invoice_investigation*.txt`, `…_draft_investigation*.txt` | raw probe output |
| **this file** | the spec |

> **Native screens captured (2026-06-28):** the `مشتريات من الموردين` purchase screen (header + line grid +
> the "Temporarily Save On-Screen Data" button) — confirmed every header/line field mapping in §4b/§5.
