# Performance Stage 1 — Measure and Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Know where time goes (baseline) and make CI fail when a guarded endpoint starts running more queries, before any speed fix lands.

**Architecture:** A small query-budget harness in `apps/tests/perf/` measures each guarded endpoint twice (few rows, many rows) and asserts the count is flat and under a ceiling from one `BUDGETS` table. The existing slow-request view (`apps/sync/views.py:slow_requests`) gains total-time ranking. A read-only `perf_top_queries` command reads `pg_stat_statements` when the owner has enabled it; the owner enables it with written steps after closing.

**Tech Stack:** Django 4.2 TestCase + `CaptureQueriesContext`, DRF, React (SyncPage), PostgreSQL 16 `pg_stat_statements`.

**Spec:** `docs/superpowers/specs/2026-11-19-performance-boost-design.md` (Stage 1, §4, §9).

## Global Constraints

- Nothing in this stage changes what any endpoint returns, and nothing writes to SOFTECH.
- Wall time is **not** asserted in CI; only query counts (spec §6 Stage 1).
- Ceilings are "measured today + small margin", never a target to work towards in this stage; Stage 3 lowers them.
- Claude never restarts the office Postgres; the owner runs the steps after closing (spec §9).
- Help text for any changed screen: Arabic + English, bump `updated` (CLAUDE.md rule 5b).
- Run the backend suite serially, never `--parallel` on the office PC (memory: PC memory + CI timeouts).
- Branch: work on `claude/perf-stage1-*`, PR to `main`, CI green before merge.

## Review Focus

1. **An endpoint returns 403 for the test user** — a budget test that measures a 403 counts 2–3 queries and passes forever. Every budget measurement must assert `status_code == 200` first (Task 1 helper).
2. **Row growth that never reaches the code path** — "many rows" created for the wrong branch / status is filtered out and the count looks flat. Each test asserts the response actually contains ≥ the many-row count (Task 1 helper takes `min_rows`).
3. **Caches hiding queries** — the second call of a memoised path (e.g. `branch_scope` memo) runs fewer queries. The helper clears the Django cache and calls `core.branch_scope` invalidation before each measurement (Task 1).
4. **`pg_stat_statements` absent** (CI, dev, office before restart) — `perf_top_queries` must print a clear "not enabled" line and exit 0, not crash (Task 4 test).
5. **Slow-request view with zero rows or `days` garbage** — must still return 200 with an empty list (Task 3 test).

---

### Task 1: Query-budget harness + budgets table + polled endpoints

**Files:**
- Create: `apps/tests/perf/__init__.py`
- Create: `apps/tests/perf/budget.py`
- Create: `apps/tests/perf/budgets.py`
- Create: `apps/tests/perf/test_budget_polled.py`

**Interfaces:**
- Produces:
  - `budgets.BUDGETS: dict[str, Budget]` keyed by a short route name (e.g. `'sync/freshness'`).
  - `budgets.Budget` = `NamedTuple(kind: Literal['poll','list','report','track'], ceiling: int, note: str)`. `kind` maps to spec §4 targets (poll ≤ 300 ms, list ≤ 800 ms, report ≤ 2 s, track ≤ 100 ms); `note` says where the ceiling came from.
  - `budget.measure(client, url: str, *, method='get', data=None) -> tuple[int, Response]` — clears `django.core.cache.cache`, calls `core.branch_scope.bump_generation()` to drop the branch-scope memo, runs the request inside `CaptureQueriesContext`, returns (query count, response).
  - `budget.assert_budget(testcase, name: str, client, url: str, *, grow: Callable[[], None], min_rows: int, rows_of: Callable[[Response], int] = default_rows, method='get', data=None) -> None` — measure once, call `grow()`, measure again; assert both responses are 200, assert `rows_of(second) >= min_rows`, assert second count == first count (flat), assert second count ≤ `BUDGETS[name].ceiling`. Failure message prints both counts and the 5 most repeated SQL shapes (strip literals with a regex) so the N+1 is obvious.
  - `budget.default_rows(resp)` — `len(resp.data['results'])` if paginated, else `len(resp.data)` if list, else `0` (polled endpoints pass `min_rows=0`).

