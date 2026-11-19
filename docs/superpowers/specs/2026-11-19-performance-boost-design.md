# Performance boost — fast and light on a small VPS

**Status:** APPROVED by the owner and Stages 1–5 BUILT, all on main (2026-11-19): #232 #235 (measure + guard), #236 (server setup, switches OFF), #233 #237 (slow screens), #242 #243 (exports as background jobs), #241 (live updates), plus #240 #247 (fail-fast SOFTECH connect for screen reads). Stage 6 = doc 40 (approved, built per table on the owner's go); Stage 7 (index cleanup) waits for a week of writer stats. Owner steps open: §8 and the list in §12.
**Builds on:** full audit `docs/full-project-audit/07_PERFORMANCE_AUDIT.md` (PERF-1…PERF-10),
light load test `docs/uat/light-load.md`, SOFTECH delta sync doc 40 (approved, not built),
VPS runbook §7.3 / §13.6 / §13.7.

---

## 1. Intent

Every screen, list, report and export must feel instant for **20–40 staff working at the same
time** on the production VPS (**4 vCPU · 8 GB RAM**, Postgres, Redis, nginx, scheduler with a JVM,
OCR sidecar). No single user, export or background job may slow everyone else down.

Why now: the system is moving to the VPS for many users. The light load test (10 users, one
process) already showed p95 of 3 s overall and 5 s on a poll every screen makes; cheap requests ran
5–12× slower than alone because they queued behind slow ones.

## 2. Goals, non-goals, anti-goals

**Goals**
- Speed targets per kind of request (§4), measured on the VPS at 20 and 40 users.
- No request in the web process runs longer than 30 s; no export runs inside a web request.
- A CI check that fails when a guarded screen gets slower or starts running many more queries.
- Less steady background load: fewer and cheaper polls, fewer SOFTECH rows read.

