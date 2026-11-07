# Data Lifecycle Stage 3: Register, Rules and First Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** awaiting owner approval. Nothing is built.

**Goal:** One code-defined register of what we keep and why, with previewed, audited, reversible cleanup: row rules can run in the office, file rules stay locked to preview until the VPS.

**Architecture:** New app `apps/data_lifecycle` holds the rules, policies, run records and holding folder. The 04:45 `daily_retention` job and `retention` lane stay, and call into it as extra steps. There is no screen or API in this stage (Stage 5): rule changes go through a service function, exposed by `manage.py lifecycle`.

**Tech Stack:** Django 4.2, PostgreSQL, APScheduler (existing job only), React for one small "removed" note.

**Spec:** [docs/superpowers/specs/2026-11-07-data-lifecycle-design.md](../specs/2026-11-07-data-lifecycle-design.md) (§5, §6 Stage 3, §7, §8). The spec arrives on `main` with Stage 1.

**Depends on:** Stage 1 merged to `main` (`run_daily_retention() -> SyncRun | None`, `RETENTION_LOCK_KEY`). Not merged at the time of writing. Stage 2 is independent.

---

## Findings from the pre-build checks

The design told the builder to check four things first. All four were checked on 2026-11-07 against the code and, read-only, the office database.

### 1. Everything that references `DemandCalculationRun`

| Reference | On delete | Who reads it | Tolerates pruned rows? |
|---|---|---|---|
| `ItemDemandMetrics.run`, `ItemDemandAggregated.run` | CASCADE | These are the pruned rows | n/a |
| `TransferRecommendationRun.demand_run`, then `TransferRecommendation.run` | CASCADE | Latest run only (`views.py`, `isr_views.py:160`, `isr_writer.py:527`, `lost_sales_engine.py`) | Yes |
| `LostSalesRun.demand_run` | CASCADE | Latest run only (`views.py:2425`) | Yes |
| `ShortageSnapshot.run`, `ShortageObservation` | CASCADE | Own stored rows; never pruned (`shortage.py:compute_deltas`) | Yes |
| `DeadStockSnapshot.run`, `DeadStockLine` | CASCADE | Own stored lines; computed only from the latest run | Yes |
| `IsrPush.run` | SET_NULL | Shows the number only (`isr_views.py:57`, `tab_exports.py:116`). Pushing uses stored lines | Yes |
| `SalesRatePush.run` | SET_NULL | Shows the number only (`rate_writer_views.py:54`). Executing uses stored lines | Yes |
| `CoverageTopUp.run` | SET_NULL | Filtered by the latest run only (`coverage_writer.py:613`) | Yes |
| `PivotSheetSnapshot.run` (`related_name='+'`) | SET_NULL | `receipt_check` uses its stored `lines` | Yes |
| Cached ISR snapshot `run_id` (`isr_fulfillment.py:388`) | Not stored in the database | Shown in the workbook and saved on the proposal. Its numbers travel inside the snapshot | Yes |

**Result:**
- No reader needs a pruned run's rows. Every detail read goes through a latest-run lookup. No API accepts a run id from the client.
- No JSON or text column stores a demand-run id. The only `run_id` hits are `insurance_insuranceauditevent` (`after`, `meta`), which are insurance re-price runs, a different thing.
- Run headers are never deleted, so the CASCADEs never fire.
- `isr_fulfillment.py:622` only checks that the header exists. That check is always true, because headers stay. It is harmless, but it does not show what the design assumed; the table above does.
- The "keep runs still in use" rule from §5.2 is therefore insurance rather than a need. It stays, as the design says. Today it would hold 3 runs, from the 4 `proposed` rate pushes. No `IsrPush` is open.
- `TransferRequest.source_recommendation` has 0 rows set, so pruning pending recommendations breaks no link.

### 2. Readers that a smaller keep set would break (new)

- **Tied latest-run lookups.** `apps/images/views.py:783` and `apps/images/pipeline.py:218` use `order_by('-calc_date').first()`. Several runs can share a date (3 on 2026-11-01). With only 3 runs kept, this could pick a run with no rows, and the image priority list would go empty. Task 1 fixes both.
- **The runs are more frequent than the design assumed.** There were 7 successful runs from 1 to 4 November, against the "twice a week" in §5.2. Runs 110 and 111 started in the same second, the duplicate-scheduler problem the one-scheduler lock addressed. So "last 3" can mean about 2 days of history. Nothing reads older detail, so nothing breaks, but the owner should know.
- **`rule_dead_stock_growth` changes meaning slightly.** It still finds a run at least 20 days old, but with only monthly runs that run can be about 20 to 50 days old instead of about 30. Over a longer window, its 10% threshold fires more easily. The message prints the comparison date. The plan follows the design; see the owner decisions.
- **Other readers with no run filter.** `batches/stock_expiry.py:374`, `batches/rebalance.py:120`, `batches/expiry_audit.py:444`, `demand/views.py:902` and `insights/rules.py:2170` use the latest `calc_date` or highest `run_id`. Pruning does not affect them. Two runs on one date can already mix rows, which is an existing quirk left out of this stage and listed as a follow-up.

### 3. Media paths held in text or JSON fields: **yes, one field**

All 1,173 text, JSON and long character columns were scanned, for forward-slash and Windows paths.

- **`enrichment.ItemEnrichment.image_url`** holds media paths in 299 rows. 280 are relative `/media/image_candidates/…` paths, all on approved candidates. The other 19 are full addresses starting `http://localhost:8000/media/…`, saved by `apps/images/views.py:603,674`. These only work on that machine, today and after cutover (follow-up below). The field is a cache that `primary_image_url` falls back to, so the file behind it must not disappear silently.
- `images_imagecandidate.source_url` also matched, but those are outside websites, not our media.

