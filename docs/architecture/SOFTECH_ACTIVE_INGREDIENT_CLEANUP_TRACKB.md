# SOFTECH Active-Ingredient Cleanup — Track B (Destructive Writeback) Design

**Status:** DRAFT / NOT BUILT. This is the gated, destructive phase. Nothing in
this plan runs until (a) the pre-flight probe (B0) is done, (b) the owner reviews
a dry-run manifest, and (c) an explicit config gate + `--confirm` is set.

**Prereqs already shipped (Track A):** `apps/composition` — parser, mirror
(`SoftechIngredientRaw`, `SoftechIngredientClassRaw`, `SoftechItemAI`), review
workbench (`/composition`), canonical taxonomy (`chronic.ActiveIngredient` /
`IngredientStrength` / `IngredientClass`), classifier, search index. Track B
consumes the **approved** canonical mapping and replays it into SOFTECH.

Related patterns to mirror: `apps/discount_approvals/replication.py` (readback-
verify, preserve usercode, no-schema-change), `apps/pos_orders/writer.py`
(collision-safe serial alloc, dry-run, offline queue, audit ledger).

---

## 1. What we know (probe-confirmed, 2026-08-25/29)

| Fact | Value | Consequence for Track B |
|---|---|---|
| `activeingredients` | PK `aicode`; `ainame`, `classcode`, `usercode`, `modif_lastupdate`, 3 unused "new modified" cols; 7,857 rows | We INSERT/UPDATE/DELETE here |
| `itemsai` | `itemcode`, `aicode`, `usercode`, `modif_lastupdate`, `aiblock`; 13,947 links; **no strength column** | We RE-POINT links here |
| Class taxonomy | `basic_data` where `bdatasno=600`, `bdatacode` 1-23 → `bdataname` | New classes = append rows here |
| **Triggers** | NONE on either table | Writes won't auto-revert (unlike branch `items`) — but **no safety net either** |
| **Declared FKs** | NONE | Deletes won't cascade AND won't be blocked → **orphan-prevention is entirely ours** |
| Current integrity | 0 orphans, 63 unused AI rows, 7,794/7,857 used | Baseline to preserve |
| aicode / bdatacode allocation | **UNKNOWN** | ⚠️ B0 must determine this before any INSERT |

---

## 2. Target end-state (owner decisions, locked)

- **Two tiers kept** in `activeingredients`: a bare-molecule row (`AMLODIPINE`)
  AND molecule-with-strength rows (`AMLODIPINE 5MG`, `AMLODIPINE 10MG`).
- **Atomic molecules**: combination rows (`AMLODIPINE + VALSARTAN`) are split;
  items re-pointed to the atomic component rows.
- **Dedup**: the dozens of "AMLODIPINE …" rows collapse to the canonical set.
- **Classes** populated on cleaned rows via `classcode`; the extended taxonomy
  (67 new classes) appended to `basic_data(600)`.

Mapping: each canonical `ActiveIngredient` → one **tier-1** aicode
(`ActiveIngredient.softech_aicode`, NEW field); each `IngredientStrength` → one
**tier-2** aicode (`IngredientStrength.softech_aicode`, exists). Each
`IngredientClass` → one `basic_data(600)` bdatacode (`IngredientClass.softech_code`).

---

## 3. Decisions (LOCKED by owner 2026-08-29)

1. **Item link target = BOTH.** Each item links to the strength-tier row AND the
   bare-molecule row, so molecule-level "find similars" works inside SOFTECH's own
   UI too. A combination item gets, per component molecule, BOTH links (2 links ×
   N molecules). This roughly multiplies `itemsai` link count — planner reports
   the exact projected total for review.
2. **Deletes = final gated pass only (B6).** After re-pointing, old dirty rows are
   left **orphaned/unused** (harmless — 63 already are). They are DELETED only in
   the separate, explicitly-confirmed B6 pass — which may be deferred indefinitely.
   B2-B5 never delete an `activeingredients` row.
