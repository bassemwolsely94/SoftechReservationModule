# Crews piece 2b — call center onto crews (up to the money gate) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Seed the call center as the crew «الكول سنتر», compute its KPI figures from its members' dated identities next to the old `CC`-branch rollups, produce an old-vs-new comparison report for the owner, and rewrite PBX extension classification to read crews and data instead of fixed lists — without switching any money figure.

**Architecture:** `apps/crews/cc_seed.py` turns `CallCenterConfig` into dated manual members. `apps/crews/kpi.py` computes a call-center crew month from `identities()` spans with the exact expressions of `KpiResolver.compute_call_center_month` (same SOFTECH returns rule, same CDR call rule), and `build_crew_rollups` stores the result in a NEW shadow table `CrewKpiRollup` that nothing else reads. `apps/crews/cc_comparison.py` builds the owner workbook (stored CC rollup / old rule recomputed now / crew value, per month × KPI, per person, per target). Every existing reader of the `CC` branch keeps working unchanged; its six copies of the lookup collapse into one helper so Part B switches one place.

**Tech Stack:** Django/DRF, PostgreSQL, openpyxl, SOFTECH Sybase reads via `config/sybase.py`, Issabel CDR via `config/issabel.py`.

**Spec:** `docs/superpowers/specs/2026-11-13-branch-classification-and-crews-design.md` §5.6, §5.8, §6.6, §6.8, §6.8b, §10. Piece 2a plan: `docs/superpowers/plans/2026-11-13-crews-piece2a-foundation.md`.

## Inventory of call-center representations (2026-11-18, office DB `elrezeiky_db`)

| # | Representation | Where | Part A (this PR) | Part B (after owner sign-off) |
|---|---|---|---|---|
| 1 | Fake Branch `CC` (id 15, kind `call_center`) | created by `get_cc_branch()` `build_call_center_rollups.py:25` — **without `kind`, so a fresh DB gets kind `retail`** and `build_kpi_rollups` would then zero it | `get_cc_branch()` sets `kind=call_center` on create (safety fix, no figure changes on office DB) | kind → `closed`, `get_cc_branch()` removed |
| 2 | `'CC'` lookups `Branch.objects.filter(softech_branch_id='CC')` | `forecasting/views.py:294`, `references.py:47`, `kpi_export.py:153,514`, `engine.py:199`, `rollup_refresh.py:61` | collapse into `apps/forecasting/call_center.py::legacy_cc_branch()` (same rows read) | helper returns the crew source |
| 3 | `'CC'` scope keys | `engine.py:201,394,450` (ForecastResult `scope_key='CC'`, 31 rows), `kpi_export.py:492-543` (legacy workbook row 23) | unchanged (money) | crew scope; rows migrated value-for-value |
| 4 | `CallCenterConfig.sales_agent_usercodes` `['62','63','64']`, `call_agent_extensions` `['10','12','15']` | `forecasting/models.py:387`, read by `kpi.py:405`, `build_call_center_rollups.py`, `pic_analytics/queries/calls.py:259`, `insights/rules.py:187` | seed source for the crew; still the live source | read-only one release, then removed; readers use `identities()` |
| 5 | `KpiActualRollup` rows on branch 15 | 352 rows, 2024-08 → 2026-11; 13 metrics (8 always 0: cash, credit, delivery, insurance, net_revenue, order_count, regular — written by an earlier branch rollup before `build_kpi_rollups` skipped CC) | untouched; crew values go to shadow `CrewKpiRollup` | `KpiActualRollup.crew` FK, rows moved |
| 6 | `SalesTarget` scope branch = CC | 5 rows, Oct-2026 (call_count 2200, beauty 52 500, cash_delivery 1 060 000, gross_profit 250 000, customer_count 850). **`SalesTarget.actual_value()` resolves 4 of them over PurchaseHistory of branch 15 → 0**; only the KPI board (rollups) shows the real figure | reported in the comparison | crew scope on `SalesTarget`; actual via one crew function |
| 7 | PBX `AGENT_EXTS` 10–18, `HQ_ADMIN_EXTS`, `BRANCH_EXTS` | `pbx/management/commands/classify_pbx_extensions.py:18-35` (in the `branch_liveness_literals` baseline) | rewritten: crews + employee data + a confirmed-types data file; baseline line removed | — |
| 8 | Role `call_center` | permission role | stays (spec §6.6) | stays |
| 9 | SOFTECH `crmbranchcode='100'` | delivery/sync | stays; it is a SOFTECH fact | stays |
| 10 | `Branch.KIND_CALL_CENTER` | `branches/models.py:88` | stays (CC row keeps it until Part B) | stays as a closed-history kind |

