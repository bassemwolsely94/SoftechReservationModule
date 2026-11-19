# Crews piece 2b — Part B: switch the call center to the crew Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the call-center crew «الكول سنتر» the only source of call-center figures, targets and forecasts; rebuild its history from the crew rule; retire the fake `CC` branch.

**Architecture:** `KpiActualRollup`, `SalesTarget` and `ForecastResult` gain a nullable `crew` FK (exactly one of branch/crew where it applies). One helper `apps/forecasting/call_center.py::call_center_crew()` replaces `legacy_cc_branch()` for every reader. A one-shot command `migrate_call_center_to_crew` (dry-run default) re-points every CC row to the crew, overwrites the computed metrics with the crew rule, audits old→new per month, moves the CC targets and forecasts, and closes the CC branch. `build_crew_rollups` then writes `KpiActualRollup(crew=…)` and the shadow `CrewKpiRollup` goes.

**Spec:** `docs/superpowers/specs/2026-11-13-branch-classification-and-crews-design.md` §6.6, §6.8, §6.8b. Part A plan: `docs/superpowers/plans/2026-11-18-crews-piece2b-call-center.md`.

## Owner rulings (2026-11-18, relayed by the parent session in the owner's words)

- **A "Rebuild from crew":** every month is rebuilt from the crew rule, not copied value-for-value.
- **B "Old rule":** returns = any earlier doc-115 sale at the same branch with the same document number made by a crew seller code (`cc_returns_from_softech` semantics, no date filter). Sales and calls use crew identities with their dates.
- **C "Add them":** extensions 11, 13, 14, 16, 17, 18, 201 join the crew, dated with the seed (history included).
- **D "Board figure":** incentives use the board's rollup figure, now from the crew; the target screen and `SalesTarget.actual_value()` must read the crew (today they read 0 for CC).
- **E:** seed the office crew as part of the rollout.

## Global Constraints

