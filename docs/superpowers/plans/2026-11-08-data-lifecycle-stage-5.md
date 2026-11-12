# Data lifecycle Stage 5 (data health screen) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give admins, supervisors and quality managers one screen, `/data-health` (صحة البيانات), showing what is growing, what the rules did, which files are held, and which data problems are open.

**Architecture:** The screen and API sit in the existing `apps/data_lifecycle`. A daily `DataHealthSnapshot` (new) adds database totals, media sizes and problem counts next to Stage 3's per-table `TableSizeSnapshot`, which is reused. The screen reads stored snapshots; only a forced refresh recomputes. Rule changes, previews and restore call Stage 3's `policy.set_policy`, `runner.preview_rule` and `holding.restore`, with no new rule logic.

**Tech Stack:** Django/DRF, PostgreSQL, React/Vite, TanStack Query, Tailwind.

**Spec:** `docs/superpowers/specs/2026-11-07-data-lifecycle-design.md` (§6 Stage 5, §7, §9).

## Global Constraints

- Company-level by nature: no branch scoping; the code says so and names who may see it.
- Roles: admin everything. Supervisor and quality manager: Growth and Problems only. Everyone else: nothing.
- Rules (read or change), preview, held-file list, thumbnail and restore are admin only, checked on the server with `core.permissions.IsAdminRole`.
- No SOFTECH reads or writes. Problem counts use local mirrors.
- Customer data is counts only: no names or phones in any response, log or error. No exports in this version.
- Held files never expose `hold_path`, `original_path`, `sha256` or `rows` in any response.
- Prescription files never get a thumbnail or URL; `pos_rx` samples count as prescriptions. Thumbnails are an allowlist (Task 2), so an unknown kind gets none.
- Screen: Arabic RTL, every grid sortable (`useSortableRows` + `SortTh`), forced-refresh button (`RefreshButton`), no modals for routine actions (the reason field is inline).
- Tests run serially with a unique `TEST_DB_NAME`. Never bare `git stash`. No new `# nosec` / `# noqa` without a written reason.

## Review Focus

1. Thumbnail request for a held prescription, a `pos_rx` sample, or an orphan file from a prescription folder: 404, whoever asks.
2. A new install with zero or one snapshot: every tab renders, the forecast says it needs more days, nothing raises.
3. Sizes shrank after a cleanup (negative rate): the forecast shows no date rather than a negative one.
4. One problem count fails (missing table, timeout): that row shows no number, the others and the snapshot still save, the daily run does not fail.
5. Two people press refresh at once: one computation runs; the second gets the same "running" answer.

---

### Task 1: Daily snapshot

**Files:**
- Modify: `apps/data_lifecycle/models.py`; `apps/sync/maintenance.py` (add step `retention:data_health` right after `retention:purge_held`, with a lazy-import wrapper like `_snapshot_table_sizes`); `config/settings.py` (`DATA_HEALTH_DISK_LEVEL_PERCENT = config(..., default=80, cast=int)`, beside the `LIFECYCLE_` settings)
- Create: `apps/data_lifecycle/health.py`, `apps/data_lifecycle/problems.py`, migration `apps/data_lifecycle/migrations/0002_datahealthsnapshot.py` (via makemigrations; if Stage 3 has added a 0002, take the next number)
- Test: `apps/tests/test_lifecycle_health.py`

**Interfaces:**
- Produces: model `DataHealthSnapshot`: `day` (DateField, unique), `taken_at`, `db_bytes`, `empty_bytes`, `media_bytes`, `media_files`, `disk_total_bytes`, `disk_free_bytes` (all BigInteger default 0), JSON default dict: `empty_by_table` `{table: bytes}`, `media_by_folder` `{folder: {bytes, files}}`, `media_by_type` `{type_key: {bytes, files}}`, `problems` `{key: int | None}`. Ordering `-day`.
- Produces: `health.take_snapshot(include_tables=False) -> DataHealthSnapshot | None`: `update_or_create` on today's local date. Never raises (logs, returns None). With `include_tables=True` also calls `runner.snapshot_table_sizes()` first (forced refresh only; the daily job has its own step).
- Produces: `health.scan_media(index) -> (total_bytes, files, by_folder, by_type)`. Walks `MEDIA_ROOT` with `os.scandir`. Folder is the first path part, except `invoice_bundles/pages`, which stays separate. `type_key` is `app.Model.field` of the sorted-first ref in the `build_reference_index()` index, else `'unreferenced'`. A missing `MEDIA_ROOT` gives zeros.
- Produces: `problems.PROBLEMS`: tuple of frozen dataclass `Problem(key, label_ar, label_en, owner_role_ar, link, note_ar, count)`, where `count` is a zero-arg callable. `problems.count_all() -> {key: int | None}`: each count in its own try; a failure logs the key and exception class only, and gives None.