This check is of today's data plus the code that writes paths. Task 8 keeps it true by treating `image_url` as a reference.

**Files shared between rows (new, more serious than the text field).** The design treats a file as belonging to one row. It does not:

| Same path held by | Rows | What would go wrong |
|---|---|---|
| `ImageCandidate.local_file` and `ProductMedia.file` | 607 | Removing a rejected candidate's file could delete a live product image |
| `SupplierInvoice.source_image` and `OcrSample.image` | 4 | The 5-year invoice rule would delete a keep-forever OCR learning sample |

Task 8 makes the mover refuse any file that a row outside the rule's own candidates still uses.

**Files no record uses: the design's guess is now verified, with one addition.** The 770 files on disk that no `FileField` references come to 248 MB:

| Files | Size | What they are | Handling |
|---|---|---|---|
| 76 | 213 MB | Bundle pages | Their own rule |
| About 386 | Under 1 MB | `invoice_bundles/bundle*.pdf` test fixtures | Test runs are writing into the real media folder; Task 9 stops that at the source |
| About 240 | About 8 MB | Other fixtures: `chatter/…/photo.png`, `chatter_voices/…/note.webm`, `vision/voice/…/voice.webm`, 13 byte-identical `reservations/…/2021-10-01*.png` | As above |
| 20 | 25 MB | **Real** invoice page images in `invoice_images/`, plus a real PDF and photos | Probably left when `reprocess` deletes invoices (`views.py:1176`) without their files. Stage 4's "files follow their record" stops this. The 5-year age limit below covers these |
| 43 | Under 1 MB | Replaced thumbnails in `products/…/thumbs/` | Normal rule |
| 5 | 2 MB | `media/reports/`: command output with no `FileField` | Excluded from the rule |

So the design's guess (test runs and bundle pages) was right for most files, but not all: an "unused" file can be a real document.

### 4. `invoice_bundles/pages` after finalisation: **nothing needs them**

- `invoice_bundles` appears in code only in `ingest.py:73` and `models.py:137`. No frontend code and no stored field refers to the pages.
- Pages are read only inside `process_bundle`, while it runs.
- `reprocess` (`views.py:1169`) renders again from `source_file`, which stays, and refuses batches with queued or finalised invoices.
- So pages are unused from the moment a batch finishes, not only after finalisation.

**Catch:**
- The design's condition is "every invoice finalised or cancelled". The status list has no `cancelled`; the nearest is `rejected`, which this plan uses.
- 59 of the 65 bundle invoices are still in `review`, so the rule frees none of the 213 MB until those are finished. See the owner decisions.

### 5. Notifications all unread

- All 760,249 notifications are unread, with 0 `read_at` values across 760,013 log rows, for 91 recipients, going back to 7 August.
- Read notifications older than 30 days are pruned, so what this really shows is that nobody has marked one read in about 30 days, and no unread notification from the last 90 days was ever read.
- Both paths look correct on reading: REST `views.py:283` and the websocket `consumers.py:142`. No test covers the websocket path.
- Not yet proven either way. Task 10 settles it with a test and one live click.

---

## Global Constraints

- Our data only: no SOFTECH reads or writes, no new entry in `softech_write_manifest.py`, no change to mirrored rows.
- **No rule may select** a money, SOFTECH-write, permission, approval, finance or insurance record (§2).
- New rules start in `preview`. Switching to `on` needs a preview under **7 days** old. Admins can change only the mode and lengthen a period, never go below a floor.
- File rules stay in preview unless `LIFECYCLE_FILE_RULES_ENABLED` is true. Default **False**, set only on the VPS.
- `LIFECYCLE_HOLD_ROOT` is outside `MEDIA_ROOT`, never served by URL. Hold period: **30 days**.
- Every mode or period change writes `AuditLog` with before, after and a required reason.
- Rate rule: last **3** completed runs, plus the last run of each month for **24** months, plus referenced runs. Headers stay. `SalesRatePush` and its lines are kept forever.
- `IsrPush` holds a run only while `proposed` or `approved`, for **90 days** from creation. The same limit applies to `SalesRatePush`.
- Floors: prescriptions **3 years**, financial documents **5 years**.
- No new scheduler job: rules run as steps inside `run_daily_retention`, under its lock. No popups for routine cleanup; only the circuit breaker alerts, admins only.
- Run tests with a unique `TEST_DB_NAME`, serially, never `--parallel`. Security sweeps need a clean test database.
- No new `# nosec`, `# noqa` or baseline line without a written reason. Migrations: re-check numbers before each push; another session may be merging.
- Work on branch `claude/data-lifecycle-stage-3`, from `main` after Stage 1.

## Review Focus

1. **A file used by two rows:** a rejected candidate sharing a path with a live `ProductMedia` must stay. Pinned in Task 8, `test_shared_path_is_skipped_and_counted`.
2. **An obsolete item comes back after its image was removed:** the pipeline must be able to fetch it again; `seen_urls` and `phash` must not block it. Pinned in Task 9, `test_returned_item_can_refetch_removed_image`.
3. **Four or more runs on one date:** every "latest run" reader still finds rows after pruning. Pinned in Task 1, `test_latest_reader_ignores_pruned_tie`, and Task 5, `test_every_latest_definition_is_kept`.
4. **Media folder missing or half restored at cutover:** file rules must stop rather than act on a wrong picture. Pinned in Task 9, `test_missing_media_stops_file_rules`.
5. **Someone re-runs OCR on an invoice whose image was removed:** a clear message, not a crash. Pinned in Task 10, `test_reocr_on_removed_image_returns_message`.

