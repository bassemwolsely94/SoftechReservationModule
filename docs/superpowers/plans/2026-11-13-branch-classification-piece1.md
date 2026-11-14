# Branch Classification (Piece 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `Branch.kind` becomes the only test of "is this branch live", new SOFTECH branches arrive as `pending`, per-branch exports follow the live branch list, and CI blocks new fixed branch lists.

**Architecture:** Extend `apps/branches` (queryset helpers, `pending` kind, `display_order`, a sellable-stock helper); move every liveness filter onto the helpers; make the KPI export and purchasing v2 pivot layouts computed; add a new-value test and a static guard with a ratchet baseline. No SOFTECH writes are added; SOFTECH-writing call sites only get *narrower* target sets.

**Tech Stack:** Django 4.2 / DRF, PostgreSQL, React 18 + Vite, openpyxl, Django test runner (`manage.py test`).

**Spec:** `docs/superpowers/specs/2026-11-13-branch-classification-and-crews-design.md` (§5, §8, §10)

## Global Constraints

- Liveness = `kind` only. `is_active` is never used to decide live/closed in new or changed code; `is_operational` only means "temporarily paused".
- Kinds: `hq`, `retail`, `call_center`, `closed`, `pending` (label «جديد — بانتظار التصنيف»).
- Initial `display_order`: 160 → 1, 170 → 2, 140 → 3, 150 → 4, 130 → 5, HQ 100 → 0, every other branch → 100 (then ordered by code).
- KPI export layout (owner 2026-11-13): "branches, then totals, then call center"; with today's 5 retail branches the workbook must be **cell-for-cell identical** to the current output.
- Catalog/POS stock excludes quarantine stores 102/103/105, HQ store `100:110`, and every store of a branch whose kind is `closed` or `pending` (owner 2026-11-13, covers test branch `B01`).
- SOFTECH-writing paths (`discount_approvals/replication.py`, `purchasing/rate_writer.py`, `purchasing/isr_writer.py`, `purchasing/isr_guards.py`) keep their quarantine set exactly `102/103/105`; their branch set may only shrink (add `kind` filter, keep `is_operational`/`db_host`).
- Incentives keep the quarantine-only set (money; out of scope).
- Every new/changed screen, tab or status updates `apps/help/content/<module>.py` (AR + EN) and bumps `updated`.
- Arabic UI wording: «سيرفر» not «خادم»; never show a bare branch code (use `BL`/`useBranchLabels`).
- Test DB: run with a unique `TEST_DB_NAME`; run sweeps serially, never `--parallel`.

**Deferred to piece 2 (crews), by the spec:** PBX extension classification (§5.6), retiring the `CC` row and its `'CC'` literals (§5.8/§6.6). The `CC` row is already kind `call_center`, so `live()`/`retail()` exclude it from day one.

## Review Focus

1. A branch synced from SOFTECH with a code never seen before (e.g. `230`) — expected: row created `pending`, not in any picker/export/analytics, one admin notification (deduped across syncs).
2. Sync run over an existing closed/retail branch — expected: `kind`, `is_operational`, `pos_enabled`, `display_order` untouched (pinned in Task 2).
3. A sixth retail branch in the KPI export — expected: no IndexError, 6 blocks, totals sum 6 rows, call-center block below totals (Task 5).
4. Two branches with the same `display_order` — expected: stable tie-break by code, not random order (Task 1).
5. `?scope=` with an unknown value on `/api/branches/` — expected: 400 with an Arabic message, not a silent fallback to all (Task 3).

---

### Task 1: Branch model — `pending` kind, `display_order`, queryset helpers

**Files:**
- Modify: `apps/branches/models.py`
- Create: `apps/branches/migrations/0013_branch_pending_kind_display_order.py`
- Create: `apps/branches/migrations/0014_close_test_branch_b01.py`
- Test: `apps/tests/test_branch_kind.py`

**Interfaces:**
- Produces:
  - `Branch.KIND_PENDING = 'pending'` in `KIND_CHOICES` with label «جديد — بانتظار التصنيف».
  - `Branch.display_order = PositiveIntegerField(default=100, db_index=True, verbose_name='ترتيب العرض')`; `Meta.ordering = ['display_order', 'softech_branch_id']`.
  - `BranchQuerySet.live()` (kind in hq, retail), `.retail()`, `.closed()`, `.pending()`, `.ordered()` (`display_order`, `softech_branch_id`); `operational()` kept as an alias of `live()` (existing callers).
  - `apps.branches.models.hq_code() -> str`: the `softech_branch_id` of the single `kind='hq'` row, cached per process; raises `ImproperlyConfigured` when not exactly one.
  - `Branch.is_live` property.

