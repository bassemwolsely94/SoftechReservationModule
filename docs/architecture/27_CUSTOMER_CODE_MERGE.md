# 27 — Customer-code (PIC) duplicates & merge (B7)

**Status:** 🔍 INVESTIGATION (HQ + all 5 nodes; points-balance source open) · 📝 DESIGN PROPOSED, owner decisions recorded (2026-10-08) — build waits on replication + native code-change findings. No SOFTECH write exists.
Probes: `python manage.py investigate_pic_merge [--suggest] [--pic A --pic B …]` · `python manage.py investigate_pic_replication [--host …] [--pic …]` (apps/customers).

## Confirmed facts (live probe 2026-10-08, HQ)

| Topic | Finding |
|---|---|
| Customer master | `localcustomers` — ONE row per PIC (197,779 rows = 197,779 codes; `branchcode` = creating branch). No triggers. `personsdata` holds no retail PICs. |
| Deactivation | `localcustomers.phcodestatus`: `'1'` active (197,759) · `'0'` = deactivated (6) · `'5'` (2, meaning unknown) · blank (12 = NOT deactivated, just unset). Companion columns `phcodestatususercode` / `phcodestatustime` (set on 1 code, 2018). `piclock`=1 on 6 codes. **Owner-confirmed:** 03HD3059 (`'0'`) is a deactivated duplicate of 06HD8958 (same name + address); 04HD1532 (blank) is a duplicate of 04HD2371 that staff simply stopped using. |
| Duplicates in practice | Almost never deactivated: 24 non-active codes vs 11,409 real shared phone numbers / 24,540 codes (pairs 9,948). Placeholder numbers (01000000000-style, > 10 codes) excluded. |
| Main-code link | `pphcode` = the code itself on all but 27 codes; those 27 point to the neighbouring code (`01HD188 → 01HD187`). Owner: data do NOT match → likely concurrent-save accidents, but the mechanism is SOFTECH's own and is examined further (probe section [13]). `relativecode` = 0 everywhere. |
| Points | Balance = `localcustomerspoints` (one row per PIC; `totpoints` earned − `conpoints` consumed), maintained only by trigger `tr_picpoints` on INSERT into the `picpoints` log. `localcustomers.picpoints` = enrollment flag 1/0. 34 balance rows have no customer row. |
| History | 189 SOFTECH tables carry a customer-code column (sales, claims, points log, patient data …) → a merge can never move history; it stays under the old code. |

## Second probe (2026-10-08) — findings