---

### Task 1: Readers use one run

**Files:**
- Modify: `apps/forecasting/service.py:60`, `apps/incentives/views.py:1544`, `apps/images/views.py:783`, `apps/images/pipeline.py:218`
- Create: `apps/tests/test_lifecycle_readers.py`

**Interfaces:**
- Consumes: `apps.purchasing.shortage._latest_run(None)`. No run returns an empty result, not an error.

- [ ] **Step 1: Write the failing tests**

`test_forecast_processes_each_item_once`: two successful runs with the same item and branch; the service processes 1 row, from the newest.
`test_slow_movers_use_latest_run`: same setup; the incentive source returns the item once.
`test_latest_reader_ignores_pruned_tie`: 4 successful runs on one `calc_date`, rows only on the newest 3; both image readers return rows.

- [ ] **Step 2: Run to verify they fail**

Run: `python manage.py test apps.tests.test_lifecycle_readers`
Expected: FAIL (rows counted once per run; the tie picks the empty run).

- [ ] **Step 3: Filter all four readers to `_latest_run(None)`**

- [ ] **Step 4: Run to verify they pass, plus the existing suites**

Run: `python manage.py test apps.tests.test_lifecycle_readers apps.tests.test_images_r7 apps.tests.test_images_sales_priority`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/forecasting/service.py apps/incentives/views.py apps/images/views.py apps/images/pipeline.py apps/tests/test_lifecycle_readers.py
git commit -m "fix(demand): forecasting, incentives and image readers use the latest run only"
```

### Task 2: Transit alerts stop writing a note every day

**Files:**
- Modify: `apps/transits/management/commands/sync_in_transit.py` (`_fire_alerts` about line 982, `_fire_local_receipt_alerts` about line 1097)
- Modify: `apps/help/content/transfers.py` only if its text says a note is added daily, then bump `updated`
- Test: `apps/tests/test_transit_alert_levels.py`

- [ ] **Step 1: Write the failing tests**

`test_same_level_next_day_writes_no_note`: a transfer alerted `critical` yesterday, still `critical` today: note count and `alert_sent` count are unchanged, the digest still sends, `alert_notification_count` goes up by 1, `last_alert_sent_at` is today.
`test_level_change_writes_one_note_and_event`: `high` to `critical`: exactly 1 new note, 1 new event.
`test_local_alert_writes_once`: level `local` on two days: 1 note.
`test_mismatch_alert_still_written`: `_notify_mismatch` is unchanged.

- [ ] **Step 2: Run to verify they fail**

Run: `python manage.py test apps.tests.test_transit_alert_levels`
Expected: FAIL on the first and third tests.

- [ ] **Step 3: Write the note and event only when `transfer.last_alert_level != level`**

Capture the old level before the guard fields are overwritten. The per-day guard, digest and counters stay as they are.

- [ ] **Step 4: Run to verify they pass**

Run: `python manage.py test apps.tests.test_transit_alert_levels apps.tests.test_transits_sync`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/transits/management/commands/sync_in_transit.py apps/tests/test_transit_alert_levels.py
git commit -m "fix(transits): write alert notes and events only when the level changes"
```

### Task 3: App, models and the rule register

**Files:**
- Create: `apps/data_lifecycle/{__init__,apps,models,register,policy}.py`, `apps/data_lifecycle/migrations/0001_initial.py`
- Modify: `config/settings.py` (`INSTALLED_APPS`, `LIFECYCLE_FILE_RULES_ENABLED`, `LIFECYCLE_HOLD_ROOT`), `.gitignore`
- Create: `apps/tests/test_lifecycle_register.py`

**Interfaces:**
- Produces, in `models.py`:
  - `LifecycleRulePolicy`: `rule_key` (unique), `mode` (`off` / `preview` / `on`), `keep_days_override` (null), `changed_by`, `changed_at`, `reason`.
  - `LifecycleRun`: `started_at`, `finished_at`, `is_preview`, `sync_run` (null FK).
  - `LifecycleRunLine`: `run`, `rule_key`, `count`, `bytes`, `skipped_shared`, `stopped_by_breaker`, `error`, `is_preview`.
  - `HeldFile`: `original_path`, `hold_path`, `rule_key`, `size`, `sha256`, `moved_at`, `purge_after`, `restored_at`, `restored_by`, `purged_at`, plus `primary_model`, `primary_pk`, `primary_field` (indexed) and `rows` (JSON list of `{model, pk, field, value}`, every reference cleared). The list form is needed because one file can have several rows (finding 3). `HeldFile` is not registered in Django admin.
  - `ObsoleteItemSeen`: `item` (unique FK), `first_seen_at`, `cleared_at`.
  - `UnreferencedFileSeen`: `path` (unique), `first_seen_at`, `last_seen_at`. Not in the design; needed for "2 scans 30 days apart".
  - `TableSizeSnapshot`: `taken_at`, `table`, `total_bytes`, `heap_bytes`, `index_bytes`, `row_estimate`. The design's "consider shipping early", tables only; see Task 10.
- Produces, in `register.py`: dataclass `Rule(key, label_ar, label_en, kind, floor_days, default_days, reason, margin, ceiling, candidates, targets, age_field=None)`, where `kind` is `row`, `file` or `p56`, `RULES: dict[str, Rule]`, `KEEP_FOREVER: dict[str, str]` mapping `app.Model.field` to a reason, and `PROTECTED_APPS`.
- Produces, in `policy.py`: `get_mode(key) -> str`, `keep_days(key) -> int`, `set_policy(key, *, mode=None, keep_days=None, user, reason) -> LifecycleRulePolicy`, raising `PolicyRefused` with an Arabic message.