- [ ] **Step 1: Write the failing harness self-test** in `test_budget_polled.py`:

```python
class HarnessSelfTest(TestCase):
    def test_refuses_a_403(self):
        _, _, client = make_salesperson('perf_403')
        with self.assertRaises(AssertionError):
            assert_budget(self, 'sync/freshness', client, '/api/sync/slow-requests/', grow=lambda: None, min_rows=0)
```

- [ ] **Step 2: Run it** — `./venv/Scripts/python.exe manage.py test apps.tests.perf.test_budget_polled -v 2` → FAIL (`ModuleNotFoundError` / import error).

- [ ] **Step 3: Implement `budget.py` and `budgets.py`** with the interfaces above. Start `BUDGETS` with the polled routes only: `notifications/`, `notifications/category-counts`, `sync/status`, `sync/freshness`, `dashboard/summary`. Ceilings are filled in Step 5.

- [ ] **Step 4: Write the polled budget tests**, one test per route, admin client (`make_admin`), with `grow` adding realistic rows for that route (notifications: 30 unread notifications across 3 categories for the user; dashboard/freshness: 30 reservations across statuses + a few `PurchaseHistory` rows dated today; sync/status: a few `SyncRun` rows). Temporarily set every ceiling to `999`.

- [ ] **Step 5: Run, read the measured counts, set ceilings** = measured + 2 (write the measured number in `note`, e.g. `'measured 46 on 2026-11-19; Stage 3 target: ≤ 8'`). Re-run → PASS. Expect `sync/freshness` and `dashboard/summary` to be the largest (audit: 46 and 35).

- [ ] **Step 6: Commit** — `git add apps/tests/perf && git commit -m "test(perf): query-budget harness and polled-route budgets (perf stage 1)"`

### Task 2: Budgets for lists, search and reports

**Files:**
- Create: `apps/tests/perf/test_budget_lists.py`
- Create: `apps/tests/perf/test_budget_reports.py`
- Modify: `apps/tests/perf/budgets.py` (add rows)

**Interfaces:**
- Consumes: `assert_budget`, `BUDGETS`, `default_rows` from Task 1; factories in `apps/tests/factories.py`.

Routes (the locustfile set plus the slow-log leaders):

| Name | URL | Test user | Grow (many rows) |
|---|---|---|---|
| `reservations` | `/api/reservations/` | admin | 25 reservations, 2 lines each |
| `customers` | `/api/customers/` | pharmacist (branch-scoped — exercises phone masking) | 25 customers |
| `customers?search` | `/api/customers/?search=أحمد` | pharmacist | 25 matching customers |
| `items?search` | `/api/items/?search=بارا` | admin | 25 matching items |
| `search/universal` | `/api/search/universal?q=بارا` | admin | 10 items + 10 customers matching |
| `supply/cases` | `/api/supply/cases/` | admin | 20 cases, 2 availability lines each |
| `pos-orders` | `/api/pos-orders/` | admin | 20 orders, 2 lines each |
| `insurance/claims` | `/api/insurance/claims/` | admin | 15 claims with prescriptions |
| `purchasing/metrics` | `/api/purchasing/metrics/` | purchasing role | 30 metrics rows in one run |
| `purchasing/filter-options` | `/api/purchasing/filter-options/` | purchasing | 30 items over 5 effect codes |
| `batches/stock-expiry/summary` | `/api/batches/stock-expiry/summary/` | admin | 30 expiry balances |
| `incentives/targets` | `/api/incentives/targets/` | admin | 10 targets |
| `purchasing/shortage/candidates` (and `confirmed`, `deltas`, `med-types`) | as named | purchasing | 20 candidates |
| `audit/screen-view` | `POST /api/audit/screen-view/` | pharmacist | — (`kind='track'`, `min_rows=0`; asserts ceiling only — read the view for the payload) |

