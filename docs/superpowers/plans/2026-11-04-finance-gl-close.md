# Finance General Ledger — Plan 3 of 3: Close & Reconcile — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let finance close a month on the ledger (checklist, closing stock at SOFTECH cost, auto-reversal, reopen), close the year, see sub-ledgers and ledger-vs-SOFTECH differences, push late SOFTECH changes into the current open month, and cut over: import their 2026 manual-only entries and validate Jan–Aug 2026 against their 31-08-2026 workbook.

**Architecture:** More modules in `apps/finance/gl/` (Plan 1's package). Period state changes live in one service (`gl/close.py`); every entry it creates goes through Plan 1's `save_draft` / `approve` / `reverse`, never around them. SOFTECH is read in exactly two SELECT-only reader modules (`gl/softech_stock.py`, `gl/softech_checks.py`); everything else reads Postgres. Sub-ledgers and the supplier check reuse the A/P reconciliation and receivables mirrors — no new matching logic.

**Tech Stack:** Django 5.2 + DRF, PostgreSQL, Sybase ASE read-only via `config.sybase.get_sybase_connection`, openpyxl, React 18 + Vite + TanStack Query + Tailwind.

**Spec:** `docs/superpowers/specs/2026-11-04-finance-general-ledger-design.md` (§9 screens 7–9, §10, §11, §11a, §13)

**Depends on:** Plan 1 (`docs/superpowers/plans/2026-11-04-finance-gl-foundation.md`) with rulings R1–R5 (`.superpowers/sdd/2026-11-04-finance-gl-foundation/progress.md` on `claude/finance-gl`), and Plan 2 merged first. From Plan 2 this plan uses only the names `GLParty`, `PostingRule`, `SourceException` and the contract in **Plan 2 contract** below; all Plan 2 access goes through `gl/plan2_adapter.py` (Task 1) so a rename in Plan 2 is a one-file fix.

## Global Constraints

- **Never write to SOFTECH.** SOFTECH reads only in `apps/finance/gl/softech_stock.py` and `apps/finance/gl/softech_checks.py`, SELECT-only, through `config.sybase.get_sybase_connection()` (the gate and read-only check apply); Sybase quirks: `SET ROWCOUNT n` not `TOP`, no `getColumnTypeName`. No other `gl/` module imports `config.sybase` (Plan 1's rule stays for them).
- Plan 1's constraints all hold: `Decimal(18,2)`; >2 decimals rejected; `ROUND_HALF_UP` only where rounding is unavoidable; approved entries immutable; one live entry per source key; all-branch users only (`sees_everything`); every state change audited with before/after through Plan 1's fatal `ledger._audit(...)` (as built: a failed audit write rolls the posting back — not `AuditLog.log`, which swallows errors); nothing before 2026-01-01.
- Every entry this plan creates is made with Plan 1's `save_draft` then `approve` / `reverse` (`gl/ledger.py`). No direct `LedgerEntry.objects.create` / `.update(status=...)` outside `gl/ledger.py`.
- Close, reopen and year-end need `ledger.finalize` (manager grant, Plan 1 Task 1). Explaining differences needs `ledger.approve`. Editing comparison checks and the closing-stock store map needs `ledger.edit`. Importing manual entries needs `ledger.create`; imported entries arrive as **drafts**.
- Months close in order: a month can close only if the previous month is closed (except January 2026, the first ledger month). Reopening is allowed up to 3 closed months back (owner, 2026-11-04; SystemSetting `gl_reopen_window_months`, default 3) and cascades: reopening month M also reopens every closed month after M, which are then closed again in order.
- Closing stock = SOFTECH's own stock-at-date snapshot `storebal_date` for the exact month-end date, valued `nowqty × nowcostprice`, signed (negative rows count), summed per store, each store rounded once to 2 decimals `ROUND_HALF_UP` (verified 2026-11-04: this reproduces finance's 8,739,116.86 for 31-12-2025 to the piastre — see Task 3).
- Closing stock **includes** the quarantine stores 102/103/105 and 152 (owner, 2026-11-04 — accounting correctness; overrides the spec's exclusion) and excludes only closed stores (store role `closed` via `apps.batches.store_roles.resolver()`, e.g. 110, 120). This is a GL-only rule: `store_roles`, FEFO, replenishment and every operational stock number keep excluding quarantine as today. Per-store overrides in the setting `gl_closing_stock_stores` (Task 3). With this default 31-12-2025 gives 8,739,116.86 = finance's 2026 opening 5301.
- Missing SOFTECH snapshots: from the November 2026 month-end on, finance runs SOFTECH's stock-at-date report every month-end (owner, 2026-11-04) and a missing store blocks the close. For month-ends up to SystemSetting `gl_stock_carry_forward_until` (default 2026-10-31) a store with no snapshot on that date takes its latest earlier snapshot, labelled «محمول من <date>» — so quarters stay exact while the monthly split inside a quarter shows the whole stock change in the month that has a snapshot.
- Arabic-first UI; every new screen/tab gets help in `apps/help/content/finance.py` (AR + EN, `updated: '<execution date>'`); tabbed pages call `useHelpTab(tab)`; `apps/tests/test_help.py` passes. Sortable grids (`useSortableRows` / `SortTh`); select/approve grids use `useGridKeyboard`; branch names via the branch-label helper, never bare codes; «سيرفر» not «خادم»; long jobs show `ProgressBar`; SOFTECH-fed screens get a refresh button + FreshnessBar domain.
- Tests run with a unique `TEST_DB_NAME`. SOFTECH is mocked in tests (patch the reader functions); real finance workbooks are never committed — tests build synthetic workbooks with openpyxl.

## Plan 2 contract (what this plan assumes Plan 2 provides)

Confirmed by Plan 2 (`docs/superpowers/plans/2026-11-04-finance-gl-drafting.md`, commit f909702d; re-checked against the copy on main fb19d444 on 2026-11-04 — same shape; `SourceException` reaches its document through `source_doc` FK → `GLSourceDoc.source_key`; `GLParty` party_type `supplier` covers both 2341 and 2351); re-check against Plan 2 as merged before Task 1 and adjust only `gl/plan2_adapter.py` if anything moved.

| Name | Used for | Shape (per Plan 2) |
|---|---|---|
| `GLParty` | sub-ledger names, supplier ↔ A/P recon link | `code` (= `LedgerLine.party_code`), `party_type`, `name`, `softech_personcode` (blank if none), `status` + property `is_confirmed` |
| `SourceException` | close checklist; late corrections | `kind` (incl. `closed_period_change`), `source_date`, `status` `open|resolved|ignored`, `original_entry` FK `LedgerEntry` (PROTECT). **Ruling P19:** `closed_period_change` is raised **once per group** (branch-day, party-day or document) on the group's first member (lowest source_key); `detail` holds `group_key`, `member_source_keys` and `entry_id`; the whole group's proposed lines are in the model field `proposed_lines` (`save_draft` line dicts). `original_entry` is set when the group's live entry is approved; when it is a draft, `original_entry` is null and `detail.entry_id` is set; null with no `entry_id` = a brand-new group. The other members are held without exceptions of their own; once this one resolves, Plan 2's engine releases them on its next run covering their date |
| drafting job | must not post into a non-open month | calls `gl.periods.accepts_postings(entry_date)` before any create/replace/reverse (Plan 2 ships a local fallback with the same contract — month missing or `open` — which Task 2 replaces); on `False` it raises `closed_period_change` and never reverses |
| `PostingRule` | not used here | — |
| `GLDraftRun` | close checklist note | `status` running|success|partial|failed, `date_from`, `date_to`, `source_types` (JSON list; `[]`/null = all types), `finished_at` (adapter only) |

Plan 2 rulings that bind this plan: **P21** — the drafting engine never replaces or reverses an entry an accountant has edited (it raises `ledger_error` with `detail.code='edited_by_user'`); Plan 3's correction entries carry `corrects` and a `#corr:` source key, so the engine never treats them as its own group entries. **P22** — scheduled drafting is off by default (`GL_DRAFTING_SCHEDULE_ENABLED=False`), so the close checklist shows when drafting last covered the month (Task 6). Full rulings: `.superpowers/sdd/2026-11-04-finance-gl-drafting/progress.md` on Plan 2's branch.

Plan 2 adds no `GLAccount.feed`; Task 1 adds it. Plan 2's source verification (shared note `gl-plan2-source-verification.md`): branch cash sales reproduce finance's 6002 within 0–1.7 %; card, purchase returns (5101) and VAT do not yet — Task 4 Step 1 sets `blocks_close=False` on any check whose SOFTECH side does not reproduce finance's figure.

## Review Focus

1. **The SOFTECH snapshot for a month-end is missing or incomplete** (SOFTECH has none for 31-01, 28-02, 30-04, 31-07-2026; 31-08-2026 has 15 of 17 stores) → up to the carry-forward date each missing store visibly uses its latest earlier snapshot; after it, close is blocked with the date and the missing stores named, and the instruction to run SOFTECH's stock-at-date report; nothing partial is ever posted. (Tasks 3, 6)
2. **Someone approves, reverses or a draft lands while a close is running, or the close fails half-way** (SOFTECH timeout) → approvals into a `closing` month get 409; a failed close returns the month to `open` with no close entries left behind. (Task 6)
3. **Reopening a month with later months closed, more than 3 closed months back, or December after year-end** → within the window it reopens that month and every later closed month and reverses all their close entries (year-end too), so the trial balance equals the one before those closes; beyond the window it is refused. (Tasks 6, 7)
4. **A SOFTECH document in a closed month changes twice** → the second correction nets against original + first correction; the account never carries the old amount twice. (Task 2)
5. **Finance's journal has rows that don't balance per entry, unknown account codes, entries mixing manual-only and SOFTECH-fed accounts, or the same file imported twice** → all shown in the preview, nothing written until confirmed, mixed entries skipped unless the accountant includes them one by one, and a re-import creates no duplicates. (Task 8)

## File Structure

| File | Responsibility |
|---|---|
| `apps/finance/gl/close_models.py` | `ClosingStockSnapshot`, `ClosingStockStore`, `GLSoftechCheck`, `GLComparisonLine` (re-exported from `apps/finance/models.py`) |
| `apps/finance/gl/plan2_adapter.py` | the only module touching Plan 2 models: `party_names`, `party_personcodes`, `open_exception_count`, `closed_period_change`, `mark_exception_resolved` |
| `apps/finance/gl/periods.py` | month periods: `month_period`, `previous_month`, `next_month`, `accepts_postings`, `first_open_period_after` |
| `apps/finance/gl/corrections.py` | late SOFTECH changes into closed months: `effective_lines`, `post_late_correction` |
| `apps/finance/gl/softech_stock.py` | SOFTECH `storebal_date` reader + store→branch map + valuation |
| `apps/finance/gl/softech_checks.py` | SOFTECH-side figures for the comparison (sales, expenses) — SELECT-only |
| `apps/finance/gl/compare.py` | ledger-vs-SOFTECH comparison: compute, persist, explain, drill-down |
| `apps/finance/gl/subledgers.py` | sub-ledgers + GL supplier vs A/P recon |
| `apps/finance/gl/close.py` | checklist, month close, auto-reversal, reopen, year-end |
| `apps/finance/gl/manual_import.py` | finance 2026 journal → draft entries (manual-only accounts) |
| `apps/finance/gl/validation.py` | Jan–Aug 2026 report vs the 31-08-2026 workbook |
| `apps/finance/gl/close_views.py`, `close_serializers.py` | REST for all of the above (urls added to `gl/urls.py`) |
| `apps/finance/recon_balances.py` | + `ap_balance_as_of` (same formula as `reconciliation_equation`, dated) |
| `apps/finance/management/commands/import_gl_manual_entries.py`, `gl_validate_workbook.py` | CLI |
| `apps/finance/migrations/00NN_gl_close.py`, `00NN_gl_compare_checks_seed.py` | the next free numbers after Plan 2's migrations (schema; seed checks) |
| `apps/sync/tasks.py`, `apps/sync/freshness.py` | nightly comparison refresh + `gl_compare` freshness domain |
| `frontend/src/pages/finance/gl/PeriodClosePage.jsx`, `SubledgersPage.jsx`, `SoftechComparePage.jsx` | screens 7–9 + cutover tab |
| `frontend/src/pages/ReconciliationPage.jsx`, `ContractReceivablesPage.jsx` | accept `?party=` / `?personcode=` deep links |
| `apps/tests/test_gl_*.py` | tests per task |

---

### Task 1: Close models, account fields, Plan 2 adapter

**Files:**
- Create: `apps/finance/gl/close_models.py`, `apps/finance/gl/plan2_adapter.py`
- Modify: `apps/finance/models.py` (re-export), `apps/finance/gl/models.py` (`GLAccount`, `LedgerEntry` fields below), `FinancialPeriod`
- Create: `apps/finance/migrations/00NN_gl_close.py`
- Test: `apps/tests/test_gl_close_models.py`

**Interfaces:**
- Consumes: Plan 1 `GLAccount`, `LedgerEntry`, `FinancialPeriod.status`; Plan 2 `GLParty`, `SourceException` (adapter only).
- Produces:
  - `GLAccount.feed` — `softech|manual|both`, default `manual`; the importer (Task 8) imports lines only on `manual`. If Plan 2 already added an equivalent field, reuse it and drop this one.
  - `LedgerEntry.corrects` — FK self null, `related_name='corrections'`, `on_delete=PROTECT` (a late-correction entry points at the closed-month original).
  - `FinancialPeriod.closing_stock` — FK `ClosingStockSnapshot` null, `SET_NULL`.
  - `ClosingStockSnapshot(period FK PROTECT, as_of date, read_at, read_by FK StaffProfile null, total Decimal(18,2), excluded_total Decimal(18,2), missing_stores JSON list, entry FK LedgerEntry null, reversal FK LedgerEntry null)` — one per close attempt; the latest with `entry` set is the period's.
  - `ClosingStockStore(snapshot FK CASCADE related_name='stores', store_code, store_name, branch FK null, included bool, rows int, value Decimal(18,2), snapshot_date date, carried bool)` — `carried=True` when `snapshot_date < as_of` (carry-forward, Task 3).
  - `GLSoftechCheck(key unique, label, kind movement|balance, account_codes JSON list, group_names JSON list, source sales|purchases|stock_at_cost|expenses|supplier_balance, sign debit|credit, per_party bool, blocks_close bool=True, tolerance Decimal(18,2)=1.00, is_active bool, order)`. Seeded by Task 4's data migration.
  - `GLComparisonLine(period FK, check FK GLSoftechCheck, branch FK null, party_code blank, ledger_amount, softech_amount, difference Decimal(18,2), computed_at, explanation text blank, explained_by FK null, explained_at null, explained_difference Decimal(18,2) null)`; unique `(period, check, branch, party_code)`. Property `needs_explanation = abs(difference) > check.tolerance and (explanation == '' or explained_difference != difference)`.
  - `plan2_adapter`: `party_names(codes: list[str]) -> dict[str, str]`, `party_personcodes(codes) -> dict[str, str]` (code → SOFTECH personcode, confirmed parties only), `open_exception_count(date_from, date_to) -> int` (status `open`, `source_date` in range), `closed_period_change(exception_id) -> ClosedPeriodChange(exception_id, status, original_entry: LedgerEntry | None, draft_entry_id: int | None, source_date, group_key, member_source_keys: list[str], proposed_lines: list[dict])` (from the fields `original_entry` and `proposed_lines`, and `detail.entry_id`, `detail.group_key`, `detail.member_source_keys` — Ruling P19, confirmed by Plan 2 2026-11-04), `mark_exception_resolved(exception_id, *, user, entry)` (Plan 2's engine releases the held members on its next run covering their date), `last_draft_run_through(period) -> datetime | None` (latest `GLDraftRun` with status `success`/`partial`, `source_types` empty or null (all types), `date_from <= period_start` and `date_to >= period_end`).

- [ ] **Step 1: Write the failing tests** — `test_comparison_line_unique_per_period_check_branch_party`, `test_needs_explanation_when_difference_changes_after_explaining`, `test_account_feed_defaults_manual`, `test_entry_corrects_protects_original` (deleting the original raises `ProtectedError`), `test_period_closing_stock_link`.
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_gl_close_models` — Expected: FAIL (import error).
- [ ] **Step 3: Implement** the models, adapter and migration (`makemigrations finance`, rename to `00NN_gl_close.py`; Arabic verbose names).
- [ ] **Step 4: Run** the tests and `python manage.py makemigrations --check --dry-run` — Expected: PASS, "No changes detected".
- [ ] **Step 5: Commit** — `feat(finance-gl): close and comparison models`

### Task 2: Periods helpers and late corrections

**Files:**
- Create: `apps/finance/gl/periods.py`, `apps/finance/gl/corrections.py`
- Modify: `apps/finance/gl/ledger.py` (`approve`, `reverse`)
- Test: `apps/tests/test_gl_corrections.py`

**Interfaces:**
- Consumes: Plan 1 `save_draft`, `approve`, `reverse`, `LedgerError`, `OPENING_DATE`; Task 1 `LedgerEntry.corrects`, adapter.
- Produces:
  - `month_period(d: date) -> FinancialPeriod` — Plan 1's `ledger._period_for(d)` made public (keep `_period_for` as an alias; do not add a second get-or-create), `previous_month(p) -> FinancialPeriod | None`, `next_month(p) -> FinancialPeriod`.
  - `accepts_postings(d: date) -> bool` — `month_period(d).status == 'open'`. Plan 2's drafting job calls this.
  - `first_open_period_after(d: date) -> FinancialPeriod` — earliest month period with `status='open'` and `period_start > d`, creating the next month if none.
  - `ledger.approve(..., _close_service: bool = False)` — when True, a period in status `closing` is accepted (only `gl/close.py` passes it). Otherwise unchanged; approving into `closing` raises `LedgerError('period_closing')` (new code, Arabic message «الفترة قيد الإقفال»), mapped to 409 in Task 10.
  - `ledger.reverse(...)` — when the original's period is not open: if `entry_date` is None, the reversal is dated `first_open_period_after(original.entry_date).period_start` and gets `corrects=original`; an explicit `entry_date` in a non-open period still raises `closed_period`.
  - `effective_lines(original: LedgerEntry) -> dict[tuple[account_code, branch_id, party_code], Decimal]` — signed net (debit − credit) of the original plus every approved entry with `corrects=original`.
  - `post_late_correction(original_id: int, new_lines: list[dict], *, user, reason: str, exception_id: int | None = None) -> LedgerEntry` — draft dated `first_open_period_after(original.entry_date).period_start`, `book=original.book`, `source_type=original.source_type`, `corrects=original`, `source_key` = `f'{group_key}#corr:exc{exception_id}'` when called for an exception (`group_key` from `detail.group_key`, **not** the document's source_key — Ruling P19; one exception = one group = one correction, and the live-source-key constraint makes a second post fail with `source_conflict`), else `f'{original.source_key}#corr:{YYYY-MM of correction date}:{n}'` (n = count of existing corrections + 1), description «تصحيح قيد <number> — <reason>». Lines = `new_lines` aggregated by (account, branch, party) minus `effective_lines(original)`; zero nets dropped; positive net → debit, negative → credit. All nets zero → `LedgerError('nothing_to_correct')`. Refuses if the original's period is open (`LedgerError('period_open')` — use normal re-drafting there). With `exception_id`: refuses unless the exception is `open` (`LedgerError('exception_not_open')`) and refuses when `draft_entry_id` is set and that entry is still a live draft (`LedgerError('exception_has_draft')`, «للمجموعة دي مسودة لسه — راجعها أو احذفها الأول»); `new_lines` are the group's whole proposed lines; calls `mark_exception_resolved` in the same transaction as the draft. Audited `gl_late_correction_drafted` with `group_key` and `member_source_keys`.
  - `post_late_document(exception_id: int, *, user) -> LedgerEntry` — for a `closed_period_change` exception with **no** `original_entry` and no `draft_entry_id` (a brand-new SOFTECH group in a closed month): one draft of the group's proposed lines as-is, dated `first_open_period_after(source_date).period_start`, `source_key` = `detail.group_key` (posted once per group; a second call hits `exception_not_open` or `source_conflict`), description noting the original document date; resolves the exception in the same transaction (Plan 2's next run releases the members). With an `original_entry`, the API calls `post_late_correction` instead; with `draft_entry_id` it refuses with `exception_has_draft`.

- [ ] **Step 1: Write the failing tests** —
  - `test_accepts_postings_false_for_closing_and_closed`
  - `test_first_open_period_after_skips_closed_months` (Jan–Mar closed, Apr open → correction for Feb dated 1 Apr)
  - `test_approve_into_closing_period_refused_unless_close_service`
  - `test_reverse_of_closed_month_entry_lands_in_first_open_month`
  - `test_correction_contains_only_the_net_difference` (original Dr 5100 1000 / Cr 2341 1000; new lines 1100 → correction Dr 5100 100 / Cr 2341 100)
  - `test_second_correction_nets_against_original_plus_first` *(Review Focus 4)* — after an approved first correction to 1100, new lines 1050 → Dr 2341 50 / Cr 5100 50
  - `test_correction_refused_when_original_period_open`
  - `test_nothing_to_correct`
  - `test_correction_resolves_exception` (adapter mocked)
  - `test_new_document_in_closed_month_drafted_in_first_open_month` (exception without `original_entry`)
  - `test_group_exception_posts_one_correction_keyed_by_group_key` (branch-day group of 3 documents, one exception → one correction whose `source_key` starts with `group_key`; a second call → `exception_not_open`, still one entry)
  - `test_exception_with_live_draft_refused` (`detail.entry_id` = a draft → `exception_has_draft`, nothing posted)
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_gl_corrections apps.tests.test_gl_ledger` — Expected: new tests FAIL, Plan 1's ledger tests still PASS.
- [ ] **Step 3: Implement** `periods.py`, `corrections.py` and the two `ledger.py` changes.
- [ ] **Step 4: Run** the same command — Expected: all PASS.
- [ ] **Step 5: Commit** — `feat(finance-gl): period helpers and late-change corrections into the open month`

### Task 3: SOFTECH stock at cost (read-only)

**Files:**
- Create: `apps/finance/gl/softech_stock.py`
- Test: `apps/tests/test_gl_softech_stock.py`

**Interfaces:**
- Consumes: `apps.batches.store_roles.resolver`, `QUARANTINE_ROLES`, `CLOSED`; `Branch.softech_branch_id`; `SystemSetting`.
- Produces:
  - `read_storebal(as_of: date) -> list[StoreRow]` — `StoreRow(store_code, rows: int, value: Decimal)`; one SELECT on HQ: `SELECT storecode, nowqty, nowcostprice FROM SOFTECHDB9.dbo.storebal_date WHERE storebaldate = ?`, products summed in Python `Decimal(str(qty)) * Decimal(str(cost))` per store, store total quantised once to 0.01 `ROUND_HALF_UP`. Also `snapshot_stores(as_of) -> set[str]` from `storebal_datem` (`storebaldate`, `storecode`) — which stores SOFTECH ran the report for on that date. Store names from `SOFTECHDB9.dbo.stores` (`storecode`, `storename`). Query timeout 600 s.
  - `store_map() -> dict[store_code, StoreRule(branch_code, included, label)]` — defaults: store code = branch code when a `Branch` has that `softech_branch_id`; HQ stores 100–105 → branch `100`; `152` → `150`; `included = role != CLOSED` with `role = resolver()(branch_code, store_code)` — quarantine stores are included (owner, 2026-11-04). Overridden per store by SystemSetting `gl_closing_stock_stores` (JSON `{store: {"branch": "150", "included": true}}`; invalid entries logged and ignored, like `store_roles._role_map`).
  - `expected_stores() -> set[str]` — included stores whose last non-empty snapshot (any date) had a non-zero value; a store missing from `snapshot_stores(as_of)` is reported missing.
  - `valuation(as_of: date) -> Valuation(as_of, stores: list[dict(store_code, store_name, branch_code, included, rows, value, snapshot_date, carried)], total, excluded_total, missing_stores: list[str], carried_stores: list[str])` — `total` = Σ included; nothing is rounded again after the per-store rounding. When `as_of <= gl_stock_carry_forward_until`, an expected store absent on `as_of` is read from its latest `storebal_datem` date before `as_of` (`carried=True`, listed in `carried_stores`, not in `missing_stores`); after that date it is listed in `missing_stores`.

- [ ] **Step 1: Verify against SOFTECH (read-only, record output in the task report).** Re-run for `as_of = 2025-12-31`: per-store values and the sum of all stores except `120` must equal **8,739,116.86** (finance's 2026 opening 5301; measured 2026-11-04: 100 891,792.71 · 101 59,555.78 · 102 513,281.37 · 103 146,911.64 · 104 232,890.48 · 105 2,084.56 · 130 980,046.74 · 140 1,096,578.26 · 150 1,820,201.20 · 152 601.47 · 160 1,857,154.20 · 170 1,138,018.45; 120 = 725.90). Also list `storebal_datem` dates in 2026 (on 2026-11-04: 23-01, 24-02 (2 stores), 31-03, 31-05, 30-06, 31-08, 30-09).
- [ ] **Step 2: Write the failing tests** (patch the cursor) — `test_store_total_rounded_once_half_up` (rows 1×0.333 + 1×0.333 + 1×0.334 → 1.00, not three rounded rows), `test_negative_rows_count`, `test_quarantine_included_closed_excluded_by_default`, `test_setting_overrides_store_inclusion_and_branch`, `test_invalid_setting_entry_ignored`, `test_missing_store_carried_forward_until_cutoff` *(Review Focus 1)*, `test_missing_store_reported_after_cutoff` *(Review Focus 1)*, `test_no_snapshot_for_date_after_cutoff_reports_all_expected_missing` *(Review Focus 1)*.
- [ ] **Step 3: Run** `python manage.py test apps.tests.test_gl_softech_stock` — Expected: FAIL.
- [ ] **Step 4: Implement** `softech_stock.py`.
- [ ] **Step 5: Run** — Expected: PASS.
- [ ] **Step 6: Commit** — `feat(finance-gl): closing stock valuation from SOFTECH storebal_date (read-only)`

### Task 4: Ledger-vs-SOFTECH comparison

**Files:**
- Create: `apps/finance/gl/softech_checks.py`, `apps/finance/gl/compare.py`
- Modify: `apps/finance/recon_balances.py` (add `ap_balance_as_of`)
- Create: `apps/finance/migrations/00NN_gl_compare_checks_seed.py` (data migration: the five seed checks below; backwards deletes them)
- Test: `apps/tests/test_gl_compare.py`

**Interfaces:**
- Consumes: Plan 1 `trial_balance`, `account_statement`; Task 1 models; Task 3 `valuation`; `apps.finance.queries.sybase_accounting` (`get_branchesales_by_month`, `get_dailyexpenses_by_branch_month`); `APInvoice`, `ReconParty`; adapter `party_personcodes`.
- Produces:
  - Seed checks: `sales` (movement, group المبيعات, source `sales`, credit), `purchases` (movement, group تكلفة المبيعات, source `purchases`, debit), `stock_at_cost` (balance, account 1390, source `stock_at_cost`, debit), `expenses` (movement, groups المصروفات العموميه / مصروفات بيع وتوزيع / مصروفات التشغيل, source `expenses`, debit), `supplier_balance` (balance, account 2341, source `supplier_balance`, credit, `per_party=True`, `blocks_close=False` — spec §11a).
  - SOFTECH sources, each `(period) -> dict[(branch_code | None, party_code | ''), Decimal]` plus `detail(period, branch_code) -> list[dict]` (daily or per-document rows):
    - `sales` — `get_branchesales_by_month(year, month)` net sales per branch (daily rows for detail).
    - `purchases` — Postgres `APInvoice` with `party_type='supplier'`: doccode 10 `doc_value` − doccode 120 `doc_value`, by `branchcode`, `docdate` in the month.
    - `stock_at_cost` — `valuation(period.period_end)` included stores by branch (per store in detail).
    - `expenses` — `get_dailyexpenses_by_branch_month(year, month)`.
    - `supplier_balance` — per GL party with a confirmed personcode: `ap_balance_as_of(party, period.period_end)`.
  - `ap_balance_as_of(party: ReconParty, as_of: date) -> Decimal | None` in `recon_balances.py` — `opening_balance + Σ invoices(docdate ≤ as_of, not return) − Σ returns − Σ payments(voucher_date ≤ as_of)`, OWED convention; `None` when `opening_balance_date > as_of`. Same terms as `reconciliation_equation`, no new matching.
  - `compute(period, *, check_keys: list[str] | None = None, user=None) -> list[GLComparisonLine]` — ledger side = net movement in the month (movement) or balance at `period_end` (balance) of the check's accounts/groups from approved + reversed entries, signed by `sign`; per branch, or per party when `per_party`. Upserts lines (keeps `explanation`), sets `computed_at`. Audited `gl_comparison_computed`.
  - `explain(line_id, *, user, text: str) -> GLComparisonLine` — sets explanation, `explained_difference = difference`; empty text refused. Audited.
  - `is_stale(period) -> bool` — True when any approved/reversed entry dated in the period has `approved_at` (or its reversal's) later than the oldest `computed_at` of the period's lines, or no lines exist.
  - `detail(line_id) -> dict` — `{ledger: account_statement rows for the check's accounts × branch/party in the month, softech: source detail rows, by_day: [{date, ledger, softech, difference}] (movement checks only)}`.
  - Read-only SOFTECH note: `softech_checks.py` reuses the existing `sybase_accounting` functions; the step below verifies their fields on 2026 data before trusting them.

- [ ] **Step 1: Verify sources (read-only, record in the task report).** For 2026-03: `get_branchesales_by_month(2026, 3)` total per branch vs finance's monthly sales sheet for March; `APInvoice` supplier purchases for March vs finance's monthly purchases sheet (note whether `doc_value` includes VAT and whether all suppliers are mirrored); `get_dailyexpenses_by_branch_month(2026, 3)` total. Record which field reproduces finance's figure; if a source does not, set that check's `blocks_close=False` in the seed and list it as an open question.
- [ ] **Step 2: Write the failing tests** (SOFTECH sources patched) — `test_movement_check_by_branch`, `test_balance_check_uses_period_end`, `test_supplier_check_per_party_uses_ap_balance_as_of`, `test_ap_balance_as_of_excludes_later_documents`, `test_recompute_keeps_explanation_and_flags_changed_difference`, `test_explain_requires_text`, `test_is_stale_after_new_approval`, `test_detail_by_day_sums_to_line`.
- [ ] **Step 3: Run** `python manage.py test apps.tests.test_gl_compare` — Expected: FAIL.
- [ ] **Step 4: Implement** `ap_balance_as_of`, `softech_checks.py`, `compare.py`.
- [ ] **Step 5: Run** the module plus `apps.tests.test_reconciliation` (or the existing recon test modules) — Expected: PASS.
- [ ] **Step 6: Commit** — `feat(finance-gl): ledger vs SOFTECH comparison with explanations and drill-down`

### Task 5: Sub-ledgers

**Files:**
- Create: `apps/finance/gl/subledgers.py`
- Test: `apps/tests/test_gl_subledgers.py`

**Interfaces:**
- Consumes: Plan 1 `LedgerLine`, `account_statement`; adapter `party_names`, `party_personcodes`; Task 4 `ap_balance_as_of`.
- Produces:
  - `SUBLEDGERS = {'suppliers': {'accounts': ['2341'], 'by': 'party'}, 'creditors': {'accounts': ['2351'], 'by': 'party'}, 'notes_payable': {'accounts': ['2343'], 'by': 'due_month'}, 'customers': {'accounts': ['1341'], 'by': 'party'}, 'employees': {'accounts': ['1351'], 'by': 'party'}, 'partners': {'groups': ['جارى الشركاء'], 'by': 'account'}}`.
  - `subledger(kind: str, date_from: date, date_to: date) -> dict` — rows `{key, name, opening, debit, credit, closing, link}` (closing in the account's nature, from approved + reversed lines), totals row, and `unassigned` (lines on the accounts with blank `party_code`) shown as its own row. `link`: suppliers → `{'to': '/reconciliation', 'party': <personcode>}`; customers → `{'to': '/finance/receivables', 'personcode': <personcode>}`; others none.
  - `notes_payable` rows: open per `cheque_no` (credit − debit ≠ 0 at `date_to`), grouped by `due_date` month (`'YYYY-MM'`, blank due date → «بدون تاريخ استحقاق»), each month with its cheques (`cheque_no, party, due_date, amount`).
  - `supplier_vs_ap(as_of: date) -> list[dict]` — per supplier party: `gl_balance` (2341, credit nature), `ap_balance` (`ap_balance_as_of`, or `None` with reason «لا يوجد ربط بسوفتيك» / «رصيد افتتاحي بعد التاريخ»), `difference`. Used by the supplier comparison check and the sub-ledger screen.

- [ ] **Step 1: Write the failing tests** — `test_supplier_rows_per_party_with_opening`, `test_unassigned_lines_row`, `test_notes_payable_grouped_by_due_month_and_paid_cheques_drop_out`, `test_partners_by_account`, `test_supplier_link_only_for_confirmed_party`, `test_supplier_vs_ap_difference`.
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_gl_subledgers` — Expected: FAIL.
- [ ] **Step 3: Implement** `subledgers.py` (aggregate queries, no per-line Python loops over the year).
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `feat(finance-gl): sub-ledgers linked to A/P reconciliation and receivables`

### Task 6: Month close, auto-reversal, reopen

**Files:**
- Create: `apps/finance/gl/close.py`
- Test: `apps/tests/test_gl_close.py` (`TransactionTestCase` for the concurrency test)

**Interfaces:**
- Consumes: Tasks 1–5; Plan 1 `save_draft`, `approve`, `reverse`.
- Produces:
  - `checklist(period) -> list[dict]` — items `{key, label_ar, ok: bool, blocking: bool, detail}` in this order:
    1. `previous_closed` (blocking; Jan 2026 always ok)
    2. `no_drafts` — no `draft` entries dated in the month (blocking; detail = count + link filter)
    3. `no_exceptions` — `open_exception_count(period_start, period_end) == 0` (blocking)
    4. `comparison_fresh` — `not is_stale(period)` (blocking)
    5. `comparison_explained` — no line with `needs_explanation` on a check with `blocks_close` (blocking)
    6. `suppliers_explained` — same for `supplier_balance` (not blocking; detail = unexplained count and total)
    7. `drafting_ran` — `last_draft_run_through(period)` (not blocking; P22: scheduled drafting is off by default, so the detail says when SOFTECH drafting last covered the whole month, or «التسجيل الآلي من سوفتيك لم يغطِّ الشهر كله»)
    8. `stock_snapshot` — `valuation(period_end).missing_stores == []` (blocking; detail names date and stores, and says «شغّل تقرير رصيد المخازن في تاريخ من سوفتيك لهذا التاريخ»); carried stores are listed in the detail as a non-blocking note («محمول من <date>»)
  - `close_month(period_id, *, user) -> FinancialPeriod` — (a) in a transaction with `select_for_update` on the period: status must be `open` and every blocking item ok, else `CloseError(code, items)`; set `closing`; commit. (b) outside the transaction: `valuation(period_end)` (slow SOFTECH read). (c) in a transaction: re-run the checklist (a draft may have appeared before `closing` took effect); create `ClosingStockSnapshot` + `ClosingStockStore` rows; post the closing-stock entry — date `period_end`, `book='closing'`, `source_type='closing_stock'`, `source_key=f'closing_stock:{YYYY-MM}'`, per branch `Dr 1390 / Cr 5302` with the branch on both lines, description «بضاعة آخر المدة <month> — تقييم سوفتيك», approved with `_close_service=True`; unless the month is December, post the auto-reversal as its **own** entry (mirrored lines via `save_draft` + `approve(_close_service=True)`, not `reverse()` — `reverse()` would mark the closing entry `reversed` and break reopen): date `next_month.period_start` (next month created open if missing), `book='closing'`, `source_type='closing_stock_rev'`, `source_key=f'closing_stock_rev:{YYYY-MM of the closed month}'`, description «عكس تلقائي لبضاعة آخر المدة <month>»; set `status='closed'`, `closed_by`, `closed_at`, `closing_stock`. December additionally calls `year_end_close` (Task 7) inside this step. Any exception in (b) or (c) → status back to `open`, no entries left (step c is one transaction), audited `gl_period_close_failed` with the error.
  - `reopen_month(period_id, *, user, reason: str) -> list[FinancialPeriod]` — `ledger.finalize`; reason required; refuses unless `closed`; `months` = this month and every later closed month; refuses with `CloseError('outside_window')` when M is not among the latest `gl_reopen_window_months` (default 3) closed months. In one transaction: set every month in `months` to `open` first, then for each `reverse()` every approved entry whose `source_key` is `closing_stock:{YYYY-MM}`, `closing_stock_rev:{YYYY-MM}`, and for a December `year_end:{year}` / `year_end_stock:{year+1}` (reversals dated as their originals — all those dates are now in open months; reversal mirrors carry a blank `source_key`, so re-closing can reuse the keys); clear `closing_stock`; audited `gl_period_reopened` with reason and the list of months. The months are then closed again one by one in order with `close_month`.
  - `CloseError(Exception)` with `.code` (`not_open|checklist|outside_window|not_closed|snapshot_missing`) and Arabic `.message`.

- [ ] **Step 1: Write the failing tests** —
  - `test_checklist_blocks_on_drafts_exceptions_stale_comparison_unexplained_and_missing_stock`
  - `test_suppliers_unexplained_does_not_block`
  - `test_close_posts_closing_stock_per_branch_and_reversal_on_first` (1390 balance at `period_end` = valuation total; on the 1st of next month 1390 back to 0)
  - `test_monthly_and_ytd_trading_account_after_two_closes` (Plan 1 `trading_and_pl` for Feb alone and Jan–Feb gives cost of sales = purchases − Δstock and purchases − (closing − opening))
  - `test_close_requires_previous_month_closed`
  - `test_snapshot_missing_blocks_and_posts_nothing` *(Review Focus 1)*
  - `test_softech_failure_returns_period_to_open_without_entries` *(Review Focus 2)*
  - `test_approve_during_closing_gets_period_closing` *(Review Focus 2)*
  - `test_reopen_reverses_close_entries_and_trial_balance_returns_to_before` *(Review Focus 3)*
  - `test_reopen_cascades_to_later_closed_months` (Jan–Mar closed, reopen Feb → Feb and Mar open, Jan closed; close Feb then Mar again works) *(Review Focus 3)*
  - `test_reopen_refused_beyond_three_closed_months` (Jan–Apr closed, reopen Jan → `outside_window`) *(Review Focus 3)*
  - `test_carried_stock_closes_with_note` (month-end before the cutoff with one store missing closes; store row `carried=True`)
  - `test_close_and_reopen_require_finalize` (service checks the profile via `matrix_allows`)
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_gl_close` — Expected: FAIL.
- [ ] **Step 3: Implement** `close.py`.
- [ ] **Step 4: Run** the module plus `apps.tests.test_gl_ledger apps.tests.test_gl_statements` — Expected: PASS.
- [ ] **Step 5: Commit** — `feat(finance-gl): month close with SOFTECH closing stock, auto-reversal and reopen`

### Task 7: Year-end close

**Files:**
- Modify: `apps/finance/gl/close.py`
- Test: `apps/tests/test_gl_year_end.py`

**Interfaces:**
- Consumes: Task 6; Plan 1 `trial_balance`, `GLAccountGroup.section`.
- Produces:
  - `year_end_close(year: int, *, user) -> tuple[LedgerEntry, LedgerEntry]` — called only from `close_month` for December (inside step c). (1) Closing entry dated 31-12, `book='closing'`, `source_type='year_end'`, `source_key=f'year_end:{year}'`: for every account in groups with section `trading` or `pl`, one line per (account, branch, party_code) clearing its year balance (party kept so an account with `requires_party=True` — Plan 1 ruling R1 — still approves; groups per ruling R3, so «مخزون آخر المدة» (5302, trading) is cleared and «بضاعة آخر المدة» (1390, balance sheet) is not) (approved + reversed entries from 1-1 to 31-12, including December's unreversed closing stock on 5302); the net to `2409` per branch (debit if a loss). Partners' accounts are balance-sheet and untouched. (2) Stock carry-forward dated 1-1 next year, `book='opening'`, `source_type='year_end_stock'`, `source_key=f'year_end_stock:{year+1}'`: per branch `Dr 5301 / Cr 1390` for December's closing stock (next year's opening stock, spec §11a). Both approved with `_close_service=True` (the 1-1 entry lands in the open January).
  - Carry-forward of balance-sheet balances needs no entry — Plan 1's `trial_balance` opening column already sums everything before `date_from`.

- [ ] **Step 1: Write the failing tests** — `test_pl_accounts_zero_after_year_end`, `test_2409_receives_net_result_per_branch`, `test_partners_untouched`, `test_next_year_opening_stock_on_5301_and_1390_zero`, `test_next_year_trial_balance_opening_equals_closing_bs`, `test_reopen_december_reverses_year_end_entries` *(Review Focus 3)*.
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_gl_year_end` — Expected: FAIL.
- [ ] **Step 3: Implement** `year_end_close`.
- [ ] **Step 4: Run** the module plus `apps.tests.test_gl_close` — Expected: PASS.
- [ ] **Step 5: Commit** — `feat(finance-gl): year-end close to retained earnings with stock carry-forward`

### Task 8: Importer for finance's 2026 manual-only entries

**Files:**
- Create: `apps/finance/gl/manual_import.py`, `apps/finance/management/commands/import_gl_manual_entries.py`
- Test: `apps/tests/test_gl_manual_import.py`

**Interfaces:**
- Consumes: Plan 1 `normalize_ar`, `save_draft`; Task 1 `GLAccount.feed`; `Branch` names.
- Produces:
  - `parse_journal(path: str, sheet_name: str | None = None) -> list[JournalRow]` — finds the header row by finance's pivot field names (spec §6): `رقم العملية` (account code), `Trans. Name`, `اسم الفرع`, `discreption` (finance's spelling), `condition` (`Debt`/`Credit`; also accept «مدين»/«دائن»), `balanc` (amount, credit rows negative), book (`نقدى`/`اجل`), `date`, optional `رقم القيد`, `suppliar code`, `customer code`, `كود الموظف`, `Payment cheque number`, `due date` (field names as they appear in the 31-08-2026 workbook pivots). `JournalRow(row_no, date, book, entry_ref, account_code, branch_name, description, side, amount, party_code, cheque_no, due_date)`. Rows without date/account/amount are reported, not guessed.
  - `group_entries(rows) -> list[JournalGroup]` — by `(date, book, normalize_ar(description))` (owner, 2026-11-04: this is how finance's يومية files group entries); by `entry_ref` only if such a column exists. Handling of `mixed` entries below is provisional until finance answers (owner is asking them). `JournalGroup(key, date, book, description, rows, balanced: bool, accounts_feed: set[str], status)` with `status` one of `manual` (all lines on `feed='manual'` accounts → import), `softech` (no manual lines → skip, drafts replace it), `mixed` (skip unless included), `unbalanced`, `unknown_account`, `unknown_branch`, `before_opening` (all four → not importable).
  - `resolve_branch(name: str) -> Branch | None` — `normalize_ar` match on `Branch.name`, then SystemSetting `gl_branch_aliases` (`{alias: softech_branch_id}`, defaults = finance's six branch names listed in Task 9); reused by Task 9.
  - `preview(path, sheet_name=None) -> dict` — `{manual_accounts: [{code, name}] (the list finance confirms, spec §11a), groups: [...], counts by status, totals}`.
  - `import_entries(path, *, user, include_mixed: list[str] = (), sheet_name=None) -> dict` — one draft per importable group: `book` cash/credit from نقدى/اجل, branch via `resolve_branch`, `source_type='manual_import'`, `source_key='manual_import:' + sha1(date|book|sorted lines)[:20]` — re-importing the same group hits Plan 1's live-source-key constraint and is counted `already_imported`. `mixed` groups listed in `include_mixed` are imported with **all** their lines. Audited `gl_manual_import` with counts. Never approves.
  - Command: `python manage.py import_gl_manual_entries <xlsx> [--sheet NAME] [--preview] [--include-mixed KEY ...]`.

- [ ] **Step 1: Write the failing tests** (synthetic workbook) — `test_header_found_by_pivot_field_names`, `test_groups_by_entry_ref_when_present_else_date_book_description`, `test_manual_group_imported_as_draft`, `test_softech_group_skipped`, `test_mixed_group_skipped_unless_included` *(Review Focus 5)*, `test_unbalanced_and_unknown_account_reported_not_imported` *(Review Focus 5)*, `test_reimport_creates_no_duplicates` *(Review Focus 5)*, `test_branch_alias_setting`, `test_preview_lists_manual_accounts`.
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_gl_manual_import` — Expected: FAIL.
- [ ] **Step 3: Implement** parser, grouping, preview, import, command.
- [ ] **Step 4: Run** — Expected: PASS. When finance's unprotected 2026 journal exists (spec §13), run `--preview` locally and record header row, columns found and status counts in the task report; adjust header aliases only.
- [ ] **Step 5: Commit** — `feat(finance-gl): import finance 2026 manual-only journal entries as drafts`

### Task 9: Jan–Aug 2026 validation report

**Files:**
- Create: `apps/finance/gl/validation.py`, `apps/finance/management/commands/gl_validate_workbook.py`
- Test: `apps/tests/test_gl_validation.py`

**Interfaces:**
- Consumes: Plan 1 `parse_trial_balance_sheet`, `trial_balance`, `normalize_ar`; Task 8 branch resolution (`resolve_branch(name) -> Branch | None`, exported from `manual_import.py`).
- Produces:
  - Workbook layout (pinned 2026-11-04 from `المركز المالى 31-08-2026.xlsx`, sheet names have a trailing space — match with `normalize_ar`). Every sheet is a pivot of `Sum of balanc`: header row 3, the group (`Sub account name`) only on its first row, `<group> Total` rows and a `Grand Total` row to skip, balances signed (debit +, credit −):
    - «ميزان الفروع» — `Sub account name | رقم العملية | Trans. Name | <one column per branch> | Grand Total`; branch columns are finance's branch names: «شركة الرزيقي» (HQ 100), «صيدلية د علياء النزهة2» (130), «صيدلية د بليغ الجيزة» (140), «صيدلية الرزيقى عين شمس» (150), «صيدلية باب الحديد» (160), «صيدلية د  محسن عباسية» (170) — seed these as the default `gl_branch_aliases` (Task 8).
    - «ميزان المراجعة» — same rows, columns `Debt | Credit | Grand Total` (YTD, all branches).
    - «المشتريات والمبيعات» — `Sub account name | رقم العملية | Trans. Name | 1 | 2 | … | 8 | Grand Total | المتوسط الشهرى`; month columns are integers; rows are 5100–5106 and 6002–6023.
    - Party sheets (`code | name | Credit | Debt | Grand Total`): «الموردين» (`suppliar code`), «الدائنون», «العملاء» (`customer code`); «مدينون» (`كود الموظف`, by MONTH); «اوراق الدفع» (year, due month, due date, cheque no., supplier).
  - `parse_branch_trial_balance(path, sheet_name='ميزان الفروع') -> list[BranchTBRow(code, branch_label, balance)]`, `parse_monthly_sheet(path, sheet_name='المشتريات والمبيعات') -> list[MonthRow(code, month: int, amount)]`, `parse_party_sheet(path, sheet_name) -> list[PartyRow(party_code, name, balance)]` — header row found by its labels (`رقم العملية` / `suppliar code` / `customer code` / `كود الموظف`), not by position.
  - `validate(path, *, through: date = date(2026, 8, 31)) -> dict` — `{ytd: [{code, name, branch, ledger, workbook, difference}], monthly: [{code, name, month, ledger, workbook, difference}], parties: [{kind, party_code, name, ledger, workbook, difference}] (suppliers 2341, creditors 2351, customers 1341, employees 1351 — checks the GLParty mapping), unmapped_branches, unknown_accounts, totals}`; ledger side from approved + reversed entries 2026-01-01..`through` (per branch for `ytd`, per month for `monthly`); only rows with `|difference| > 0.01` plus a totals row per account.
  - `export_validation(result) -> bytes` — xlsx, RTL, sheets «حسب الفرع» and «شهري», with an empty «التفسير» column for finance's written explanations (spec §11 step 4), `#,##0.00`.
  - Command: `python manage.py gl_validate_workbook <xlsx> [--through 2026-08-31] [--out report.xlsx]` — exit 1 when any difference remains.

- [ ] **Step 1: Re-check the layout** above against the real workbook (read-only, OneDrive Personal Vault must be unlocked by the owner; headers only in the task report — no figures in the repo).
- [ ] **Step 2: Write the failing tests** with a synthetic workbook in that layout (trailing-space sheet names, group-on-first-row, `Total`/`Grand Total` rows, integer month headers) — `test_branch_tb_parsed_per_branch`, `test_finance_branch_names_resolve_via_default_aliases`, `test_monthly_sheet_parsed`, `test_party_sheets_parsed`, `test_only_differences_listed_with_account_totals`, `test_unmapped_branch_reported`, `test_drafts_ignored`, `test_export_has_explanation_column`.
- [ ] **Step 3: Run** `python manage.py test apps.tests.test_gl_validation` — Expected: FAIL.
- [ ] **Step 4: Implement** `validation.py` and the command.
- [ ] **Step 5: Run** — Expected: PASS.
- [ ] **Step 6: Commit** — `feat(finance-gl): Jan–Aug 2026 validation report against finance's workbook`

### Task 10: REST API

**Files:**
- Create: `apps/finance/gl/close_views.py`, `apps/finance/gl/close_serializers.py`
- Modify: `apps/finance/gl/urls.py`
- Test: `apps/tests/test_gl_close_api.py`

**Interfaces:**
- Consumes: Tasks 2–9.
- Produces (prefix `/api/finance/gl/`; reuse Plan 1's `gl/views.py` helpers as built — `_perms(...)` (IsAuthenticated + `AllBranchOnly` + `matrix_permission('ledger', ...)`), `_ledger_error`, `_j`; add `period_closing`, `exception_not_open`, `exception_has_draft` to `CONFLICT_CODES`; Decimals as strings; `CloseError` → 400 `{code, detail}` except `not_open` → 409):

  | Method · path | Action | Notes |
  |---|---|---|
  | `GET periods/?year=` | view | months with status, closed_by/at, closing-stock total |
  | `GET periods/{id}/checklist/` | view | `checklist()` |
  | `POST periods/{id}/close/` | finalize | `close_month`; runs in a background thread (`core.threads.start_thread`) and returns 202; `GET periods/{id}/` shows `closing` until done |
  | `POST periods/{id}/reopen/ {reason}` | finalize | |
  | `GET periods/{id}/closing-stock/` | view | snapshot per store; `?preview=1` reads SOFTECH without posting |
  | `GET compare/?period=&check=` · `POST compare/refresh/ {period, checks?}` | view | refresh is SOFTECH-backed, audited |
  | `GET compare/lines/{id}/` | view | `detail()` |
  | `POST compare/lines/{id}/explain/ {text}` | approve | |
  | `GET/PATCH compare/checks/` | view / edit | edit: tolerance, accounts, groups, blocks_close, is_active; audited |
  | `GET subledgers/{kind}/?from&to` · `GET subledgers/suppliers-vs-ap/?as_of` | view | `?format=xlsx` needs export |
  | `POST corrections/ {original_id, lines, reason, exception_id?}` | create | `post_late_correction` |
  | `POST corrections/from-exception/ {exception_id, reason}` | create | one call per exception = per group (P19): `original_entry` set → `post_late_correction` with the group's proposed lines; `draft_entry_id` set → 409 `exception_has_draft`; else `post_late_document`. `exception_not_open` → 409 |
  | `POST manual-import/preview/` · `POST manual-import/ {include_mixed}` (multipart) | create | upload is size/type checked with `core.upload_safety` (`max_upload_bytes`, `capped_rows`), as Plan 1's `accounts_import` does |
  | `POST validation/` (multipart, `through`) | view + export | returns the xlsx |
  | `GET closing-stock-stores/` · `PATCH closing-stock-stores/` | view / edit | the `gl_closing_stock_stores` setting with defaults filled in; audited |

- [ ] **Step 1: Write the failing tests** — `test_close_needs_finalize` (accountant 403), `test_close_returns_202_and_period_shows_closing`, `test_checklist_shape`, `test_reopen_requires_reason`, `test_explain_needs_approve`, `test_check_patch_needs_edit`, `test_non_all_branch_user_403`, `test_manual_import_rejects_non_xlsx`, `test_validation_returns_xlsx`, `test_approve_into_closing_period_409`.
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_gl_close_api` — Expected: FAIL.
- [ ] **Step 3: Implement** serializers, views, urls.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `feat(finance-gl): close, comparison, sub-ledger and cutover API`

### Task 11: Scheduler and freshness

**Files:**
- Modify: `apps/sync/tasks.py` (job), `apps/sync/freshness.py` (`gl_compare` domain + reader)
- Test: `apps/tests/test_gl_compare_job.py`

**Interfaces:**
- Produces: job `gl_compare_refresh` — daily 03:30 (after the 02:15 finance sync) plus a catch-up on scheduler start if the last success is older than a day: `compute()` for every `open` month from January 2026 with `user=None`; per-month failures logged and skipped. Freshness domain `'gl_compare': {'label_ar': 'مقارنة الحسابات بسوفتيك', 'source': 'gl_compare', 'cadence_min': 1440, 'kind': 'snapshot'}` reading the latest `GLComparisonLine.computed_at`.
- [ ] **Step 1: Write the failing tests** — `test_job_computes_open_months_only`, `test_job_continues_after_month_failure`, `test_freshness_domain_reads_latest_computed_at`; extend `apps/tests/test_scheduler_jobs.py`'s job list if it enumerates ids.
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_gl_compare_job apps.tests.test_scheduler_jobs apps.tests.test_finance_freshness` — Expected: new tests FAIL.
- [ ] **Step 3: Implement** the job and domain.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `feat(finance-gl): nightly ledger-vs-SOFTECH refresh and freshness domain`

### Task 12: Frontend — period close (months, year, cutover)

**Files:**
- Modify: `frontend/src/api/client.js` (`glApi` methods for Task 10), `frontend/src/pages/FinanceHubPage.jsx` (tab «إقفال الفترة» 🔒), `frontend/src/App.jsx` (route `/finance/close`)
- Create: `frontend/src/pages/finance/gl/PeriodClosePage.jsx`

**Interfaces:**
- Produces: tabs `months` · `stock` · `cutover`, `useHelpTab(tab)`.
  - `months`: 2026 months grid (status chip open/closing/closed, closed by/at, closing stock); selecting a month shows the checklist inline (✓/✗, blocking items first, each with a link to where it is fixed — journal filtered to drafts, Plan 2's review inbox, comparison filtered to unexplained); «إقفال الشهر» enabled only when every blocking item is ok and the user has `ledger.finalize`; while `closing`, a `ProgressBar` and polling; «إعادة فتح» with an inline reason field (no modal) on the latest 3 closed months, stating which later months reopen with it. December shows that closing it also closes the year.
  - `stock`: closing-stock preview per store for a chosen month-end (included/excluded, branch, value, missing stores) and the store map editor (`ledger.edit`).
  - `cutover`: manual-import upload → preview (manual accounts list first, then groups by status with counts, `mixed` rows selectable with `useGridKeyboard`) → import; validation upload → download report and a short summary (differences count, total).
  - `data-tour`: `finance-gl-close-months`, `finance-gl-close-checklist`, `finance-gl-close-action`, `finance-gl-close-stock`, `finance-gl-cutover-import`, `finance-gl-cutover-validate`.
- [ ] **Step 1: Implement** client methods, route, tab, page.
- [ ] **Step 2: Run** `cd frontend && npm run build` — Expected: success (`check-sort` passes).
- [ ] **Step 3: Verify in the app** (preview server, dev DB with a few approved entries and SOFTECH reads mocked or a month with a snapshot, e.g. 2026-03): checklist shows blocking items; after clearing them, close posts the stock entry and the month shows closed; reopen with a reason returns it to open; console clean. Screenshot in the task report.
- [ ] **Step 4: Commit** — `feat(finance-gl): period close screen with cutover tools`

### Task 13: Frontend — sub-ledgers and SOFTECH comparison

**Files:**
- Create: `frontend/src/pages/finance/gl/SubledgersPage.jsx`, `frontend/src/pages/finance/gl/SoftechComparePage.jsx`
- Modify: `FinanceHubPage.jsx` (tabs «الأستاذ المساعد» 📚, «مقارنة سوفتيك» 🔍), `App.jsx` (`/finance/subledgers`, `/finance/softech-compare`; add `'accountant'` to the `/reconciliation` `RequireRole` — owner, 2026-11-04; the recon API already needs only `finance.view`, which `accountant` has), `frontend/src/pages/ReconciliationPage.jsx` (read `?party=<personcode>` and preselect that supplier), `ContractReceivablesPage.jsx` (read `?personcode=` and open that contract)

**Interfaces:**
- Produces:
  - `SubledgersPage`: tabs per `SUBLEDGERS` kind (`useHelpTab`), date range, rows with opening/debit/credit/closing, «بدون طرف» row, click → Plan 1 account statement filtered by party; supplier rows link to `/reconciliation?party=`, customer rows to `/finance/receivables?personcode=`; notes payable grouped by due month (expandable); suppliers tab has a «مقارنة بسداد الموردين» toggle showing `supplier_vs_ap`. Excel per tab.
  - `SoftechComparePage`: month picker, FreshnessBar (`gl_compare`) with refresh, grid check × branch (or party) with ledger / SOFTECH / difference, red when `needs_explanation`; row opens a side panel with `detail()` (by-day table, ledger lines, SOFTECH rows) and the inline explanation box (`ledger.approve`); checks editor for `ledger.edit`.
  - `data-tour`: `finance-gl-subledger-tabs`, `finance-gl-subledger-link`, `finance-gl-compare-grid`, `finance-gl-compare-detail`, `finance-gl-compare-refresh`.
- [ ] **Step 1: Implement** both pages and the two deep-link reads.
- [ ] **Step 2: Run** `cd frontend && npm run build` — Expected: success.
- [ ] **Step 3: Verify in the app**: a supplier row's link opens reconciliation on that supplier; a comparison line explains and turns neutral; refresh shows progress. Screenshot.
- [ ] **Step 4: Commit** — `feat(finance-gl): sub-ledgers and ledger-vs-SOFTECH comparison screens`

### Task 14: Help, docs, full regression

**Files:**
- Modify: `apps/help/content/finance.py` — screens `finance.gl_close` (tabs months/stock/cutover, statuses open/closing/closed explained), `finance.gl_subledgers` (per-tab), `finance.gl_softech_compare`; AR + EN; `updated` = execution date; targets from Tasks 12–13. Update `finance.gl_journal` help: late corrections («تصحيح قيد») and the `period_closing` refusal.
- Modify: `docs/architecture/35_FINANCE_GENERAL_LEDGER.md` (close flow, store map, comparison checks, corrections, cutover commands, Plan 2 contract), `04_API_REGISTRY.md`, `05_UI_REGISTRY.md`, `03_DATABASE_DICTIONARY.md`.
- [ ] **Step 1: Write** help and docs.
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_help apps.tests.test_gl_close_models apps.tests.test_gl_corrections apps.tests.test_gl_softech_stock apps.tests.test_gl_compare apps.tests.test_gl_subledgers apps.tests.test_gl_close apps.tests.test_gl_year_end apps.tests.test_gl_manual_import apps.tests.test_gl_validation apps.tests.test_gl_close_api apps.tests.test_gl_compare_job` plus Plan 1 and Plan 2 `test_gl_*` modules (unique `TEST_DB_NAME`) — Expected: all PASS.
- [ ] **Step 3: Run** `python manage.py test apps.tests` and `cd frontend && npm run build` — Expected: no new failures vs main.
- [ ] **Step 4: Commit** — `docs(finance-gl): close and reconcile help, architecture doc 35`

---

## After this plan (owner and finance steps, not code)

1. Finance runs SOFTECH's stock-at-date report on every month-end from November 2026 on (earlier gaps are carried forward, see Global Constraints).
2. Finance answers how entries that mix manual-only and SOFTECH-fed accounts should be imported (Task 8, provisional default: skipped unless included one by one).
3. Import manual entries (`--preview` first, finance confirms the manual-account list), approve them, run `gl_validate_workbook` until every difference is fixed in a rule or explained in the «التفسير» column.
4. Close Jan → Aug in order; Sep–Oct the same; go-live = the first open month after sign-off (spec §11a).
