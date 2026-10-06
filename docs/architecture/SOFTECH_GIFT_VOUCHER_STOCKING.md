# SOFTECH Gift-Coupon Stocking — Current (RPA) Behaviour & Replication Spec

**Status:** BEHAVIOUR CONFIRMED (2026-10-06) by the read-only probe
`python manage.py investigate_gift_vouchers` (raw output: `softech_gift_vouchers_investigation.txt`,
full line archive `softech_gift_vouchers_lines.csv`: 15,463 lines / 107 docs). Two details remain:
the 102230 line/header values (§4) and the meaning of doccode 170.

## 1. The two items — one paper coupon, two SOFTECH legs
Both items live in family 9955, `itemmedicine=60` (هدايا عملاء), `itemexpiry=1` (expiry mandatory),
`itempartno=1` (lot/serial field enabled) and `suppcode=1268`.

| | **102230** | **118639** |
|---|---|---|
| Name | COUPON FOR POINTS كوبون هدية على مشتروات العملاء بقيمة 50 جنيه | COUPON SERVED TO CUSTOMER إستحقاق كوبون |
| Role | The coupon **issued against loyalty points** (`itempointsys=1`) | The coupon **redeemed on a sale**: a −50 EGP line on the customer invoice |
| Price | cost 400 / sale 400 (the points price), `posdiscp=100` | cost 0 / sale **−50**, `pharmacydiscp=100`, `itemnosaleclassif=10` |
| Note | `itemnomoreuse=1` (flagged discontinued, yet still stocked; our validator would block it, see §6) | comment: «يجب ارفاق سيريال الكوبون و الصرف من الكول سنتر» |
| Main movements | doccode **170** (45,404 lines, HQ), 125/25 transfers | doccode **115** customer sale (30,520 lines), **125→25** HQ→branch transfers (8.4k), returns 30/80/180/181 |

**Every printed serial is purchased ONCE ON EACH ITEM.** Life of serial `27101-ZWU704` (traced):
```
2026-07-15  doccode 10   100/63944  item 102230  +1  serial 27101-ZWU704  exp 2029-08-23  (purchase, supplier 1268)
2026-07-15  doccode 10   100/63945  item 118639  +1  serial 27101-ZWU704  exp 2029-08-23  (purchase, supplier 1268)
2026-09-19  doccode 170  100/107802 item 102230  -1  (issued against the customer's points at HQ / call center)
2026-09-19  doccode 125  100/107799 item 118639  -1  → branch 170   (transfer out of HQ)
2026-09-23  doccode 25   170/32619  item 118639  +1  ← from 100     (received at branch 170)
2026-09-23  doccode 115  170/414525 item 118639  -1  customer 1500  (redeemed on a sale at −50 EGP)
```

## 2. Purchase document shape (confirmed from history)
- Supplier **1268** (ptcode 20, ptclassif 10, credit days 1000, `personmaxbal` 20,000,000; `personcredit`
  12,538,820 ≈ sum of all coupon purchase values). Branch/store **100** (HQ), usercode **1509** (BASSEM).
- **One document per item per batch of 200 serials.** A batch = 2 docs (102230 = 200 × 400 = **80,000**;
  118639 = 200 × 0 = **0**). Several batches are often posted the same day (2026-07-15: docs
  63936–63945 = 5 batches = serials 26301–27300).
- `docnumber2` = date-coded **ddmmyyyy[NN]** (e.g. `15072026`, `2703202602`) and is NOT unique per doc
  (several docs share it). ⇒ the writer's SofTech dup-guard (supplier + doccode + docnumber2) would
  wrongly match a same-day sibling. **Coupon docs need a unique docnumber2** (ddmmyyyy + 2-digit sequence,
  already the house pattern) or a different idempotency key.
- Header of 118639 doc 63943: `fatstatuscode=30`, `fatcurrentstatus=90`, `docvalue=0`,
  **`docvalue1=-10000`** (= 200 × −50 sale value), `cashiercode=1509`, `docvaluebc=0`. These differ from the
  generic purchase capture (10/15, docvalue1=0, no cashiercode). It is not yet known whether the native
  save sets them or a later "close" step does → compare with the 102230 header (§4).

### Line (118639, doc 63943, real row)
```
itemcode=118639 transqty=1 transprice=0 newqty=<running stkbal> newcostprice=0 (trigger)
itemexpirydate=<unique per line>  item_partno=<SERIAL e.g. 26901-LBS116>
itemsaleprice=-50 itemsaleprice_tax=-50 itemsalestax=0 pharmacydiscp=100 additionaldiscp=0
transprice_total=0 origintaxp=0 custdiscp=1.0 specialdiscp=0 bonusqty=-50 dblitemflag=<1..200>
storecode2='0' retqty=0 promtype=1 suppliercode=personcode=1268 usercode=1509
```