Problems (key, count, link, owner role). "Over 90 days" uses the date named, cut at now − 90 days:

| key | count | link | owner |
|---|---|---|---|
| `customers_shared_phone` | `Customer` rows, non-empty `phone`, whose phone appears on more than one row | `/customers/merge` | خدمة العملاء |
| `phones_bad_format` | non-empty `phone` not matching `^01[0125][0-9]{8}$`; note: some are landlines | None | خدمة العملاء |
| `customers_no_sales` | `Customer` with no `PurchaseHistory` (`~Exists`); note: not proof of junk | None | الإدارة |
| `ingredients_pending` | `IngredientParseCandidate` status pending or needs review | `/composition` | الجودة |
| `items_undefined_scientific` | `Item.name_scientific` case-insensitively in `{'undefined', 'undefined item'}` | `/composition` | الجودة |
| `followups_missed_90d` | `FollowUpTask` status `missed`, `due_date` older | `/followups` | المتابعات |
| `deliveries_stuck_90d` | `DeliveryOrder` not in `TERMINAL_STATUSES`, `created_at` older | `/delivery` | التوصيل |
| `supply_open_90d` | `SupplyCase` in `OPEN_STATUSES`, `first_detected_at` older | `/supply` | المشتريات |
| `stockcount_open_90d` | `StockCountSession` not `closed`, `created_at` older; exclude mode `daily` only if the design baseline demands it (it does not: keep them) | `/stock-count` | المخزون |
| `pos_ready_90d` | `SoftechSalesOrder` `STATUS_READY`, `created_at` older; note: never auto-closed | `/pos` | نقاط البيع |

`empty_bytes`: sum of `expected_gain` from `apps.sync.management.commands.reclaim_space.table_info` for each table at or above `runner.TABLE_SIZE_MIN_BYTES`, each table in its own try; `empty_by_table` keeps the non-zero values. Reused, not re-derived. `db_bytes`: `pg_database_size(current_database())`. Disk: `shutil.disk_usage(MEDIA_ROOT)`, zeros on failure.

- [ ] **Step 1:** Write failing tests in `apps/tests/test_lifecycle_health.py`:
  - `test_scan_media_groups_by_folder_and_type`: temp `MEDIA_ROOT` with one referenced file (index built by hand), one orphan, one under `invoice_bundles/pages/batch_1/`; assert totals, three folders, `by_type['unreferenced']['files'] == 2`.
  - `test_scan_media_missing_root_is_zero`.
  - `test_count_all_survives_one_failure` (Review Focus 4): patch one problem's `count` to raise; its value is None, others are ints, and the log holds no phone.
  - `test_shared_phone_counts_rows_not_groups`: three rows on one phone, one on another, one blank → 3.
  - `test_followups_missed_only_past_90_days`, `test_supply_open_excludes_terminal`, `test_bad_phone_format`.
  - `test_take_snapshot_same_day_updates_one_row`, `test_take_snapshot_never_raises` (patch `scan_media` to raise → returns None).
  - `test_daily_retention_has_data_health_step`: the step list contains `retention:data_health` after `retention:purge_held`.