- [ ] **Step 1: Write the failing tests** in `apps/tests/test_branch_kind.py`:
  `test_live_is_hq_and_retail_only` (rows of every kind; `live()` returns hq+retail), `test_pending_excluded_from_live_and_retail`, `test_ordered_ties_break_by_code` (two rows `display_order=5`, codes 150/140 → 140 first), `test_hq_code_returns_single_hq`, `test_hq_code_raises_when_two_hq`.
- [ ] **Step 2: Run** `venv/Scripts/python.exe manage.py test apps.tests.test_branch_kind --keepdb` — FAIL (no `live`/`pending`).
- [ ] **Step 3: Implement** the model changes and migration 0013 (schema + data: set `display_order` per Global Constraints).
- [ ] **Step 4: Migration 0014** (data): `Branch.objects.filter(softech_branch_id='B01').update(kind='closed', is_operational=False, pos_enabled=False)`; reverse is a no-op. Add `test_migration_closes_b01` using the migration's function on a planted B01 row.
- [ ] **Step 5: Run** the test module — PASS. Run `manage.py makemigrations --check --dry-run` — "No changes detected".
- [ ] **Step 6: Commit** `feat(branches): pending kind, display order and live() helpers`.

### Task 2: Sync creates new branches as `pending` and tells admins

**Files:**
- Modify: `apps/sync/tasks.py:448-480` (`sync_branches`)
- Modify: `apps/notifications/models.py` (`NOTIFICATION_TYPES` + category map near line 183)
- Create: `apps/notifications/migrations/00NN_branch_pending_type.py` (choices only)
- Test: `apps/tests/test_branch_sync_pending.py`

**Interfaces:**
- Consumes: `Branch.KIND_PENDING` (Task 1).
- Produces: notification type `branch_pending` («🏷️ فرع جديد بانتظار التصنيف», category settings), sent with `Notification.send_to_admins(..., dedup_key=f'branch_pending:{code}')`.

