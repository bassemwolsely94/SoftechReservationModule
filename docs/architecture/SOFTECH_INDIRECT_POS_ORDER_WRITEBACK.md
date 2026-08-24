# SOFTECH Indirect-POS Pending Sales-Order Writeback — Investigation & Spec

**Investigation date:** 2026-06-21
**Target:** SOFTECHDB9.dbo (Sybase ASE 12.5 — HQ server `192.168.1.8`, branchcode=100)
**Mode:** read-only probes (`apps/sync/management/commands/investigate_pos_cashier.py` + ad-hoc)
**Objective:** Reverse-engineer how the native ERP client creates a **pending sales order**
that is handed to a separate **Cashier** — so our platform can write the identical record
(matching the SOFTECH `م صرف` / dispense serial) and add our own data (referral doctor,
prescription image, sales channel) without ever touching the finalized `stktrans`/`stktransm`.

---

## 0. Two order pathways (clarified by the business owner)

1. **`piccrmorders` family** — **home-delivery sales channel ONLY** (the "SofTech Call Center
   Orders" screen; every row tagged `<<< From Call Center`). Fully mapped on the read side
   (see `docs/architecture/` notes + `apps/delivery/management/commands/sync_crm_orders.py`).
   Narrow path; not the primary target.

2. **In-Direct Point of Sale → Cashier** — available in **all branches**, **handles all order
   types** (cash `Ctrl+F2`, home-delivery `Ctrl+F3`, contract `Ctrl+F4`). "Indirect" = the
   seller builds the order and **sends it to a separate Cashier screen**; the seller is not the
   cashier (the *direct* POS is seller=cashier). **THIS is the pathway to mimic.**

---

## 1. The pending-order tables (CONFIRMED)

The indirect-POS pending order is stored in the **`5`-suffixed staging twins** of the final
sales tables (the `5` suffix is SOFTECH's convention for "pending/live", cf. `piccrmorders5`):

| Table | Role | Notes |
|---|---|---|
| **`stktransm5`** | pending sales-order **header** | 43-col twin of `stktransm`; one row per order |
| **`stktrans5`**  | pending sales-order **lines**  | 45-col twin of `stktrans`; one row per item |
| **`branchesales5`** | pending **payment** breakdown | twin of `branchesales`; one row per tender; linked by `(branchcode,doccode,docnumber)`. See §6e |

> ⚠️ These are NOT `stktransm`/`stktrans`. Writing here = a *pending* order awaiting the
> cashier, exactly per the constraint "only populate the pending sales order table."
> Related variants exist but are out of scope: `stktransm5_ext`, `stktransm5_ot`,
> `stktransm5_revise`, `stktransmcomm5` (comments), `stktransmclassif5`, `stktrans5_ot`.

### Key `stktransm5` columns (header)
`branchcode`, `doccode`, **`docnumber`** (= the `م صرف` dispense serial), `docdate`,
`storecode`, `docvalue`, `docvaluepay` (0 until cashier takes payment), `ptcode`,
**`ptclassifcode`** (sales channel: 90=delivery, 91=cash, 10=contract, 15=insurance…),
`phcode` (customer PIC), `usercode` (seller), **`cashiercode`** (the cashier hand-off),
**`refdoctorcode`** (referral doctor — native!), `fatstatuscode` (e-invoice status),
`patientpayment`, `comments`, `mitemsys`, `origdoc`, `docpaydue`, `cust_branch_code`,
`custdiscp`/`specialdiscp`/`origintaxp`.

### Key `stktrans5` columns (lines)
`branchcode`, `doccode`, `docnumber`, `docdate`, `storecode`, `itemcode`, `transqty`,
`transprice`, `transprice_total`, `itemsaleprice`, `itemsalestax`, `pharmacydiscp`,
`additionaldiscp`, `custdiscp`, `specialdiscp`, `bonusqty`, `usercode`, `trans_time`,
`personcode`, `itemexpirydate`, `item_partno`.

### Cross-check (proves docnumber = `م صرف` serial)
`stktransm5` row `branch=100 doccode=115 docnumber=6536 phcode=100HD5112 docvalue=140.0`
is the **same record** as the Call-Center-Orders screen row `100HD5112 | 6536 | 140.00`.
Its 7 lines are present in `stktrans5` for `(100,115,6536)`.

---

## 2. Doc types observed in `stktransm5` (live, branch 100)

| doccode | rows | docvaluepay | ptclassifcode | interpretation |
|---|---|---|---|---|
| **110** | 28 (no. 2→29) | `0` (unpaid) | NULL | **generic pending "out" order** (indirect-POS, awaiting cashier) |
| **115** | 15 (no. 2222→7203) | = docvalue (paid) | 90 (delivery) | customer **sale** (delivery / call-center) |

> doccode `115` = customer sale (matches `stktrans` convention). doccode `110` routes to the
> generic `lastdocnumberout` counter (see §3) and is unpaid — the strongest candidate for the
> indirect-POS pending order. **OPEN:** confirm the exact doccode + status the *Cashier* screen
> filters on (see §6).

---

## 3. Serial allocation — `lastdocnumbers` (CONFIRMED mechanism)

`lastdocnumbers` is the global document-number generator. Two rows matter:

```
branchcode  lastdocnumberin  lastdocnumberout  lastdocnumberout_cust  paymentsno  ver_branch
000         0                29                7709                   8102        0   ← counter row used by tr_stktransm5
100         18671            104787            6923                   7449        1   ← HQ identity row (ver_branch='1')
```

The **`tr_stktransm5` INSERT trigger** (readable, not encrypted) stamps `trans_time` then writes
the inserted `docnumber` back into the **`branchcode='000'`** counter row, into a column chosen
by doccode:

```
doccode '30'  -> lastdocnumberin_cust
doccode '115' -> lastdocnumberout_cust          (currently 7709)
doccode '10'  -> lastdocnumberin_supp
doccode '120' -> lastdocnumberout_supp
else  <99     -> lastdocnumberin
else  >=99    -> lastdocnumberout               (currently 29 ; doccode 110 lands here)
```

**Implication for allocation (CORRECTED — verified by the live rollback probe, see §6m):** the trigger
does NOT generate the number, AND you must **NOT pre-`UPDATE` the counter**. The native pattern is:
**read the current counter, INSERT with `current + 1`, and let `tr_stktransm5` bump the counter to that
value.**

```sql
BEGIN TRAN
  SELECT @cur = lastdocnumberout_cust FROM lastdocnumbers HOLDLOCK WHERE branchcode='000'  -- lock+read
  -- @no = @cur + 1   (computed in the client; do NOT write the counter yourself)
  INSERT INTO stktransm5 (... docnumber=@no ...)   -- tr_stktransm5 sets lastdocnumberout_cust=@no
  INSERT INTO stktrans5  (... docnumber=@no, one row per item ...)
COMMIT
```

> ⚠️ **Do NOT do `UPDATE lastdocnumbers SET lastdocnumberout_cust = lastdocnumberout_cust + 1` first.**
> Pre-setting the counter to the *same* value the INSERT trigger then writes makes the `stktransm5`
> header insert **silently not persist** (lines still insert; header vanishes). Proven on branch 130:
> header with `docnumber == pre-set counter` → 0 rows; header with `docnumber = current+1` (no pre-update)
> → lands, and the trigger bumps the counter correctly. `HOLDLOCK` on the read serializes against the live
> POS. `branchesales5` paymentsno works the same way — its (hidden) trigger bumps `lastdocnumbers.paymentsno`,
> so read current + 1 per tender.

> ⚠️ The connector's `commit/rollback` are currently **no-ops** (`config/sybase.py` treated
> Sybase as read-only). For this writeback we must issue real `BEGIN TRAN`/`COMMIT` or rely on
> the single atomic `UPDATE` for allocation. This is a connector change to design carefully.

---

## 4. No stored procedure — bare DML

Searching `syscomments` for procedures referencing `stktransm5` returns **only triggers**
(`tr_stktransm5`, plus unrelated `tr_dm_*`). There is **no creation stored procedure** — the ERP
client issues direct INSERTs. Our writeback mirrors that (replay the client's DML), consistent
with the established discount-writeback philosophy.

---

## 5. Referral-doctor subsystem (native — maps our "referral doctor" feature)

SOFTECH already has a full referral-doctor model; `stktransm5.refdoctorcode` links into it:
`refdoctors`, `refdoctors_m`, `refdoctors_deal`, `refdoctors_groups`, `refdoctorsschedule`,
`custrefdoctors`, `doctorsspecialty`, `picdoctors` (PIC↔doctor: `refdoctorcode`, `maindoctor`,
`doctorcomment`). Our platform can store richer doctor data in PostgreSQL **and** populate
`stktransm5.refdoctorcode` so the order carries the referral natively.

---

## 6. OPEN questions — status

1. ✅ **RESOLVED** (§6b). At a branch, an indirect-POS order awaiting the cashier is doccode **`115`**
   and is identified by simply **being present in `stktransm5`** (no paid flag; `docvaluepay` is
   pre-filled). It leaves `stktransm5` → final `stktransm` when the cashier completes payment.
2. ✅ **RESOLVED** (§6b). Each branch ASE has its OWN `lastdocnumbers` `branchcode='000'` counter
   row; branch 130's `lastdocnumberout_cust` = 468734. Writing to a branch uses `get_branch_connection()`
   and that branch's `'000'` row.
3. ⚠️ **PARTIAL** (§6b golden template captures all 43 header + 45 line column values of a real row).
   Final NOT-NULL/sentinel validation still needs a **test-instance trial insert** (see risk).
4. ✅ `docdate` = date-only (midnight); `trans_time` = real clock. Set both like the native client.
5. ✅ **RESOLVED** (§6c). `ptcode='10'` always; `ptclassifcode` = channel (91 cash / 90 delivery /
   10 contract / 15 insurance / 11 employee / 99 VIP / 30 permanent).

**Remaining true blocker:** the **computed-field behavior** (below) — validate on `SOFTECH_TEST_HOST`.

---

## 6b. BRANCH-confirmed facts (branch 130 / 192.168.30.12 — live cashier)

Probed branch 130's own ASE (`get_branch_connection('192.168.30.12')`) against the live Cashier
screen. This resolves most of §6:

- **Pending indirect-POS / call-center orders at a branch are ALL doccode `115`** (the branch
  `stktransm5` held 11 rows, all 115). The HQ-only doccode 110 is not the branch pending type.
- **"Awaiting cashier" = simply present in `stktransm5`.** It is NOT a paid flag — every row already
  has `docvaluepay == docvalue`. The order is **removed from `stktransm5` and written to the final
  `stktransm` when the cashier completes payment** (same lifecycle as `piccrmorders5`). The tendered
  payment method/breakdown is captured separately at finalization (the cashier payment grid).
- **Serial:** branch `lastdocnumbers` row `branchcode='000'` → `lastdocnumberout_cust` = 468734
  (just past the visible 468730). doccode 115 → `lastdocnumberout_cust`, as the trigger dictates.
- **Channel:** `ptcode='10'` + `ptclassifcode='90'` = delivery. (Still want a cash/contract sample
  to map `91`/`10`.)

### Golden template — real pending header (`stktransm5`, branch 130, docnumber 468730)
```
branchcode=130  doccode=115  docnumber=468730  docdate=<date-only>  storecode=130
supp_main_code=''  docnumber2=0  comments=NULL  docvalue=217.5  cust_branch_code=1500
origintaxp=0  custdiscp=0  specialdiscp=0  docvaluepay=217.5  fatstatuscode=30
ptcode=10  ptclassifcode=90  cust_branch_store=8  docvaluereturn=0  fatcurrentstatus=90
docwritedate=NULL  cust_professional=2  saleprice_extrap=0  usercode=2050  trans_time=<clock>
patientpayment=0  table_dumped=NULL  docvalue1=217.5  docvalue2=154.65  docvalue3=26.71
phcode=130HD16822  personnewbal=62  docvaluebc=217.5  bcrate=1.0  bcurrency=1
docvaluepaybc=217.5  cashiercode=2050  mitemsys=AR  origdoc=5  refdoctorcode=NULL
docpaydue=NULL  vf1=NULL  vf2='00002_1'
```
(`mitemsys`: 'AR' on this branch retail order vs 'CS' on the call-center one 468097 — likely
source/module marker. `usercode==cashiercode` here = seller is default cashier until reassigned.)

### Golden template — real pending line (`stktrans5`, docnumber 468730, line 1)
```
branchcode=130 doccode=115 docnumber=468730 docdate=<date> storecode=130 itemcode=89236
transqty=1 transprice=207.5 newqty=1 newcostprice=154.649 itemexpirydate=<date>
itemsaleprice=207.5 itemsalestax=25.4825 itemsaleprice_tax=182.0175 pharmacydiscp=0
additionaldiscp=14 transprice_total=207.5 origintaxp=0 custdiscp=0 specialdiscp=0
bonusqty=207.5 dblitemflag=1 r_docnumber=0 r_docdate=1900-01-01 saleprice_extrap=0
s_doccode='000' usercode=2050 personcode=1500 retqty=0 vf4=62
```

### 6c. Sales-channel mapping (CONFIRMED — `persontypesclassif` + live samples)

All customer sales use **`ptcode='10'`**; the channel is `ptclassifcode`:

| Channel | ptcode/ptclassif | Arabic | Payment posture (final stktransm) |
|---|---|---|---|
| **Cash** | 10 / **91** | عميل نقدى | `docvaluepay == docvalue` (paid in full); `docpaydue=NULL` |
| **Delivery** | 10 / **90** | عميل Delivery | `docvaluepay == docvalue` (COD collected); occasional `docvaluereturn` (in-order exchange) |
| **Contract / credit (آجل)** | 10 / **10** | تعاقدات / آجل | `docvaluepay = 0` or partial → balance posted to account; `phcode` mandatory |
| Contract (deferred + manual disc.) | 10 / 33 | تعاقد - سداد آجل - خصم يدوي | as contract |
| Health insurance | 10 / 15 | تأمين صحي | split: `patientpayment` (patient share) vs company |
| Company employees | 10 / 11 | موظفيين شركة الرزيقي | |
| Permanent customer | 10 / 30 | عميل دائم | seen on a live pending order (br130 #468258) |
| VIP | 10 / 99 | Vip | |

> The pending `stktransm5` row pre-fills `docvaluepay = docvalue` (expected total); the cashier
> records the actual tender/breakdown at finalization. For OUR write, set `ptclassifcode` per the
> chosen channel and mirror the native pending-row posture (validate cash-vs-contract `docvaluepay`
> behavior on the test instance — see risk below).

### 6d. Computed-field formulas (CONFIRMED — `items` row vs order line 468730)

The computed fields are deterministic functions of `items` × qty × discounts × customer specs.
Verified by comparing the branch-130 `items` rows for itemcodes 89236 & 2 against the order line:

| Field | Source / formula | Confirmed |
|---|---|---|
| `itemsaleprice`, `unitsaleprice` | **copy from `items`** (per-branch price) | 207.5 = 207.5 |
| `itemsaleprice_tax` | **copy from `items`** (pre-tax price) | 182.0175 = 182.0175 |
| tax rate | `items.itemsalestaxp` (e.g. 14) | ✓ |
| `transprice` / `transprice_total` | `itemsaleprice·qty − discounts` | 207.5 (no disc here) |
| `itemsalestax` (line) | `transprice_total − transprice_total/(1+taxp/100)` | 25.4825 |
| **header** `docvalue` = `docvalue1` | `Σ transprice_total` | 217.5 |
| **header** `docvalue2` | `Σ (newcostprice · qty)` = COGS | 154.65 |
| **header** `docvalue3` | `Σ itemsalestax` = total VAT | 26.71 |
| `bonusqty` | observed = `transprice_total` (points/eligible base — verify) | 207.5 |

**Line discount + price (CONFIRMED on contract order 451978):**
- `transprice = round(itemsaleprice × (1 − custdiscp/100), 2)` — verified: `315×(1−.06)=296.1`,
  `79×(1−.17)=65.57`.
- `transprice_total = transprice × transqty` — verified `296.1×2=592.2`.
- The **effective discount %** is recorded in the line's `custdiscp` (item discount columns
  `pharmacydiscp`/`additionaldiscp`/`specialdiscp`/`posdiscp` were 0 on that order; the net landed
  in `custdiscp`). **For our writeback `custdiscp` is an INPUT:** `0` for cash/delivery retail
  (as in order 468730), or the contract %.

**`newcostprice` — CONFIRMED source = `stkbal.nowcostprice`:**
- `stkbal` row `(branchcode=130, storecode=130, itemcode=89236).nowcostprice = 154.649` ==
  the order line `newcostprice`. So read `stkbal.nowcostprice` per (branchcode, storecode, itemcode)
  at insert time. (`stkbalexpiry` is batch-level and was empty for this item — store-level cost is
  authoritative for COGS. `stkbal` cols: `nowcostprice`, `opencostprice`, `rcostprice`, `nowqty`.)

**`personnewbal`** — customer loyalty **points** new balance (loyalty subsystem; the only field
still needing its own calc — defer/validate on test).

**Discount-tier source (for contract pricing):** retail customers are NOT in `personsdata`
(no row for `130HD16822`). `custdiscpclassif` classifies ITEMS (Med:Local 25%, Imported/Agent 15%…)
via `items.itemstoreclassif`; `custdiscounts(personcode, custdiscpcode, custdiscp)` is the
per-customer table — BUT the sampled contract customer (`03HD2624`) had NO `custdiscounts` rows yet
got 6%/17%, so contract % comes from contract terms (likely `companiesitems`/agreement/manual), not
a flat `custdiscounts` join. Treat the contract discount as a **policy input** our app supplies.

### ✅ Formula status: SPECIFIED for cash/delivery; contract-% is an input
The full line+header math is now deterministic given `(item, qty, custdiscp)` + `stkbal.nowcostprice`:
`transprice → transprice_total → itemsalestax → docvalue1/2/3`. Remaining for `SOFTECH_TEST_HOST`
validation only: (a) `personnewbal`/points calc, (b) whether the cashier/triggers recompute any of
`docvalue1/2/3`/`bonusqty`/`dblitemflag` (so we know which to populate vs leave blank), (c) exact
`bonusqty`/`dblitemflag`/`vf2` semantics.

---

## 6e. Payment subsystem — `branchesales5` (CONFIRMED via contract order 468740)

A pending order's cashier payment breakdown lives in **`branchesales5`** (pending twin of
**`branchesales`** = finalized). So a complete indirect-POS pending order is **THREE tables**:
`stktransm5` (header) + `stktrans5` (lines) + `branchesales5` (payment split). It is linked to the
order by **`(branchcode, doccode, docnumber)`** = `ref_docnumber`.

`branchesales5` columns: `branchcode, doccode, docnumber, docdate, paymentsno (int PK serial),
paymenttype, paymentvalue, ref_docnumber, localpayment_remain, localpayment_sno, usercode,
trans_time, personcode, cheqdate, creditcardtype, bcurrency, bcrate, paymentvaluebc, intervalcode`.

**One row per payment tender** (split payments = multiple rows). Confirmed paymenttype codes
(no lookup table — hardcoded):

| paymenttype | Arabic | meaning | extra cols |
|---|---|---|---|
| **30** | نقدى | **cash** (dominant — ~94% of tenders) | — |
| **10** | أجل | **credit / deferred** (contract balance) | — |
| **40** | فيزا / بطاقة | **card** (electronic) | `creditcardtype` = brand (1=card seen; no lookup table — hardcoded); `cheqdate` reused as card value-date |
| (50/cheque, wallet) | — | NOT observed in 30 days at br130 — if used, other hardcoded codes | `cheqdate` for cheques |

Enumerated from `branchesales` (final), 30-day window @ br130: only **10/30/40** occur.

Worked example — order **468740** (`docvalue=275.4`), split mixed payment:
```
branchesales5: paymentsno 497013  paymenttype 10 (credit)  paymentvalue 210.6
               paymentsno 497014  paymenttype 30 (cash)    paymentvalue  64.8   →  Σ = 275.4
stktransm5.docvaluepay = 64.8   (= the NON-credit portion; the 210.6 credit becomes customer debt)
```
(Order 468739 likewise: 304.2 credit + 93.6 cash = 397.8.)

### Serial allocation — TWO counters per order
Both come from the branch `lastdocnumbers` `branchcode='000'` row:
1. **`docnumber`** (the `م صرف` serial) — `lastdocnumberout_cust` for doccode 115 (per `tr_stktransm5`).
2. **`paymentsno`** — `lastdocnumbers.paymentsno`, incremented **once per payment line**
   (468740 used 497013 + 497014; branch counter was 497006 → advances per tender).

### `docvaluepay` / `patientpayment` rule (CONFIRMED)
`docvaluepay = Σ paymentvalue WHERE paymenttype != 10 (credit)` — i.e. cash/card collected NOW; the
credit (type 10) portion = `docvalue − docvaluepay` is the deferred balance posted to the customer
account. Verified: pure cash sale 468770 (docvalue 4000, docvaluepay 4000); contract 468740 (64.8 paid /
210.6 credit). **`patientpayment` is NOT the same as docvaluepay:** it is `0` for a pure cash sale, but
equals the cash down-payment on a credit/contract sale (468740: patientpayment=64.8). I.e. it's the
out-of-pocket portion on a credit sale, not the cash-sale total.

### Insurance (ptclassif=15) — handled separately, NOT in live POS
No `ptclassif=15` sales exist in current `stktransm` (HQ or branches, recent windows). Health insurance
is processed via the existing **`apps/insurance`** motalba/claims subsystem (company receivable), not a
regular 115 POS sale. If an insurance order is ever pushed through this writeback, the patient co-pay
would be `patientpayment` (a cash tender) and the company share a motalba claim — but this path is
**unconfirmed (no live sample)** and out of scope for the cash/delivery/contract writeback.

> **Phase-2 design note:** whether OUR writeback pre-fills `branchesales5` (we know the tender, e.g.
> COD cash or contract credit) or leaves payment for the cashier to enter is a design choice — but
> the cashier screen reads pending orders by joining `stktransm5` ⋈ `branchesales5`, filtered by the
> channel checkboxes (Cash / Home Delivery / Contract = `ptclassifcode` groups). If we want the order
> to appear "ready to settle" we likely populate `branchesales5`; if we want the cashier to choose
> the tender, we may leave it. **Validate on test.**

---

## 6f. The full "Save" process — a TRIGGER CHAIN, not a stored procedure (CONFIRMED)

Probe `investigate_save_process` (output: `docs/architecture/softech_save_process_investigation.txt`)
searched every stored proc and trigger touching the sale-commit tables. Result:

- **NO master stored procedure orchestrates Save.** Zero procs reference
  `stktransm5/stktrans5/branchesales5/picpoints/itempoints`. The ERP client commits via
  **client-side bare DML**; all side-effects come from a **trigger chain** (same philosophy as the
  discount writeback). The "documented process" is the trigger chain below.

| Table (event) | Trigger | Body readable? | What it does |
|---|---|---|---|
| `stktransm5` INSERT | `tr_stktransm5` | ✅ | stamps `trans_time`, bumps `lastdocnumbers` (per-doccode counter) |
| `stktrans5` INSERT | **none** | — | pending lines have NO trigger (no stock/points side-effects) |
| `branchesales5` INSERT | `tr_branchesales5_insert` | ❌ hidden | pending payment side-effects |
| `stktransm` INSERT (FINAL) | `tr_stktransm` | ❌ hidden | finalization: accounting / e-invoice / etc. |
| `stktrans` INSERT (FINAL) | `tr_stktrans` | ❌ hidden | finalization: **stock + points earning** |
| `branchesales` INSERT (FINAL) | `tr_branchesales_insert` | ❌ hidden | cash drawer / customer balance |
| `stkbal` UPDATE | `tr_stkbal_update` | ❌ hidden | stock-balance / weighted-avg cost recompute |
| `picpoints` INSERT | `tr_picpoints` | ✅ | maintains `localcustomerspoints` (totpoints/conpoints) + `r3stktransm.personnewbal` |
| `lastdocnumbers` UPDATE | `tr_lastdocnumbers` | ❌ hidden | counter replication |
| `stktransm_inv` INSERT | `tr_stktransm_inv` | ✅ | e-invoice (FAT) doc-number allocator → `lastdocnumbers_inv` |

> "Hidden" = `syscomments.text` is NULL (vendor-protected body — same method as `tr_items_update`).
> We cannot read the exact stock-deduction / points-earning / accounting math.

### Why this is GOOD news for our writeback
The **heavy logic (stock deduction, points earning, accounting, e-invoice) fires only on the FINAL
tables** (`stktransm`/`stktrans`/`branchesales`/`stkbal`), i.e. **when the cashier finalizes** — not
when a row is added to the pending `stktransm5`/`stktrans5`. The pending side is light:
`tr_stktransm5` only timestamps + counters; `stktrans5` has no trigger. **So our writeback (which
only creates the PENDING order) does NOT earn points, deduct stock, or post accounting — the
cashier's finalization does, via SOFTECH's own (hidden) triggers.** We only have to populate the
pending rows with correct displayed values (price/tax/cost/discount per §6d).

### Points — source of truth (OBSERVED on cash sale 468770)
> **CORRECTED 2026-08-19** (SOFTECH_POS_FIELD_GAPS.md + memory, verified via `verify_pos_points`):
> the award is **PER ITEM and NOT reproducible read-only** — same-`itemstoreclassif` items earn
> different %. The `value/10` below and any per-classification model each matched some sales only by
> coincidence. We compute no figure; SOFTECH awards at finalization. And **returns DO deduct points**
> — the "asymmetric" note below is wrong.
- **Formula:** `points = docvalue / 10` (1 point per 10 EGP). Verified: docvalue 4000 → **400 points**;
  pending header `personnewbal=400` (a preview), and at finalization a `picpoints` row `points=400`
  was written and `localcustomerspoints.totpoints` rose 4184→4584.
- **Eligibility is channel/enrollment-driven — NOT `items.itempointsys`.** The earning item had
  `itempointsys=0` yet earned 400 points (cash channel, ptclassif=91). The earlier contract sale
  (ptclassif=10) earned 0. So cash earns `value/10`; contract/credit does not. (Customer enrollment
  flag `localcustomers.picpoints=1` also relevant.) `itempointsys` likely only *excludes* specific
  items, it does not gate the default.
- **Ledger:** the `picpoints` row is keyed to the **final** invoice (`doccode=115, docnumber=452724`),
  written at finalization → `tr_picpoints` (readable) updates `localcustomerspoints(totpoints,conpoints)`.
  Balance = `Σtotpoints − Σconpoints`. Already wired in `apps/loyalty/pic_bridge.py`.
- **`personnewbal`** on the pending header = client preview of the points; the authoritative `picpoints`
  ledger row is written at finalization. **⇒ our pending writeback can leave points to finalization.**
- **⚠️ Returns do NOT reverse the points ledger (observed).** Settling a cash return (doc 21479,
  `personnewbal=−400`) stamped `−400` on the return `stktransm` header but wrote **NO `picpoints` row**
  and left `localcustomerspoints` unchanged — the customer **kept** the 400 points earned on the sale.
  So earning is asymmetric: sales write `picpoints` (+value/10); returns only record the negative on the
  doc. (Either a SOFTECH gap or a separate batch reconciliation we haven't found.) Irrelevant to our
  write path (we never touch points), but important to know when mirroring loyalty in our system.

---

## 6g. Indirect-POS replication blueprint (full read-only census)

Census probe: `investigate_indirect_pos_full` → `docs/architecture/softech_indirect_pos_full_census.txt`.
Goal: replicate the Indirect-POS *order-creation* in our extended system for all channels.

### Trigger map (the entire process)
**Readable (behavior fully known):**
- `tr_stktransm5` (INS) — stamps `trans_time`; re-stamps the per-doccode `lastdocnumbers` counter.
- `tr_picpoints` (INS) — maintains `localcustomerspoints` balance (earn/consume).
- `tr_stktransm_inv` (INS) — e-invoice (FAT) serial allocation → `lastdocnumbers_inv`.
- `tr_piccrmordersnos_ins` (INS) — home-delivery serial registry: `snoflag=1` → stamps
  `piccrmorders.docnumber5` (staging); `snoflag=0` → stamps `piccrmorders.docnumber` (final).
- `tr_piccrmorderstatus_ins` (INS) — propagates `orderstatus` to `piccrmorders5`/`piccrmorders`.
- `tr_acctrans3`, `tr_sacctrans3` — accounting serial counters in `lastdocnumbers`.

**HIDDEN (vendor-protected — `syscomments.text` NULL — bodies UNREADABLE):**
`tr_branchesales5_insert`, `tr_branchesales_insert`, `tr_stktransm`, `tr_stktrans`,
`tr_stkbal_update`, `tr_lastdocnumbers`, `tr_acctrans`.

**No triggers at all** on: `stktrans5`, `stktransmcomm5`, `stktransmclassif5`, `stktransm5_ext`,
`stktransm5_revise`, `branchesalescc5`, `piccrmitems`, `localcustomerspoints`, `lastdocnumbers_inv`.

### NO stored procedure creates a sale (confirmed)
All sale-named procs are reporting rollups (`sp_sales_*`, `sp_itemmonthlysale1`). Save = bare DML.

### The order-creation sequence we replicate (pending side — all bare DML, one transaction)
```
1. docnumber  = allocate from lastdocnumbers (branchcode='000'):
                 UPDATE ... SET lastdocnumberout_cust = lastdocnumberout_cust + 1  (doccode 115)
                 then read it back.   [tr_lastdocnumbers (hidden) handles replication only]
2. INSERT stktransm5  (header: branch, doccode=115, docnumber, channel ptclassifcode, phcode,
                       usercode, cashiercode, docvalue/docvaluepay/docvalue1/2/3, refdoctorcode …)
                       → tr_stktransm5 (readable) timestamps + re-stamps counter
3. INSERT stktrans5   (one row per item; computed price/tax/cost per §6d)   [no trigger]
4. (optional) INSERT stktransmcomm5 / stktransmclassif5  (commission / classification) [no trigger]
5. paymentsno = allocate from lastdocnumbers.paymentsno (per tender)
6. INSERT branchesales5 (one row per tender; paymenttype 30/10/40)
                       → tr_branchesales5_insert (HIDDEN — pending-payment side-effects unknown)
```
The **cashier finalization** (NOT us) later creates `stktransm`/`stktrans`/`branchesales` and updates
`stkbal`, firing the hidden triggers that do **stock deduction, points earning, accounting, e-invoice**.

### The ONE create-side unknown that needs a test instance
`tr_branchesales5_insert` is the only hidden trigger on the pending-create path. Its side-effects
(e.g. does inserting a credit tender immediately post to the customer's account balance, or only at
finalization?) cannot be read. Everything else on the create side is known. **Full-fidelity
replication of the payment side requires observing `tr_branchesales5_insert` on a test instance.**

### Hard limit of read-only investigation
The 7 hidden triggers (stock/accounting/finalization) cannot be reverse-engineered further without
either vendor documentation or a test instance to observe before/after state. For *our* scope
(creating pending orders + sending to the cashier) this is acceptable: those triggers fire on the
cashier's finalization, which SOFTECH owns — we only need the create-side sequence above.

---

## 6h. EMPIRICAL finalization deltas (observed live — order 468740 settled, branch 130)

Controlled experiment: a real pending contract order (`stktransm5` docnumber **468740**, PIC 130HD9668,
mixed pay 64.8 cash + 210.6 credit, items 107295 & 94965) was settled on the branch-130 cashier while we
snapshotted before/after (`observe_finalization`). Net effect of the cashier "settle" (= the hidden
finalization triggers + client DML):

| Area | Observed change |
|---|---|
| Pending tables | `stktransm5` / `stktrans5` / `branchesales5` for 468740 → **all DELETED** |
| **Final order** | NEW `stktransm` row **docnumber 452723** created (a DIFFERENT number — see counters) |
| Final lines | `stktrans` 452723: same items, `transprice`=net (91.8 / 183.6), `newcostprice`=`stkbal.nowcostprice` |
| Final payments | `branchesales` 452723: 2 rows (type10 210.6 + type30 64.8), **`ref_docnumber=468740`** (link to pending) |
| **Stock** | `stkbal.nowqty` −1 per item (2.667→1.667) — deduction happens at FINALIZATION |
| **Points** | none — both items `itempointsys=0` (not eligible); `personnewbal=0` |
| **E-invoice** | NO `stktransm_inv` row for this contract sale |
| Cashier | final `cashiercode=1509` (the real cashier) vs pending `usercode=2050` (seller) |

### ⭐ Two separate serial sequences (KEY)
`lastdocnumbers` has TWO rows per branch and they drive DIFFERENT stages:
- **`branchcode='000'` (ver_branch=0)** → **PENDING/staging** counters. `lastdocnumberout_cust`=468768
  (the "م صرف" order serial, e.g. 468740) and pending `branchesales5.paymentsno` (497045).
- **`branchcode=<own>` e.g. '130' (ver_branch=1)** → **FINAL** counters. `lastdocnumberout_cust`=452723
  (the final invoice number == the settled doc) and final `branchesales.paymentsno` (481831).

**⇒ The pending order serial (468740) is NOT the final invoice number (452723).** They are independent
sequences; the link between them is `branchesales.ref_docnumber` (= the pending docnumber) on the final
payment rows. (`tr_stktransm5` bumps the `'000'` counter for pending; the hidden `tr_stktransm`/
`tr_lastdocnumbers` bump the branch's own `ver_branch=1` counter at finalization.)

### Final header computed fields (from the settled row 452723)
`docvalue1`=324.0 = **gross (pre-discount list)**; `docvalue`=`docvalue`/net=275.4; `docvalue2`=243.213=COGS;
`docvalue3`=0 (these items tax-exempt; non-zero = VAT total otherwise). `docvaluepay`=`patientpayment`=64.8
(cash collected); 210.6 credit posted to account. `fatstatuscode`=50 / `fatcurrentstatus`=15 (e-invoice
state). `personnewbal`=points balance (0 here).

### What this means for OUR writeback (de-risked further)
We create ONLY the pending order using the **`'000'` (ver_branch=0) counters** — `stktransm5` + `stktrans5`
(+ optional `branchesales5`). **Everything at settlement — final-doc allocation from the branch's own
counter, stock deduction, points, accounting, e-invoice, and deleting the pending rows — is done by the
cashier (SOFTECH) and its hidden triggers. We never replicate that side.** A points-eligible-item sale
should be observed once (to capture the `picpoints`/`personnewbal` formula) but is not on our write path.

---

## 6i. RETURN / refund flow (observed — pending doccode 30, branch 130)

Refunding the settled invoice 452723 created a **pending return** in `stktransm5` that mirrors a sale
with three differences:

| Aspect | Sale (doccode 115) | Return / refund (doccode 30) |
|---|---|---|
| header `doccode` | 115 | **30** |
| pending serial source | `lastdocnumbers['000'].lastdocnumberout_cust` | **`['000'].lastdocnumberin_cust`** (=21630) |
| final serial source | `['<branch>'].lastdocnumberout_cust` | **`['<branch>'].lastdocnumberin_cust`** (21477→next) |
| line link to original | — | **`stktrans5.r_docnumber` = original invoice (452723)** |
| payment link to original | — | **`branchesales5.ref_docnumber` = original invoice (452723)** |

Otherwise identical: same `stktransm5`/`stktrans5`/`branchesales5` three-table shape, same
`docvalue/docvalue1/2/3`, same payment split (210.6 credit + 64.8 cash), positive `transqty`,
`usercode`=`cashiercode`=the operator doing the refund. (`tr_stktransm5` already showed doccode 30 →
`lastdocnumberin_cust`.) On settle, expect `stkbal.nowqty` to go **+1 per item** (stock returns) and a
final return doc from the branch's `_in_cust` counter — captured next via `observe_finalization`.

> Implication: replicating returns is the same writeback as sales, swapping doccode 115→30, the
> `_out_cust`→`_in_cust` counter, and setting `r_docnumber`/`ref_docnumber` to the original invoice.

### Return settlement — OBSERVED (refund 21630 settled)
Settling the refund produced the mirror of a sale settlement:
- Pending return (`stktransm5`/`stktrans5`/`branchesales5` 21630) → **deleted**.
- **Final return doc**: doccode 30, docnumber **21478** ← `lastdocnumbers['130'].lastdocnumberin_cust`
  (21477→21478, exactly as predicted). Lines `r_docnumber=452723`; payments `ref_docnumber=452723`
  (210.6 credit + 64.8 cash), final `paymentsno` from the branch's `ver_branch=1` counter.
- **Stock returned**: `stkbal.nowqty` +1 per item → back to 2.667 (sale −1 and refund +1 net to zero).
- Test fully reversed; customer balance net zero. **Full create→settle→refund→settle lifecycle validated.**

---

## 6k. DELETE / cancel a pending order (admin cashier "Delete" — OBSERVED)

Deleting pending order 468769 from the cashier admin screen produced:
- `stktransm5` / `stktrans5` / `branchesales5` for that docnumber → **all removed**.
- **No** final `stktransm` row, **no** `picpoints`, **no** physical `stkbal.nowqty` change, **no**
  `lastdocnumbers` counter change (the serial is **abandoned as a gap**, not rolled back).
- `stkbal.nowqtyout` (a reserved/committed counter, NOT physical stock) dropped 1.0→0.0 — likely the
  pending reservation releasing, but branch 130 is live so partly concurrent-activity noise; physical
  `nowqty` was untouched.
- Static: **no DELETE trigger** on any of the three pending tables; no deletion proc; `stktransm5_backup`
  is a dormant 2020-era archive (NOT a live delete log).

**⇒ Delete = a plain `DELETE FROM {stktransm5,stktrans5,branchesales5} WHERE branchcode=? AND doccode=?
AND docnumber=?`** — side-effect-free. **Our system uses this for (a) cleaning up trial pending orders,
and (b) error recovery when a push half-fails.** Safe to issue directly (mimics the native Delete).
Open (validate on test): whether a clean create should also set `stkbal.nowqtyout` (reserve) and Delete
release it — physical `nowqty` is unaffected either way, so this is a display/reservation nicety, not a
stock-integrity risk.

---

## 6m. LIVE ROLLBACK PROBE — write path validated on production (zero residue)

Executed `pos_probe --clone 468771` on branch 130: the real serial allocation + `stktransm5` +
`stktrans5`×2 + `branchesales5`×2 INSERTs + verify-readback, inside a transaction that was **rolled
back**. Result `ok=True`: header landed (docnumber 468813, docvalue 275.4, docvaluepay 64.8, ptclassif
10), 2 lines, 2 payments (paymentsno 497104/497105), `trans_time` stamped by `tr_stktransm5`. Then full
ROLLBACK; verified our row is gone (the 468813 that exists is an unrelated live cash order — `vf2='00002_1'`,
value 279.5 — the live POS grabbed the serial ~2s after our probe released it).

Confirmed by the probe:
1. **The full 3-table pending write is schema-valid against production.**
2. **Native serial allocation = read current + insert `current+1`; the INSERT triggers bump the counters.**
   Do NOT pre-`UPDATE` the counter (breaks the header insert — see §3 correction).
3. **`tr_branchesales5_insert` (hidden) bumps `lastdocnumbers.paymentsno`** — confirmed empirically.
4. **Connector quirks (now handled in `apps/pos_orders/writer.py`):** parameterized INSERTs silently
   don't land on this ASE → use inline literals; one statement per cursor (a left-open ResultSet breaks
   later DML); real `begin/commit/rollback` work and rollback fully undoes counter bumps + inserts.
5. **Branch 130 is NOT off-peak** (a real sale ~every 2s; live POS reused our released serial). The COMMIT
   path must run off-peak; `HOLDLOCK` on the counter read serializes allocation.

The probe (`pos_probe`) is the validated, zero-residue rehearsal for the commit path.

---

## 7. Proposed writeback design (Phase 2 — after §6 confirmed)

- **PG model `SoftechSalesOrder`** (new, in `apps/callcenter` or a new `apps/pos_orders`):
  mirrors what we pushed — `branchcode`, `doccode`, allocated `docnumber` (the `م صرف` serial),
  `phcode`, channel, seller, cashier, `docvalue`, status, **plus our extras**: referral doctor
  (FK + softech `refdoctorcode`), prescription image (reuse `CallLog.prescription_image` /
  `CallLogAttachment`), source channel, link to `CallLog`/`CallItem`/`Customer`. Immutable
  audit of the exact DML executed + before/after counter values.
- **Writer service** (mirror `apps/discount_approvals/replication.py` style): atomic serial
  allocation + `stktransm5`/`stktrans5` insert in one transaction; verify-readback; structured
  error capture. **Test instance first** once `SOFTECH_TEST_HOST` is configured.
- **Connector change:** real transaction support (`BEGIN TRAN`/`COMMIT`/`ROLLBACK`) for the
  write path only; reads stay unaffected.

---

## 8. Files

| File | Purpose |
|---|---|
| `apps/sync/management/commands/investigate_indirect_pos_full.py` | Full trigger/proc census of the whole subsystem (→ `softech_indirect_pos_full_census.txt`) |
| `apps/sync/management/commands/investigate_save_process.py` | Sale-commit trigger-chain dump (→ `softech_save_process_investigation.txt`) |
| `apps/sync/management/commands/observe_finalization.py` | READ-ONLY before/after snapshot+diff of a cashier settlement (empirically infers the 7 hidden triggers' net effects) |
| `apps/sync/management/commands/investigate_pos_cashier.py` | Read-only table/column/trigger discovery (this report's source) |
| `apps/sync/management/commands/investigate_crm_orders.py` | Read-only piccrmorders (home-delivery path) probe |
| `docs/architecture/softech_pos_cashier_investigation.txt` | Raw probe output (schemas, candidates, trigger text) |
| **`docs/architecture/SOFTECH_INDIRECT_POS_ORDER_WRITEBACK.md`** | **This report** |
