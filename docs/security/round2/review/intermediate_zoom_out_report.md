# Stage 8: Intermediate zoom-out review

Target: `docs/security/2026-11-05-full-project-test-plan.md` (full file)
Reviewer: `egm-zoom-out` (fresh context) · Standard: `zoom-out-standard.md`
Inputs: the Stage 5, 6 and 7 reports, plus the original context. The reviewer also checked
`canary.py`, `test_branch_canary_sweep.py`, `CLAUDE.md`, the P-54 cutover spec and `DEPLOY.md`.

**Verdict: Revise.** 0 Blockers, 5 Majors, 2 Nits. Majors 1–2 combine earlier findings; Majors 3–5
are gaps no earlier stage raised.

## 🟡 Major 1: This is a debt-and-delta round, not a "whole project re-check" (§1 line 13, §4 lines 86–87, §6 lines 205–212)

Most of the work has already been measured. These baselines are open:

- about 460 `role_unproven` lines;
- 463 overblocks;
- 22 canary leaks;
- 222 `sql_from_text` lines;
- the write-site gaps.

Done is still defined only as "every batch green", with no target for any baseline count.

**Suggestion:**
- Restate the scope as: what was added since round 1, plus paying down the measured debt, plus
  suite batches 7 and 8.
- Give §6 a target for each baseline: empty, or reasoned lines only.

## 🟡 Major 2: The serial chain will stall on R1; make R0 a sizing and owner-decision gate (§4, R0, R1, §5)

R1 is almost all stop-and-ask, and every later batch waits for it. R7 and R8 don't depend on R1–R6.
Round 1 handled this by putting a batch's ask items to the owner together at its start and parking
them as `@pending` (design lines 115–118). This plan drops both.

**Suggestion:**
- **R0 output:** a sized backlog per batch, plus one owner decision pack.
- **Pending rule:** reinstate `@pending` / `PENDING.md`.
- **Parallel work:** R7 and R8 may run alongside R1–R6.

## 🟡 Major 3: The root cause gets another catch-up round, not a fix (§1 lines 11–13, §3 lines 74–82)

Modules keep landing after their batch has closed. Finance GL Plans 2 and 3 are landing during this
review. CLAUDE.md has no security definition of done for a new module. The generic sweeps catch new
routes, but per-module items still slip through: the matrix module, branch scoping, writer
registration and test depth.

**Suggestion:**
- Add a "new-module definition of done" to the CLAUDE.md batch rules.
- Turn the missing checks into ratcheted guards.
- Features merged during round 2 are covered by whichever batch is open at the time.

## 🟡 Major 4: R4 hand-extends a sweep that already finds new models; the real gap is its skip list (R4 lines 150–152)

`canary.py::branch_linked_models()` already walks every model that has a branch field. Models the
planter cannot build go into `planter.skipped`. The only check on them is "planted > 40"
(`test_branch_canary_sweep.py:92`), so a newly skipped model passes silently. The sweep also calls
list routes only. The GL is company-level, so the canary can't see it.

**Suggestion:**
- Ratchet `planter.skipped` as a baseline with reasons.
- Add detail-route coverage.
- Give company-level modules an explicit role-refusal check.

## 🟡 Major 5: Production enforcement is neither in scope nor declared out of scope (§3 line 63, §6)

Production runs RBAC and the network policy in `log` mode. Round 1 planned to switch to `enforce`
at the VPS cutover (TEST_SUITE line 162, P-54 line 68, DEPLOY line 71). The plan never mentions
`role_leaks_log`, the one baseline that measures the protection production actually relies on.

**Suggestion:** do one of these two:
- add an R3 exit item: `role_leaks_log` holds only reasoned lines for the new modules, and the
  would-deny log has been reviewed, so the owner can switch to `enforce`. Same for the network
  policy.
- list the switch as an explicit non-goal, with the reason.

## 🟢 Nits

1. **R3 lines 144–146 vs R8 line 190:** "Hidden means forbidden" is built twice, and a Django test
   that parses JSX will break on refactors. Use R8's Playwright run, or a nav map exported as JSON
   that both sides read.
2. **Lines 197–198:** owner question 2 is overtaken by critic M3, if work runs only on a non-writer
   copy. Reword it as a production decision, or drop it.

## Effect on the plan

- **Scope:** debt, plus delta, plus batches 7 and 8, plus a gate against it recurring.
- **Approach:** reuse the auto-discovering sweeps and ratchet their blind spots.
- **Structure:**
  - R0 becomes the sizing and decision gate;
  - `@pending` returns;
  - R7 and R8 run in parallel;
  - R3 gains an exit item for enforce-readiness, or the switch becomes a declared non-goal.
- **Unchanged:** the aims and their order, and the stop-and-ask list.