Rule keys, targets and limits. "Count" means rows for row rules and files for file rules. Margin and ceiling are the "left to the builder" values:

| Key | Kind | Fields or target | Keep / floor | Margin | Ceiling |
|---|---|---|---|---|---|
| `rate_runs` | row | `ItemDemandMetrics`, `ItemDemandAggregated`, pending `TransferRecommendation` | §5.2 | 150,000 | 1,500,000 |
| `transit_alert_notes` | row | `InTransitNote` automatic alerts | 90 days after closing | 2,000 | 200,000 |
| `transit_audit_events` | row | `InTransitAuditEvent` `alert_sent` (automatic, `level=`) and `synced` | 90 days after closing | 5,000 | 300,000 |
| `prescriptions` | file | The 5 fields in §5.1 | 1,095 / floor 1,095 | 200 | 5,000 |
| `ocr_pos_rx` | file | `OcrSample.image`, `module='pos_rx'` | 1,095 / floor 1,095 | 200 | 5,000 |
| `conversations` | file | `WAMediaFile.local_file`, `CallLogAttachment.file`, `CaseEvent.attachment` | 1,095 | 200 | 5,000 |
| `financial_docs` | file | The 5 fields in §5.1 | 1,825 / floor 1,825 | 100 | 2,000 |
| `bundle_pages` | file | `invoice_bundles/pages/batch_<id>/` | 30 after the last invoice is `finalized` or `rejected`, or after a `failed` batch | 500 | 5,000 |
| `images_rejected` | file | `ImageCandidate` `rejected` | 30 | 100 | 3,000 |
| `images_unreviewed` | file | `ImageCandidate` `scored`, `pending_review` | 180 | 100 | 3,000 |
| `images_obsolete` | file | `ImageCandidate.local_file`, `ProductMedia.file`, `thumbnail` | 90 after first seen | 100 | 1,000 |
| `delivery_proof` | file | `DeliveryOrder.pod_photo` | 365 | 200 | 5,000 |
| `staff_messages` | file | The 9 fields in §5.1 (`ChatterMessage`, `ReservationActivity` and `TransferRequestMessage` attachment + voice, `TaskAttachment.file`, `AvailabilityBatch.source_image`, `ShortageList.source_image`) | 365 | 500 | 5,000 |
| `unreferenced` | file | Under `media/`, no reference, 2 scans 30 days apart | see Task 9 | 100 | 1,000 |
| `p56_engine`, `p56_notifications`, `p56_pbx`, `p56_audit`, `p56_slow`, `p56_screen_views` | p56 | Existing steps, listed only | Existing | n/a | n/a |