- [ ] **Step 2:** Run them: `venv python manage.py test apps.tests.test_lifecycle_health`. Expected: FAIL on missing module.
- [ ] **Step 3:** Implement. Add `DataHealthSnapshot` with the same company-level docstring note as the other models.
- [ ] **Step 4:** Run `apps.tests.test_lifecycle_health apps.tests.test_lifecycle_runner`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(lifecycle): daily data health snapshot with media sizes and problem counts`.

### Task 2: API and RBAC

**Files:**
- Create: `apps/data_lifecycle/views.py`, `apps/data_lifecycle/urls.py`, `apps/data_lifecycle/reports.py`, `apps/users/migrations/0054_data_health_module.py` (next free number after re-checking; alter choices + grants in the style of `0045_counselling_module.py`)
- Modify: `config/urls.py` (`path('api/data-health/', include('apps.data_lifecycle.urls'))`); `core/middleware/module_access.py` (`'data-health': 'data_health'` in `MODULE_BY_PREFIX`; in `required()`: `POST /api/data-health/refresh/` needs `('view',)`); `apps/users/models.py` (`('data_health', 'صحة البيانات')` in `MODULE_CHOICES`); `apps/users/management/commands/seed_permissions.py` (module list + admin all, supervisor and quality_manager `{'view'}`, nobody else); `apps/tests/security/permission_matrix.py` (`BRANCH_SCOPE['data_health'] = 'all — company-level by nature; admin, supervisor and quality manager only'`) and regenerate `docs/security/PERMISSION_MATRIX.md`
- Test: `apps/tests/test_data_health_api.py`

**Interfaces:**
- Consumes: Task 1's model, `problems.PROBLEMS`, `health.take_snapshot`.
- Produces routes (all under `/api/data-health/`). Viewers = `IsAuthenticated, matrix_permission('data_health', post=('view',))`; admin = `IsAuthenticated, IsAdminRole`.

| Route | Who | Response / effect |
|---|---|---|
| `GET growth/` | viewers | see below |
| `GET problems/` | viewers | `{as_of, refreshing, problems: [{key, label_ar, label_en, owner_role_ar, link, note_ar, count, previous_count, change}]}` |
| `POST refresh/` | viewers | 202 `{refreshing: true}`; starts one background `take_snapshot(include_tables=True)` |
| `GET rules/` | admin | `{file_rules_locked, rules: [...]}` |
| `PATCH rules/<key>/` | admin | body `mode?`, `keep_days?`, `reason`; `set_policy`; `PolicyRefused` → 400 `{detail}`; returns that rule's row |
| `POST rules/<key>/preview/` | admin | `preview_rule`; `ValueError` → 400; returns that rule's row |
| `GET held/` | admin | `{total, rows}`, newest first, capped at 500, `?state=held` (default, not restored or purged) or `all` |
| `GET held/<id>/thumbnail/` | admin | JPEG bytes or 404 |
| `POST held/<id>/restore/` | admin | `holding.restore(id, staff)`; `FileStranded` → 500 with a generic Arabic message; other `HoldError` → 400 `{detail}` |

`reports.growth_payload()` returns `{as_of, refreshing, current: {db_bytes, media_bytes, media_files, empty_bytes, held_bytes, held_files, disk_total_bytes, disk_free_bytes}, series: [{day, db_bytes, media_bytes, empty_bytes}] (last 180 oldest first), forecast: {level_percent, daily_bytes, days_to_level}, tables: [...], types: [...], folders: [...], measures: {removed: [{rule_key, label_ar, count, bytes}], restores, missed_retention_days}}`.

- `forecast`: rate from the oldest and latest snapshot inside the last 30 days of (`db_bytes + media_bytes`), and `null` `daily_bytes` and `days_to_level` when the span is under 7 days (Review Focus 2). `days_to_level = (level% × disk_total − (disk_total − disk_free)) / daily_bytes`, floored at 0; `null` when `daily_bytes <= 0` (Review Focus 3).
- `tables`: from the latest `TableSizeSnapshot.taken_at` and the earliest within 30 days; `{table, total_bytes, heap_bytes, index_bytes, row_estimate, growth_bytes (null if not in the older set), empty_bytes, classified, rule_label_ar}`. Classified means a `row` rule target's `db_table`, or `P56_TABLES`, a constant in `reports.py` mapping the six `p56_*` keys to model labels (a test checks each resolves with `apps.get_model`).
- `types`: `media_by_type` latest vs. the snapshot closest to 30 days old, `{key, label_ar (model verbose_name), bytes, files, growth_bytes}`.
- `measures.removed`: real lines of the last 30 days summed per rule. `restores`: `HeldFile.restored_at` in 30 days. `missed_retention_days`: days in the last 30, not before the first `DataHealthSnapshot` and not today, with no successful `SyncRun(lane='retention')` (read the status values in `apps/sync/models.py`).
- Rule row: `{key, label_ar, label_en, kind, reason, keep_days, minimum_days, can_change_days (default_days not None and kind != p56), mode (policy.get_mode), stored_mode, locked (file rule while setting off), changeable (kind != p56), last_real: {at, count, bytes, error, stopped_by_breaker} | null, last_preview: {at, count, bytes, skipped_shared, error} | null, preview_fresh, changed_by, changed_at, policy_reason}`. `changed_by` is the staff display name.
- Held row: `{id, rule_key, rule_label_ar, record_type_ar, record_id, size, moved_at, purge_after, restored_at, purged_at, deleted_by, can_restore, has_thumbnail}`. `deleted_by` is `getattr(held, 'deleted_by', None)` shown by name, because Stage 4 adds who deleted a file; confirm the field name against Stage 4 before the PR.
- `has_thumbnail` allowlist, `reports.can_thumbnail(held)`: `held.rule_key` in `{'images_rejected', 'images_unreviewed', 'images_obsolete'}` **and** `held.primary_model` in `{'images.ImageCandidate', 'product_experience.ProductMedia'}`. Everything else is False. Thumbnail: open with Pillow from `_inside(hold root, hold_path)`, `thumbnail((160, 160))`, re-encode JPEG; any error → 404. `Cache-Control: private, no-store`.
- Refresh: `cache.add('data_health_refreshing', 1, 900)` guards; `core.threads.start_thread` runs `take_snapshot` and deletes the key in `finally`. `refreshing` in responses is `cache.get(key) is not None`. Close the DB connection at thread end.

- [ ] **Step 1:** Write failing tests in `apps/tests/test_data_health_api.py`, using `apps.tests.factories` and `bearer_client`:
  - Role sweep: for admin/supervisor/quality_manager/pharmacist/salesperson/viewer, GET `growth/`, `problems/`, `rules/`, `held/` status equals the §7 table; `PATCH rules/`, `POST preview`, `POST restore`, `GET thumbnail` are 403 for supervisor and quality manager.
  - `test_growth_with_no_snapshots_and_with_one` (Review Focus 2). `test_forecast_null_when_shrinking` (3). `test_forecast_days` with two crafted snapshots and exact arithmetic.
  - `test_patch_below_floor_refused_for_admin` (prescriptions, `keep_days=30` → 400), `test_patch_on_without_preview_refused`, `test_patch_needs_reason`, `test_patch_writes_audit`, `test_p56_refused`.
  - `test_preview_writes_line_changes_nothing`.
  - `test_held_rows_hide_paths`: serialized JSON contains neither the file's original path, `hold_path` nor its hash.
  - `test_thumbnail_refused_for_prescription_and_pos_rx_and_orphan` (1); `test_thumbnail_served_for_rejected_image`.
  - `TransactionTestCase` `test_restore_returns_file` (`holding.restore` is durable) and `test_restore_refused_when_path_occupied`.
  - `test_problems_contains_no_phone`: a customer with a known phone and name; neither string appears in `problems/` output.
  - `test_refresh_runs_once` (5): `start_thread` patched; two POSTs → one call, both 202; supervisor may refresh; pharmacist 403.
  - `test_p56_tables_resolve`.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement, run `python manage.py makemigrations users` for the choice, combine into the grant migration, then `python manage.py makemigrations --check`.
- [ ] **Step 4:** Run `apps.tests.test_data_health_api apps.tests.security` serially (background, long). Regenerate the matrix when `test_permission_matrix` says so. Canary: `DataHealthSnapshot` must not land in `skipped`.
- [ ] **Step 5:** Commit: `feat(lifecycle): data health API and the data_health RBAC module`.

### Task 3: Screen

**Files:**
- Create: `frontend/src/pages/DataHealthPage.jsx` (shell, tabs), `frontend/src/pages/dataHealth/GrowthTab.jsx`, `RulesTab.jsx`, `HeldFilesTab.jsx`, `ProblemsTab.jsx`, `format.js` (`fmtBytes`, `fmtDate`)
- Modify: `frontend/src/api/client.js` (`dataHealthApi`), `frontend/src/App.jsx` (lazy route `data-health`), `frontend/src/components/navGroups.js` (`{ to: '/data-health', icon: '🩺', label: 'صحة البيانات', roles: ['admin','supervisor','quality_manager'], module: 'data_health' }`, near the other admin entries)

**Interfaces:** Consumes Task 2's routes exactly.

- Tabs in order: `growth` النمو, `rules` القواعد, `held` الملفات المحجوزة, `problems` المشكلات; `useHelpTab(tab)`. Non-admins see only growth and problems (`useAuth`-style role check as elsewhere; the server is the real gate). Keep the tab in state.
- Header: `RefreshButton` posting `refresh/`, then polling (`refetchInterval` 4000 while `refreshing`), and "آخر قياس" with `as_of`.
- Growth: tiles (database, media, estimated empty space, days to level or "يحتاج ٧ أيام قياس على الأقل"), one inline-SVG line chart of database and media size using theme tokens with both series labelled directly, grids for tables (with a «غير مصنف» badge), upload types, measures. Follow the `dataviz` skill.
- Rules: grid of rule rows, with one inline expanded row per selected rule: mode select, days input (min = `minimum_days`), required reason text box, Save, Preview. Server refusals appear inline as Arabic text. p56 rows read-only. When `file_rules_locked`, file rows show «مقفلة حتى الانتقال إلى السيرفر» and the `on` option is disabled.
- Held: grid with thumbnail cell only when `has_thumbnail` (fetch as blob with the auth client, object URL, revoke on unmount), rule, record, size, purge date, deleted by, Restore button with an inline confirm (not a modal).
- Problems: grid with label, count (`—` when null), change, owner, note, link (`react-router` `Link`, only when `link` exists).
- `data-tour`-style help targets if `apps/help` content references them (Task 4 uses `data-help` conventions of `StockAuditPage.jsx`).

- [ ] **Step 1:** Implement; `npm run lint` on the new files; `npm run build` (includes `check-sort`). Expected: both pass.
- [ ] **Step 2:** Browser check with the preview servers on a free backend port (port 8000 can be the office backend) against a local dev database; seed snapshots through `manage.py shell`: every tab renders in RTL at desktop and phone width; as supervisor, Rules and Held are hidden and `/api/data-health/rules/` is 403; a below-floor save shows the Arabic refusal inline; refresh shows progress and finishes; no console errors.
- [ ] **Step 3:** Commit: `feat(lifecycle): data health screen with growth, rules, held files and problems`.

### Task 4: Help and documents

**Files:**
- Create: `apps/help/content/data_health.py` (Arabic + English; `key` `data_health`; route `/data-health`; tabs `growth`, `rules`, `held`, `problems`; `updated` `2026-11-08`), and add it to `MODULE_FILES` before `'admin'`
- Modify: `docs/architecture/36_DATA_LIFECYCLE.md` (status line, Code table, a "Data health screen" section, Stage 5 BUILT); `docs/architecture/11_ERP_INDEX.md` (doc 36 entry, if absent or stale); `docs/product-review/00_INDEX_AND_DECISION_LEDGER.md` (P-56 entry)

- [ ] **Step 1:** Write them, stating plainly that thumbnails are limited to item images, and that the Problems tab fixes nothing.
- [ ] **Step 2:** Run `apps.tests.test_help`. Expected: PASS.
- [ ] **Step 3:** Commit: `docs(lifecycle): help and architecture notes for the data health screen`.

### Final

- [ ] Whole-branch review. Then the full `apps.tests` suite serially with a unique `TEST_DB_NAME`, `npm run build`, `npm run lint`, and a re-check for new Stage 3 and Stage 4 commits.
- [ ] Push and open a PR, not merged, stating it must land after Stage 3.