- Office DB is touched only after merge: `migrate_call_center_to_crew` dry-run first, reviewed, then `--apply` once.
- A month × metric whose crew value is not computable (any of the notes `returns_unreachable`, `cdr_unavailable`, `cdr_unreachable`, `no_members`, `no_sellers`) keeps its stored value; the audit names the source per metric (`crew` | `stored`).
- Audit: one `AuditLog.log('cc_crew_history_rebuilt', user=…, obj=crew, old_data={metric: stored}, new_data={metric: new}, extra={'year','month','source': {metric: 'crew'|'stored'}})` per month; plus `cc_targets_moved_to_crew`, `cc_forecasts_moved_to_crew`, `cc_branch_closed` (old/new kind).
- Idempotent: a second `--apply` finds no CC rows and changes nothing.
- No SOFTECH writes; SOFTECH reads via `config.sybase` with `?` parameters (parameterise `cc_softech`'s IN list).
- Tests: `TEST_DB_NAME=test_crews2b_b<n>` cloned from `test_crews2b_final`, serial, `--keepdb`, focused modules only.

## Review Focus

1. Re-run of the rebuild is a no-op; a month with CDR unavailable keeps the stored `call_count`.
2. A chain-scope `call_count` target (`SalesTarget.actual_value`, scope chain) must not double count once CC rows move to the crew (rows with `branch=None` must be summed exactly once).
3. `analytics_branches()` and every branch-total reader keep excluding the call center after the CC row is closed and its rollups re-pointed.
4. Target editors without the `crews` module can still pick the call-center crew on the target screen.
5. `rollup_refresh` now rebuilds the crew month when sales sync after its build (the October 2026 staleness cause).

---

### Task 1: Owner rules in the crew engine + crew FKs

**Files:** `apps/crews/kpi.py`, `apps/forecasting/cc_softech.py` (parameterise), delete `apps/crews/softech_returns.py`, `apps/crews/cc_seed.py` (extras default on), `apps/crews/cc_comparison.py`, `apps/crews/models.py` (drop `CrewKpiRollup`, `has_history` reads `KpiActualRollup.crew`), `apps/forecasting/models.py`, `apps/incentives/models.py`, migrations (`forecasting`, `incentives`, `crews 0003`), `apps/crews/management/commands/build_crew_rollups.py`, tests `test_crews_kpi.py`, `test_crews_cc_seed.py`, `test_crews_cc_comparison.py`.

**Interfaces (produces):**
- `KpiActualRollup.crew = FK('crews.Crew', null, PROTECT, related_name='kpi_rollups')`; `branch` nullable; `CheckConstraint((branch IS NULL) != (crew IS NULL), name='kpi_rollup_branch_xor_crew')`; `UniqueConstraint(crew, year, month, metric, condition=crew not null, name='uniq_crew_kpi_rollup')`.
- `SalesTarget.SCOPE_CREW = 'crew'` («طاقم»), `SalesTarget.crew = FK null PROTECT`.
- `ForecastResult.crew = FK null PROTECT`.
- `compute_crew_month(crew, year, month, *, returns=True, cdr_rows=None, per_member=False)` — returns via `cc_returns_from_softech(year, month, sorted(seller codes active in the month))`; per member: same function with that member's codes.
- `cc_seed.seed(..., include_pbx_agent_extensions=True)` default; command flag becomes `--without-pbx-agent-extensions`.
- `build_crew_rollups` writes `KpiActualRollup(crew=…, branch=None)` (same stale-row rule).
- `compare()` unchanged in shape; `old_now` stays the `CallCenterConfig` rule (that is what the owner compares against).
- Tests: returns use old rule (sale before membership counted); extras seeded by default; rollups land in `KpiActualRollup` with crew; check constraint rejects both/neither.
- [ ] RED → implement → GREEN → commit `feat(crews): owner rules — old returns rule, PBX agent extensions, crew FK on rollups/targets/forecasts`.

### Task 2: Rerun the comparison with the owner rules (controller, office DB, read-only)

- [ ] `compare_call_center_crew --seed-in-transaction --from 2024-08` → workbook + markdown; add before/after totals and October 2026 attainment to the PR body and `2026-11-18-cc-crew-comparison.md` (section "With the owner's rules").

### Task 3: Readers switch to the crew

**Files:** `apps/forecasting/call_center.py` (`call_center_crew()`; remove `legacy_cc_branch`), `views.py` (`_call_center_block`), `references.py`, `kpi_export.py` (`cc_targets`, recon key `'call_center'`), `engine.py` (member `key=f'crew:{id}'`, `crew` FK on results, `CC_ONLY_METRICS` by member type), `rollup_refresh.py` (staleness counts crew rows; rebuild calls `build_crew_rollups`), remove `build_call_center_rollups` command and `get_cc_branch`, `apps/pic_analytics/queries/calls.py` + `apps/insights/rules.py` (crew seller codes for the period), `apps/forecasting/admin.py` (`CallCenterConfig` agent fields read-only, label «انتقلت إلى طاقم الكول سنتر»), `apps/incentives/models.py` `SalesTarget.actual_value()` crew scope → `apps/crews/kpi.py::crew_actual(crew, metric, start, end) -> float` = Σ `KpiActualRollup(crew, metric)` for months overlapping the period (board figure); chain-scope rollup sums keep `branch` rows only + crew rows once (Review Focus 2). Tests: the existing KPI board/export/forecast/rollup-refresh/pic tests updated from the CC branch to the crew; new tests for Review Focus 2, 3, 5.
- [ ] RED → implement → GREEN → commit `feat(forecasting): call-center readers use the crew`.

### Task 4: Target screen + help

**Files:** `apps/incentives/serializers.py` (`crew`, `crew_name`, scope label), `apps/incentives/views.py` (select_related crew, `_tgt_desc`, `GET targets/crews/` → non-archived crews `{id,name,type}` under the targets permission), `frontend/src/api/client.js`, `frontend/src/pages/TargetsPage.jsx` (scope «طاقم» + crew select), help `apps/help/content/incentives.py` (targets screen) + `analytics`/KPI board help where the call-center block is described + `crews.py` + `callcenter.py` (AR + EN, `updated: '2026-11-18'`). Tests: API create/list crew target, attainment reads crew rollup, editor without crews module gets the crew list; `test_help`; `npm run build`.
- [ ] RED → implement → GREEN → commit `feat(incentives): crew-scoped targets on the target screen`.

### Task 5: One-shot migration command + retire CC

**Files:** `apps/crews/management/commands/migrate_call_center_to_crew.py`, `apps/crews/cc_switch.py`; tests `apps/tests/test_crews_cc_switch.py`; remove remaining `'CC'` literals (grep test), `docs/architecture/16_*` note.
- `plan_switch(user=None) -> dict` (no writes): per month × metric `{stored, crew, new, source}`, targets and forecasts to move, October attainment before/after. `apply_switch(user) -> dict`: one transaction — seed crew if absent (extras on), re-point every CC `KpiActualRollup` to the crew, overwrite computed metrics, audit per month, move `SalesTarget(branch=CC)` → `scope_type='crew', crew, branch=None`, `ForecastResult(branch=CC)` → `crew, branch=None, scope_key=f'crew:{id}'`, CC branch `kind='closed'`. Command: dry-run prints the table; `--apply` requires `--confirm-months N` equal to the planned month count.
- [ ] RED → implement → GREEN → commit `feat(crews): one-shot call-center switch to the crew, CC branch closed`.

### Task 6: Final review, PR body, merge, office run

- [ ] Whole-branch review; serial focused tests; PR body (rulings, before/after, Oct attainment); wait for every check; `gh pr merge 176 --merge --match-head-commit <sha>` after `git fetch`.
- [ ] Office: `migrate crews forecasting incentives`; `migrate_call_center_to_crew` dry-run → review → `--apply --confirm-months N`; report figures.