- [ ] **Step 1: Failing tests:** `test_new_softech_branch_created_pending` (fake cursor row `('230','Name',...)` → `kind='pending'`, `is_operational=False`, `pos_enabled=False`), `test_new_branch_notifies_admins_once` (run twice → one notification), `test_existing_branch_curated_fields_untouched` (closed row with `display_order=7` stays closed/7 after sync).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement:** add `'kind': Branch.KIND_PENDING, 'is_operational': False` to `get_or_create` defaults; on `created` call `send_to_admins`.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(sync): new SOFTECH branches arrive pending`.

### Task 3: `/api/branches/` scopes, audited kind/order edits, settings screen

**Files:**
- Modify: `apps/branches/views.py:27-34, 58-66`, `apps/branches/serializers.py`
- Modify: `apps/audit/models.py` (`ACTION_CHOICES`: `branch_classified` «فرع — تغيير التصنيف», `branch_order_changed` «فرع — تغيير الترتيب»)
- Modify: `frontend/src/api/client.js:363-366`, `frontend/src/components/BranchSelect.jsx`, `frontend/src/components/BranchMultiSelect.jsx`, `frontend/src/pages/SettingsPage.jsx:324-352`
- Modify: `apps/help/content/admin.py` (branches settings screen: kinds, pending, display order)
- Test: `apps/tests/test_branch_api_scope.py`, `frontend/src/components/BranchSelect.test.jsx`

**Interfaces:**
- Produces:
  - `GET /api/branches/?scope=live|live_hq|retail|all|pending` — default `live`; `all`/`pending` admin only (403 otherwise); unknown scope → 400 `{'detail': 'نطاق الفروع غير معروف'}`. `?all=1` kept as an alias of `scope=all`. Results use `.ordered()`.
  - Serializer adds `kind_label`, `display_order` (writable by admin), `is_live`.
  - PATCH of `kind` or `display_order` writes an AuditLog row with before/after.
  - Frontend: `branchesApi.list({scope})`; `BranchSelect`/`BranchMultiSelect` accept `showClosed` (bool) and render closed rows with «مغلق»; the filter bars that show history get a «إظهار الفروع المغلقة» toggle which calls `scope=all`.
  - Note on `live` vs `retail`: `live` includes HQ; screens that never pick HQ pass `scope=retail`.

- [ ] **Step 1: Failing backend tests:** `test_default_scope_is_live` (closed, pending, CC absent; HQ present), `test_scope_retail_excludes_hq`, `test_scope_all_admin_only` (non-admin → 403), `test_unknown_scope_400`, `test_kind_change_audited` (before/after in AuditLog), `test_results_follow_display_order`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** views/serializer/audit.
- [ ] **Step 4: Failing frontend test** `BranchSelect.test.jsx`: closed branch hidden unless `showClosed`, shown with «مغلق» when set. Run `npx vitest run src/components/BranchSelect.test.jsx` — FAIL, implement, PASS.
- [ ] **Step 5: SettingsPage:** status chip from `kind` (`hq/retail` → «يعمل» or «موقوف مؤقتاً» when `!is_operational`, `closed` → «مغلق», `pending` → «جديد — بانتظار التصنيف», `call_center` → «كول سنتر»); admin dropdown to change kind; numeric display-order field. Help text updated + `updated` bumped; the help also says a newly classified branch needs its cash account mapped in «قواعد الترحيل» (finance GL raises `unmapped_account` until then, spec §5.6).
- [ ] **Step 6: Run** backend tests, `npx vitest run`, `npm run build` — all PASS.
- [ ] **Step 7: Commit** `feat(branches): scoped branch list, audited classification, settings UI`.

### Task 4: Move every liveness filter onto `kind`

**Files (modify; each line from the 2026-11-13 sweep):**
- Pickers/reports → `.live()` or `.retail()`: `apps/analytics/views.py:500,1917,1920`; `apps/batches/expiry_audit.py:599,831,1063,1113`; `apps/batches/rebalance.py:118`; `apps/delivery/branch_watchdog.py:110`; `apps/demand/views.py:1248`; `apps/notifications/phone_alerts/views.py:153`; `apps/payments/audit_views.py:125`; `apps/portal/views.py:283` (→ `Branch.objects.get(softech_branch_id=hq_code())`); `apps/purchasing/catchup.py:99`; `apps/purchasing/dead_stock.py:235` (drop `CLOSED='110'` constant); `apps/purchasing/engine.py:630`; `apps/stockcount/daily/service.py:426`, `views.py:214`; `apps/transits/management/commands/sync_in_transit.py:242`; `apps/forecasting/management/commands/build_kpi_rollups.py:37` (→ `.retail()`, drop the `'CC'` exclude); `apps/batches/stock_expiry.py:77`; `apps/config/views.py:235`; `apps/customers/status_drift.py:94`; `apps/forecasting/backtest.py:49`; `apps/pos_orders/pos_cancel_sync.py:61`; `apps/purchasing/distribution.py:156`; `apps/purchasing/management/commands/generate_isr.py:40`; listing `all()` sites `apps/gamification/challenges.py:48`, `apps/insights/views.py:139`, `apps/product_experience/services.py:278` (→ `.live()`); label maps over `all()` stay.
- `apps/forecasting/kpi.py:40-45` `analytics_branches()` → `Branch.objects.retail()` minus `analytics_excluded_branch_codes()` (paused retail branches stay in, spec §6.9).
- SOFTECH node selection (narrow only, keep existing filters, add `.live()`): `apps/discount_approvals/replication.py:46`, `apps/discount_approvals/views.py:655`, `apps/purchasing/rate_writer.py:297`, `apps/delivery/management/commands/sync_crm_orders.py:390`.
- Leave as-is (investigation commands, listed in the Task 7 baseline with reason "one-off probe"): `apps/customers/management/commands/investigate_pic_*.py`, `apps/sync/management/commands/investigate_*.py`, `test_replication_cycle.py`.
- HQ literals → `hq_code()`: module constants at `apps/finance/gl/softech_stock.py:21`, `finance/gl/statements.py:353`, `finance/queries/sybase_gl.py:119`, `insights/rules.py:711`, `purchasing/dead_stock.py:27`, `distribution.py:26`, `distribution_plan.py:35`, `isr_fulfillment.py:34`, `isr_guards.py:37`, `isr_softech.py:39`, `isr_writer.py:40`, plus `.exclude(softech_branch_id='100')` in `customers/status_drift.py:94`. Constants become call-time lookups (module import must not hit the DB).
- Test: `apps/tests/test_branch_liveness_callsites.py`

**Interfaces:**
- Consumes: `live()`, `retail()`, `hq_code()` (Task 1).

- [ ] **Step 1: Failing tests:** `test_analytics_branches_retail_minus_excluded` (paused retail included, HQ/closed/pending/CC excluded), `test_rate_writer_targets_unchanged_on_live_set` (planted HQ+5 retail+closed+pending: `_eligible_branches()` == today's set minus closed/pending), `test_dead_stock_ignores_closed_branches_by_kind`, `test_phone_alert_branch_list_live_only`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** the call-site moves listed above.
- [ ] **Step 4: Office-DB check (read-only):** run `manage.py shell` printing `_eligible_branches()` and `analytics_branches()` codes before/after on the office DB; expected after = `['130','140','150','160','170']` for analytics and the writer set minus `B01`. Paste the output into the PR.
- [ ] **Step 5: Run** the full `apps.tests` suite with a unique `TEST_DB_NAME` (serial) — PASS.
- [ ] **Step 6: Commit** `refactor: branch liveness from kind everywhere`.

### Task 5: KPI export and purchasing v2 pivot follow the live branch list

**Files:**
- Modify: `apps/forecasting/kpi_export.py:54-60, 105-120, 210-380, 495`
- Modify: `apps/purchasing/views.py:1136-1160, 1276`
- Modify: `apps/purchasing/isr_fulfillment.py:408` (`branch_column_order` → order by `display_order` via `apps.branches.models.order_codes(codes)`)
- Test: `apps/tests/test_kpi_export.py`, `apps/tests/test_purchasing_pivot_v2_branches.py`

**Interfaces:**
- Produces:
  - `apps.branches.models.order_codes(codes: Iterable[str]) -> list[str]` — sorts by `display_order`, then numeric code; unknown codes last.
  - In `kpi_export.py`: `KpiLayout(n_branches: int)` with `target_row(i)`, `ach_row(i)`, `total_tgt_row`, `total_ach_row`, `cc_label_row`, `cc_tgt_row`, `cc_ach_row`; for n=5 these equal today's 8..17 / 18 / 19 / 21 / 22 / 23. Every hard-coded `'X22'`/`'X23'`/`E23`-style reference to the *output* sheet goes through the layout; the reconciliation reader of *legacy* files keeps its fixed cells.

- [ ] **Step 1: Golden test:** `test_five_branch_export_identical_to_baseline` — generate the export on the existing 5-branch fixture *before* changing code, save every cell's value/formula to `apps/tests/fixtures/kpi_export_5_golden.json`, assert equality.
- [ ] **Step 2: Failing tests:** `test_six_branch_export_no_crash_and_shifted` (6 retail branches → 6 blocks, total formulas reference 6 target rows, call-center label on row 23), `test_branch_order_follows_display_order`, `test_pivot_v2_includes_new_live_branch` (a planted retail `230` gets a column), `test_pivot_v2_hq_column_by_kind`.
- [ ] **Step 3: Run** — golden PASS, the rest FAIL.
- [ ] **Step 4: Implement** `KpiLayout` and `order_codes`; pivot v2 iterates `Branch.objects.live().ordered()` with HQ found by kind.
- [ ] **Step 5: Run** — all PASS (golden still identical).
- [ ] **Step 6: Commit** `fix(exports): KPI and purchasing pivots follow the live branch list`.

### Task 6: One sellable-stock rule (adds store 110 and closed/pending branches to catalog/POS)

**Files:**
- Modify: `apps/batches/store_roles.py` (export `QUARANTINE_STORE_CODES = frozenset({'102','103','105'})`)
- Modify: `apps/catalog/models.py:6` (`EXCLUDED_STORE_CODES = QUARANTINE_STORE_CODES`, kept for SOFTECH-writing and incentives callers) and add `exclude_unsellable(qs) -> QuerySet` / `is_sellable(stock: ItemStock) -> bool`
- Modify (→ `exclude_unsellable` / `is_sellable`): `apps/catalog/pos_search.py:37`, `quicksell.py:71`, `serializers.py:46,85`, `universal.py:101`, `views.py:223,371,487`, `apps/customers/repeat_order.py:111`, `apps/dashboard/views.py:154`, `apps/offers/engine.py:135`, `apps/offers/targeting.py:188,227`
- Modify (→ import `QUARANTINE_STORE_CODES`, same values): `apps/batches/queries.py:109`, `procurement/engine.py:838-839`, `procurement/queries.py:147`, `purchasing/engine.py:655`, `purchasing/isr_guards.py:403`, `purchasing/isr_writer.py:39,432`, `purchasing/queries.py:162`, `shortage/stock_check.py:14`, `stockcount/daily/picker.py:30`, `stockcount/engine.py:71`, `supply/engine/allocation.py:26`, `supply/position.py:28` (SQL strings built from the constant with a fixed, non-user value — keep them out of the sql-from-text baseline by building the `IN (...)` list from the frozenset at import).
- Test: `apps/tests/test_sellable_stock.py`

**Interfaces:**
- Produces: `exclude_unsellable(qs)` excludes `softech_store_code__in=QUARANTINE_STORE_CODES`, `(branch.softech_branch_id=hq_code() AND softech_store_code='110')`, and `branch__kind__in=('closed','pending')`.

- [ ] **Step 1: Failing tests:** `test_store_110_at_hq_not_sellable`, `test_closed_branch_stock_not_sellable` (B01-like row), `test_pending_branch_stock_not_sellable`, `test_quarantine_still_excluded`, `test_isr_writer_quarantine_set_unchanged` (`isr_writer._EXCLUDED_STORES == {'102','103','105'}`).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Office-DB figures (read-only):** total sellable qty and value from `ItemStock` before/after, and the share in store 110 / B01; paste into the PR (spec §5.7 "the plan states the before/after totals").
- [ ] **Step 5: Run** — PASS; full `apps.tests` serial — PASS.
- [ ] **Step 6: Commit** `feat(catalog): one sellable-stock rule; 110 and closed branches excluded`.

### Task 7: New-value test and static guard

**Files:**
- Create: `apps/tests/test_new_values.py`, `apps/tests/new_value_registry.py`
- Modify: `apps/tests/security/static_scan.py`, `apps/tests/security/test_static_guards.py`
- Create: `apps/tests/security/baselines/branch_liveness_literals.txt`
- Modify: `CLAUDE.md` (Security definition of done: add "7. **New values:** its per-branch exports/reports are registered in `apps/tests/new_value_registry.py`.")

**Interfaces:**
- Produces:
  - `new_value_registry.EXPORTS: list[tuple[str, Callable[[], bytes|dict]]]` — Task-5 exports, ISR export, transits picking sheet, stock-count export, analytics branch report; each entry a zero-arg callable run against planted data.
  - `static_scan.branch_literal_sites(tree, path) -> set[str]` flags: `Branch.objects.filter(is_active=...)`/`filter(is_operational=True)` used as the only branch predicate; list/tuple/set literals of ≥2 three-digit strings in `{'100','130','140','150','160','170','110','120','180','190','200','210','220'}` whose context is a branch (variable name contains `BRANCH`/`branch`); assignments `HQ*='100'`. Doccode lists (names containing `DOC`/`doccode`) are not flagged.

- [ ] **Step 1: Failing unit tests** in `test_static_guards.py`: `test_branch_code_list_flagged`, `test_doccode_list_not_flagged`, `test_hq_literal_flagged`, `test_is_active_branch_filter_flagged`, `test_kind_filter_not_flagged`.
- [ ] **Step 2: Run** — FAIL; implement `branch_literal_sites`; PASS.
- [ ] **Step 3: Repo guard** `test_no_new_branch_literals` using `assert_matches_baseline('branch_liveness_literals', ...)`; generate the baseline from what is left after Tasks 4–6 (investigation commands and finance GL `seed.py` per-branch account maps, each with a one-line reason).
- [ ] **Step 4: New-value test** `test_new_values.py`: plants HQ + 5 retail + a 7th retail `230` + pending `240` + closed + CC; for each registry entry asserts no exception, `230` present, `240`/closed/CC absent; also `GET /api/branches/` default scope contains `230`, not `240`.
- [ ] **Step 5: Run** both — PASS.
- [ ] **Step 6: Commit** `test: new-value flow test and branch-literal guard`.

### Task 8: Finish

- [ ] **Step 1:** Full backend suite serial with a unique `TEST_DB_NAME`; `npx vitest run`; `npm run build`; `ruff`/lint as in CI — all PASS.
- [ ] **Step 2:** Run in a browser (`frontend/e2e` pattern): `/settings` branches tab shows kinds and order; a branch filter on `/purchasing` shows live branches only and the «إظهار الفروع المغلقة» toggle reveals closed ones.
- [ ] **Step 3:** Update `docs/architecture/11_ERP_INDEX.md` (branches row: kind is authoritative, pending), `07_BUSINESS_RULES.md` (branch rules), `02_MODULE_REGISTRY.md#branches`.
- [ ] **Step 4:** Open PR with the Task 4 and Task 6 office-DB before/after outputs; merge to main after all checks are green (never `--auto`); fast-forward the laptop folder.
