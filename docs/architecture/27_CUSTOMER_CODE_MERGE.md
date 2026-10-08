# 27 — Customer-code (PIC) duplicates & merge (B7)

**Status:** 🔍 INVESTIGATION done (HQ + branch node) · 📝 DESIGN PROPOSED (2026-10-08) — awaiting owner approval. No SOFTECH write exists.
Probe: `python manage.py investigate_pic_merge [--suggest] [--pic A --pic B …]` (apps/customers).

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

**Consequences for the design**
* The merge writes at **HQ only**, through the channel in step 4. Writing directly to a branch node would race with SOFTECH's own replication.
* After the write, a **read-back on every node that holds the old or main code** (status + balance). A node that has not caught up within the check window is flagged on the merge record ("pending replication"). We never write to it.
* The pilot's rollback probe must show which way replication goes. Write on one pair at HQ, then read the nodes after 1 h and again after 24 h.
* Until replication is proven, our /pos (step 5) blocks the old code itself from our mirror, whatever the branch node says.

## Proposed design (for approval — nothing built)

1. **Candidate queue (our DB, read-only vs SOFTECH):** pairs on a real shared phone, classified
   *strong* (same normalised name + same structured address), *medium* (same name), *review* (similar name);
   *different names = family → never proposed.* Rebuilt weekly from SOFTECH.
2. **Main code (default, reviewer can swap):** most recent sale → higher points balance → older creation date.
3. **Approval:** maker-checker (proposer ≠ approver), approver role admin / supervisor, per pair, audited
   (AuditLog before/after). Bulk approval only for *strong* pairs.
4. **SOFTECH writes per approved merge** — one reviewed channel, verify by read-back, idempotent (our merge
   record + status check), gated by a new `CUSTOMER_MERGE_WRITE_ENABLED` (default off), rollback probe first:
   * points: if the old code's balance > 0 → `picpoints` −balance on the old code and +balance on the main code
     (doccode `ADJ`, vf1 `دمج ← / → <code>`, vf2 operator) in ONE transaction; `tr_picpoints` updates both
     balances — the existing pattern of `apps/loyalty/pic_bridge.adjust_softech_points`;
   * status: `localcustomers.phcodestatus='0'`, `phcodestatususercode=<approver's SOFTECH user>`,
     `phcodestatustime=getdate()` on the old code only (no trigger on the table);
   * nothing else changes in SOFTECH — history (189 tables) stays under the old code; `pphcode` untouched.
5. **Our side:** old → main mapping on the customer mirror so the coupon customer check (B2), refill reminders,
   loyalty and reports follow the main code; our /pos refuses a non-active code up front with SOFTECH's message.
6. **Rollout:** dry-run list → rollback probe on one pair → pilot 10 strong pairs (owner review) → wider.

## Open before build
* **Replication:** answered in part. Branch nodes hold their own copies and the balance matches HQ.
  Still unknown: whether `phcodestatus` changes made at HQ reach the nodes. Two ways to find out:
  (a) run the probe on the node of the branch where the owner's screenshot (POS refusing 03HD3059) was taken, or
  (b) run it on the node of a branch whose prefix matches one of HQ's 6 `'0'` codes.
  Otherwise the pilot read-back above will settle it.
* Meaning of `phcodestatus='5'` (2 codes) — not used by the merge.
* 34 balance rows without a customer row (orphans) — reported, untouched.