| Topic | Finding |
|---|---|
| Effect of `'0'` | **SOFTECH's POS refuses a sale on a `'0'` code** («غير مسموح بتنفيذ المطلوب لمريض داخلي تم غلق ملفه !», owner screenshot on 03HD3059). Deactivation is enforced natively. |
| Duplicate strength [12] | Pairs on real shared numbers: same name + same address **14** · same name **3,022** · similar name **3,314** · different names **9,384** (family / shared phone). Free-text address rarely matches; the structured fields do (03HD3059 / 06HD8958: same `homeno` 86, `floorno` 4, `apartmentno` 13) → the queue must compare `homeno/floorno/apartmentno/streetname1`. |
| `pphcode` links [13] | All 27 pairs have consecutive customer numbers, the same creation day and mostly the **same `trans_time` to the second**, usually the same user → one save producing two rows (owner's concurrent-save theory). 2016–2019 pairs: different names (unrelated); 2020–2026: mostly the same name (= real duplicates). **Not a reliable merge marker → we do not write `pphcode`.** |
| Relatives tables [14] | `localcustomersrelatives` 0 rows, `custpatientrelatives` 1, `custrelativespercent` 0 → SOFTECH's family feature is unused. Families sharing a phone stay as separate codes. |
| Points [10] | 04HD1532: balance 0 · 04HD2371: 413 (log Σ 413) · 03HD3059 (deactivated): **9 points stranded** · 06HD8958: balance **490 but log Σ 448** → the balance table and the log can differ; the balance (what the POS shows) is what moves, a mismatch is flagged. |

## Branch-node probe (2026-10-08, node 192.168.3.10)

| Topic | Finding |
|---|---|
| Customer copy | The node keeps its **own** `localcustomers` (47,361 rows, 13 branch prefixes = a subset of HQ's 197,779) and its own `localcustomerspoints` (47,359 rows). |
| Trigger | `tr_localcustomers` ON INSERT: if the phcode is new, it deletes that code's `localcustomersdata`, `localcustomerspoints`, `personphones` (ptcode '11') and `sh_pic_prefrences` rows, so a replicated insert starts clean. The merge never INSERTs a customer, so this trigger does not fire for it. |
| Deactivated code | 03HD3059 (`'0'` at HQ) is **not on this node**. The node has no `'0'` code at all (`'1'` 47,357 · blank 3 · `'5'` 1). So this node cannot tell us whether HQ's status changes reach the branches. |
| Points | 06HD8958 has the **same balance 490** (4450 − 3960) as HQ, so the balance row is in sync. Its `picpoints` log differs: Σ 3,371 over 107 rows on the node vs Σ 448 over 114 rows at HQ. The log is per node and is not the source of the balance anywhere, so the merge must move the balance, never re-sum logs. |

## All-node replication probe (2026-10-08, `investigate_pic_replication`, HQ + nodes 130/140/150/160/170)

| Topic | Finding |
|---|---|
| Who holds a customer | Each node holds **its own branch's customers** (95–97 %) plus a few hundred from HQ (100) and other branches. Closed branch 120 (`03HD…`) lives on node **130** (5,966 codes). No node holds everybody. Prefixes: 03=120 · 04/11/130=130 · 05/140=140 · 06/150=150 · 07/13/160=160 · 08/170=170 · 100=HQ. |
| 03HD3059 | `'0'` with balance 9 on node **130** too, which is the only node that holds it. **Not a replication error**: branch 150 simply never had the code. |
| Status mismatches | Rare, in both directions: 100HD6038 `'0'` at HQ / `'1'` on node 140; 07HD11624 + 07HD11663 `'0'` on node 160 / `'1'` at HQ; 06HD24310 `'5'` at HQ / `'1'` on node 150. Locks: 07HD2044, 07HD2057, 08HD1367 are locked at HQ, not on their node. So a deactivation **does not reliably reach the other side**. A branch can still sell on a code HQ closed (100HD6038 at 140). |
| `phcodestatustime` | Never set on any deactivated code (all None), and `trans_time` is not touched by a status change. SOFTECH's screen does **not** stamp who or when, nor does it reset `table_dumped`. |
| **Points balances** | Balances are **per node, not replicated**: 2,186–4,550 customers per node differ from HQ (130: 3,828 · 140: 2,237 · 150: 4,550 · 160: 2,984 · 170: 2,186). Gaps are mostly round hundreds (+400, +500, +1,000 …), and the node is usually higher. 187,222 of HQ's 197,813 balance rows were never shipped. **The 490/490 match on 06HD8958 was a coincidence.** |
| Native merge | `localcustomers2` (phcode, **sourcepic, sourcepicpoints**, usercode, trans_time, table_dumped, **mgmdate**) = a SOFTECH **merge** table: 0 rows at HQ. |
| Native PIC edit log | `picstrans` (66 rows at HQ): phcode → **phcode2**, pphcode → **pphcode2**, plus status / points / lock flags, user, time. Likely SOFTECH's "change customer code" / edit-PIC screen. |
| Manual points edits | `lcpointstrans` (12,242 rows at HQ): old → new totpoints / conpoints, status, user, time (e.g. 4,000-point grants by user 1509 on 2026-09-04). |
| Our loyalty bridge | `apps/loyalty/pic_bridge` reads and writes points at **HQ only**. Given per-node balances, what our screens show (and any CRM adjustment) can differ from what the branch POS shows. **Open: which balance does the branch POS redeem against?** |

### `--explain` findings (2026-10-08) — why balances differ

For the largest gaps on every node, the points log on both sides shows one pattern:

| Movement (`picpoints.doccode`) | HQ | Home node |
|---|---|---|
| **115** sale earnings | all branches | only its own sales (another branch's sales reach HQ, not the home node) |
| **30** POS redemption / return | all branches | only its own |
| **170** points → gift coupon (issued at HQ / call center, see SOFTECH_GIFT_VOUCHER_STOCKING) | ✅ | ❌ **never arrives** |
| **0** + `lcpointstrans` manual edits at HQ (mostly user 19, 2022-04 → 2024-05, setting consumed = earned, i.e. zeroing the balance) | ✅ | ❌ **never arrives** |

* **HQ is the consolidated ledger. A node only knows its own sales and redemptions.**
* The common gaps (+400, +500, +800, +1,000 …) are coupon conversions that the branch never received.
  Example: 05HD999 = 79 at HQ but 125,031 on node 140 (110,500 converted to coupons + a 14,452 HQ reset);
  06HD3333 = 27,421 at HQ / 149,565 on node 150.
* The reverse also happens. A customer who buys at another branch has a *lower* balance on the home node
  (06HD13141: HQ 40,964 / node 1,016).
* **Risk (pre-existing, not caused by us):** if the branch till redeems against the node balance, points
  already converted to coupons at HQ (or zeroed there) can be redeemed again at the branch.
  → owner check at a till (04HD1550: HQ 111 / node 130 3,611).
* SOFTECH's native merge table `localcustomers2` is **empty on HQ and every node**, so the merge feature was
  never used.
* `picstrans` (HQ 66, node 150 12) is the HQ **edit-customer screen's log**. `phcode` never changes
  (phcode = phcode2 on every row). The only "code changes" (3, 2019–2020) are **`pphcode` edits**:
  06HD19541 → 09HD19541 and back; 04HD1549 → 04HD549, which looks like correcting a mistyped code. So
  "changing a customer's code in SOFTECH" = editing `pphcode` on that screen; the real code never changes.
* `lcpointstrans` is used almost only at HQ (12,242 rows) and node 150 (5,653, up to 2023); the other nodes
  have < 80 rows, all from 2017–2018.

### Owner answers (2026-10-08) — what the flags mean

| Code | HQ / node | Owner |
|---|---|---|
| 100HD6038 | `'0'` / node 140 `'1'` | **blocked: drug-addicted patient** → still sellable at branch 140 (pharmacy-safety gap) |
| 07HD11624 | `'1'` / node 160 `'0'` | former ElRezeiky employee, must **not collect points**. **Decision: points-off** (`picpoints=0`), stays an active customer (`'1'`) on HQ and node 160 |
| 07HD11663 | `'1'` / node 160 `'0'` | unknown — owner investigates later; untouched until then |
| 06HD24310 | `'5'` / node 150 `'1'` | **client passed away** → `phcodestatus='5'` = deceased (06HD4420 is `'5'` too) |
| 07HD2044, 07HD2057, 08HD1367 | locked / node unlocked | **entities, not persons** → `piclock=1` used to mark a non-person account; node balances 4,524 / 7,898 / 1,102 |
| user 19 resets (2022-04 → 2024-05) | HQ only | Bassem Halim (stock count + points reset). **Deliberate:** customers who abused discounts and flooded the reports are **removed from the points system** (no vouchers / coupons). The resets never reached the branch nodes. |

`--explain` [R8] measures those removed customers: how many still show a balance on a node, whether they are still
enrolled (`localcustomers.picpoints`), and points they used at a branch till (doc 30) after the reset.

### `--explain` [R8] — customers reset at HQ (2026-10-08)

| | |
|---|---|
| Reset at HQ (lcpointstrans consumed = earned) | **3,146 customers** (user 19 = 3,090) |
| Still enrolled at HQ (`picpoints` = 1) | **2,600** (546 un-enrolled). The reset zeroed the balance but did **not** remove them from the points system |
| Earned again at HQ since the reset | 2,110 customers, **1,709,583 points** |
| Still showing a balance on a branch node | 130: 831 (1,290,241) · 140: 196 (618,056) · 150: 1,323 (1,788,449) · 160: 426 (1,575,241) · 170: 360 (616,801) = **≈ 3,136 customers, 5.89 M points**, almost all still enrolled there |
| Largest | 07HD1000 556,386 (node 160) · 07HD7977 217,846 · 06HD3333 149,565 · 07HD5788 147,249 · 05HD999 125,031 |

All nodes together show **≈ 11.7 M points more than HQ** (130 +3.29 M · 140 +1.78 M · 150 +3.65 M ·
160 +1.11 M · 170 +1.86 M) and ≈ 0.36 M less. 160HD33215 has earned 1,514,189 points from 8,499 sales,
which looks like an entity / company account (to check).

Not yet known: the points these customers **used at a branch till after their reset**. The first run failed
on a date parameter; it is fixed, and `--reset-only` reruns just this section. That figure, plus the till
check (04HD1550), shows whether the overstated balances are actually being spent.

**Our side has the same gap.** Our customer mirror carries no status / lock / deceased / points-enrolled flag,
so /pos, call-center reservations, WhatsApp refill reminders (B1) and coupon features can serve a blocked,
deceased or removed customer.

**Consequences for the design**
* There is no single place to write. A merge must act **on the node that holds each code (its home branch)
  AND at HQ**, then read both back. That is the item-discount pattern (`discount_approvals/replication`),
  where a stale node is pushed directly as a reviewed repair.
* Points: HQ's balance is the complete one. Writing an ADJ row on a node is **forbidden** in the design: node
  `picpoints` rows travel to HQ (that is how branch sales reach HQ), so the row would be applied twice there,
  a double post. The points write stays at HQ only, and how a branch till sees it depends on the till check
  above.
* If SOFTECH's own merge screen (`localcustomers2`) exists in the client, the merge should **replay its DML**
  (captured with `capture_save_sql`) instead of our own status + points pair.

## Owner decisions (2026-10-08)

* **Approvers:** admin, supervisor, **call_center**. Maker-checker stays: whoever proposes a pair cannot
  approve the same pair.
* **Main code:** ① older creation date → ② higher points balance → ③ most recent sale. The reviewer can swap.
  - `custdate` decides almost every pair, so ② and ③ are tie-breakers only.
  - A code already `'0'` (deactivated by staff) or locked never survives, even if it is older.
  - A missing / 1900 `custdate` counts as unknown, and the next rule decides.
* **Parent PIC (`pphcode`):** not used by the owner, and its purpose is unknown. SOFTECH can also change a
  customer's code "somehow". We do not write `pphcode`.
  - Before building, learn the native code change: R5 of the probe looks for its tables / procs.
  - If none is readable, run `capture_save_sql` while staff change ONE real duplicate in SOFTECH.
  - If the native change moves history or points itself, the merge should replay **that** DML rather than
    our status + points pair.

## Proposed design (for approval — nothing built)

1. **Candidate queue (our DB, read-only vs SOFTECH):** pairs on a real shared phone, classified
   *strong* (same normalised name + same structured address), *medium* (same name), *review* (similar name);
   *different names = family → never proposed.* Rebuilt weekly from SOFTECH.
2. **Main code (default, reviewer can swap):** older creation date → higher points balance → most recent sale;
   a deactivated / locked code never survives.
3. **Approval:** maker-checker (proposer ≠ approver), approver role admin / supervisor / call_center, per pair,
   audited (AuditLog before/after). Bulk approval only for *strong* pairs.
4. **SOFTECH writes per approved merge** — one reviewed channel, verify by read-back, idempotent (our merge
   record + status check), gated by a new `CUSTOMER_MERGE_WRITE_ENABLED` (default off), rollback probe first:
   * points: if the old code's balance > 0 → `picpoints` −balance on the old code and +balance on the main code
     (doccode `ADJ`, vf1 `دمج ← / → <code>`, vf2 operator) in ONE transaction; `tr_picpoints` updates both
     balances — the existing pattern of `apps/loyalty/pic_bridge.adjust_softech_points`;
   * status: `localcustomers.phcodestatus='0'`, `phcodestatususercode=<approver's SOFTECH user>`,
     `phcodestatustime=getdate()` on the old code only, plus the replication stamp (see above);
   * nothing else changes in SOFTECH — history (189 tables) stays under the old code; `pphcode` untouched
     (unless the native code change, once captured, says otherwise).
5. **Our side:** old → main mapping on the customer mirror so the coupon customer check (B2), refill reminders,
   loyalty and reports follow the main code; our /pos refuses a non-active code up front with SOFTECH's message.
6. **Rollout:** dry-run list → rollback probe on one pair → pilot 10 strong pairs (owner review) → wider.

## Open before build
* **Which balance the POS uses** (node or HQ) — owner check on one mismatched code at the branch POS.
* **SOFTECH's native merge / code change** (`localcustomers2`, `picstrans`) → `--explain` on all nodes, then
  `capture_save_sql` while staff run ONE merge or code change in SOFTECH.
* Status repair for the 7 mismatched codes (owner reasons above) — a SOFTECH write on branch nodes; awaiting approval.
* 07HD11663 — owner investigates later; no change until then.
* `phcodestatus='5'` = deceased (owner, 06HD24310).
* 34 balance rows without a customer row (orphans) — reported, untouched.
