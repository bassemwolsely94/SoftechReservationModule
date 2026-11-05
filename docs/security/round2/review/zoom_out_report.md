# Stage 5: Initial zoom-out review

Target: `docs/security/2026-11-05-full-project-test-plan.md` (full file, lines 1–212)
Reviewer: `egm-zoom-out` (fresh context) · Standard: `zoom-out-standard.md`
Context: suite design 2026-10-26, TEST_SUITE.md, PERMISSION_MATRIX.md, softech_write_manifest.py,
seed_permissions.py, ci.yml

**Verdict: Revise.** There are 0 Blockers, 5 Majors and 6 Nits.

**Context check passes.** The objective and motivation are stated. The reviewer confirmed the
manifest has 60 entries, of which 36 are `kind=write`, and the 3 sites with `idempotency=None`
(manifest lines 60, 68 and 120).

**Main problem.** The plan does not use the holes the suite has already measured. In several
places it also re-specifies tests that already exist instead of naming them and covering only
what changed.

## 🟡 Major 1: Existing baselines of open holes are missing (§3 lines 54–82, R3 lines 136–146, R7 lines 177–181)

These are the current baseline counts under `apps/tests/security/baselines/`:

| Baseline | Count | Note |
|---|---|---|
| `role_unproven` | 460 | |
| `role_overblocks` | 463 | 388 after Batch 4 |
| `role_crashes` | 6 | owned by Batch 7 |
| `branch_canary_leaks` | 22 | |
| `unsafe_exports` | 8 | |
| `sql_from_text` | 222 | was 218 |

The plan neither lists them nor commits to reducing them. `role_unproven` counts write-method
checks that were never reached. While 460 of them are unproven, aim 3 cannot be claimed, and
hand-picked cases for new roles treat a symptom.

**Suggestion.**
- R3: seed real records so `role_unproven` drops toward zero.
- R7: take `role_crashes`.
- R0: start its findings table from these baselines.
- Owner: look at why overblocks grew.

## 🟡 Major 2: R0's model-vs-database check can't catch the drift it cites (lines 92–94)

A test database migrated from scratch matches the models by construction. The cited incidents
need a database that already had the tables. CI already runs `makemigrations --check`. The check is
also new tooling inside a batch labelled "no fixes", and R0 and R6 overlap.

**Suggestion.** Make it a read-only introspection command the owner runs against the real
database, or drop it and rely on R6's static rule. Merge the R0 and R6 drift items.

## 🟡 Major 3: R1 and R6 re-specify guards that already exist (lines 114–119, 169–170)

These already exist:
- the writer kill-switch and gates: `apps/tests/test_writer_instance.py`;
- the manifest's static guard;
- `apps/tests/test_scheduler_jobs.py::test_no_job_function_registered_twice_on_the_same_cadence`;
- a scheduler heartbeat (`SCHEDULER_HEARTBEAT_KEY`, `/api/sync/scheduler-status/`).

**Suggestion.** Name these files and state only the gap.

## 🟡 Major 4: R1 re-audits all 36 write sites instead of what changed (lines 99–105)

Batch 2 / P-10 already verified every site and added switch-off tests (`test_softech_writes_*.py`).

**Suggestion.** Limit R1 to sites added or changed since 2026-10-26, sites whose callers changed,
and the 3 idempotency gaps. Two `kind=write` entries are CLI probes (`probe_ap_writeback`, which
is rolled back, and `test_replication_cycle --mode plant`). The HTTP-trigger check doesn't apply
to them.

## 🟡 Major 5: New guards clash with "fixed in the same batch" (line 25 vs R3 lines 142–143, R5 lines 159–165, R7 line 181)

The "every view gated" guard was a round-1 goal that was never built. Its first run may find many
views, and R3 could turn into a project-wide permission rewrite that is largely stop-and-ask.

**Suggestion.** Mark it a round-1 carry-over, and size it in R0 in report-only mode. Decide up
front whether the first findings get a reasoned baseline or must all be fixed in R3.

## 🟢 Nits

1. **R6 line 169:** "a duplicate-scheduler alert exists" is not true today; only the heartbeat
   exists. Either test the existing locking, or list the alert as owner-approved feature work.
2. **R8 line 189:** `config/settings_e2e.py` does not exist yet. Say R8 creates it, with the test
   runner's isolation block.
3. **R2 line 123:** "property-style" is unclear because `hypothesis` is not in
   `requirements-ci.txt`. Say whether these are table tests or a new dependency.
4. **Line 11:** `apps/*/apps.py` finds 65 apps, not 67.
5. **R7 lines 68–72, 179–180:** rank apps by per-app coverage from R0 (CI already runs
   `coverage`), not by counting test files.
6. **Lines 199–201:** move the CI wall-time question into R0, which measures it. The CI timeout
   is 75 minutes.