3. **NO test host.** `SOFTECH_TEST_HOST` is NOT available → the first real run
   executes against **production SOFTECH with no rehearsal**. Implications (raise
   the safety bar):
   - The **pilot** (decision 4) is the de-facto rehearsal — smallest possible
     first blast radius.
   - **B0 must be conclusive** about aicode/bdatacode allocation before ANY insert
     (a wrong guess collides with live data). If B0 can't prove collision-safety,
     Track B does not proceed.
   - **Reversibility (B2-B4 rollback) is mandatory, not optional** — it's the only
     undo we have.
   - Run strictly **off-hours** to minimise concurrent native-client edits.
4. **Pilot one class family first.** First real run = ONE already-classified
   family (candidate: Calcium Channel Blockers, `classcode 12`, 69 AI rows) end-to-
   end (B2→B5), validated in the SOFTECH UI, before expanding to all approved
   molecules.

> **Precondition for B1:** Track B only ever pushes **APPROVED** canonical
> molecules. The `/composition` review queue must contain approved rows for the
> pilot family before `plan_ai_writeback` has anything to emit. (Today: 0 approved.)

---

## 4. Ledger + model additions (Postgres, additive — safe)

- `ActiveIngredient.softech_aicode` (IntegerField, null, unique) — NEW.
- `WritebackRun` — one row per execution (phase, dry_run, operator, started/finished,
  counts, status, kill-switch flag).
- `WritebackOperation` — the manifest + audit + idempotency backbone. One row per
  atomic SOFTECH change:
  - `run`, `op_type` (`class_insert` | `ai_insert` | `itemsai_repoint` |
    `ai_delete`), `target_key` (bdatacode / aicode / itemcode+aicode),
    `before_json`, `after_json`, `status` (`planned` | `executed` | `verified`
    | `failed` | `rolled_back`), `error`, `verified_at`.
  - Idempotency: an op already `verified` is skipped on re-run.
  - Rollback: `before_json` + the `SoftechIngredientRaw`/`SoftechItemAI` mirror
    are the restore source.

