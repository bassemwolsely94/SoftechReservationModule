# ETA History Mirror — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A read-only copy, per ETA system (preprod / production), of every e-invoice and e-receipt ETA holds for us, backfilled from Invoicer's start through ETA's bulk packages and kept current daily.

**Architecture:** `eta_reader.py` is a per-system, read-only ETA client (own credentials, token cache, throttle) that cannot send. `eta_history.py` plans date windows, requests ETA packages, polls, downloads the ZIP, parses and upserts into two mirror tables, splitting any window ETA calls too big. A small window table makes "not fetched yet / failed / too big" always visible, so unfinished never looks empty.

**Tech Stack:** Django 5 / DRF, PostgreSQL, `requests`, `zipfile`, APScheduler (apps/sync/tasks.py), React (Settings tab section).

**Spec:** `docs/superpowers/specs/2026-11-14-eta-history-mirror-design.md`

## Global Constraints

- Read-only: the reader exposes GET calls plus exactly two POSTs (`/api/v1.0/documentpackages/requests`, `/api/v1.0/receiptpackages/requests`). No submit / cancel / reject call is reachable from it.
- Systems are `preprod` and `production` only; every mirrored row carries its system; nothing mixes systems.
- Production reads use a dedicated ERP registration: `TAX_ETA_READ_PRODUCTION_CLIENT_ID` / `TAX_ETA_READ_PRODUCTION_CLIENT_SECRET` (env/.env only, never DB). Preprod: `TAX_ETA_READ_PREPROD_CLIENT_ID` / `_SECRET`, falling back to `TAX_ETA_CLIENT_ID` / `_SECRET` only when the server's own `TAX_ETA_ENVIRONMENT` is `preprod`.
- Switches `TAX_ETA_READ_PREPROD_ENABLED`, `TAX_ETA_READ_PRODUCTION_ENABLED`, default False, reset to False under `_RUNNING_TESTS`, listed in `deploy/*.env.example`.
- ETA limits: document search window ≤ 30 days; receipt package ≤ 3000 receipts; search/get/details 2 per second; recent 3 per second; 429 → honour `Retry-After`; 503 → retry after 2 s; `truncateifexceeded` is always `false`.
- Package request status codes: 1 in progress, 2 complete, 3 error, 4 deleted; get package → 200 ZIP, 204 not ready.
- Backfill start: `TAX_ETA_HISTORY_START` (date, default `2022-06-01`, the earliest ActiveFrom in the owner's EGS workbook is 2022-06-15).
- No buyer ID or phone in logs or error text (`core/errors.public_error`). Migrations: next number after `0009_receipt_send_from` (PR #130 must be merged first).
- Permissions: VIEWER reads progress, EDITOR starts/refreshes; scheduler jobs registered in `SCHEDULER_JOB_GUARDS`; threads via `core.threads.start_thread`.
- Help: every new hint ≤ 160 characters, Arabic + English; anchors mentioning send/delete need a `warn`.

## Review Focus

1. ETA answers `OperationExceedsLimit` for a window → split in halves until it fits; a one-day window still too big is marked `too_big`, never truncated.
2. ETA unreachable / 429 / 5xx mid-backfill → the window stays `requested` or `failed` with the reason; nothing is marked loaded; the next run resumes.
3. The same document arrives from two overlapping packages or from top-up → one row (unique system+uuid), the newest status wins.
4. A package that ETA lists as `deleted`/expired before we downloaded it → the window goes back to `planned` and is re-requested.
5. Production read switch off, or production credentials missing → no ETA call; the progress screen says why, per system.

---

### Task 1: Read-only per-system reader

**Files:**
- Create: `apps/tax_invoicing/eta_reader.py`
- Modify: `config/settings.py` (new settings + test reset), `deploy/*.env.example`
- Test: `apps/tests/test_eta_history.py`

**Interfaces:**
- Produces: `class EtaReader(system: str)` with `enabled() -> bool`, `configured() -> bool`, `why_not() -> str`, `get(path, params=None) -> requests.Response`, `request_package(kind: str, body: dict) -> str` (kind `documents`|`receipts`, returns package id), `package_requests(kind, page=1, size=50) -> list[dict]`, `download_package(kind, package_id) -> bytes | None` (None on 204); exceptions reuse `eta_client.EtaUncertain` / `EtaRefused` / `EtaNotConfigured`. `SYSTEMS = ('preprod', 'production')`.

- [ ] **Step 1: Write failing tests** in `apps/tests/test_eta_history.py`:
  - `test_reader_cannot_send`: `EtaReader` has no attribute named like submit/cancel/reject, and its module source contains no `/documentsubmissions`, `/receiptsubmissions`, `/state/`, `/cancel` path.
  - `test_systems_use_their_own_hosts_and_credentials`: with `override_settings` for both systems, `EtaReader('production')` logs in to `https://id.eta.gov.eg/connect/token` with the production read client, `EtaReader('preprod')` to `https://id.preprod.eta.gov.eg/connect/token`; tokens cached separately.
  - `test_preprod_falls_back_to_the_sending_client_only_on_a_preprod_server`.
  - `test_switch_off_or_missing_credentials_makes_no_call`: `why_not()` non-empty, `requests.post`/`get` not called.
  - `test_429_waits_retry_after_then_retries_once` and `test_503_retries` (mock `time.sleep`).
- [ ] **Step 2: Run** `TEST_DB_NAME=test_etah_1 python manage.py test apps.tests.test_eta_history -v 2` → FAIL (module missing).
- [ ] **Step 3: Implement** `eta_reader.py` and the settings. Hosts from `environment.ENVIRONMENTS`. Throttle: per (system, family) minimum interval — `search`/`get` 0.5 s, `recent` 0.34 s.
- [ ] **Step 4: Run** the tests → PASS.
- [ ] **Step 5: Commit** `feat(tax): read-only per-system ETA reader`.

### Task 2: Mirror models and window tracking

**Files:**
- Modify: `apps/tax_invoicing/models.py`; Create migration `0010_eta_history_mirror.py`
- Test: `apps/tests/test_eta_history.py`

**Interfaces:**
- Produces:
  - `EtaMirrorDocument(system, uuid, submission_uuid, internal_id, doc_type, type_version, direction ['sent','received'], issuer_rin, issuer_name, issuer_branch, receiver_type, receiver_id, receiver_name, issued_at, received_at, status, net_amount, tax_amount, total_amount, currency, references JSON, raw JSON, source, fetched_at)`; unique `(system, uuid)`.
  - `EtaMirrorReceipt(system, uuid, submission_uuid, previous_uuid, receipt_number, pos_serial, branch_number, issued_at, receipt_type, status, net_amount, tax_amount, total_amount, buyer_type, raw JSON, source, fetched_at)`; unique `(system, uuid)`.
  - `EtaHistoryWindow(system, kind ['documents','receipts'], date_from, date_to, state ['planned','requested','loaded','failed','too_big'], package_id, eta_count, loaded_count, error, requested_at, loaded_at, attempts)`; unique `(system, kind, date_from, date_to)`.
- [ ] **Step 1: Failing tests:** `test_one_row_per_system_and_uuid` (IntegrityError on duplicate), `test_same_uuid_may_exist_in_both_systems`.
- [ ] **Step 2: Run** → FAIL. **Step 3:** models + `makemigrations tax_invoicing -n eta_history_mirror`. **Step 4:** PASS. **Step 5: Commit** `feat(tax): ETA history mirror tables`.

### Task 3: Package backfill engine

**Files:**
- Create: `apps/tax_invoicing/eta_history.py`
- Test: `apps/tests/test_eta_history.py` (fixtures: small ZIPs built in the test from JSON shaped like ETA's "full" package; receipts likewise)

**Interfaces:**
- Consumes: `EtaReader`, the three models.
- Produces: `plan_windows(system, kind, start: date, end: date) -> int` (receipts 4-day windows, documents 30-day), `step(system, kind, max_requests=5) -> dict` (requests planned windows, polls requested ones, downloads complete ones, upserts, returns counts), `upsert_documents(system, rows: list[dict], source) -> int`, `upsert_receipts(system, rows, source) -> int`, `progress(system) -> dict` (per kind: counts per state, oldest/newest loaded date, last error, `why_not`).
- [ ] **Step 1: Failing tests:**
  - `test_backfill_requests_polls_downloads_and_loads` (3 rows in ZIP → 3 mirrored, window `loaded`, `loaded_count == 3`).
  - `test_too_big_window_is_split_in_halves` (400 `OperationExceedsLimit` → window replaced by two halves, `planned`); `test_one_day_window_still_too_big_is_marked_too_big`.
  - `test_unreachable_eta_leaves_window_unloaded_with_reason` (ConnectionError → state unchanged or `failed`, error set, no rows).
  - `test_expired_package_is_requested_again` (package status 4 → window back to `planned`).
  - `test_reload_is_idempotent_and_newest_status_wins` (Valid then Cancelled for same uuid → one row, `cancelled`).
  - `test_request_body_never_truncates` (`truncateifexceeded` is False in every documents request).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** Map ETA fields to columns in one `_doc_fields(row)` / `_receipt_fields(row)` each; keep `raw` as received. **Step 4:** PASS. **Step 5: Commit** `feat(tax): ETA package backfill with window splitting`.

### Task 4: Top-up, command, scheduler, freshness

**Files:**
- Modify: `apps/tax_invoicing/eta_history.py` (add `top_up(system, days=3) -> dict` via documents search Sent+Received and receipts recent), `apps/sync/tasks.py` (jobs `eta_history_backfill` every 15 min, `eta_history_topup` daily 04:30), `apps/sync/freshness.py` (domains `eta_history_preprod`, `eta_history_production`, source reads the newest `loaded_at`), `apps/tests/test_scheduler_locks.py` (guards: `unique_key`, `apps.tax_invoicing.models.EtaMirrorDocument`, the `UniqueConstraint` line)
- Create: `apps/tax_invoicing/management/commands/eta_history.py` (`--system`, `--plan`, `--step N`, `--topup`)
- Test: `apps/tests/test_eta_history.py`

**Interfaces:**
- Produces: `top_up(system, days=3) -> dict`; jobs call `step()` / `top_up()` only for systems whose `EtaReader(system).enabled()`.
- [ ] **Step 1: Failing tests:** `test_topup_pages_with_continuation_token_until_EndofResultSet`, `test_jobs_skip_disabled_systems`, scheduler guard test passes with the two new jobs, freshness domain returns a timestamp after a load.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4:** PASS (including `apps.tests.test_scheduler_locks`). **Step 5: Commit** `feat(tax): ETA history top-up, jobs and freshness`.

### Task 5: Progress API and screen section

**Files:**
- Modify: `apps/tax_invoicing/views.py`, `urls.py` (`history/progress/` VIEWER, `history/refresh/` EDITOR — runs `step` + `top_up` in a thread for one system), `frontend/src/api/client.js`, `frontend/src/pages/taxinvoicing/SettingsTab.jsx` (section «سجل المصلحة — التحميل»: per system, per kind: windows loaded/planned/failed/too big, rows mirrored, date range covered, last error, why disabled; refresh button; `DataFreshnessBar` with both domains), `apps/help/content/tax_invoicing.py` (+ `updated`), `docs/architecture/36_TAX_INVOICING.md`, `apps/tests/security/baselines/*` if the sweep asks
- Test: `apps/tests/test_eta_history.py`, `frontend/src/pages/taxinvoicing/taxinvoicing.test.jsx`

**Interfaces:**
- Consumes: `progress(system)`, `step`, `top_up`.
- [ ] **Step 1: Failing tests:** `test_progress_view_needs_view_and_lists_both_systems`, `test_refresh_needs_edit_and_refuses_a_disabled_system`; frontend: section renders both systems and calls refresh with `{system: 'preprod'}`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4:** backend + `npx vitest run src/pages/taxinvoicing` + `npx eslint` PASS; `apps.tests.test_help` PASS. **Step 5: Commit** `feat(tax): ETA history progress and refresh`.

### Task 6: Proof on the test system (laptop)

- [ ] Turn on `TAX_ETA_READ_PREPROD_ENABLED=True` on the laptop `.env`; `python manage.py eta_history --system preprod --plan` then `--step 5` until the last month is loaded.
- [ ] Record: receipt package accepted with the ERP token (yes/no — if no, stop and ask the owner before any device secret), a real package's field names vs our mapping (fix mapping + fixtures, no personal data in fixtures), counts per state.
- [ ] Full tax suites + security sweep (serially) green; open the PR; merge when green per owner rule; fast-forward the laptop.
