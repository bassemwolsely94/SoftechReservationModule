# 40 — SOFTECH Delta Sync (PERF-6): read only the rows that changed

**Status:** ✅ DESIGN APPROVED by the owner (2026-11-19). Not built: each table's build is a
separate step that the owner confirms first. Evidence gates G1–G4 (§10) are still open.
No production code, no migration and no SOFTECH write is part of this document.
**Builds on:** doc 30 *SOFTECH Load Reduction*, Phase 2 (steps 2.0–2.3). This document is the
detailed plan for that phase.
**Audit item:** `docs/full-project-audit/07_PERFORMANCE_AUDIT.md` PERF-6 · roadmap Wave 3.

---

## Summary for the owner

**Today:** every 5 minutes we copy the whole stock table from SOFTECH (about 32,000 rows), even
though only a few dozen rows changed. Every hour we also copy all 199,000 customers, their
220,000 phone numbers, all 52,000 items and all barcodes again. In the last 7 days that was
**about 55 million rows out of 69 million (80 %)** read from SOFTECH. It makes SOFTECH slower
for the cashiers and makes our own sync slower.

**The change:** remember, for each table, "how far we have read" (a *watermark*). On each run,
ask SOFTECH only for rows that changed after that point. Once every night we still copy the
whole table, so a missed row is corrected within a day.

**Safety:**
- Every table has its own switch: **OFF** (today's behaviour) → **SHADOW** (still reads
  everything, but also runs the new small read and checks that it would have missed nothing)
  → **ON**. The default is OFF.
- A table is switched ON only after a full week of SHADOW with **zero missed rows**, and
  after you sign off on that report.
- Turning a switch back to OFF restores today's behaviour on the next run. No data has to be
  repaired.
- We still only *read* from SOFTECH. No index or column is added to SOFTECH.

**Expected result:** about **95 % fewer rows** read for stock, customers, items and barcodes.
That is roughly 50 million fewer rows a week. Stock stays as fresh as today (every 5 minutes).
Customers and items can become *fresher* (every 15 minutes instead of every hour), because each
run becomes cheap. Sales gain little in load, but we stop rewriting two days of sales lines in
our own database every 5 minutes.

**What we need from you:** approve this design. Later, approve each table's switch to ON when
its shadow report is clean. Section 9 lists every point where the work stops and asks.

---

## 1. Measured load today

`SoftechLoadStat`, last 7 days (90 active hours), read on 2026-11-19 from the owner's PC:
**68.8 M rows, 234 k queries, 29 k logins, 20.8 h of SOFTECH query time.**

| # | Caller (sync step) | Rows / 7 d | Share | Per run | Query time | Cadence |
|---|---|---:|---:|---:|---:|---|
| 1 | `sync_stock` (stkbal) | **25.96 M** | 38 % | ≈ 32 k | 22,833 s | 5 min |
| 2 | `sync_customers` (localcustomers + personphones + personsdata) | **19.05 M** | 28 % | ≈ 390 k | 7,022 s | 60 min |
| 3 | `sync_items` (items + lookups + itemssuppliers + itemsai + personsdata) | **6.64 M** | 10 % | ≈ 133 k | 6,618 s (max 26 s) | 60 min |
| 4 | `sync_item_barcodes` (itembarcode ⋈ items) | **3.34 M** | 5 % | ≈ 67 k | 638 s | 60 min |
| 5 | `sync_sales` (stktrans ⋈ stktransm, 115/30, two days) | 1.92 M | 3 % | ≈ 2.4 k | 2,254 s | 5 min |
| 6 | `sync_in_transit._fetch_items` (stktrans 125/25 lines) | 0.85 M | 1 % | — | **8,157 s, 79,599 queries** | 15 min |
| 7 | `sync_item_suppliers` (itemssuppliers, all rows) | 0.86 M | 1 % | ≈ 216 k | 103 s | daily |

Items 1–4 are 80 % of all rows. Item 6 is small in rows but is the largest query *count*
(one query per open transfer document).