## 3. The serial and the expiry
- **Serial = `stktrans.item_partno`** (confirmed). It also lands in `stkbalexpiry.batchno` (e.g. 102230
  row `25300-TOV143`). Format `NNNNN-AAA999`: a running number plus 3 random letters and 3 random digits.
- **Expiry is a per-line uniqueness key, not a real expiry.** The RPA assigns consecutive dates (one day
  per serial) from an 800-date pool (2028-01-01 → 2030-03-10) and **reuses the pool cyclically**. SOFTECH
  keeps on-hand per `(item, store, expiry)`. When a reused date meets stock still held under the same
  date, the two serials **merge into one stkbalexpiry row** and the serial identity is lost. Evidence: 102230
  store 100 has `2030-03-10 / 25300-TOV143 / qty 3` and three `-1` rows at other dates.
  ⇒ **The new generator must pick dates that are unused by any stkbalexpiry row for the item,
  and ideally never used before.**

## 4. Still to confirm
- [x] 102230 doc (63944): standard purchase header (`fatstatuscode=10`, `fatcurrentstatus=15`,
      `docvalue=docvaluebc=80000`, `docvalue1=0`, `cashiercode=1509`); lines `transprice=itemsaleprice=400`,
      `pharmacydiscp=0`, `custdiscp=1`, `bonusqty=0`, `item_partno=<serial>`, `newcostprice` 400 (trigger).
      118639 doc (63945) differs: header `30/90`, `docvalue1=-10000`, lines `bonusqty=-50`. Whether the
      native client or a trigger sets these is settled by the rollback clone diff (§6 step 3).
      Both docs also have a `temp_r_stk` on-screen cache row (the writer skips it, as proven for purchases).
- [x] Document types (SOFTECH `transdoc`, probe `--doctypes`, 2026-10-06) — the full coupon lifecycle:
      | doccode | `transdoc.docdescr` | Coupon step (real sample) |
      |---|---|---|
      | 10  | شراء من مورد | stocking (this module) |
      | **170** | **صرف أصناف مصروفات** (issue items as expenses) | **102230 issued to a customer against points** at HQ by the call center (usercode 64): header `phcode`=customer code (`05HD759`), `docvalue`=`patientpayment`=400, `personnewbal`=−400; line `item_partno`=serial (`27286-MFW296`) |
      | 125 | صرف - تبادل بين الفروع | 118639 transferred HQ → branch (`cust_branch_code`=140), serial on the line |
      | 25  | إستلام - تبادل بين الفروع | 118639 received at the branch (`docnumber2`=the 125 docnumber) |
      | 115 | مبيعات لعميل | 118639 redeemed on a customer sale at −50 EGP (`27288-ZXO674`, branch 170) |
      ⇒ every step carries the serial in `item_partno`, so the archive can track each coupon
      stocked → issued (to which customer) → sent to branch → redeemed.
- [ ] Whether the native save sends `item_partno` (yes: it is stored) plus any extra columns when a
      serial is typed. This will be proven by the rollback clone (§5 step 3), not by a new capture.

## 5. Current state & manual-archive issues
- **Out of stock:** HQ stkbal is 0 for both items; branches hold a few 118639 (150: 69, 160: 3,
  170: 2; **130: −309** = sold without stock).
- `Coupon_Printing.xlsx › Serial Database` (17001–27300) has **97 duplicate serial numbers** (22504–22600)
  and **100 reused random codes** (17101–17200 = 17201–17300). SOFTECH history has 7,812 distinct
  `item_partno` values, including test values like `20000-ABCFED`/`20002-ABCDEF`.
- **Archive load (2026-10-06, owner's machine):** 15,463 SOFTECH lines → **7,802 serials** (69 lines
  skipped: test values like `20000-ABCFED`, item code typed as serial, bare numbers `24315`–`24319`).
  The Excel `Serial Database` (6,400) matched 4,400 and added **2,000 Excel-only serials = exactly
  17001–19000**. These were printed but never stocked one-line-per-serial; most likely they fall in the
  2021–early-2022 era when coupons were bought as bulk qty (1000/500/200) with no serial. Conflict flags:
  number reused 1,004 (+200 from Excel), code reused 608, leg expiries one day apart 247 (an RPA run from
  serial 22741 typed the 118639 dates one day behind). **No serial was ever bought twice on the same item.**
- Batch #1 generated: 27301–27500, expiry 2030-03-11 → 2030-09-26 (6 live stkbalexpiry dates avoided).
- Next free serial after batch #1: **27501**. Last counter `lastdocnumberin_supp` (branch 100) = 65624.

## 6. Replication design
**Steps 1–2 BUILT (2026-10-06)** — no SOFTECH writes:
- Models `vouchers.CouponBatch` / `vouchers.CouponSerial` (migration vouchers/0005), logic in
  `apps/vouchers/coupons.py`, tests `apps/tests/test_coupon_archive.py`.
- `import_coupon_archive --csv softech_gift_vouchers_lines.csv --excel Coupon_Printing.xlsx`
  (or `--softech` to read the lines live, SELECT only). Idempotent; conflicts go to `conflict_note`.
