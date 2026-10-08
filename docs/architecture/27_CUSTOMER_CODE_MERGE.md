# 27 — Customer-code (PIC) duplicates & merge (B7)

**Status:** 🔍 INVESTIGATION (HQ + one node; replication probe pending) · 📝 DESIGN PROPOSED, owner decisions recorded (2026-10-08) — build waits on replication + native code-change findings. No SOFTECH write exists.
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

**Owner (2026-10-08):** "a deactivated PIC should be deactivated on both branch and HQ and it should be
replicated, maybe this is a replication error." Two facts point that way:
* other `03HD` codes ARE on the branch-150 node (03HD3141, 03HD3475), but the deactivated 03HD3059 is not;
* `localcustomers` has no UPDATE trigger, and SOFTECH's replication ships rows by the `table_dumped` stamp
  (HQ triggers on `personphones` reset it to `1900-01-01` to force a re-ship). A status change that does
  not reset the stamp is never shipped.

→ `python manage.py investigate_pic_replication` (READ-ONLY) compares HQ with EVERY node: each node's own
branch code, where HQ's non-active codes exist and with what status, status / lock / balance mismatches
on codes held by both, HQ codes a node created but no longer has, codes whose status changed after their
last ship, and SOFTECH's own code-change / parent / points-edit tables (`localcustomers_main`,
`localcustomers2`, `localcustomers_n`, `lcpointstrans`, `picstrans`, `temppic`).

**Consequences for the design (pending that probe)**
* The merge writes at **HQ**, the same way SOFTECH's own screen does, including whatever stamp makes the
  replication agent ship it. If the native screen does not re-ship, we follow the item-discount pattern of
  `discount_approvals/replication.force_replication`: re-stamp at HQ, and push to a stale node only as a
  reviewed repair.
* After the write, a **read-back on every node that holds the old or main code** (status + balance). A node
  that has not caught up is flagged on the merge record ("pending replication") and retried.
* Until replication is proven, our /pos (step 5) blocks the old code from our mirror, whatever the node says.

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
* **Replication of a status change** → `investigate_pic_replication` (all nodes).
* **SOFTECH's native code change** → R5 of the same probe, then a `capture_save_sql` capture if needed.
* Meaning of `phcodestatus='5'` (2 codes) — not used by the merge.
* 34 balance rows without a customer row (orphans) — reported, untouched.