No SOFTECH schema is modified (Golden Rule #4). The mirror tables are the
"before" snapshot; the ledger is the "what we did".

---

## 5. Commands (CLI-first, like `pos_probe`)

| Command | Writes? | Purpose |
|---|---|---|
| `ai_writeback_probe` | **read-only** | B0: capture how the native client allocates `aicode`/`bdatacode` (dbcc/sysobjects); confirm no sequence table; optional single throwaway row on TEST host |
| `plan_ai_writeback [--pilot-class KEY]` | **none** | Build manifest → `WritebackOperation` rows (status=planned) + human report. Re-mirror first to detect drift |
| `execute_ai_writeback --phase <p> --batch N --confirm` | **SOFTECH** | Execute one phase in batches; readback-verify each; honor ledger + drift-guard + kill-switch + config gate |
| `verify_ai_writeback [--run ID]` | read-only | Readback all executed ops; report drift |
| `rollback_ai_writeback --run ID` | **SOFTECH** | Restore ainame/classcode/itemsai from mirror + ledger `before_json` |

Config gate: `SystemSetting AI_WRITEBACK_ENABLED` (default **False**) — mirrors
the `POS_BLOCK_POINTS_SALES` kill-switch idea. `execute_*` refuses to run unless
enabled AND `--confirm` passed.

---

## 6. Execution phases (each gated, each reversible until B6)

**B0 — Pre-flight probe (read-only).** Determine `aicode`/`bdatacode` allocation
(max+1 vs a `lastdocnumbers`-style sequence — the native client's INSERT must be
captured, as was done for POS in `softech_save_dbcc_capture.txt`). Abort the
whole track if allocation can't be made collision-safe.

**B1 — Plan (no writes).** `plan_ai_writeback` produces the full manifest and a
report: N classes to append, N tier-1 rows, N tier-2 rows, N itemsai re-points,
N old rows to (eventually) delete. **Owner reviews and signs off the manifest.**

**B2 — Class push** to `basic_data(600)` (small, additive). Append the 67 new
classes with next `bdatacode`; store `softech_code`. Readback-verify. Lowest
risk (a lookup append) → do first so AI rows can reference them.

**B3 — AI-row insert** (additive). INSERT tier-1 + tier-2 `activeingredients`
rows with `ainame`, `classcode`, real `usercode`, `modif_lastupdate=GETDATE()`.
Readback-verify each; store allocated `aicode` on the canonical row. No existing
row touched yet → fully reversible (just delete the new rows).

**B4 — itemsai re-point** (the reshaping). Per item, for each old dirty link:
add the new clean link(s) FIRST (verify), THEN remove the old link. Never leave
an item with zero links mid-op. Batched per item; ledger every change; drift-
guard aborts a row whose `modif_lastupdate`/`usercode` changed since the mirror.

**B5 — Soak.** New structure live in SOFTECH. Validate item cards, SOFTECH-side
search, and our own search (rebuild `ItemMoleculeIndex` — results flip to
"approved"). Monitor for pharmacist-reported issues. Old dirty rows now orphaned
but present (harmless).

**B6 — Delete orphaned dirty rows** (FINAL, irreversible, separately confirmed).
Only rows with zero remaining `itemsai` references (ledger-verified). This is the
only truly unrecoverable step — deferrable indefinitely; the system is fully
functional with the old rows merely orphaned.

---

## 7. Non-negotiable safety invariants (CLAUDE.md)

1. **Dry-run first, always.** No `execute_*` without a reviewed `plan` manifest.
2. **Idempotent.** Ledger `verified` ops are skipped; never double-insert (Rule 3).
3. **Readback-verify every write** (Rule 8 auditable; replication.py pattern).
4. **Orphan-safe ordering.** Insert clean → re-point → (only then) delete dirty.
   Never delete a referenced row.
5. **Drift-guard.** Re-mirror before planning; per-row check vs mirror snapshot;
   abort on external change (concurrent native-client edit).
6. **Reversible until B6.** Full rollback from mirror + ledger for B2-B4.
7. **Gated.** Config kill-switch + `--confirm`; run off-hours; pilot first.
8. **Deterministic.** All content comes from the reviewed canonical mapping — no
   LLM decides any molecule, strength, class, or link (Rules 2/5/10).
9. **Charset.** Arabic writes use `get_sybase_connection(charset='cp1256')`.
10. **Attribution.** Stamp the approver's real `usercode` (like replication.py),
    not a fabricated service user, so SOFTECH audit stays truthful.

---

## 8. Sequencing for the first real run (no test host → pilot is the rehearsal)

0. **Approve the pilot family in `/composition`** — review + approve the Calcium
   Channel Blocker rows so there's an approved mapping to push.
1. **B0 probe (read-only)** → prove `aicode`/`bdatacode` allocation is collision-
   safe. **HARD GATE — Track B stops here if inconclusive.**
2. **B1 plan** scoped to the pilot family (`--pilot-class calcium_channel_blockers`).
   Owner reviews the full manifest (rows to insert, links to re-point, projected
   counts). Sign-off required.
3. Enable `AI_WRITEBACK_ENABLED`; run **B2 → B3 → B4** on the pilot, off-hours,
   batched, readback-verified. Verify in the SOFTECH item card + Classes screen.
4. **B5 soak** the pilot. Rebuild `ItemMoleculeIndex`; confirm our search flips to
   "approved". If anything is off → `rollback_ai_writeback --run <id>`.
5. If clean, expand B1-B4 to the rest of the **approved** molecules, batched by
   family. Never run ahead of `/composition` approvals.
6. **B6 deletes** deferred until the owner explicitly asks — likely much later, or
   never.

---

## 9. What Track B does NOT change

- SOFTECH schema (no new columns/tables). Only row-level DML on existing tables.
- The reviewed mapping — Track B is a pure replay of `/composition` approvals.
- Any non-composition SOFTECH data.
- Our Postgres search — that already works (Track A) independent of Track B.