- [ ] **Step 1: Write the tests** in the two files (lists/search → `test_budget_lists.py`; the rest → `test_budget_reports.py`), ceilings temporarily `999`. Where a model needs fields the factories lack, add a local `_make_<thing>` helper in the test file (not in `factories.py` unless a second file needs it). Read each view's queryset filter before choosing grow data so rows are not filtered out (Review Focus 2).

- [ ] **Step 2: Run** — `./venv/Scripts/python.exe manage.py test apps.tests.perf -v 2`. Any **non-flat** route fails here: that is a real N+1. Do **not** fix it in this stage; mark that test `@expectedFailure` with a comment `# N+1 found in Stage 1 — fix in Stage 3` and list it in the PR description.

- [ ] **Step 3: Set ceilings** = measured + 2 with the measured number in `note`. Re-run → PASS (expected failures reported as such).

- [ ] **Step 4: Commit** — `git commit -m "test(perf): query budgets for lists, search and reports (perf stage 1)"`

### Task 3: Slow-route ranking by total time on /sync

**Files:**
- Modify: `apps/sync/views.py:311-345` (`slow_requests`)
- Modify: `frontend/src/api/client.js:425` (`slowRequests`)
- Modify: `frontend/src/pages/SyncPage.jsx:~205-260` (slow-requests card)
- Modify: `apps/help/content/admin.py` (the `/sync` screen entry: describe the new sort and columns, AR + EN, bump `updated`)
- Test: `apps/tests/test_sync_slow_requests_ranking.py`

