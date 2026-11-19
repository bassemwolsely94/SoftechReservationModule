# Performance Stage 3 — polled screens and the slow summaries

**Spec:** `docs/superpowers/specs/2026-11-19-performance-boost-design.md` §4 (polled ≤ 300 ms,
reports ≤ 2 s), §6 Stage 3, §9 (numbers identical; "as of" label pre-approved for cached screens).
**Evidence:** `docs/full-project-audit/07_PERFORMANCE_AUDIT.md` PERF-2/4/8/10.
**Branch:** `claude/perf-s3-polled-screens-4a9ac8` — one commit per endpoint, TDD.

## Baseline (office DB, read-only, admin user, 3 warm runs, 2026-11-19)

| Endpoint | Queries | ms (min/median) | Where the time goes |
|---|---:|---:|---|
| `GET /api/sync/freshness/` | 46 | 1250 / 1373 | 2 queries per run log × 18 sources; `MAX(etamirrorreceipt.fetched_at)` 523 ms; `MAX(purchasehistory.invoice_date)` 425 ms (no index) |
| `GET /api/dashboard/summary/` | 32 | 501 / 529 | 1 COUNT per KPI; customer counts are seq scans (124–184 ms) |
| `GET /api/batches/stock-expiry/summary/` | 37 | 5517 / 6156 | DB 1.7 s; ~4 s Python building full `Item` rows 9× for one `cost_price` |
| `GET /api/incentives/targets/` | 164 | 1562 / 1779 | 4–6 queries per target (`attainment()` per row) |
| `POST /api/audit/screen-view/` | — | — | profiled in task 4 |

## Tasks (each: failing test first → fix → same output on the same data → flat query count)

1. **Freshness** (`apps/sync/freshness.py` only; never `slow_requests` in `views.py`).
   - Main-sync domains: one `SyncLog` query grouped by `table_name` (success max + attempt max).
   - Run-log sources: one `UNION ALL` of "latest success" / "latest attempt" probes, built from the
     same filters and orderings as today.
   - Indexes (concurrent, no lock): `PurchaseHistory(invoice_date)`, ETA mirror `(system, fetched_at)`
     / `(system, loaded_at)` where missing.
   - Target ≤ 8 queries, ≤ 300 ms.
2. **Dashboard summary** — reservation KPIs + funnel in one filtered-`Count` aggregate; customers,
   follow-ups, transfers, sales one aggregate each; sargable date bounds. Drop `DashboardPage`'s
   duplicate 30 s `sync/status` poll (Layout already polls it). Cache only if still slow, keyed to
   the last sales sync, with an "as of" label.
3. **Stock-expiry summary** — one grouped query (item × role × expiry band) + one `cost_price` lookup;
   bands, buckets and values computed from that in Python.
4. **Incentives targets + screen-view** — profile, then batch per-target actuals and fix the tracking
   POST to ≤ 100 ms.

## Tests
`apps/tests/test_perf_stage3.py`: per endpoint, (a) response equals the pre-change implementation
(kept in the test as the reference) on seeded data covering every branch of the logic, (b) query
count identical at N and 3N rows. Run with `TEST_DB_NAME=test_perf_s3_polled`, `--keepdb`, only
the touched modules, never `--parallel`.

## Not in scope
Market shortage (other session), Stage 1 budgets, Stage 2 settings, `slow_requests`.