`KEEP_FOREVER` holds `ProductSEO.og_image`, `InsuranceExportProfile.watermark_image`, and `OcrSample.audio` with this reason: the design names only the image for `pos_rx`, so default is keep. `auto_approved` candidates count as approved (290 rows the design's table does not name).

- [ ] **Step 1: Write the failing tests**

`test_every_filefield_is_classified`: walks `apps.get_models()` local `FileField`s (30 today); each is in a rule's `targets` or in `KEEP_FOREVER`, else fails, naming the field.
`test_unclassified_filefield_fails`: patches in a fake field; the check reports it.
`test_no_rule_targets_protected_app`: no `row` target and no selected model is in `PROTECTED_APPS` (`finance`, `payments` except file clearing, `insurance`, `users`, `audit`, `access`). A `file` rule on a protected model may clear only the file field, so `payments` file targets are listed explicitly.
`test_age_field_exists`: each rule's `age_field` exists on its model.
`test_floor_refused_for_admin`: `set_policy('prescriptions', keep_days=1000, user=admin, reason='x')` raises `PolicyRefused`. 1,200 is accepted and writes `AuditLog` with before and after.
`test_on_needs_fresh_preview`: no preview, or one 8 days old: refused. One 6 days old: accepted for a row rule.
`test_file_rule_locked_off_vps`: with the setting False, `set_policy('prescriptions', mode='on', …)` raises, whatever the preview.
`test_p56_mode_cannot_change` and `test_reason_is_required`.

- [ ] **Step 2: Run to verify they fail**

Run: `python manage.py test apps.tests.test_lifecycle_register`
Expected: FAIL (`No module named apps.data_lifecycle`).

- [ ] **Step 3: Create the app, models, migration, register and policy**

Add `LIFECYCLE_HOLD_ROOT = config('LIFECYCLE_HOLD_ROOT', default=BASE_DIR / 'media_hold')` and `media_hold/` to `.gitignore`. The module docstring says the app is company-level and names who may see it (§7). `candidates` functions can be stubs here; later tasks fill them.

- [ ] **Step 4: Run to verify they pass, plus the migration check**

Run: `python manage.py test apps.tests.test_lifecycle_register` then `python manage.py makemigrations --check`
Expected: PASS, "No changes detected".

- [ ] **Step 5: Commit**

```bash
git add apps/data_lifecycle config/settings.py .gitignore apps/tests/test_lifecycle_register.py
git commit -m "feat(lifecycle): rule register, policies and floors"
```

### Task 4: Preview, real run, circuit breaker and the daily wiring

**Files:**
- Create: `apps/data_lifecycle/runner.py`, `apps/data_lifecycle/management/commands/lifecycle.py`
- Modify: `apps/sync/maintenance.py` (`run_daily_retention` steps, docstring)
- Test: `apps/tests/test_lifecycle_runner.py`

**Interfaces:**
- Consumes: `Rule`, `get_mode`, `_batched_delete`, `_alert_admins`.
- Produces: `run_lifecycle_rules() -> int` (total removed; never raises for one rule's failure), `preview_rule(key) -> LifecycleRunLine`. Command: `manage.py lifecycle list | preview <key> | set <key> --mode M [--keep-days N] --user U --reason R | restore <held_id> --user U`.

The breaker limit is a decision the design leaves open:
`limit = min(ceiling, 1.5 × unconsumed_preview_count + margin)`. A preview is **consumed** by the next real run. A large first cleanup therefore needs its own recent preview, and every later day is held to the margin, which is the rule's normal daily volume. Without consuming it, one old large preview would let any later run pass.

- [ ] **Step 1: Write the failing tests** using a fake row rule on a test-only queryset

`test_preview_changes_nothing`: row counts identical; a line is written with the count.
`test_real_matches_preview_on_unchanged_data`: same count.
`test_breaker_stops_only_that_rule`: rule A over its limit, rule B fine: A removes 0, `stopped_by_breaker=True`, one admin alert; B runs.
`test_preview_is_consumed`: after a real run of 1,000, a run of 600 with margin 100 stops the rule.
`test_first_large_run_allowed_by_preview`: preview 1,000, real 1,400 with margin 100: passes.
`test_rule_error_does_not_stop_others`: one raises; the error is on its line; others run.
`test_off_rule_does_nothing` and `test_preview_mode_rule_only_previews`.
`test_retention_includes_lifecycle_step`: `run_daily_retention()` logs `retention:lifecycle` and `retention:purge_held` `SyncLog` rows, still under `RETENTION_LOCK_KEY`.
`test_routine_cleanup_sends_no_notification`: a normal run creates 0 `Notification` rows.

- [ ] **Step 2: Run to verify they fail**

Run: `python manage.py test apps.tests.test_lifecycle_runner`
Expected: FAIL (`No module named apps.data_lifecycle.runner`).

- [ ] **Step 3: Implement `runner.py` and the command, and add the two steps after the P-56 steps in `run_daily_retention`**

Row deletes reuse `_batched_delete`. `--user` resolves a `StaffProfile`; `set` and `restore` go only through the service functions. Add no scheduler job, so `SCHEDULER_JOB_GUARDS` is unchanged.

- [ ] **Step 4: Run to verify they pass**

Run: `python manage.py test apps.tests.test_lifecycle_runner apps.tests.test_retention_watch apps.tests.test_sync_health`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/data_lifecycle apps/sync/maintenance.py apps/tests/test_lifecycle_runner.py
git commit -m "feat(lifecycle): preview and real runs with a per-rule circuit breaker"
```

### Task 5: The rate rule

**Files:**
- Create: `apps/data_lifecycle/rules_rows.py`
- Modify: `apps/sync/maintenance.py` (`engine_runs_to_keep`)
- Test: `apps/tests/test_lifecycle_rate_rule.py`

**Interfaces:**
- Produces: `tight_runs_to_keep(now=None) -> set[int]`. `engine_runs_to_keep()` returns the tight set when `get_mode('rate_runs') == 'on'`, and today's "last 10 + monthly" otherwise. `prune_engine_runs` stays the only code that deletes these rows, so the switch is a single point and existing tests keep passing in preview.

The keep set is the union of:
- newest 3 completed runs by `started_at`;
- the newest by `-finished_at`, `-id` and `-started_at` each, since the readers use all three definitions;
- the last run of each calendar month for 24 months;
- `running` runs;
- runs referenced by `IsrPush` or `SalesRatePush` in `proposed` or `approved` and created within 90 days.

- [ ] **Step 1: Write the failing tests**

`test_fifteen_runs_over_three_months`: last 3, monthly and referenced runs remain; all headers remain; other rows go.
`test_open_isr_holds_its_run`: `proposed` at 89 days holds; at 91 days does not; `pushed` does not; `cancelled` does not.
`test_proposed_rate_push_holds_its_run`, same limits.
`test_monthly_older_than_24_months_goes`.
`test_every_latest_definition_is_kept`: a long run that started early and finished last stays, and a tie of 4 on one `calc_date` still leaves `_latest_run` from `shortage`, `rate_writer` and `views` with rows.
`test_dead_stock_growth_finds_older_run`: after pruning, `rule_dead_stock_growth` compares with a run at least 20 days old (§8).
`test_reviewed_recommendation_survives`: `approved`, `rejected` and `executed` stay; old `pending` goes.
`test_preview_mode_keeps_ten`: until switched on, today's behaviour is unchanged.
`test_isr_reader_after_prune`: `collect_requests` on a proposal whose run has no rows yet still builds, and `isr_views` shows the number.

- [ ] **Step 2: Run to verify they fail**

Run: `python manage.py test apps.tests.test_lifecycle_rate_rule`
Expected: FAIL (`tight_runs_to_keep` not defined).

- [ ] **Step 3: Implement `tight_runs_to_keep`, the rule's `candidates`, and the switch in `engine_runs_to_keep`**

The rule's real action calls `prune_engine_runs`; its preview counts the same querysets.

- [ ] **Step 4: Run to verify they pass**

Run: `python manage.py test apps.tests.test_lifecycle_rate_rule apps.tests.test_sync_health`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/data_lifecycle/rules_rows.py apps/sync/maintenance.py apps/tests/test_lifecycle_rate_rule.py
git commit -m "feat(lifecycle): rate rule keeps 3 runs plus monthly and referenced runs"
```

### Task 6: Transit row rules

**Files:**
- Modify: `apps/data_lifecycle/rules_rows.py`, `apps/transits/models.py` (`InTransitAuditEvent` docstring: automatic alert and sync rows age out; all other actions stay)
- Test: `apps/tests/test_lifecycle_transit_rule.py`

**Interfaces:**
- Produces: candidates for `transit_alert_notes`, `transit_audit_events`.

Definitions, from the code:
- An automatic note is `note_type='alert'` with a body starting `🔔 تنبيه تلقائي` (148,328 today). Mismatch notes start `🔔 تباين…` (39) and never match.
- An automatic event is `action='alert_sent'` with detail starting `level=`. `erp_mismatch:` events never match. `synced` events also count.
- Closed means `transit_status` in `received`, `cancelled`, `force_closed`. The clock is the transfer's `updated_at`; a later edit only makes it wait longer.
- `in_transit`, `erp_mismatch`, `expired_pending` are open: keep the latest automatic note per level (the level from `(…)` in the body, `local` when there is none), the latest `alert_sent` per `level=`, and the latest `synced`.

- [ ] **Step 1: Write the failing tests**

`test_closed_over_90_days_alerts_removed`, `test_closed_under_90_days_kept`, `test_open_keeps_latest_per_level`, `test_mismatch_never_selected`, `test_manual_note_never_selected`, `test_other_audit_actions_never_selected` (`viewed`, `exported`, `linked`, `unlinked`, `received`, `force_closed`).

- [ ] **Step 2: Run to verify they fail**

Run: `python manage.py test apps.tests.test_lifecycle_transit_rule`
Expected: FAIL

- [ ] **Step 3: Implement both candidate functions**

- [ ] **Step 4: Run to verify they pass**

Run: `python manage.py test apps.tests.test_lifecycle_transit_rule`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/data_lifecycle/rules_rows.py apps/transits/models.py apps/tests/test_lifecycle_transit_rule.py
git commit -m "feat(lifecycle): transit alert notes and sync events age out, mismatches stay"
```

### Task 7: Holding folder: move, restore, purge

**Files:**
- Create: `apps/data_lifecycle/holding.py`
- Test: `apps/tests/test_lifecycle_holding.py` (temporary `MEDIA_ROOT` and `LIFECYCLE_HOLD_ROOT`)

**Interfaces:**
- Produces: `hold_file(path, rows, rule_key) -> HeldFile`, `restore(held_id, user) -> HeldFile`, `purge_expired(now=None) -> int`, where `rows` is a list of `{model, pk, field, value}`.

Decisions: file first, then the database inside `transaction.atomic()`; any failure moves the file back. Clear with `Model.objects.filter(pk=pk, **{field: value}).update(**{field: ''})`, which skips `auto_now`, and treat 0 rows updated as a failure so a row changed meanwhile rolls everything back. Restore refuses if the original path is occupied or a row's field is no longer empty, and writes `AuditLog`. Purge keeps the `HeldFile` row, so the removal date stays known. Logs carry ids only, never filenames (§7).

- [ ] **Step 1: Write the failing tests**

`test_hold_moves_file_and_clears_rows`, `test_failed_db_step_puts_file_back`, `test_row_changed_meanwhile_rolls_back`, `test_restore_returns_path_and_bytes` (sha256 matches), `test_restore_refused_when_row_has_new_file`, `test_purge_only_after_30_days`, `test_purge_skips_restored`, `test_held_file_has_no_url` (`serve_media` returns 404 for the original path, and the hold root is outside `MEDIA_ROOT`), `test_restore_writes_audit`.

- [ ] **Step 2: Run to verify they fail**

Run: `python manage.py test apps.tests.test_lifecycle_holding`
Expected: FAIL

- [ ] **Step 3: Implement `holding.py`, and wire `purge_expired` to the `retention:purge_held` step**

- [ ] **Step 4: Run to verify they pass**

Run: `python manage.py test apps.tests.test_lifecycle_holding`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/data_lifecycle/holding.py apps/data_lifecycle/runner.py apps/tests/test_lifecycle_holding.py
git commit -m "feat(lifecycle): holding folder with restore and 30-day purge"
```

### Task 8: Reference index

**Files:**
- Create: `apps/data_lifecycle/references.py`
- Test: `apps/tests/test_lifecycle_references.py`

**Interfaces:**
- Produces: `build_reference_index() -> dict[str, set[Ref]]` over every classified `FileField` plus `TEXT_PATH_FIELDS = [('enrichment.ItemEnrichment', 'image_url')]`; `media_path_from_url(url) -> str | None`; `partition(candidates, index) -> (movable, skipped_shared)`.

The rule: a candidate path is movable only when every reference is one of the rule's own candidate rows. `skipped_shared` shows on the run line.

- [ ] **Step 1: Write the failing tests**

`test_url_forms`: `/media/image_candidates/x.jpg`, a full `http://host/media/…`, and one with a signature query all give `image_candidates/x.jpg`. An outside address gives `None`.
`test_shared_path_is_skipped_and_counted`: a rejected candidate sharing a path with `ProductMedia`: skipped, count 1, file untouched.
`test_invoice_image_shared_with_ocr_sample_stays`: the 4-row case from the findings.
`test_enrichment_url_counts_as_reference`: a rejected candidate whose URL sits in `image_url`: skipped.

- [ ] **Step 2: Run to verify they fail**

Run: `python manage.py test apps.tests.test_lifecycle_references`
Expected: FAIL

- [ ] **Step 3: Implement `references.py`**

- [ ] **Step 4: Run to verify they pass**

Run: `python manage.py test apps.tests.test_lifecycle_references`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/data_lifecycle/references.py apps/tests/test_lifecycle_references.py
git commit -m "feat(lifecycle): reference index so a file used elsewhere is never moved"
```

### Task 9: File rules

**Files:**
- Create: `apps/data_lifecycle/rules_files.py`
- Modify: `apps/images/pipeline.py:272-273` (`seen_urls`, `phashes_seen`), `config/settings.py` (`MEDIA_ROOT` under `_RUNNING_TESTS`)
- Test: `apps/tests/test_lifecycle_file_rules.py`

**Interfaces:**
- Consumes: `hold_file`, `partition`, `build_reference_index`, `ObsoleteItemSeen`, `UnreferencedFileSeen`.
- Produces: one `candidates` function per file rule, `refresh_obsolete_seen() -> int`, `refresh_unreferenced_seen() -> int`.

Decisions beyond the design:
- **`images_obsolete` groups by path:** `ImageCandidate`, `ProductMedia` and `ItemEnrichment.image_url` on one item are one candidate, so they move together and restore together. Obsolete means `no_more_use`, archived or `is_active=False`.
- **The two "seen" refreshes run in every mode except `off`**, including preview. Otherwise the clocks would not start until the rule goes on.
- **The obsolete clock starts when this ships,** so no image of an obsolete item can be removed for at least 90 days.
- **`unreferenced` excludes** `reports/` and `invoice_bundles/pages/`. Under a prescription folder (`reservations/`, `pos_orders/prescriptions/`, `usage_print/prescriptions/`, `callcenter/prescriptions/`, `vision/ocr/`) it also needs a file age of 3 years, and under a financial folder (`invoice_images/`, `invoice_bundles/`, `payments/`, `hr/receipts/`) 5 years. A prescription with a lost row must not leave early (§2 anti-goal).
- **Wrong-folder guard:** if more than 5% of referenced paths are missing from disk, all file rules stop for the run and admins get one alert. Bad restore at cutover is the case this catches.
- **Tests stop writing to the real media folder:** under `_RUNNING_TESTS`, `MEDIA_ROOT` becomes a temporary folder.

- [ ] **Step 1: Write the failing tests**

`test_prescription_2y11m_stays`, `test_prescription_3y1m_moves` for each of the 5 fields.
`test_pos_rx_image_moves_text_stays`: readings intact. `test_purchasing_invoice_sample_never_selected`.
`test_rejected_30_days`, `test_unreviewed_180_days_row_kept`, `test_seen_urls_still_blocks_rejected_redownload`.
`test_auto_approved_on_live_item_never_selected`.
`test_obsolete_clock_starts_when_first_seen`, `test_returning_to_use_clears_and_image_survives`.
`test_returned_item_can_refetch_removed_image`: an approved candidate with an empty file no longer blocks by `source_url` or `phash`.
`test_obsolete_group_clears_enrichment_url_and_restore_returns_it`.
`test_bundle_pages_wait_for_every_invoice`: one in `review` holds the folder; all `finalized` or `rejected` for 30 days moves it and keeps `source_file`; a `processing` batch never moves; a `failed` batch moves after 30 days.
`test_unreferenced_needs_two_scans_30_days_apart`, `test_reports_folder_excluded`, `test_orphan_prescription_needs_three_years`.
`test_missing_media_stops_file_rules`.
`test_file_rules_only_preview_off_vps`: setting False, `on` in the database: no file moves, the line is a preview.

- [ ] **Step 2: Run to verify they fail**

Run: `python manage.py test apps.tests.test_lifecycle_file_rules`
Expected: FAIL

- [ ] **Step 3: Implement the rules, the pipeline filter and the test `MEDIA_ROOT`**

In the pipeline, exclude rows with `status` in `approved`, `auto_approved` and an empty `local_file` from `seen_urls` and `phashes_seen`. Rejected and unreviewed rows keep blocking.

- [ ] **Step 4: Run to verify they pass, plus the image suites**

Run: `python manage.py test apps.tests.test_lifecycle_file_rules apps.tests.test_images_r7 apps.tests.test_media_security`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/data_lifecycle/rules_files.py apps/images/pipeline.py config/settings.py apps/tests/test_lifecycle_file_rules.py
git commit -m "feat(lifecycle): file rules in preview, locked until the VPS"
```

### Task 10: "Removed" note and safe readers

Removed files must not look broken. File rules cannot switch on until this task ships.

**Files:**
- Create: `apps/data_lifecycle/display.py`, `frontend/src/components/RemovedFileNote.jsx`
- Modify serializers that expose classified files: `reservations`, `notifications` (chatter), `transfers`, `callcenter`, `invoices`, `shortage`, `tasks`, `delivery`, `hr`, `pos_orders`, `usage_print` (`views.py:58`), `payments`
- Modify frontend: `usePosOrder.js`, `UsagePrintPage.jsx`, `InvoicePage.jsx`, `BundleWorkbench.jsx`, `DriverDeliveryApp.jsx`, `ChatterBox.jsx`, `CallCenterPage.jsx`, `CasesPage.jsx`, `ReservationDetailPage.jsx`, `TransferDetailPage.jsx`, `PaymentAuditPage.jsx`
- Modify: `apps/invoices/views.py:265-275` (blank image); confirm the guard at `apps/omni/transcription.py:179`
- Test: `apps/tests/test_lifecycle_display.py`

**Interfaces:**
- Consumes: `HeldFile.primary_model`, `primary_pk`, `primary_field`.
- Produces: `RetentionNoteMixin` with `retention_fields = (...)`, adding `retention_removed: {field: 'YYYY-MM-DD'}`. It makes one query per list page, and only for rows with an empty field. Component `<RemovedFileNote date={...} />` shows «أُزيل وفق سياسة الاحتفاظ بتاريخ …» / "Removed under retention on …".

- [ ] **Step 1: Write the failing tests**

`test_removed_field_reports_date`, `test_never_had_file_reports_nothing`, `test_list_makes_one_lookup_query` (`assertNumQueries` difference is 1).
`test_reocr_on_removed_image_returns_message`: a 400 with Arabic text, no exception.

- [ ] **Step 2: Run to verify they fail**

Run: `python manage.py test apps.tests.test_lifecycle_display`
Expected: FAIL

- [ ] **Step 3: Implement the mixin, serializer changes, the note on each listed screen, and the invoice guard**

- [ ] **Step 4: Run to verify they pass, and build**

Run: `python manage.py test apps.tests.test_lifecycle_display` then `npm run build` in `frontend/`
Expected: PASS, build succeeds.

- [ ] **Step 5: Commit**

```bash
git add apps frontend/src
git commit -m "feat(lifecycle): show a removed-under-retention note instead of a broken file"
```

### Task 11: Notification check, growth history, docs and final checks

**Files:**
- Modify: `apps/data_lifecycle/runner.py`, `apps/sync/maintenance.py` (table-size step)
- Create: `docs/architecture/36_DATA_LIFECYCLE.md`
- Modify: `docs/architecture/11_ERP_INDEX.md`, `docs/product-review/00_INDEX_AND_DECISION_LEDGER.md` (P-56 entry), `docs/deploy/2026-11-owner-go-live-steps.md` §4
- Test: `apps/tests/test_notifications.py`, `apps/tests/test_lifecycle_runner.py`

The go-live line to add to §4: the Friday media `tar` must also include `media_hold`, and the VPS `.env` sets `LIFECYCLE_HOLD_ROOT=/opt/elrezeiky/app/media_hold` on the same disk as `media/`. `LIFECYCLE_FILE_RULES_ENABLED=True` is set only after the media copy is verified.

- [ ] **Step 1: Write the tests**

`test_ws_mark_read_updates_row_and_log`: a websocket test of `consumers.py:_mark_read`. If this passes at once, that is itself a finding; keep it.
`test_table_size_snapshot_step`: one row per table over 20 MB, and the step never raises.

- [ ] **Step 2: Implement the snapshot step, then run**

Run: `python manage.py test apps.tests.test_notifications apps.tests.test_lifecycle_runner`
Expected: PASS

- [ ] **Step 3: Settle the notification question**

On the office app, click one notification, and query `is_read` and `read_at` for it. If it updates, the answer is "nobody reads them": report this to the owner, with the counts in the findings, and change nothing. If it does not, find the cause and fix it here with a test.

- [ ] **Step 4: Write docs**

`36_DATA_LIFECYCLE.md` gives the register, the findings above and how to switch a rule. Update the index, the P-56 ledger entry and the go-live line. No new route or screen, so `test_help` is unaffected. Confirm no help text says a transit note is written daily.

- [ ] **Step 5: Run everything**

Run with a unique `TEST_DB_NAME`, serially: `python manage.py test apps.tests`, then `python manage.py test apps.tests.security`, then `python manage.py makemigrations --check`, then `bandit -r apps core config -x apps/tests,migrations -ll -q -b apps/tests/security/bandit-baseline.json`, then `npm run build` in `frontend/`.
Expected: all pass, coverage at or above the CI `--fail-under` floor, no new suppression or baseline line. If a sweep lists a new model as skipped, fix or explain it.

- [ ] **Step 6: Read-only rehearsal on the office database**

Run `manage.py lifecycle preview <key>` for each rule. Compare with the findings: `transit_alert_notes` near 148,000 less the kept ones; `rate_runs` near 11 runs of rows. Report the table to the owner. Switch nothing on.

- [ ] **Step 7: Commit, and propose the next batch**

```bash
git add apps docs
git commit -m "feat(lifecycle): growth history, notification finding, docs and go-live line"
```

Switching on `rate_runs` and the transit rules is a separate owner approval after reading the rehearsal, not part of this batch.

---

## Owner decisions

The plan builds as written without an answer to these three; each changes one value.

1. **Bundle pages (213 MB).** As designed, they wait for all invoices in the batch to finish, and 59 of 65 are in `review`, so little comes back soon. Since nothing reads pages once processing ends, "30 days after the batch was processed" would be equally safe and frees it all. **Recommended: change to that.**
2. **Dead-stock comparison.** After pruning, it may compare against a run about 20 to 50 days old, not about 30, so the alert can fire a little more easily. Keeping one extra run near 30 days costs about 10 MB. **Recommended: accept the change as designed;** the date is printed in the message.
3. **Early growth history.** `TableSizeSnapshot` (tables only) ships in this stage, because history cannot be filled in later. Media size per folder and the screen wait for Stage 5. **Recommended: keep.** It is the design's optional item and easy to drop.

**Follow-ups, not in this plan:**
- The five readers with no run filter (finding 2) can mix two same-date runs. Pruning does not cause this.
- 19 `image_url` values point at `http://localhost:8000/…`. `views.py:603,674` should save a relative path, and those rows need correcting before cutover.
- `reprocess` leaves the deleted invoices' images behind (Stage 4 covers it).