**Interfaces:**
- Produces: `GET /api/sync/slow-requests/?days=7&sort=total|p95&limit=25` → `{'days', 'threshold_ms', 'sort', 'endpoints': [{'path','method','count','p50_ms','p95_ms','max_ms','total_s'}]}`. Defaults: `days=14`, `sort='p95'` (today's behaviour), `limit=10`, `limit` clamped 1..50. `total_s` = sum(ms)/1000 rounded to 1 decimal. Admin-only check unchanged.
- `syncApi.slowRequests(days = 14, sort = 'p95', limit = 10)`.

- [ ] **Step 1: Write failing tests:** `test_sort_total_orders_by_total_time` (route A: 2 × 10 000 ms, route B: 30 × 1 200 ms → `sort=total` puts B first, `sort=p95` puts A first); `test_fields_present` (`p50_ms`, `total_s` on each row); `test_limit_clamped` (`limit=999` → ≤ 50 rows); `test_empty_and_garbage_params` (no rows, `days=abc&sort=zzz` → 200, `endpoints == []`, `sort == 'p95'`); `test_non_admin_403`.
- [ ] **Step 2: Run** `manage.py test apps.tests.test_sync_slow_requests_ranking` → FAIL.
- [ ] **Step 3: Implement** in `slow_requests`; unknown `sort` falls back to `'p95'`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Frontend:** a two-option toggle «الأبطأ / الأكثر استهلاكًا للوقت» (p95 / total) in the card header, columns p50, p95, max, count, total (s); keep `data-tour="admin-sync-slow-requests"`; table sortable via the project's `useSortableRows` + `SortTh` (memory: sortable grids everywhere). Query key includes `sort`.
- [ ] **Step 6: Help + build:** update `admin.py` help; run `./venv/Scripts/python.exe manage.py test apps.tests.test_help` → PASS; `cd frontend && npm run build` → no errors.
- [ ] **Step 7: Commit** — `git commit -m "feat(sync): rank slow routes by total time (perf stage 1)"`

### Task 4: `perf_top_queries` command + owner steps for query statistics

**Files:**
- Create: `apps/sync/management/commands/perf_top_queries.py`
- Create: `docs/deploy/2026-11-office-pg-query-stats.md`
- Modify: `deploy/LINKDATACENTER_VPS_RUNBOOK.md` §7.3 (add the same settings for the VPS)
- Test: `apps/tests/test_perf_top_queries.py`

**Interfaces:**
- Produces: `manage.py perf_top_queries [--limit 20] [--sort total|mean|calls] [--reset]`. Read-only except `--reset`, which calls `pg_stat_statements_reset()` and requires `--confirm`. Output: one line per query — calls, total s, mean ms, rows, first 160 chars of normalised SQL. When the extension is missing or not preloaded, prints `pg_stat_statements is not enabled — see docs/deploy/2026-11-office-pg-query-stats.md` and exits 0.

- [ ] **Step 1: Write failing tests:** `test_not_enabled_prints_hint_and_exits_zero` (test DB has no extension → output contains `not enabled`, no exception); `test_reset_requires_confirm` (`--reset` without `--confirm` → `CommandError`). Detection: `SELECT 1 FROM pg_extension WHERE extname='pg_stat_statements'` plus a guarded trial `SELECT … LIMIT 1` that catches the "must be loaded via shared_preload_libraries" error.
- [ ] **Step 2: Run** `manage.py test apps.tests.test_perf_top_queries` → FAIL.
- [ ] **Step 3: Implement** the command (raw SQL via `connection.cursor()`; the `--sort` value is chosen from a fixed dict, never interpolated from input).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Write the owner doc** `docs/deploy/2026-11-office-pg-query-stats.md`, Arabic summary + English steps, for **after closing**: (1) back up `postgresql.conf` (path from `SHOW config_file;`); (2) set `shared_preload_libraries = 'pg_stat_statements'`, `track_io_timing = on`, `pg_stat_statements.track = top`; (3) restart the Windows service (`Restart-Service postgresql-x64-16` from an admin PowerShell — confirm the name with `Get-Service postgresql*`); (4) `CREATE EXTENSION IF NOT EXISTS pg_stat_statements;` in `elrezeiky_db`; (5) check: `manage.py perf_top_queries --limit 5` prints rows; (6) undo: restore the backup file and restart. Note the memory warning: stop only the services listed in memory "Office restart: only :8000" if needed — Postgres restart alone is enough here. Add the same three settings (+ `random_page_cost = 1.1`) to runbook §7.3.
- [ ] **Step 6: Commit** — `git commit -m "feat(sync): perf_top_queries command; owner steps for query statistics (perf stage 1)"`

### Task 5: Definition of done + baseline record

**Files:**
- Modify: `CLAUDE.md` (Security definition of done → add item 9)
- Modify: `docs/full-project-audit/07_PERFORMANCE_AUDIT.md` (new §6 "Stage 1 baseline")
- Modify: `docs/architecture/11_ERP_INDEX.md` (design-docs row for the performance boost spec + this plan)

- [ ] **Step 1: CLAUDE.md item 9:** "**Speed:** every new list/report endpoint gets a row in `apps/tests/perf/budgets.py` and a budget test (flat query count + ceiling); exports go through the shared export job once Stage 4 lands (design `docs/superpowers/specs/2026-11-19-performance-boost-design.md`)."
- [ ] **Step 2: Baseline:** from the office DB (read-only) record into §6: slow-request ranking by total time for the last 14 days (the new `sort=total` view or the same query via shell), the full `BUDGETS` table (route, kind, measured count), and — only if the owner has already run Task 4's steps — `perf_top_queries --limit 20`. Otherwise write "pending owner restart" and the date.
- [ ] **Step 3: Index row** in `11_ERP_INDEX.md` design table: status "🟡 Stage 1 in progress".
- [ ] **Step 4: Full check:** `./venv/Scripts/python.exe manage.py test apps.tests.perf apps.tests.test_sync_slow_requests_ranking apps.tests.test_perf_top_queries apps.tests.test_help apps.tests.test_sync_r7` → all pass; `cd frontend && npm run lint && npm run build` → clean.
- [ ] **Step 5: Commit, push, PR** — `git commit -m "docs(perf): stage 1 baseline and definition of done"`; PR body lists measured counts, any `@expectedFailure` N+1s found, and the owner step (Task 4 doc) to run after closing.