## Global Constraints

- **Money gate (binding):** no incentive, target, KPI or forecast figure may change source in this PR. No reader of `KpiActualRollup`, `SalesTarget`, `ForecastResult`, `CallCenterConfig` changes behaviour. `CrewKpiRollup` is read by nothing except the comparison report and `Crew.has_history()`.
- No SOFTECH writes. SOFTECH reads only through `config.sybase.get_sybase_connection`; usercodes passed as `?` parameters, dates as `'YYYYMMDD'` strings built from `date` objects.
- Seed: one crew «الكول سنتر», type `call_center`, manual include rows dated from the first day of the earliest month with a CC rollup (office: 2024-08-01), open-ended, reason «بذرة الكول سنتر من إعداد الكول سنتر (piece 2b)». One row per usercode, one per extension; a usercode/extension owned by an `Employee` (`softech_usercode` / `pbx_extensions`) stores the employee FK. PBX `AGENT_EXTS` extensions not in `CallCenterConfig` (11,13,14,16,17,18) are **not** seeded by default (they would change `call_count` history); `--include-pbx-agent-extensions` adds them, and the comparison lists them as an owner question.
- Crew sales rule = `PurchaseHistory.softech_user` (SOFTECH `stktransm.usercode`) inside each identity span, never `cashiercode`.
- Generic sellers: a member code for which `apps.crews.unattributed.is_generic(...)` is true is labelled «بائع غير محدد» in every per-person row.
- Tests: `TEST_DB_NAME=test_crews2b_<n>`, `--keepdb`, focused modules, serial, never `--parallel`, never the full suite or sweeps without checking free RAM first. Python: `../../../venv/Scripts/python.exe` from the worktree root. Clone a migrated DB (`CREATE DATABASE test_crews2b_1 TEMPLATE test_crews_5`) instead of a 2-hour migrate when it exists.
- Audit: every seed / reseed writes `AuditLog.log('crew_cc_seeded' | 'crew_cc_reseeded', ...)`; rollup builds log their run in stdout only (they write no money source).

## Review Focus

1. A member whose span starts mid-month counts only invoices on or after that day — test `test_partial_month_span_counts_only_inside_span` (Task 2).
2. Distinct PIC count across two members who served the same customer counts the customer once — `test_pic_count_distinct_across_members` (Task 2).
3. SOFTECH unreachable or CDR unconfigured must not crash or silently zero: values marked «غير محسوب» and the explanation names the cause — `test_returns_unreachable_marked_not_zero` (Task 2), `test_report_marks_unrecomputable_call_count` (Task 3).
4. Re-running the seed must not duplicate rows; reseed must refuse when a non-shadow reference exists (Part B FKs) — `test_seed_idempotent_and_reseed_replaces` (Task 1).
5. Old `CC` readers return exactly what they returned before the helper refactor — `apps.tests.test_kpi_rollup`, `test_kpi_export`, `test_forecast_horizon`, `test_kpi_board_extract` all pass unchanged (Task 1 step 4).

---

### Task 1: Call-center crew seed, shadow rollup table, one CC lookup