- `generate_coupon_batch [--size 200] --out DIR`: next serials, unique codes, expiry dates that move
  forward from the latest ever used (no cycling), skipping every SOFTECH stkbalexpiry date of both
  items (read live). Writes `coupon_batch_<id>_print.xlsx` (4-up, collated) and
  `coupon_batch_<id>_dataload.tsv` (the RPA grid, as an interim fallback).
- `export_coupon_batch <id> --out DIR` re-exports a batch.
- Settings: `COUPON_POINTS_ITEM`, `COUPON_SERVED_ITEM`, `COUPON_SUPPLIER`, `COUPON_BRANCH`,
  `COUPON_BATCH_SIZE`, `COUPON_MIN_EXPIRY_DAYS`, `COUPON_PRINT_TITLE`.

**Step 3 (SOFTECH push) — BUILT (2026-10-06, approved by the owner), writer gate still OFF:**
- `apps/vouchers/coupon_push.py` + `push_coupon_batch BATCH_ID [--probe | --commit]`, tests
  `apps/tests/test_coupon_push.py`. Migration vouchers/0006 links a batch to its two SupplierInvoices.
- `ensure_invoices`: one SupplierInvoice per leg (vendor 1268, branch 100, status confirmed), one line per
  serial (qty 1, `batch_number`=serial, expiry, points 400/400, served −50/0).
- `assign_docnumber2`: each document gets its own `ddmmyyyyNN` supplier invoice no, above every number used
  that day in SOFTECH (read) and in our unpushed invoices; stored once, never renumbered → the writer's
  dup-guard (supplier+doccode+docnumber2) blocks any repeat post.
- Native extras (from reference docs): points line `custdiscp=1`; served line `custdiscp=1`,
  `bonusqty=−50`, `pharmacydiscp=100`; served header `fatstatuscode=30`, `fatcurrentstatus=90`,
  `docvalue1=−50×n`; both headers `cashiercode`=usercode. Usercode `COUPON_USERCODE` (default 1509).
- **First `--probe` on HQ (batch #1, 2026-10-06): both 200-line docs inserted (ok, 200/200, serials in
  order) and rolled back; every line column matched 63944/63945; only header diff was `cashiercode`
  (NULL vs 1509) — the native save sends it, now added.**
- `--probe`: inserts both full documents on HQ, reads them back, ALWAYS rolls back, and diffs header + line 1
  against 63944/63945 (ignoring identity, dates, serial, expiry, running newqty). Run off-peak.
- `--commit` (needs `INVOICE_WRITER_ENABLED=True`): points leg first; served is not pushed if points fails;
  a re-run resumes the missing leg and never re-posts a finalized one. Serials → `stocked` with doc numbers.
- Writer changes (apps/invoices/writer.py): purchase lines send `item_partno` when the line has a
  batch/serial; `push_final`/`probe_invoice` accept `usercode`, `header_extra`, `line_extra`; the probe now
  captures the inserted rows before rollback (`full_header`/`full_lines`) — this also restores
  `clone_purchase`'s column diff.
- Validation exceptions (apps/invoices/validations.py): `INVOICE_ALLOW_DISCONTINUED_ITEMS` (default 102230)
  and `INVOICE_ZERO_COST_ITEMS` (default 118639); every other item keeps the full rule set.
- Optional settings (code defaults, not in settings.py): `COUPON_USERCODE`, `COUPON_POINTS_PRICE`,
  `COUPON_SERVED_PRICE`, `COUPON_REF_POINTS_DOC`, `COUPON_REF_SERVED_DOC`.

Original step-3 notes:
1. **Archive** (`apps/vouchers`): `CouponSerial` (serial unique, number, code, item legs, expiry,
   purchase doc per leg, status, source), plus `CouponBatch` (200 serials, its two SupplierInvoices).
   Seeded from the SOFTECH lines CSV (authoritative) and reconciled with the Excel `Serial Database`;
   conflicts are flagged, not dropped.
2. **Generator:** next serials from the archive (27301…), random `AAA999` codes unique against the archive,
   and per-line expiry dates unused by any stkbalexpiry row / archive entry for the item. Print sheet
   (4 per page, collated) exported from the batch.
3. **Push:** one batch = two `SupplierInvoice`s (vendor 1268, branch 100, 200 lines each, qty 1)
   through the existing `apps/invoices/writer.py`. Required writer changes:
   - carry `item_partno` (serial) on purchase lines;
   - coupon line template exactly as §2 (price fields, `custdiscp`, `bonusqty`);
   - unique `docnumber2` per doc; idempotency = PG batch status + docnumber2 guard;
   - a scoped validator allowance for `itemnomoreuse=1` on 102230 (it is stocked deliberately);
   - verify-readback of 200 lines; **rollback clone of doc 63943/63944 first, then diff every column**
     (existing `clone_purchase` pattern); then ONE real batch, gated by `INVOICE_WRITER_ENABLED`.