Not in this design (other callers, not table syncs): `eta_recon._softech_rows` (5.4 M),
`customers.status_drift` (0.8 M), `customers.duplicates` (0.6 M), the finance month scans
(doc 30 F9) and the purchasing engine's own sales pull (doc 30 F8). They are listed in §11.

## 2. Evidence: what SOFTECH offers to detect a change

Sources: the `probe_softech_change_columns` run on 2026-11-11 (`scratch/softech_change_columns_probe.txt`
on the owner's PC) and a small read-only probe for this design on 2026-11-19 06:05
(aggregates only, `SET ROWCOUNT`, `SOFTECH_READ_ONLY=True`). Raw output: Appendix A.

| Table | Change column(s) | Indexed? | Behaviour seen |
|---|---|---|---|
| `stkbal` (340 k rows, 32 k with qty > 0) | `modif_lastupdate` (5 NULL of 340 k) | **No** (only `ivm_time`, which is always NULL) | Stamped in **batches** at HQ: every 5–20 min one time per batch, all at second `:50` (06:00:50, 05:50:50, 05:30:50 …). That looks like the time a branch's batch **arrives** at HQ, not the branch's clock. About 2.6 k rows change a day. |
| `stktrans` | `trans_time` (branch clock), `table_dumped` | `trans_time` **no**; `table_dumped` only inside a personcode index | `table_dumped` is **NULL on every row** at HQ (today and yesterday), so it cannot be used. `docdate` is date-only. |
| `stktransm` | `trans_time`, `table_dumped`, `docwritedate` | **`(branchcode, doccode, trans_time)`** and **`(branchcode, doccode, docnumber, docdate)`** | `docwritedate` is NULL. `table_dumped` = `trans_time`. **`docnumber` is a sequence per (branch, doccode)**: today's first number = yesterday's last + 1 on every branch and doc type that had documents today (130/115, 160/115, 160/30, 170/115 …). |
| `items` (51.9 k) | `itemlastupdate` (0 NULL) | No (cheap scan) | 51 changed in 24 h, 183 in 7 days. **Not yet proven** that a price or cost change always bumps it: the 11-11 probe found no price change to test. |
| `itembarcode` (85 k) | `modif_lastupdate`, `deltrans_time` | No | Not measured (the query timed out, see Appendix A note). |
| `localcustomers` (199 k) | `trans_time` (0 NULL), `table_dumped` (6.6 % NULL), `custdate` | **`table_dumped` yes** | Both move daily (40 / 46 rows in 24 h). Which one moves when a *field* changes (status, lock, points, name) is **not yet proven** (probe section [6b]). |
| `personphones` (220 k) | `modif_lastupdate`, `table_dumped` | No | Not measured. |
| `itemssuppliers` (44 k main), `itemsai`, `users` | `modif_lastupdate` | No | Not measured. |
| `personsdata` | none useful | — | Only 1,797 rows: always read in full. |

**Two warnings from the evidence:**

1. **HQ stock lags the branches, under both methods.** On 2026-11-19, branch 170's last
   `stkbal` batch at HQ was 00:25:50, but HQ already had its sale lines up to 00:30:14. HQ
   receives that branch's stock change only when the branch sends its next batch. A delta read
   is exactly as current as today's full read, because both read HQ. Neither is "more stale".
2. **The 11-11 probe showed "moved but not bumped" rows** (7 of 19 bumped). The samples are
   movements made minutes *after* the branch's last batch (moved 00:17:27, batch 00:16:09).
   That fits warning 1, not a missing bump, but it is not proven. The fair test is section [3]
   of the improved probe (read the same rows twice, 15 min apart: did every quantity change
   come with a newer `modif_lastupdate`?). It has not been run in working hours yet. It is
   gate **G1** below, and SHADOW mode (§6) proves the same thing on live traffic.

## 3. Common design (all tables)

### 3.1 Watermark on our side
One new PostgreSQL table in `apps/sync` (**stop-and-ask S1**, schema change that affects the sync):

| Field | Meaning |
|---|---|
| `stream` | e.g. `stkbal`, `localcustomers`, `stktransm:160:115` (one row per branch/doccode for sales) |
| `value_ts` / `value_num` | the watermark: a SOFTECH-side time **taken from the rows' own column**, or a doc number. Never our clock, so clock drift between the PCs and SOFTECH cannot cause a gap |
| `mode` | `off` / `shadow` / `on` (copied from the switch, for the report) |
| `last_delta_at`, `last_full_at`, `last_full_ok` | when the last delta and last full run finished |
| `rows_last_delta`, `misses_last_shadow` | for the `/sync` panel and the shadow report |

Rules:
- The watermark advances **in the same PostgreSQL transaction** as the rows it covers. A crash
  in the middle leaves the old watermark, and the next run reads the same rows again. All
  writes are already idempotent upserts, so reading twice is harmless.
- Each read uses **watermark minus an overlap** (10 min for stamp columns) and `>=`. A batch
  stamped at the same second as the watermark, or a row committed a moment late, is read
  again rather than missed.
- If there is no watermark (first run, after OFF→ON, or after a failed full run), the run is a
  **full** run. A delta never starts from nothing.
- The watermark only ever moves forward. If SOFTECH returns a smaller maximum than the stored
  watermark (clock reset, sequence reset), the run is treated as a full run and an alert is
  logged. **Stop-and-ask S6.**

### 3.2 Switches
One setting per table in `config/settings.py` (read-side, so not in `config/writers.py`),
each `off | shadow | on`, **default `off`**:

`SYNC_DELTA_STOCK`, `SYNC_DELTA_CUSTOMERS`, `SYNC_DELTA_ITEMS`, `SYNC_DELTA_BARCODES`,
`SYNC_DELTA_SALES`.

- `off` — today's code path, unchanged. It stays in the code permanently as the fallback.
- `shadow` — today's full read is still what writes to our database. The delta query also
  runs, and its result is compared with what actually changed (§6). Nothing it reads is
  written. Cost: one extra small read per run.
- `on` — the delta read writes. A full read runs on the nightly schedule (§3.3).

`run_full_sync` (the manual "full" button and the initial backfill) always reads in full, in
every mode.

### 3.3 Safety nets
- **Nightly full refresh** (per table, about 03:00–04:00, before the 06:00 morning chain):
  today's full step function, run once instead of 288 or 24 times. It corrects any missed row
  within one day and resets `last_full_at`.
- **Weekly deep reconcile** (Friday 04:30): for each table, compare **counts and sums**
  between SOFTECH and our mirror (§6.2). It also lists rows that exist in our mirror but no
  longer in SOFTECH (deletes). The result is written to the `/sync` page. A difference opens
  a Notification to admins. It **reports**; it does not delete anything without approval
  (today's sync does not delete either).

### 3.4 What "changed" means for deletes
SOFTECH has no delete log that we can read (`itembarcode.deltrans_time` might be one; not yet
checked). A delta read cannot see a row that was deleted. So for every table, deletes are found
by the nightly full refresh (stock: sold-out and vanished rows are set to 0, as today) or by the
weekly reconcile (customers, items, barcodes, sales: report only, as today).

## 4. Per table, ordered by load

### 4.1 Stock — `stkbal` (38 % of rows) — rollout 1st

| | |
|---|---|
| **Detect change** | `stkbal.modif_lastupdate`, stamped at HQ per arriving branch batch. Query: `SELECT itemcode, branchcode, storecode, nowqty, monthlyqty, onorderqty, modif_lastupdate FROM stkbal WHERE modif_lastupdate >= ?` **with no `nowqty > 0` filter**, so a row that sold out arrives as 0. |
| **Second detector (belt and braces)** | If G1 or the shadow week shows rows changing *without* a new stamp: also take the keys moved since the watermark from `stktrans` (`docdate >= today`, indexed by `stktrans_ndx50 (branchcode, docdate, doccode)`). Then read `stkbal` only for those keys, in chunks of 200 per branch through the `(branchcode, storecode, itemcode)` index. **Do not join `stktrans` to `stkbal` in one statement:** that join timed out at 120 s in this probe (Appendix A). |
| **Watermark** | one stream `stkbal`: the maximum `modif_lastupdate` read, minus 10 min overlap. |
| **Late / back-dated** | A branch that was offline sends its batch late, but it is stamped when it *arrives* at HQ, so it is newer than the watermark and is read. If G1 shows the stamp is the branch's clock instead, the movement-key detector becomes mandatory (**stop-and-ask S7**). A back-dated document changes `nowqty` now, so it is stamped now. |
| **Deletes** | Rare. The nightly full refresh keeps today's "zero every positive row SOFTECH no longer returns" step. That step **must never run after a delta read**: in a delta run, every row not in the result would be zeroed. Guard: the sold-out step runs only when the run is full. A test must cover it. |
| **Code note** | `sync_stock` already compares with the mirror and writes only changed rows (P-56). The delta path reuses that write. Only the read and the sold-out guard change. |
| **Full reconcile** | nightly full (one 32 k read) + weekly count/sum (§6.2). |
| **Load saved** | 288 reads × 32 k = **≈ 9.2 M rows/day** → about 300 runs × (rows of the last 5 min + 10 min overlap ≈ 50–300) + one full 32 k ≈ **0.1 M rows/day (−98 %)**. Query **time** falls less: with no index on `modif_lastupdate`, SOFTECH still scans 340 k rows on the server. But today most of the 28 s per run is moving 32 k rows to us, and a scan that returns 100 rows is expected to take 1–2 s. The shadow week measures it. An index on SOFTECH would make it cheaper, but it is a SOFTECH schema change and is **not proposed** (**stop-and-ask S3**). |

### 4.2 Customers — `localcustomers` + `personphones` + `personsdata` (28 %) — rollout 2nd

| | |
|---|---|
| **Detect change** | (a) `localcustomers`: rows with `trans_time >= ?` **or** `table_dumped >= ?` (the second is indexed). Which of the two moves on a field change is gate **G2** (probe [6b]). Both are read until G2 settles it. (b) `personphones.modif_lastupdate >= ?` gives the PICs whose phones changed; for those PICs, read **all** their phone rows and their `localcustomers` row (index on `phcode`). (c) `personsdata` (1.8 k rows) and the lookup tables `persontypes` / `persontypesclassif`: always read in full, because they are tiny. |
| **New customers** | covered by (a), because a new row carries a fresh `trans_time`. As a second check, record the maximum `branchcustcode` per branch and read anything above it (index `localcustomers_ndxw`). |
| **Watermark** | streams `localcustomers` (time) and `personphones` (time), each minus 10 min overlap. |
| **Late / back-dated** | customer edits happen at the branch and replicate in batches. Same rule as stock: they are only caught if the stamp is the arrival time. G2 checks this. The nightly full corrects anything missed within a day. |
| **Deletes** | Customer rows are not deleted by today's sync either. A merged PIC (doc 27) or a closed file shows up in the weekly reconcile as "in mirror, not in SOFTECH" (today: 198,996 in our copy vs 198,764 in SOFTECH). A **deleted phone row** leaves no trace in the delta, so it can stay on the customer until the nightly full. That is accepted. A blocked phone (`phoneblock = 1`) is an update, so it *is* caught. |
| **Side effects** | the guest-merge pass (`synced_phones`) runs on the changed customers only. That is correct: a guest can only match a phone that just arrived. |
| **Full reconcile** | nightly full (today's step, once) + weekly count/sum. |
| **Load saved** | 24 × ≈ 390 k = **≈ 9.4 M rows/day** → one full ≈ 390 k + 24–96 deltas × a few hundred ≈ **0.4 M/day (−95 %)**. With the saving, the delta can run every **15 min** (more current customers on the POS) and still read far less than today. That cadence is the owner's choice (**S5**). |

### 4.3 Items — `items` + lookups (10 %) — rollout 3rd

| | |
|---|---|
| **Detect change** | `items.itemlastupdate >= ?` (52 k-row scan, cheap). It also needs the item codes whose supplier or ingredient rows changed: `itemssuppliers.modif_lastupdate >= ?` and `itemsai.modif_lastupdate >= ?`. Those items are rebuilt in full (all fields), because one item row is built from several tables. The small lookups (classif, family, producers, tree, units, shape, origin, effect, active ingredients, `personsdata` names) are always read in full; they are a few thousand rows. |
| **Open question (gate G3)** | Does a **price** change (`itemsaleprice`, `unitsaleprice`, tax price) and a **cost** change (`itemcostprice`, "updated on every stock receive") bump `itemlastupdate`? This is a financial field (POS prices, margins). If cost changes do not bump it, cost has to come from somewhere else: either a nightly full only, or a re-read of the items received today (doc 10 lines since the watermark). **Stop-and-ask S4** before items go ON. |
| **Watermark** | streams `items`, `itemssuppliers`, `itemsai` (time, 10 min overlap). |
| **Late / back-dated** | Items are edited centrally at HQ, so there is no replication lag. |
| **Deletes** | Items are archived, not deleted (`itemarchive`, `itemnomoreuse` are updates). `itemsai` rows that are removed are corrected by the nightly full. |
| **Full reconcile** | nightly full + weekly count, plus `SUM(itemsaleprice)` and `SUM(itemcostprice)` compared with the mirror. |
| **Load saved** | 24 × ≈ 133 k = **≈ 3.2 M/day** → full ≈ 133 k + lookups ≈ 24 × 5 k + changed items ≈ **0.27 M/day (−92 %)**. It also removes the 26 s maximum query from the hourly lane. |

### 4.4 Barcodes — `itembarcode` (5 %) — rollout 4th

| | |
|---|---|
| **Detect change** | `itembarcode.modif_lastupdate >= ?`. **Plus** every barcode of the items that the items delta flagged in that run, read by `itemcode` (index `itembarcode_x`). Today's query only keeps barcodes of items that are not archived, so an item that becomes archived changes the barcode set without touching any barcode row. |
| **Open question (gate G4)** | Coverage of `modif_lastupdate` and what `deltrans_time` means (a soft-delete time?). The count query timed out in this probe and was not repeated. |
| **Watermark** | stream `itembarcode` (time, 10 min overlap). Runs right after items, in the same lane. |
| **Late / back-dated** | edited centrally, so no lag. |
| **Deletes** | Today's sync never deactivates a barcode that disappears from SOFTECH (upsert only). Delta does not change that. The weekly reconcile reports it. If `deltrans_time` turns out to be a delete marker, the delta can set `is_active=False` for those rows. That is a behaviour change, so it is decided separately. |
| **Full reconcile** | nightly full + weekly count. |
| **Load saved** | 24 × ≈ 67 k = **≈ 1.6 M/day** → ≈ **0.08 M/day (−95 %)**. |

### 4.5 Sales — `stktrans` ⋈ `stktransm`, doccodes 115/30 (3 %) — rollout 5th

| | |
|---|---|
| **Detect change** | **Doc number per (branch, doccode)**, confirmed as a sequence (today's first = yesterday's last + 1). For each branch and for 115 and 30: headers with `branchcode = ? AND doccode = ? AND docnumber > ?` (indexed by `stktransm_x`), bounded by `docdate >= today − 7` so the index range stays short. Then their lines by the full key (branch, doccode, docnumber, docdate), which is indexed. **Always (branch, doccode, docnumber)**, never the doc number alone (see memory "SOFTECH docnumber collisions"). |
| **Watermark** | one stream per (branch, doccode), e.g. `stktransm:160:115` = the highest doc number written to `PurchaseHistory`. That is 2 doc types × 5 operating branches + HQ, about 12 rows. |
| **Late / back-dated** | A branch that was offline delivers its documents late, but their numbers are above the watermark, so they are read whatever their `docdate`. A document entered today with yesterday's date also gets a new number, so it is read too. **Edits to a document already read** (not expected for 115/30: a return is its own 30 document) are not seen by a number watermark. Safety: keep the existing **03:45 seven-day catch-up** (`sales_history_catchup`), which re-reads and upserts the last 7 days every night. |
| **Gaps** | A missing number in a sequence (a cancelled or unsaved document) is normal. The watermark is the highest number seen, not "the next expected number". |
| **Deletes** | A deleted or voided document is not removed by today's sync either. The weekly reconcile compares count and sum per (branch, day, doccode) for the last 35 days. |
| **Money rule** | Sales totals feed incentives, KPIs and analytics. The proof is **exact** equality of count and `SUM(transprice_total)` per (branch, day, doccode) between the delta and today's two-day read during shadow. Nothing approximate is accepted. **S2.** |
| **Load saved** | Rows are small: ≈ 2.4 k per run → ≈ 20–60. The real gain is on **our** side. Today every 5 minutes deletes and reinserts every line of two days of invoices in `PurchaseHistoryLine` (≈ 288 × 2 k lines a day of churn and WAL). Delta writes only new invoices. |

### 4.6 Transit lines — `sync_in_transit._fetch_items` (1 % rows, top query count) — companion fix

Not a watermark problem: it is an N+1 query (one query per open 125/25 document, 79,599 queries
and 8,157 s in 7 days, max 30 s). The fix is the one in the audit: one `IN (…)` query per
(branch, doccode) per cycle for all open documents, chunked by 200. New 125 documents can use
the same per-(branch, 125) doc-number watermark as §4.5 instead of the 30-day date window. It
ships behind its own switch `SYNC_DELTA_TRANSIT` (default `off`) and is tested in shadow
mode in the same way. This can be built in parallel with §4.1; it shares no code.

### 4.7 Left as they are
`branches`, `itemsclassif`, `persontypes*`, `users` and the ERP permission mirror (already gated
to hourly) are small. They stay full reads. `stkbalexpiry` (daily sweep), insurance and finance
scans are outside this doc (see §11).

## 5. Rollout order

| Step | Table | Gate before SHADOW | Gate before ON |
|---|---|---|---|
| 0 | — | Owner approves this doc. Build the watermark table + switches + shadow report (all switches `off`). | — |
| 1 | Stock | G1 (probe [3] in working hours, twice) | 7 days of SHADOW with 0 misses + owner sign-off (S2) |
| 1b | Transit batching | — | 7 days of SHADOW: identical line sets |
| 2 | Customers | G2 (probe [6b]) | 7 days SHADOW, 0 misses + sign-off |
| 3 | Items | G3 (price and cost bump test after a real price update) | 7 days SHADOW, 0 misses, including at least one price-update day + sign-off (S4) |
| 4 | Barcodes | G4 | 7 days SHADOW + sign-off |
| 5 | Sales | — | 7 days SHADOW, exact count/sum equality + sign-off (S2) |
| 6 | (option) customers/items every 15 min | — | owner choice (S5) |

One table at a time. The next table enters SHADOW only after the previous one has run ON for a
week without a reconcile difference.

## 6. Proving that no row is missed (switch in SHADOW)

### 6.1 Per run: "every real change was in the delta"
In SHADOW the full read still runs and still writes. Before it writes, it already knows which
rows **really changed** compared with our mirror: `sync_stock` computes this today (`changed`),
and the same comparison is added for customers, items and barcodes. The shadow check is:

> **missed = (keys that really changed in this run) − (keys the delta query returned)**

- `missed` must be **empty**. Each run stores `rows_full`, `rows_changed`, `rows_delta`,
  `missed`, the delta query time and the full query time, plus up to 20 sample keys (codes
  only; no names or phones).
- `delta − changed` (rows read but unchanged) is allowed and expected: overlap, and rows
  touched without a value change. A large share only means wasted reads.
- For sales: the set of invoice ids and the per-(branch, day, doccode) count and
  `SUM(transprice_total)` from the two-day read must equal what the delta read returns.

### 6.2 Counts and sums side by side
Shown on the `/sync` page for each table in SHADOW, and later as the weekly reconcile:

| Table | SOFTECH side (one aggregate query) | Our side |
|---|---|---|
| stkbal | per branch: `COUNT(*) WHERE nowqty>0`, `SUM(nowqty)` | same over `ItemStock` |
| localcustomers | `COUNT(*)`, count per `phcodestatus`, `SUM(picpoints)` | same over `Customer` |
| items | `COUNT(*)`, `SUM(itemsaleprice)`, `SUM(itemcostprice)`, count archived | same over `Item` |
| itembarcode | `COUNT(*)` with today's join filter | active `ItemBarcode` count |
| sales | per (branch, day, doccode), last 35 days: `COUNT(DISTINCT docnumber)`, `SUM(transprice_total)` | same over `PurchaseHistory` / lines |

Pass criterion for ON: **7 consecutive days, 0 misses, sums equal** after each nightly full.
The 7 days must include a Friday, a full working day on every branch, and (for items) a price
update. If a branch had a connection outage during the week, that is a useful test of late
batches; it is noted in the report.

## 7. Rollback
1. Set the table's switch to `off` (`.env` + restart the scheduler, as for every setting
   today). The next run is today's full read. Nothing else is needed: the full read rewrites
   the mirror, and the watermark rows are ignored while the switch is `off`.
2. When the switch goes back to `on`, the first run is a **full** run (§3.1), so a stale
   watermark is never used.
3. The code for the full path is never deleted, so rollback is always available.
4. If a miss is found while ON: switch OFF, run "full" from `/sync`, and record the miss in the
   shadow report.

## 8. Effect on the data-freshness bar
`apps/sync/freshness.py` reads the last **successful** `SyncLog` per table. A delta run is a
successful run, so the bar stays green at the same 5 / 60 min cadence. It does not falsely turn
amber.

Changes (small, part of the build):
- `SyncLog` gets a `mode` value (`full` / `delta`). `records_processed` in delta mode is the
  number of **changed** rows (often 0–100). The `/sync` page labels it «صفوف متغيرة» so a
  small number does not look like a failure.
- Each domain returns `last_full_at`. The tooltip shows «آخر مطابقة كاملة: …».
- New stale rule: a domain is **stale** if its last delta is older than 3 × cadence (as
  today) **or** its last full refresh is older than 26 h (the nightly full failed). That makes
  a failed nightly safety net visible to staff. **Stop-and-ask S8** (it changes what staff see).
- The «تحديث» button on the bar runs a delta (fast). The `/sync` page keeps the "full" button
  for admins.
- If customers and items move to 15 min (S5), the catalog and customers domains get a 15 min
  cadence, so the bar's stale threshold tightens with it.

## 9. Stop-and-ask points
| # | Before … | Why |
|---|---|---|
| S1 | adding the watermark table (PostgreSQL migration in `apps/sync`) | CLAUDE.md: schema change that affects the SOFTECH sync |
| S2 | switching **any** table from SHADOW to ON | owner signs the 7-day shadow report; for sales, the totals feed money reports |
| S3 | any idea of adding an index, trigger or column **on SOFTECH** (e.g. on `stkbal.modif_lastupdate`) | SOFTECH schema change: never without the owner and the vendor. Not proposed. |
| S4 | items ON, if G3 shows price or cost changes do **not** bump `itemlastupdate` | prices and costs drive POS and margins; needs the owner's choice of fallback |
| S5 | changing the cadence of customers/items (60 → 15 min) | changes load and freshness |
| S6 | if a watermark would move **backwards** (SOFTECH clock or sequence reset) | the run falls back to full automatically; a human decides why it happened |
| S7 | if G1 shows `modif_lastupdate` is the branch's clock, not the HQ arrival time | the stock design changes to the movement-key detector |
| S8 | the new "full refresh older than 26 h" stale rule on the bar | changes what staff see |
| S9 | any shadow miss > 0 | stop, investigate, do not proceed to ON |

## 10. Open evidence gates (read-only, owner's PC, working hours)
- **G1** — `python manage.py probe_softech_change_columns --watch 15`, once in the morning and
  once in the afternoon. Section [3]: every quantity change must carry a newer
  `modif_lastupdate`. Section [2b]: confirm the batch rhythm.
- **G2** — the same run, section [6b]: customers whose flags changed must have a newer
  `trans_time` and/or `table_dumped`.
- **G3** — after a real price update in SOFTECH: section [5]. Also check one received purchase
  (doc 10): did `itemcostprice` change, and was `itemlastupdate` bumped?
- **G4** — a bounded count of `itembarcode.modif_lastupdate` and `deltrans_time` coverage.

Avoid joins between `stktrans` and `stkbal` in these probes (Appendix A note).

## 11. Out of scope (listed so nothing is lost)
- Other heavy readers: `eta_recon._softech_rows` (5.4 M rows a week), `customers.status_drift`,
  `customers.duplicates`, finance month scans (doc 30 F9), the purchasing engine's own sales
  pull (doc 30 F8 / Phase 3.1), one connection per job (doc 30 Phase 3.3).
- Moving `branches` out of the 5-minute lane.
- Any SOFTECH write path. This design reads only.

---

## Appendix A — read-only probe, 2026-11-19 06:05 (SOFTECH server time)
`SOFTECH_READ_ONLY=True`, `SET ROWCOUNT` on every statement, aggregates only (no names or phones).

- **Indexes:** `stkbal`: `(storecode, itemcode)`, `(itemcode)`, `(branchcode, storecode, itemcode)`,
  `(ivm_time)`. `stktrans`: 11 indexes, none on `trans_time`; `(branchcode, docdate, doccode)`
  and `(branchcode, doccode, docnumber, docdate, …)` exist. `stktransm`:
  `(branchcode, doccode, docnumber, docdate)` and `(branchcode, doccode, trans_time)`.
  `items`: none on `itemlastupdate`. `itembarcode`: `(itemcode, itembarcode)`.
  `localcustomers`: `(phcode)`, `(table_dumped)`, `(branchcustcode)`.
  `personphones`: `(ptcode, personcode, phoneno, phonetype)`.
- **Date columns:** `personphones`: `modif_lastupdate`, `table_dumped`. `itemssuppliers`,
  `itemsai`: `modif_lastupdate`. `users`: `modif_lastupdate`, `userdate`.
- **stktrans `table_dumped`:** NULL on all rows of today (177) and yesterday (3,845, all branches).
- **stktransm today:** `docwritedate` NULL. `table_dumped` = `trans_time`.
- **Doc numbers (yesterday last → today first):** 130/115 465206 → 465207; 160/115 943099 → 943100;
  160/30 24577 → 24578; 170/115 421153 → 421154; 160/125 36352 → 36364 (125 numbers are
  shared with other uses; still increasing).
- **stkbal change times, last 3 h:** 06:00:50, 05:50:50, 05:30:50, 05:15:50, 05:10:50,
  05:00:50 … (1–3 rows each at that hour). Per branch, last stamp: 100 → 22:13:19 (yesterday),
  130 → 00:10:50, 140 → 23:39:50, 150 → 00:30:50, 160 → 06:00:50, 170 → 00:25:50. Rows changed
  in 24 h: 973 / 164 / 353 / 293 / 735 / 305. Closed branches (110, 120, 180–220) still hold
  ≈ 100 k zero-quantity rows; a delta read never touches them.
- **Note (load):** one probe query (`DISTINCT` keys moved today `LEFT JOIN stkbal`) hit the
  120 s timeout. The next five queries on the same connection also timed out, so the server
  was still busy with it. SOFTECH answered normally at 06:13. Lesson: no `stktrans`↔`stkbal`
  join in the delta design or in probes; look up keys in chunks through the indexes instead.
- **Row counts:** `personphones` 220,450 · `personsdata` 1,797 · `itemssuppliers` (main) 44,275 ·
  `itembarcode` 85,195.
- From the 2026-11-11 probe: `stkbal` 340,343 rows (32,001 with qty > 0); `items` 51,912;
  `localcustomers` 198,764; `stktrans` late lines dated yesterday but written after midnight: 0
  (measured on `trans_time`, the branch clock, so it does not measure replication lag).