**Non-goals**
- A bigger VPS (the 16 GB / 8 vCPU quote stays the owner's separate choice).
- A new task-queue product (Celery, RQ), a read replica, or an async rewrite of views.
- Changing what any screen shows or any business rule. Numbers on screens and in exports must be
  identical before and after.

**Anti-goals (failure even if faster)**
- A cache that shows stale money or stock figures without saying how old they are.
- Breaking SOFTECH safety: any change to SOFTECH reads goes through doc 40's switches and gates.
- Running out of memory: the 8 GB budget (runbook "Resource budget") must still hold with the
  scheduler mid-sync.
- Removing data or indexes on guesswork.

## 3. What is already done (do not redo)

| Item | State |
|---|---|
| PERF-1 monitoring-alert flood | 14-day retention, PR 154. Bell default = decision D-19, still open |
| PERF-2 sales-history date index | Done, 315 → 4.1 ms (PR 154) |
| PERF-3 more web processes | `deploy/elrezeiky-web-extra@.service` + runbook §13.6 exist, **not installed** |
| PERF-4 N+1 on reservations / customers / supply | Done, PR 166 |
| PERF-5 filter-options DISTINCT | Done, `7694b905` |
| PERF-6 SOFTECH delta sync | Design doc 40 approved, not built |
| Frontend code splitting | 196 lazy routes; main chunk ~0.7 MB raw; palette/drawers lazy (FE-19) |
| Slow-request log | `SlowRequestMiddleware` → `sync_slowrequest` (≥ 1000 ms) |
| Background export pattern | `PicExportJob` + `apps/pic_analytics/jobs.py` (thread in the web process) |
| Load test | `deploy/loadtest/locustfile.py`, run once at 10 users |

## 4. Speed targets (p95, measured on the VPS at 40 users, scheduler running)

| Kind | Examples | Target |
|---|---|---|
| Polled on every screen | bell counts, `sync/status`, `sync/freshness`, `pbx/live` | ≤ 300 ms |
| Lists and search | reservations, customers, items, universal search, POS lookups | ≤ 800 ms |
| Dashboards and reports on screen | dashboard summary, stock-expiry summary, PIC overview, purchasing, shortage, incentives targets | ≤ 2 s (or a cached result with its age shown) |
| Tracking / fire-and-forget | `audit/screen-view` | ≤ 100 ms |
| Export start | any export button | the request returns in ≤ 1 s; the file follows as a job |
| Any web request | — | hard stop at 30 s (statement timeout) |

Login stays as is (password hashing cost is a security choice).

## 5. Approaches considered

| | Approach | Trade-off | Verdict |
|---|---|---|---|
| **A** | Server setup first, then each slow screen, plus speed checks in CI | Needs one owner step on the VPS; touches many modules over several PRs | **Chosen by the owner (2026-11-19)** |
| B | Fix only the slow screens | Cheaper to start, but one Python process remains: one long export still freezes everyone (load test L-02) | Rejected |
| C | Large rebuild: task queue, reporting replica, async views | Too much for 20–40 users; extra processes do not fit 8 GB | Rejected |

## 6. Design — seven stages, each its own PR with before/after numbers

### Stage 1 — Measure and guard

- **Baseline:** enable `pg_stat_statements` and `track_io_timing` (runbook §7.3 addition; office
  too while it is the writer). Record a baseline from `sync_slowrequest` and the locustfile.
- **Speed budget test (CI):** a new test module (e.g. `apps/tests/perf/test_query_budgets.py`)
  calls each guarded endpoint with realistic fixture data (50+ rows) and asserts a **query-count
  ceiling** per endpoint (`assertNumQueries`-style, ceiling not exact). Query counts are stable in
  CI; wall time is not, so time is not asserted in CI.
- **Guarded list:** every endpoint in §4's rows plus every list endpoint the locustfile hits. New
  list endpoints are added as they are built (added to the CLAUDE.md "definition of done").
- **Runtime budget:** `SlowRequestMiddleware` already logs ≥ 1 s. Add a small `/sync`-screen view
  (or extend the existing slow-request tab) ranking routes by total time over 7 days, so drift is
  visible without a developer.

### Stage 2 — Server setup (code here; installation is an owner step)

- **3 web processes** (runbook §13.6 units) behind the nginx upstream; WebSocket groups already go
  through Redis.
- **Shared cache in Redis** (`django-redis` or Django's built-in `RedisCache`) replacing
  `LocMemCache`, so throttles, rate counters and caches are shared by all processes. This must land
  **before** the extra processes are enabled, or per-process counters weaken the N3–N6 limits.
  Dev/test keep LocMem.
- **Connections:** `CONN_MAX_AGE` ≈ 60 s with `CONN_HEALTH_CHECKS` on the VPS (env-driven; dev
  stays 0). Check `max_connections` against 3 processes × thread pool + scheduler; add pgbouncer
  only if the count does not fit.
- **Statement timeout:** `-c statement_timeout=30000` in `OPTIONS` for web processes only (env
  flag); the scheduler and management commands keep no limit. The `audit_log` connection gets the
  same web limit.
- **Postgres tuning:** apply runbook §7.3 values; `random_page_cost = 1.1` on SSD.
- Memory check after install: `free -m` above 1 GB with the scheduler mid-sync.

### Stage 3 — Slow screens

Fix in order of total time in the slow log, each with a budget test from Stage 1:

1. Market shortage `api/purchasing/shortage/{confirmed,deltas,med-types,candidates}/` (19–33 s).
2. `batches/stock-expiry/summary` (4–7 s, mostly Python).
3. `incentives/targets` (3 s).
4. `audit/screen-view` (2.7 s for a tracking POST).
5. `sync/freshness` (46 queries → one grouped query per domain) and `dashboard/summary`
   (9 status counts → one grouped count).
6. Universal search customer branch (`UPPER(name) LIKE '%x%'` → use the existing folded/trigram
   search machinery from the unified item search work).
7. `pic-analytics/overview` long ranges (pre-aggregated monthly rollup).
8. `help/*` endpoints (1.5–3 s) and anything else the Stage 1 ranking shows.

**Caching rule:** only data that changes on a sync or engine run may be cached, keyed by that
run's id or timestamp, and the response says when it was computed. Money and stock on POS and
cashier paths are never served from cache.

### Stage 4 — Exports off the web request

- **One shared export job model** generalised from `PicExportJob` (owner, params, status,
  progress, file bytes or a protected file, 48 h retention, one active job per user per kind,
  audit entry at download). PIC analytics moves onto it; its behaviour does not change.
- **Runner:** a small separate service `elrezeiky-jobs` (no JVM unless an export needs SOFTECH)
  that claims queued jobs with `SELECT … FOR UPDATE SKIP LOCKED`. When the service is not
  installed (dev), jobs fall back to today's thread.
- **Writers:** Excel built with `openpyxl` `write_only=True` and querysets read with `.iterator()`
  in chunks, so memory stays flat for large files. CSV where the screen already offers CSV.
- **Front end:** one shared "export" button/hook: start → progress → download, the same for every
  screen; the user can keep working.
- **Scope:** all 34 export routes and the other `openpyxl` writers in views. Small exports that
  finish in under ~3 s may stay synchronous but must still use the streaming writer.
- Export safety rules stay as they are (`core/export_safety.py`, formula guard, access stamp,
  new-value registry).

### Stage 5 — Polling

- Push bell counts, freshness and sync status over the existing WebSocket (Channels + Redis);
  timers become a slow fallback (e.g. 120 s) only while the socket is down, instead of 8 s.
- Remove the duplicate 30 s `sync/status` poll on the dashboard.
- Global React Query defaults: no refetch while the tab is hidden; review every
  `refetchInterval` (155 sites) and keep fast ones only where a person is watching live work
  (POS queue, delivery dispatch, PBX).
- `pbx/live` 6 s poll per extension → WebSocket event from the AMI bridge if it already emits one;
  else 15 s.

### Stage 6 — SOFTECH reads

Build doc 40 as approved: per-table OFF → SHADOW → ON switches, evidence gates G1–G4, owner
confirms each table. This stage follows doc 40 and its own plan; nothing in this document changes
it. Plus the remaining audit item: batch `sync_in_transit._fetch_items` into one `IN (…)` query
per cycle (read-only).

### Stage 7 — Index cleanup

After a full week of production `pg_stat_statements` / `pg_stat_user_indexes` with no restart,
list zero-scan indexes (≈ 3.6 GB on the office copy, 1.5 GB on `purchasing_itemdemandmetrics`),
show the list to the owner, then drop the agreed ones `CONCURRENTLY` via migrations. Drop the
duplicate `(recipient_id, is_read)` notification index straight away (identical twin).

## 7. Verification

- Every PR: budget tests green; before/after numbers (query count, ms) in the PR description.
- After Stage 2 install and after Stages 3–5: runbook §13.7 load test at 20 then 40 users from
  another machine, plus the **interference test** (one large export running during the poll mix).
  Results go into `07_PERFORMANCE_AUDIT.md`. Done = §4 targets met at 40 users, 0 failures,
  free memory above 1 GB.

## 8. Order and stop points

1 → 2 (code) → owner installs 2 → 3 → 4 → 5 → load test → 6 (per doc 40) → 7.
Stop and ask the owner before: installing anything on the VPS, any SOFTECH sync change (Stage 6),
dropping indexes (Stage 7), and any change that alters what a cached screen shows.

## 9. Owner decisions (2026-11-19)

- **Redis down → safety first.** Security counters (login, OTP / 2FA, N3–N6 per-phone and
  proof-of-work limits) **fail closed**: if Redis cannot be reached, those requests are refused
  with a clear "try again shortly" message, never allowed without a limit. Plain performance
  caches fail open (compute without the cache). Rate counters live in their own Redis database
  with `noeviction`, apart from the cache and the Channels layer, so a full cache can never evict
  a limit. Tests cover both the refuse path and the cache-miss path.
- **Visible changes approved once, for every screen:** (a) a cached screen shows an "as of HH:MM"
  label for its data age; (b) customer search moves to the folded/trigram matching and may return
  more Arabic name variants than today. Neither needs a per-screen stop. Any other change to what
  a screen shows (different totals, columns, filters) still needs the owner first. The non-goal in
  §2 ("numbers identical") still holds for every total and figure.
- **Office Postgres restart allowed once, after closing,** to add `pg_stat_statements` to
  `shared_preload_libraries` and turn on `track_io_timing`. Claude does not restart it: Stage 1
  hands the owner exact steps (config lines, restart, check, undo) to run after closing. The
  baseline week starts from that restart.

## 10. Calls made after the builder check (owner may override)

- **Statement timeout ships OFF** (env flag) in Stage 2 and is switched on only after Stages 3–4
  have moved the long work out of web requests. Background threads, the jobs runner, OCR, the
  scheduler and management commands never get it.
- **Memory:** the jobs runner starts without a JVM; any export that reads SOFTECH live stays on the
  in-process thread until it is moved to the mirror. If `free -m` stays under 1 GB, the first cut is
  one extra web process instead of two; nothing else is cut without the owner. The 16 GB quote
  remains the real fix if both are needed.
- **Which server:** the office stays the writer until cutover (scheduler, engines, SOFTECH writes).
  Index statistics for Stage 7 come from **the writer** (office before cutover, VPS after), never
  from a reader. The load test runs on the VPS per runbook §13.7; a second run after cutover with
  the scheduler on the VPS is the one that counts for §4.
- **OCR:** `deploy/elrezeiky-ocr.service` exists. Stage 4 checks whether any OCR still runs on
  web-process threads; if so it moves onto the same jobs runner.
- **Connections:** try `CONN_MAX_AGE` ≈ 60 with a capped ASGI thread pool first and count
  connections under the load test; if the count does not fit `max_connections`, pgbouncer
  (transaction mode) becomes an owner install step.

## 11. Left to the builder

- Exact query-count ceilings per endpoint (measure, then set ceiling ≈ measured + small margin).
- How each slow screen is fixed (query rewrite, index, rollup, cache) — profile first.
- Whether the shared export model lives in an existing app (e.g. `apps/sync`, which owns
  operational plumbing) or a new small one; it must follow the security definition of done.
- Which polled values get WebSocket events first (start with the bell).

## 12. Where it stands (2026-11-19, end of day)

**On main and live on the office server:**

| Stage | PRs | Result |
|---|---|---|
| 1 Measure + guard | #232, #235 | 18+ routes under CI query budgets (`apps/tests/perf/`); /sync ranks slow routes by total time; `perf_top_queries` |
| 2 Server setup | #236 | Redis caches (limits fail closed), `DB_CONN_MAX_AGE`, web `statement_timeout`: all OFF until set in `.env` |
| 3 Slow screens | #233, #237 | Market shortage 10–15+ s → 0.2–0.55 s warm; freshness 46 → 5 queries, dashboard 32 → 8, stock-expiry 37 → 2, incentives targets 164 → 18 |
| 4 Exports | #242, #243 | Purchasing, ISR fulfilment, advanced/pivot, shortage, stock-audit, tax history/recon exports and PIC run as background jobs (`apps/export_jobs`); `elrezeiky-jobs` unit is an owner install |
| 5 Polling | #241 | Bell counts + freshness pushed over the WebSocket; slow fallback polls; no polling in hidden tabs |
| SOFTECH reads | #240, #247 | Screen reads connect with one 5 s attempt and skip a node that failed in the last 60 s; syncs and writers unchanged |

**Owner steps still open (nothing above needs them to keep working as today):**
1. #237's index migrations on the office DB (coordinator, 02:00 build).
2. Office Postgres restart after closing for `pg_stat_statements` (`docs/deploy/2026-11-office-pg-query-stats.md`).
3. VPS: `CACHE_REDIS_URL` + `LIMITS_REDIS_URL` (own DB, `noeviction`), then the extra web processes, then `DB_CONN_MAX_AGE` and `WEB_STATEMENT_TIMEOUT_ENABLED` (runbook §7.3, §13.6); optional `elrezeiky-jobs`.
4. Load test at 20 then 40 users (runbook §13.7) against §4, with the export interference test.
5. Keep the office `venv` folder "Always keep on this device" in OneDrive: a cold `import redis` took 42 s.

**Not done:** Stage 6 (doc 40, per table on the owner's go), Stage 7 (index cleanup after a week of writer stats),
the deferred Stage 1 review minors (fresh user per budget call; track ceiling on the dearer call).