**Files:**
- Create: `apps/crews/cc_seed.py`, `apps/crews/management/__init__.py`, `apps/crews/management/commands/__init__.py`, `apps/crews/management/commands/seed_call_center_crew.py`
- Modify: `apps/crews/models.py` (`CrewKpiRollup`; `has_history()` also true when rollups exist), `apps/crews/admin.py` (read-only registration)
- Create: `apps/crews/migrations/0002_crewkpirollup.py`
- Create: `apps/forecasting/call_center.py`; Modify: `forecasting/views.py`, `references.py`, `kpi_export.py`, `engine.py`, `rollup_refresh.py` (lookups only), `management/commands/build_call_center_rollups.py` (`get_cc_branch` kind)
- Test: `apps/tests/test_crews_cc_seed.py`

**Interfaces:**
- Produces:
  - `CrewKpiRollup(crew FK Crew CASCADE related_name='kpi_rollups', year int, month int, metric str ≤30, value Decimal(16,2), notes JSON list default [], computed_at auto_now)`; `unique_together (crew, year, month, metric)`; docstring: "shadow — read only by the comparison report until the owner signs off (piece 2b gate)".
  - `apps/forecasting/call_center.py::legacy_cc_branch() -> Branch | None` = `Branch.objects.filter(softech_branch_id='CC').first()`; `LEGACY_CC_KEY = 'CC'`. All six lookups call it.
  - `cc_seed.CC_CREW_NAME = 'الكول سنتر'`, `SEED_REASON` (text above), `seed_start() -> date` (first day of earliest CC rollup month, else first day of current month), `seed_plan(include_pbx_agent_extensions=False) -> list[dict]` (`{'kind': 'usercode'|'extension', 'value', 'employee_id'|None, 'label'}`), `seed(user=None, include_pbx_agent_extensions=False, dry_run=False) -> dict` (`{'crew_id', 'created', 'skipped', 'start'}`; idempotent: an existing open include for the same value is skipped), `reseed(user=None, **kw)` (deletes the crew's manual rows and `CrewKpiRollup` rows, then seeds; audited). `extra_pbx_agent_extensions() -> list[str]` = extensions of `AgentExtension` rows typed `agent` (active) minus the config extensions, sorted numerically.
  - Command `seed_call_center_crew [--dry-run] [--reseed] [--include-pbx-agent-extensions]`.
- [ ] **Step 1: Failing tests** `test_seed_creates_crew_and_dated_rows` (config codes/exts → 6 include rows from 2024-08-01 when a CC rollup for 2024-08 exists), `test_seed_links_employee_by_usercode_and_extension`, `test_seed_idempotent_and_reseed_replaces`, `test_seed_audited`, `test_has_history_true_with_rollups`, `test_get_cc_branch_creates_call_center_kind`, `test_legacy_cc_branch_helper_used_everywhere` (grep the five modules: no `softech_branch_id='CC'` left outside `call_center.py` and `build_call_center_rollups.py`).
- [ ] **Step 2: Run** `TEST_DB_NAME=test_crews2b_1 ../../../venv/Scripts/python.exe manage.py test apps.tests.test_crews_cc_seed --keepdb` → FAIL.
- [ ] **Step 3: Implement**; `makemigrations crews` → rename to `0002_crewkpirollup.py`.
- [ ] **Step 4: Run** the new module + `apps.tests.test_kpi_rollup apps.tests.test_kpi_export apps.tests.test_forecast_horizon apps.tests.test_kpi_board_extract apps.tests.test_kpi_rollup_refresh apps.tests.test_crews_membership` → PASS; `makemigrations --check --dry-run` clean.
- [ ] **Step 5: Commit** `feat(crews): seed the call-center crew + shadow crew rollups; one CC lookup`.

---

### Task 2: Crew KPI month from identity spans + `build_crew_rollups`

**Files:**
- Create: `apps/crews/kpi.py`, `apps/crews/softech_returns.py`, `apps/crews/management/commands/build_crew_rollups.py`
- Test: `apps/tests/test_crews_kpi.py`

**Interfaces:**
- Consumes: `identities(crew, start, end)` (2a), `KpiResolver` internals `_ph_qs`, `_line_qs`, `_PROFIT_EXPR`, `beauty_types`, `month_bounds`; `count_calls` (`apps/forecasting/callcount.py`); `fetch_cdr_rows`, `cdr_configured` (`config/issabel.py`); `KpiActualRollup.M_*` metric keys.
- Produces (`apps/crews/kpi.py`):
  - `Span = tuple[str, date, date]` (value, from, to inclusive).
  - `seller_spans(crew, start, end) -> list[Span]`, `extension_spans(crew, start, end) -> list[Span]` from `identities()` (`kind == 'softech_user'` / `'extension'`).
  - `sales_q(spans, prefix='') -> Q` — OR of `softech_user=v & invoice_date__date between`; empty spans → `Q(pk__in=[])`.
  - `compute_sales(year, month, spans) -> dict[metric, Decimal]` — the five metrics of `compute_call_center_month` with identical expressions, base querysets narrowed by `sales_q`.
  - `count_calls_spans(rows, spans) -> int` — keep rows whose `src` is a span value and whose `calldate[:10]` is inside that span, then `count_calls(kept, {v for v,_,_ in spans})`.
  - `@dataclass CrewMonth(kpis: dict, per_member: dict[tuple, dict], notes: list[str])`; `compute_crew_month(crew, year, month, *, returns=True, cdr_rows=None) -> CrewMonth` — sales from `compute_sales`; net of returns from `softech_returns.returns_for_spans` (on failure note `'returns_unreachable'`, kpis stay gross); `call_count` from `cdr_rows` if given, else live CDR when `cdr_configured()`, else omitted with note `'cdr_unavailable'`. `per_member` keyed by `Identity.member_key`, same metrics per member (calls per member by extension).
  - `apps/crews/softech_returns.py::returns_for_spans(year, month, spans, lookback_days=400) -> {'amount','profit','docs'}` — the `cc_softech` SQL with `o.usercode IN (...)` replaced by `OR`ed `(o.usercode = ? AND o.docdate >= ? AND o.docdate < ?)` per span (span = membership on the original sale's date; identities taken over `[month_start - lookback_days, month_end]`).
  - Command `build_crew_rollups [--crew ID] [--year Y --month M | --months N | --since YYYY-MM] [--cdr-csv PATH] [--no-returns]` — every non-archived `call_center` crew (spec §6.8: rollups only for call-center crews), writes `CrewKpiRollup` (`notes` stored per row).
- [ ] **Step 1: Failing tests** (PurchaseHistory/Line fixtures as in `test_kpi_rollup.py`; SOFTECH mocked at `apps.crews.softech_returns.get_sybase_connection`): `test_full_month_spans_equal_compute_call_center_month` (bit-equal for all five metrics), `test_partial_month_span_counts_only_inside_span`, `test_pic_count_distinct_across_members`, `test_cashiercode_never_credits` (an invoice whose cashier is a member but seller is not → excluded), `test_returns_subtracted_and_sql_parameterised` (assert `?` params, no usercode in SQL text), `test_returns_unreachable_marked_not_zero`, `test_call_count_spans_equal_count_calls_full_month`, `test_call_count_excludes_calls_outside_span`, `test_cdr_unavailable_note`, `test_build_command_writes_only_shadow_table` (`KpiActualRollup` count unchanged), `test_per_member_sums_to_total_for_additive_metrics`.
- [ ] **Step 2: Run** `TEST_DB_NAME=test_crews2b_2 ... test apps.tests.test_crews_kpi --keepdb` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(crews): call-center crew KPIs from dated identities + shadow rollup builder`.

---

### Task 3: Old-vs-new comparison report

**Files:**
- Create: `apps/crews/cc_comparison.py`, `apps/crews/management/commands/compare_call_center_crew.py`
- Modify: `apps/tests/new_value_registry.py` (entry `crew_cc_comparison`, absent narrowed to `{PENDING, CLOSED}` with reason "the report exists to show the old CC figures")
- Test: `apps/tests/test_crews_cc_comparison.py`

**Interfaces:**
- Consumes: Task 1 `legacy_cc_branch`, `cc_seed.seed`; Task 2 `compute_crew_month`, `compute_sales`, `count_calls_spans`; `KpiResolver.compute_call_center_month`, `cc_returns_from_softech`; `SalesTarget`, `ForecastResult`; `unattributed.generic_rule/is_generic`; `core.export_safety.safe_sheet` / `neutralise_formulas`.
- Produces:
  - `METRICS = ['cash_delivery','gross_profit','beauty','customer_count','pic_count','call_count']` (the CC board set, `forecasting/views.py` `CC_METRICS`).
  - `REASONS` dict code → Arabic + English text: `same` «مطابق», `drift_since_build` «تغيّرت بيانات المبيعات/المرتجعات منذ بناء الرقم القديم», `membership` «اختلاف أعضاء الطاقم عن أكواد الإعداد», `returns_unreachable` «لم يُحسب خصم المرتجعات (SOFTECH غير متاح)», `cdr_unavailable` «عدد المكالمات غير قابل لإعادة الحساب هنا (CDR غير متاح) — القيمة المخزنة فقط», `return_before_membership` «مرتجع لبيع سابق لبداية العضوية», `no_stored_value` «لا يوجد رقم مخزن قديم».
  - `compare(crew, start: (y,m), end: (y,m), *, returns=True, cdr_rows_by_month=None) -> dict` → `{'months': [{year, month, metric, stored, old_now, crew, diff_stored_crew, diff_old_crew, reason}], 'people': [{year, month, member_key, label, generic, metric, old, crew, diff}], 'targets': [{target_id, metric, period, target, achieved_board, achieved_salestarget_today, achieved_crew, pct_board, pct_crew, pace_board, pace_crew}], 'forecasts': [{scenario_id, scenario, metric, forecast, target}], 'questions': [str], 'totals': {...}}`. `old_now` = `compute_call_center_month` + `cc_returns_from_softech` + `count_calls` with `CallCenterConfig` lists; `old` per person = the same per config code; reason chosen per row in order: `no_stored_value`, `cdr_unavailable`, `returns_unreachable`, `same` (|diff| < 0.01), `membership` (old_now ≠ crew), `drift_since_build` (stored ≠ old_now).
  - `build_workbook(result) -> Workbook` — sheets «ملخص» (month × KPI rows, money format, RTL), «حسب الشخص», «المستهدفات», «التنبؤات», «أسئلة للمالك», «شرح الفروق»; every sheet through `safe_sheet`, then `neutralise_formulas(wb)`; no phone numbers.
  - `markdown_summary(result) -> str` — per-KPI totals across months, count of rows per reason, the target table and the questions (PR body attachment).
  - Command `compare_call_center_crew [--from 2024-08] [--to YYYY-MM] [--out PATH.xlsx] [--md PATH.md] [--no-returns] [--seed-in-transaction]` — `--seed-in-transaction` seeds the crew inside `transaction.atomic()` and rolls back after computing, so the report runs on a DB where the seed must not persist yet.
- [ ] **Step 1: Failing tests:** `test_identical_membership_gives_same_reason`, `test_extra_member_gives_membership_reason`, `test_stored_drift_reason`, `test_report_marks_unrecomputable_call_count`, `test_targets_section_shows_salestarget_zero_and_board_value`, `test_generic_member_labelled_unattributed_seller`, `test_workbook_sheets_and_no_formulas`, `test_seed_in_transaction_leaves_no_rows`.
- [ ] **Step 2: Run** `TEST_DB_NAME=test_crews2b_3 ... test apps.tests.test_crews_cc_comparison --keepdb` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it + `apps.tests.test_new_values` → PASS.
- [ ] **Step 5: Commit** `feat(crews): call-center old-vs-crew comparison report for owner sign-off`.

---

### Task 4: PBX extension classification from crews and data

**Files:**
- Modify: `apps/pbx/management/commands/classify_pbx_extensions.py` (rewrite)
- Create: `apps/pbx/classification.py`, `apps/pbx/data/confirmed_extension_types.json` (the owner-confirmed types moved out of code: `{"agent": [...10–18], "hq": [...], "branch": [...], "confirmed": "owner, before 2026-11"}`)
- Modify: `apps/tests/security/baselines/branch_liveness_literals.txt` (remove the `classify_pbx_extensions.py::<module>` line and its reason)
- Test: `apps/tests/test_pbx_classification.py`

**Interfaces:**
- Produces (`apps/pbx/classification.py`): `proposed_types(today: date) -> dict[str, tuple[str, str]]` extension → (type, source) with priority: (1) `agent` when an extension identity of any non-archived `call_center` crew on `today` (source `crew:<name>`); (2) an `Employee.pbx_extensions` entry → `hq` if the employee's assignment on `today` is at `hq_code()`'s branch, `branch` if at a retail branch (source `employee:<hr_number>`); (3) the confirmed data file (source `confirmed`). Gateways never touched. `classify(apply: bool, user=None) -> list[dict]` (`{extension, old, new, source}`); with `apply`, saves and writes one `AuditLog.log('pbx_extensions_classified', ...)` with the change list.
- Command: `classify_pbx_extensions [--apply]` — default is a dry run printing the change list and the «other» extensions left for review.
- [ ] **Step 1: Failing tests:** `test_crew_extension_becomes_agent`, `test_employee_extension_by_assignment_branch`, `test_confirmed_file_is_last_resort`, `test_gateway_untouched`, `test_dry_run_changes_nothing`, `test_apply_audited`, `test_new_crew_extension_needs_no_code_change`.
- [ ] **Step 2: Run** `TEST_DB_NAME=test_crews2b_4 ... test apps.tests.test_pbx_classification --keepdb` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it + `apps.tests.security.test_static_guards` → PASS (the baseline shrank by one line).
- [ ] **Step 5: Commit** `feat(pbx): classify extensions from crews and employee data, not fixed lists`.

---

### Task 5: Help, docs, real-data comparison, PR, owner gate

- [ ] `apps/help/content/crews.py` (AR + EN): the call-center crew, how its figures are made (seller = usercode inside the member's dates, calls by its extensions, «بائع غير محدد»), that the KPI board still shows the old figures until the owner approves the comparison; bump `updated` to `2026-11-18`. `apps/help/content/callcenter.py`: one line that the call-center agents list now lives in the crew «الكول سنتر» (data only — figures unchanged); bump `updated`. Run `apps.tests.test_help`.
- [ ] `docs/architecture/16_BRANCH_KPI_FORECASTING.md`: Phase-5 note pointing to the crew and the gate.
- [ ] Check free RAM; then on the local DB (read-only for money): `compare_call_center_crew --seed-in-transaction --from 2024-08 --out docs/superpowers/plans/2026-11-18-cc-crew-comparison.xlsx --md docs/superpowers/plans/2026-11-18-cc-crew-comparison.md` (run in background; SOFTECH and CDR reads only).
- [ ] Serial test run of every module touched (Tasks 1–4 + `test_help`, `test_new_values`, `security.test_static_guards`, `security.test_permission_matrix`), `makemigrations --check`, `manage.py check`.
- [ ] PR to `main` with the comparison summary in the body and the workbook committed; **do not merge**; ask the owner to sign off.

---

## Part B — held until the owner signs off the comparison (not built in this PR)

1. `KpiActualRollup.crew` FK + branch nullable + check (exactly one); CC rows moved to the crew value-for-value (or rebuilt from `CrewKpiRollup` if the owner prefers the crew figures); `CrewKpiRollup` dropped.
2. `SalesTarget` crew scope and `ForecastScenario`/`ForecastResult` crew scope; the 5 CC targets and 31 CC forecast rows migrated value-for-value; one `crew_actual(crew, metric, start, end)` for the target engine (fixes the CC `actual_value() = 0` finding).
3. Engine / KPI board / KPI export / references / rollup refresh read the crew through `legacy_cc_branch()`'s replacement; `build_call_center_rollups` reads `identities()`.
4. `CallCenterConfig` agent lists read-only (one release), then removed; `pic_analytics` and `insights` read the crew.
5. CC branch → kind `closed`; `get_cc_branch()` removed; acceptance test: every past month's achieved, target, achieved-vs-target and derived incentive figure identical before/after.
