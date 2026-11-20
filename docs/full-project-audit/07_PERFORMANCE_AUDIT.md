# 07 — Performance audit

**Measured:** 2026-11-15, 10:56–11:04 UTC (12:56–13:04 Cairo)
**Repo:** `.claude/worktrees/full-audit` on branch `claude/full-audit`. No repo files were edited.
**DB measured:** the office PostgreSQL dev database `elrezeiky_db`, PostgreSQL 16.13 on Windows, **12 GB**.
It runs on **default settings**: `shared_buffers` = 128 MB, `work_mem` = 4 MB, `effective_cache_size` = 4 GB, `track_io_timing` off.
Production (runbook §7.3) plans `shared_buffers` = 1.5 GB and `work_mem` = 32 MB, so absolute times on the VPS should be lower. Query counts and plan shapes will be the same.

**How the numbers were taken**

- **Safety.**
  - Each endpoint was called in-process through DRF `APIRequestFactory` + `force_authenticate`, in a transaction opened with `SET TRANSACTION READ ONLY` and then rolled back. Postgres would refuse any write.
  - `config/sybase.py` connect functions, `jpype.startJVM`, `threading.Thread.start` and outbound sockets were monkey-patched to raise, so no SOFTECH, thread or network side effects were possible.
  - SQL was captured with `CaptureQueriesContext`.
- **Single user, no concurrency.** Middleware is bypassed, so module-access, slow-log and network-zone costs are not included.
- **Users.**
  - User 1 (superuser, sees all branches) for most calls.
  - User 103, an admin with staff profile 102 and the largest unread-notification backlog, for the bell endpoints.
- **Cache state.** Every endpoint was called once, cold. Repeat calls are marked "warm".
- **Statistics caveat.** `pg_stat_*` counters do not cover the database's whole life (`stats_reset` is null). `n_live_tup` disagrees with `reltuples`: for example `customers_purchasehistory` shows 185 live tuples against 1.7 M real rows. The counters were most likely lost in the 2026-11-12 Postgres OOM restarts, so seq_scan and idx_scan numbers cover only the last few days. Use them as relative signals only.
- **`pg_stat_statements`** is **not installed**. Only `plpgsql` and `pg_trgm` are present, so there is no top-queries-by-total-time data.

---

## 1. Measured endpoint table

ms = wall time inside the view, including serialization. db = the sum of the captured SQL times.

| Endpoint (GET) | Queries | Wall ms | DB ms | Worst query (ms) | N+1 / notes |
|---|---:|---:|---:|---|---|
| `/api/dashboard/summary/` (cold) | 35 | 2311 | 2268 | `COUNT(*) customers_purchasehistory WHERE doc_code='115' AND (invoice_date AT TIME ZONE 'Africa/Cairo')::date >= …` (924) | 9 separate `COUNT(*) reservations WHERE status=?` |
| `/api/dashboard/summary/` (warm, two runs) | 35 | 1268 / 1263 | 1236 / 1229 | same family, `SUM(total_amount)` (468) | as above |
| `/api/notifications/category-counts/` as user 1 (85 unread) | 2 | 29 / 19 | 25 / 17 | `GROUP BY category` (14) | — |
| `/api/notifications/category-counts/` as user 103 (63,515 unread) | 2 | **414** | 410 | same query (402). Cold EXPLAIN ANALYZE: **2,358 ms**, 29,347 buffers read | grows with backlog |
| `/api/notifications/unread-count/` | 1 | 5–17 | 3–15 | COUNT | — |
| `/api/notifications/` (list) | 1 | 34–42 | 20–23 | list | — |
| `/api/sync/status/` | 2 | 23 | 12 | syncrun | — |
| `/api/sync/freshness/` (cold / warm) | 46 | 1510 / 1163 | 1437 / 1094 | per-day `COUNT` on `customers_purchasehistory` by `(invoice_date AT TIME ZONE …)::date` (645 / 415) | 6× `MAX(sync_synclog.created_at)` |
| `/api/reservations/` (page of 50) | **59** | 474 | 230 | list (68) | **51× `reservationline` by reservation_id** |
| `/api/customers/` (page of 50) | **54** | 181 | 100 | `COUNT(*)` (81) | **51× `branches ⋈ staffprofile_restricted_branches`** |
| `/api/customers/?search=ahmed` | 41 | 887 / 666 | 835 / 600 | `SELECT DISTINCT …` + `COUNT(DISTINCT …)` (416 / 324) | 38× restricted-branches |
| `/api/items/` | 6 | 316 | 281 | `COUNT(*) FROM (SELECT DISTINCT catalog_item …)` (249) | — |
| `/api/items/?search=panadol` | 6 | 528 | 503 | same `COUNT(DISTINCT …)` (267) | — |
| `/api/search/universal?q=panadol` | 18 | 1462 | 1426 | `customers_customer WHERE UPPER(name) LIKE '%PANADOL%' OR …` (**1067**) | 3× restricted-branches |
| `/api/purchasing/summary/` | 4 | 191 | 185 | metrics aggregate (101) | — |
| `/api/purchasing/metrics/` (gap list) | 3 | 235 | 183 | metrics page (179) | 88 KB |
| `/api/purchasing/aggregated/` | 3 | 102 | 72 | (70) | — |
| `/api/purchasing/filter-options/` (two runs) | 10 | **1861 / 1829** | 1704 / 1694 | `SELECT DISTINCT effect_code, effect_name, effect_name_ar, catalog_item.name …` (259) | DISTINCT defeated by `Meta.ordering`, see PERF-5. 103 KB |
| `/api/supply/cases/` | **53** | 177 | 80 | (18) | **50× `supply_availabilityline` per case** |
| `/api/dashboard/supply/` | 18 | 73 | 42 | (20) | 5 near-identical `COUNT` on supplycase |
| `/api/insurance/claims/` (two runs) | 9 | 744 / 666 | 143 / 134 | prescriptions prefetch (57) | **about 520 ms is Python/serializer**, not SQL |
| `/api/pos-orders/` | 6 | 95 | 29 | `COUNT(*)` (13) | 110 KB |
| `/api/batches/stock-expiry/summary/` | 38 | **3680** | 1131 | `SUM/COUNT DISTINCT stockexpirybalance` (183) | 9× `DISTINCT item_code, expiry_date`. **About 2.5 s Python** |
| `/api/finance/gl/reports/trial-balance/?from=2026-01-01&to=2026-11-15` | 2 | 42 | 34 | (24) | GL ledger nearly empty in dev, so not representative |
| `/api/finance/gl/entries/` | 1 | 24 | 14 | — | almost no rows in dev |
| `/api/pic-analytics/overview/?from=2026-10-01&to=2026-10-31` | 20 | 1018 | 735 | `customers_customer WHERE softech_pic IN (SELECT pic FROM picdayfact …)` (249) | 5× `config_systemsetting` |
| `/api/pic-analytics/overview/?from=2026-01-01&to=2026-10-31` | 19 | **6585** | 3836 | `picdayfact GROUP BY pic … COUNT(DISTINCT …)` (944) | about 2.7 s Python |

### Slow-request log (P-56, read only)

P-56 is the `SlowRequestMiddleware` that records requests at or above `SLOW_REQUEST_MS` (1000 ms) into the `sync_slowrequest` table. There are no files under `logs/`. The table holds **1,623 rows from 2026-10-31 to 2026-11-15**. Status codes: 200 = 1582, 5xx = 5.

| Route | n | p50 ms | p95 ms | max ms | Total s |
|---|---:|---:|---:|---:|---:|
| `api/notifications/category-counts/` | **620** | 1326 | 4598 | 16882 | **1125** |
| `api/purchasing/filter-options/` | 66 | 1887 | 4154 | **308858** | 575 |
| `api/sync/freshness/` | 115 | 1359 | 5019 | 218296 | 445 |
| `api/batches/stock-expiry/summary/` | 65 | 4383 | 10841 | 25914 | 346 |
| `…/softech-reprice/plan/<id>/apply/` POST | 16 | 8460 | 77326 | 78974 | 340 |
| `…/softech-reprice/apply-batch/` POST | 22 | 7220 | 32246 | 61308 | 286 |
| `api/purchasing/isr/filter-options/` | 5 | 4459 | 209969 | 260939 | 277 |
| `api/purchasing/export/` | 2 | 127174 | — | 164213 | 254 |
| `api/dashboard/summary/` | 87 | 1985 | 6425 | 12624 | 230 |
| `api/usage-print/sheet/` | 2 | 69672 | — | 132428 | 139 |
| `api/sync/branch-health/` | 5 | 22363 | — | 23140 | 111 |
| `api/finance/cash-view/` | 3 | 13493 | — | 63649 | 84 |
| `api/finance/receivables/summary/` | 1 | 72814 | — | 72814 | 72 |
| `api/insurance/claims/` | 27 | 1218 | 4964 | 7908 | 50 |

The slow log agrees with the measurements. The bell badge, filter options, freshness bar and dashboard are the polled or high-frequency routes that are repeatedly at or above 1 s.

---

## 2. Database shape (measured)

### Top 25 tables by total size

| Table | Total | Heap | Indexes | Est. rows |
|---|---:|---:|---:|---:|
| purchasing_itemdemandmetrics | **2513 MB** | 1035 MB | **1477 MB** | 568k |
| customers_purchasehistory | 1095 MB | 319 MB | 777 MB | 1.71M |
| notifications_notification | **1049 MB** | 458 MB | 591 MB | 879k |
| customers_purchasehistoryline | 780 MB | 467 MB | 312 MB | 3.78M |
| tax_invoicing_etamirrorreceipt | 578 MB | 474 MB | 104 MB | 331k |
| purchasing_salestransactionline | 561 MB | 131 MB | 430 MB | 1.01M |
| stock_audit_stockledgerline | 502 MB | 253 MB | 249 MB | 1.09M |
| notifications_notificationlog | 488 MB | 99 MB | 389 MB | 906k |
| customers_customer | 354 MB | 111 MB | 243 MB | 199k |
| purchasing_itemdemandaggregated | 349 MB | 119 MB | 230 MB | 181k |
| procurement_purchaseline | 335 MB | 125 MB | 210 MB | 265k |
| catalog_item | 224 MB | 92 MB | 132 MB | 52k |
| purchasing_transferrecommendation | 200 MB | 90 MB | 110 MB | 98k |
| finance_matchevidence | 185 MB | 98 MB | 87 MB | 664k |
| delivery_deliveryorder | 182 MB | 53 MB | 130 MB | 34k |
| pbx_cdrcall | 182 MB | 70 MB | 112 MB | 134k |
| pic_analytics_picdayfact | 160 MB | 52 MB | 108 MB | 333k |
| finance_journalentry | 150 MB | 46 MB | 103 MB | 294k |
| finance_journalline | 146 MB | 81 MB | 65 MB | 948k |
| purchasing_itemseasonality | 127 MB | 79 MB | 48 MB | 217k |
| pbx_pbxevent | 124 MB | 67 MB | 57 MB | 216k |
| finance_matchcandidate | 116 MB | 36 MB | 80 MB | 174k |
| tax_invoicing_etareconline | 99 MB | 71 MB | 27 MB | 462k |
| finance_reconauditevent | 96 MB | 78 MB | 18 MB | 126k |
| finance_apinvoice | 86 MB | 37 MB | 48 MB | 138k |

### Sequential-scan-heavy tables (since the last stats loss)

- `customers_purchasehistory`: 798 seq scans read **454 M tuples**, about 570k rows per scan, which is the whole table. 25.6 M index scans.
- `customers_customer`: 117 seq scans, 20 M tuples.
- `catalog_item`: 518 seq scans, 13.5 M tuples.
- `finance_allocation`: 124 seq scans, 9.5 M tuples.
- `branches_branch` (15 rows): 145,519 seq scans. Harmless per scan, but it shows how often branch lookups repeat (see PERF-4).

### Unused non-unique, non-PK indexes

**2,498** indexes have `idx_scan = 0`, totalling **3.65 GB**. The counter window is short, so these are candidates to review, not a list to drop. The largest:

| Index | Size |
|---|---:|
| `purch_metrics_date_priority` | 363 MB |
| `notification.dedup_key` (btree) | 89 MB |
| `notification.dedup_key` `_like` | 90 MB |
| `purch_metrics_item_branch_date` | 93 MB |
| `purch_metrics_date_abc` | 80 MB |
| `purch_metrics_date_branch` | 80 MB |
| `purch_agg_date_value` | 71 MB |
| `purchasehistory.docnumber` | 56 MB |
| `purchasehistory.docnumber` `_like` | 56 MB |

`purchasing_itemdemandmetrics` also has unused single-column and `_like` indexes on `abc_class`, `branch_id`, `demand_pattern` and `root_cause`, each 41–52 MB.

### Dead-tuple bloat

Live-tuple counts here are distorted by the stats loss above. Taken as raw numbers:

| Table | Dead tuples |
|---|---:|
| `customers_purchasehistoryline` | 96k (sync deletes and re-inserts 2 days of lines every 5 minutes, F2) |
| `customers_customer` | 28.8k (14.5 %) |
| `finance_apinvoice` | 19k |
| `finance_allocation` | 14.8k |

---

## 3. Findings

### PERF-1 (P1) — Notification flood makes the polled bell badge slow and grows the largest hot table

- **Evidence (measured):**
  - 726,280 notifications, and **none marked read** (`is_read = true` count = 0).
  - The oldest notification is 2026-08-17. The table is 1,049 MB, plus 488 MB of `notificationlog`.
  - Staff profile 102 (an admin) has **63,515 unread**: `transit_critical` 46,847, `transit_overdue` 5,147, `delivery_sla_alert` 4,637, `branch_connectivity` 2,529.
  - Seven more profiles have about 17.5k unread each.
- **Cost of `category-counts` for that user (measured):** 2,358 ms cold (EXPLAIN ANALYZE, bitmap heap scan over 63,515 rows, 29k buffers read) and 414 ms warm. Other users: 19–29 ms.
- **Slow-log impact:** it is the **#1 route by count and total time** (620 hits ≥ 1 s, 1,125 s total, max 16.9 s).
- **Polling multiplier:**
  - `useNotificationSocket` reconciles every 30 s per open tab via `fetchNotifications` + `notificationStore.refresh()`, which calls `category-counts`.
  - When the websocket is not live it polls every **8 s**.
  - With 20 users × 1–3 tabs that is roughly 40–120 bell calls per minute.
- **Fix:**
  - (a) Dedupe or roll up the monitoring alerts (`transit_*`, SLA and connectivity) into one live row per subject instead of one row per tick. The `dedup_key` index exists but has 0 scans.
  - (b) Auto-expire or mark read monitoring notifications older than N days, through the data-lifecycle module.
  - (c) Add a partial index `(recipient_id, category) WHERE NOT is_read`, or keep a per-recipient counter.
  - (d) Short-cache the counts per user, for example 15 s.
- **Expected gain:** at the backlog of the other users (85 unread) the same query takes 17 ms, so this route drops from about 0.4–2.4 s to tens of ms for the worst users. Table growth stops.
- **Risk:** product decision on which alerts may be collapsed. A new partial index adds small write overhead on a write-heavy table.

### PERF-2 (P1) — `customers_purchasehistory` has no index on `invoice_date` / `doc_code`, and the queries filter on a non-sargable expression

- **Evidence (measured):**
  - The table has 22 indexes, none on `invoice_date` or `doc_code`.
  - The dashboard and freshness filter on `(invoice_date AT TIME ZONE 'Africa/Cairo')::date >= …`.
  - EXPLAIN ANALYZE of the dashboard `SUM(total_amount)`: parallel seq scan, **40,646 buffers (about 320 MB) read, 545 ms**.
  - The same query with a plain timestamptz bound (`invoice_date >= '2026-11-08 00:00+02'`) is still a seq scan, because there is no index: 202 ms.
  - These scans account for the 454 M seq-tuple reads on the table.
- **Affected endpoints:**
  - `dashboard/summary` makes several such queries per call: 1.2–2.3 s measured; slow log 87 hits, p95 6.4 s.
  - `sync/freshness`: 1.1–1.5 s measured; slow log 115 hits, max 218 s.
- **Polling multiplier:**
  - `DashboardPage` refetches the summary every **90 s**.
  - `DataFreshnessBar` refetches freshness every **60 s** (4 s while refreshing), on every screen that shows it.
- **Fix:**
  - (a) Rewrite the filters as timestamptz range predicates: compute the Cairo-midnight bound in Python.
  - (b) Add a composite index `(doc_code, invoice_date)`, which can INCLUDE `total_amount`.
  - (c) Collapse the 9 reservation `COUNT ... status=?` queries into one `values('status').annotate(Count)`.
  - (d) Cache the summary for 30–60 s. The data is synced every 5 min anyway.
- **Expected gain:** from about 0.5 s and 320 MB of I/O per query to an index range scan over one week of rows. The exact figure needs a re-measure after the index exists, which was not done here (read-only audit).
- **Risk:** the index adds write overhead to `sync_sales`, which deletes and re-inserts 2 days of rows every 5 min (F2). That is modest at about 1.7 M rows. Only build it `CONCURRENTLY`.

### PERF-3 (P1) — Single Daphne process serves all HTTP and WebSocket traffic on a 4-vCPU VPS

- **Evidence (code):**
  - `deploy/elrezeiky-web.service` runs one `daphne -b 127.0.0.1 -p 8000 config.asgi:application`, with no `--workers` and no gunicorn/uvicorn.
  - Sync Django views run on asgiref's thread pool inside **one Python process**, so all Python-side work (serializers, Excel exports, the in-process OCR the runbook mentions) shares one GIL, which means **one core**.
  - Measured endpoints that are Python-bound:
    - `stock-expiry/summary`: about 2.5 s of the 3.7 s is Python.
    - `pic-analytics overview` (10 months): about 2.7 s of the 6.6 s.
    - `insurance/claims`: about 0.5 s of the 0.7 s.
  - The slow log has exports running 70–165 s (`purchasing/export`, `usage-print/sheet`). While one of these runs, every other user's request competes for the same GIL.
- **Database connections (code):**
  - `CONN_MAX_AGE = 0`, so a new PG connection is opened for every request.
  - No `statement_timeout` is set: `OPTIONS` has only `connect_timeout`. A runaway query (filter-options max 309 s) holds a connection and a core.
- **Caching (code):** `CACHES` is `LocMemCache`, which is per-process. That is fine with one process but will not be shared if workers are added.
- **Fix:**
  - Run HTTP under `gunicorn -k uvicorn.workers.UvicornWorker -w 3` (or 3 Daphne instances behind the nginx upstream), and keep one Daphne for `/ws/`, or let channels-redis fan out.
  - Move exports and OCR to the scheduler or a job queue (pic-analytics already has export jobs).
  - Add `-c statement_timeout=30s` in `OPTIONS` for the web role only.
  - Set `CONN_MAX_AGE` to around 60 with health checks, or add pgbouncer.
  - Move to a shared cache (Redis is already deployed) before going multi-worker.
- **Expected gain:** throughput for CPU-bound requests can scale up to about 3× (3 of 4 cores). This is an estimate.
- **Risk:**
  - Memory: about 0.8 GB per web process including the JVM, and the runbook budget for 8 GB is already tight. Measure RSS first.
  - The scheduler must stay a single process. The one-scheduler lock already exists.
  - LocMem caches must move to Redis first.

### PERF-4 (P2) — N+1 queries on list endpoints

All measured, at 50 rows per page.

- **`/api/reservations/`: 59 queries.**
  - `ReservationListSerializer.get_lines` calls `obj.lines.select_related('item').all()` (`apps/reservations/serializers.py:235`).
  - The viewset already does `prefetch_related('lines__item')` (views.py:145), but the new `select_related` creates a fresh queryset that **bypasses the prefetch**, so there is one query per row.
  - Fix: iterate `obj.lines.all()`.
- **`/api/customers/`: 54 queries. `/api/customers/?search=`: 41 queries.**
  - `mask_dict` → `phones_visible` → `core/branch_scope.allowed_branch_ids` runs `profile.restricted_branches.values_list(...)` once per serialized row.
  - Universal search has the same pattern (3×).
  - Fix: memoize the allowed-branch set on the request or the profile (one lookup per request). This also explains the 145k seq scans on the 15-row `branches_branch`.
- **`/api/supply/cases/`: 53 queries.**
  - `availability_line_ids = PrimaryKeyRelatedField(source='availability_lines', many=True)` runs one query per case.
  - Fix: add `prefetch_related('availability_lines')` in the viewset.
- **`/api/batches/stock-expiry/summary/`:** 9 near-identical `DISTINCT item_code, expiry_date` queries, plus heavy Python.
- **`/api/sync/freshness/`:** 46 queries, including 6 repeated `MAX(sync_synclog.created_at)` lookups. One grouped query would do.
- **Expected gain:** about 50 fewer round-trips per page view on reservations and customers. Measured DB time is about 100–230 ms, mostly round-trips, so a few hundred ms saved under load (estimated).
- **Risk:** none material.

### PERF-5 (P2) — `purchasing/filter-options`: `.distinct()` is silently widened by `Meta.ordering`

- **Evidence (measured):**
  - The captured SQL is `SELECT DISTINCT effect_code, effect_name, effect_name_ar, catalog_item.name …`.
  - `_codelist` in `apps/purchasing/views.py` (around line 2008) does `base_qs.exclude(...).values(*fields).distinct()` with **no `.order_by()`**, so Django adds `Item.Meta.ordering = ['name']` to the DISTINCT list.
  - Each list therefore returns about one row per item instead of one row per code, and Python dedupes afterwards.
  - Result: 10 queries, 1.7 s DB, 103 KB response. Slow log: 66 hits, p95 4.2 s, max **309 s**.
  - `isr/filter-options` (slow log max 261 s) should be checked for the same pattern.
- **Fix:** add `.order_by()` before `.distinct()`, and cache the result per `run_id`, because options only change when a new engine run finishes.
- **Expected gain:** each DISTINCT returns tens of rows instead of tens of thousands. Not re-measured.
- **Risk:** none. Output is the same after the existing Python dedupe.

### PERF-6 (P2) — SOFTECH read load: the Phase 2 delta sync is still not built

**Evidence (measured from `SoftechLoadStat`, the last 7 days):**

- Only 58 active hours were recorded, because the office runtime was down part of the week.
- Totals: 10,398 logins, 105,712 queries, **32.5 M rows**, 28,031 s of SOFTECH query time. 99 % of rows are from HQ.

| Caller | Runs / queries | Rows | Query time | Note |
|---|---:|---:|---:|---|
| `sync_stock` (every 5 min) | 393 runs | **12.48 M** (about 31.7k per run) | 8,734 s | F1 still open. `QUERY_STOCK` still has `WHERE sb.nowqty > 0` and does not filter on `modif_lastupdate` |
| `sync_customers` (hourly, full) | 104 runs | **10.33 M** (about 99k per run) | 2,209 s | F5 |
| `sync_items` | 380 queries | 3.11 M | 2,106 s | max 19.3 s per query. F5 |
| `sync_item_barcodes` | — | 1.67 M | — | — |
| `sync_sales` (2-day window, every 5 min) | — | 0.99 M | — | F2 |
| `sync_in_transit._fetch_items` | **39,406 queries** | 420k | 4,117 s | max 20 s. Per-document lines query, so an N+1 against SOFTECH. Phase 1.4 caches final documents, but open ones are still one query each |
| `retention_watch` | 498 logins, 1,494 queries | — | 625 s | max 28.7 s |
| `customer_merge_candidates` | — | 604k | — | — |

- **What doc 30 already fixed:** Phase 1 (F3, F4, F6, F7, F10 partial).
- **What remains (code):**
  - Phase 2.1 stock delta, 2.2 sales watermark, 2.3 items and customers delta. The `probe_softech_change_columns` command exists but its outcome has not been applied.
  - F8: a second sales pull for the purchasing engine.
  - F9: the hourly finance month scan.
  - Phase 3.3: one connection per job.
- **Fix:** run the read-only change-column probe, then build 2.1 and 2.3, which cover the stock and customer pulls (about 70 % of rows read). Batch `_fetch_items` into one `IN (...)` query per cycle.
- **Expected gain:** stock plus customers is 22.8 M of 32.5 M rows (70 %) in this window. A working delta would remove most of that, but the size depends on the change rate, which is unknown.
- **Risk:** stale stock if `modif_lastupdate` is not set by every writer. That is why the doc requires the probe plus a nightly full reconcile. **No SOFTECH change is proposed by this audit.**

### PERF-7 (P2) — Index bloat on `purchasing_itemdemandmetrics` (1.48 GB of indexes on 1.04 GB of heap)

- **Evidence (measured):**
  - Nine or more indexes show 0 scans: `date_priority` 363 MB, `item_branch_date` 93 MB, `date_abc` 80 MB, `date_branch` 80 MB, plus single-column and `_like` on `abc_class`, `branch_id`, `demand_pattern`, `root_cause` (41–52 MB each).
  - The engine rewrites about 568k rows per run, so every index costs write time and WAL.
  - `notification.dedup_key` btree + `_like` (179 MB) and `purchasehistory.docnumber` + `_like` (112 MB) are also unused.
- **Fix:** after a full week of uninterrupted stats (or from the production stats), drop the `varchar_pattern_ops` `_like` twins where no `LIKE 'x%'` exists, and drop the redundant date indexes. There are two identical `(recipient_id, is_read)` indexes on notification (`…4e3567_idx` and `…684eac_idx`), so one can go.
- **Expected gain:** faster engine runs and less WAL and backup size. About 3.6 GB is the upper bound across all unused indexes. Not quantified per run.
- **Risk:** dropping an index that a rare monthly report needs. The stats window is short because of the OOM restarts, so verify on production stats first.

### PERF-8 (P2) — Python-heavy analytics endpoints

- **Measured:**
  - `pic-analytics/overview` for 10 months: 6.6 s, of which 3.8 s DB with a 944 ms `GROUP BY pic` over `picdayfact` (333k rows).
  - `stock-expiry/summary`: 3.7 s.
  - `insurance/claims` list: 0.7 s, 0.5 s of it Python.
- **Fix:** pre-aggregate monthly `picdayfact` rollups. For stock-expiry, profile the Python loop (likely per-row dict building over all expiry balances). Cache both per data refresh, since their data changes only on sync.
- **Risk:** low.

### PERF-9 (P3) — Office dev PostgreSQL runs untuned defaults

- **Measured:** `shared_buffers` = 128 MB, `work_mem` = 4 MB, `random_page_cost` = 4, `max_connections` = 100, no `pg_stat_statements`.
- The 12 GB DB, with 2.5 GB hot purchasing tables, cannot stay cached, which matches the 40k-buffer reads above.
- Production plans 1.5 GB / 32 MB (runbook §7.3).
- **Fix:**
  - Apply the §7.3 values on the office server while it remains the writer.
  - Add `pg_stat_statements` to `shared_preload_libraries` on the VPS, so real top-N data exists after cutover.
  - Set `random_page_cost = 1.1` on SSD.
  - Enable `track_io_timing`.
- **Risk:** needs a restart (owner step).

### PERF-10 (P3) — Frontend polling footprint

- **Code-split (code):** `App.jsx` has **196 `lazy()` routes** and only 2 static page imports, so code splitting is good. Nginx gzips JS; its comment says the main chunk is about 5 MB.
- **Polling (code):** 141 `refetchInterval`/`setInterval` sites. The ones that run for every user on every screen:

| Source | Request | Interval |
|---|---|---|
| `useNotificationSocket` | notifications list + `category-counts` | 30 s reconcile; **8 s** poll when the websocket is down |
| `Layout` | `sync/status` | 60 s |
| `DashboardPage` | `sync/status` (in addition) | 30 s |
| `DashboardPage` | `dashboard/summary` | 90 s |
| `DataFreshnessBar` | `sync/freshness` | 60 s; 4–5 s while refreshing |
| `CallPopBanner` | `/pbx/live/?fresh=1` | **6 s** for every user with an extension |
| `usePosOrder` | queue | 20 s |
| `DeliveryDashboard` | — | 15 s |

- **Estimate for 20 users with one tab each on the dashboard:**
  - Per minute: about 40 bell, 20 + 40 sync-status, 13 dashboard-summary and 20 freshness calls.
  - DB time: about 13 × 1.25 s + 20 × 1.1 s + 40 × (0.02–0.4 s), roughly **40–55 DB-seconds per minute** before any real work. That is about 0.7–0.9 of a core continuously, on the warm, untuned office numbers.
  - With the websocket down, bell traffic rises 3.75×.
- **Fix:**
  - PERF-1 and PERF-2 remove most of this cost.
  - Additionally: set `refetchIntervalInBackground: false` globally (React Query already pauses in hidden tabs by default unless overridden; check `refetchIntervalInBackground` usage), drop Dashboard's duplicate 30 s `syncStatus`, and push freshness and counts over the existing websocket.
- **Risk:** none.

---

## 4. Capacity verdict for 20 concurrent staff (4 vCPU / 8 GB / PG16)

- **Database:** with the §7.3 tuning, the steady polling load is fine once PERF-1 and PERF-2 land. Without them, the bell, dashboard and freshness polls alone keep about one core busy (estimate above).
- **Web tier:** under-provisioned in shape, not in size. One Daphne process means one core for Python. A single 70–165 s export or OCR job stalls everyone's requests behind the GIL, and there is no `statement_timeout`.
- **Recommendation:** 3 HTTP workers + Redis cache + `statement_timeout` + exports and OCR off the web process. Re-check RSS against the 8 GB budget, which already includes 0.8 GB per JVM-carrying process.
- **Verdict:** **adequate for 20 users after PERF-1 to PERF-5 and the worker change. Risky as deployed today.**

### What a Locust test should cover

1. **Background poll mix per virtual user:**
   - every 30 s: bell (`notifications/` + `category-counts`)
   - every 60 s: `sync/status` and `sync/freshness`
   - every 90 s: `dashboard/summary`
   - every 6 s: `pbx/live` for about 5 users
   - Include one user with a 60k unread backlog.
2. **Interactive mix:**
   - customers search
   - universal search
   - items search
   - reservations list
   - purchasing metrics + filter-options
   - supply cases
   - insurance claims list
   - pos-orders list and create (create against a dry-run or test node only)
   - GL trial balance and account statement, with a production-sized ledger
3. **Interference test:** start one `purchasing/export` or `usage-print/sheet` and one OCR upload, then measure p95 of the poll mix while they run (the GIL / single-process risk).
4. **Concurrency:** ramp 5 → 20 → 40 users. Watch PG connections (`CONN_MAX_AGE = 0` churn), web RSS, swap, and p95 per route, against the existing `SlowRequest` table.
5. **Websocket-down scenario:** 8 s bell polling.
6. **Environment:** run against staging only, never against the SOFTECH writer, and with the scheduler running, because sync bursts every 5 min compete for the same DB.

---

## 5. Not measured / limits

- **GL screens:** the dev ledger is nearly empty, so trial-balance (42 ms) and entries (24 ms) are not representative.
- **Middleware cost:** not included.
- **Concurrency:** none tested; every call was single-threaded and in-process.
- **No new indexes created:** expected gains from new indexes are not measured.
- **`pg_stat_*` counters:** partial (reset by the 2026-11-12 crashes).
- **Scripts used** (scratchpad, read-only):
  - `perf_db.py`
  - `perf_slow.py`
  - `perf_ep.py` (endpoint harness with the READ ONLY transaction and SOFTECH, thread and socket blocks)
  - `perf_explain.py`
  - `perf_uid.py`
  - `perf_load.py`

---

## 6. Stage 1 baseline (performance boost, 2026-11-19)

Design: `docs/superpowers/specs/2026-11-19-performance-boost-design.md`. Plan:
`docs/superpowers/plans/2026-11-19-perf-stage1-measure-and-guard.md`.

### 6.1 Slow-request log, last 14 days, ranked by total time (office, read only)

325 slow calls (≥ 1 s). The office runtime was down part of the window, so counts are low; read it as
a ranking. Window 2026-11-05 → 2026-11-19 includes calls from before PERF-5 (filter-options) merged.

| Route | n | p50 ms | p95 ms | max ms | total s |
|---|---:|---:|---:|---:|---:|
| `GET api/purchasing/filter-options/` | 41 | 1880 | 21374 | 308858 | 519 |
| `GET api/sync/freshness/` | 53 | 1270 | 3120 | 218296 | 317 |
| `GET api/purchasing/isr/filter-options/` | 4 | 6091 | 260939 | 260939 | 273 |
| `GET api/purchasing/export/` | 1 | 164213 | 164213 | 164213 | 164 |
| `POST api/purchasing/isr/fulfilment/` | 6 | 6376 | 69256 | 69256 | 160 |
| `POST api/purchasing/rates/propose/` | 3 | 52585 | 61140 | 61140 | 160 |
| `POST api/purchasing/rates/pushes/<int:pk>/execute/` | 3 | 52214 | 55892 | 55892 | 144 |
| `GET api/usage-print/sheet/` | 2 | 132428 | 132428 | 132428 | 139 |
| `GET api/purchasing/shortage/confirmed/` | 4 | 29512 | 32613 | 32613 | 105 |
| `GET api/batches/stock-expiry/summary/` | 16 | 4976 | 8174 | 10830 | 82 |
| `GET api/purchasing/shortage/deltas/` | 3 | 29132 | 31930 | 31930 | 80 |
| `POST api/purchasing/isr/fulfilment/export/` | 3 | 23794 | 48601 | 48601 | 79 |
| `GET api/purchasing/shortage/med-types/` | 3 | 19501 | 22390 | 22390 | 61 |
| `GET api/purchasing/shortage/candidates/` | 3 | 18875 | 22402 | 22402 | 60 |
| `GET api/notifications/` | 18 | 2219 | 6890 | 8944 | 52 |

Not yet in any Stage 3 session: `isr/filter-options`, `isr/fulfilment` (+ export), `rates/propose` and
`rates/pushes/…/execute` (SOFTECH-adjacent: stop and ask before changing), `usage-print/sheet` and
`purchasing/export` (both Stage 4 exports).

### 6.2 Query budgets (CI, `apps/tests/perf/`)

Measured with the budget harness (`PERF_BUDGET_REPORT=1 manage.py test apps.tests.perf`). Few rows →
many rows; ceiling = measured + 2 (`apps/tests/perf/budgets.py`).

| Route | Kind | Queries | Note |
|---|---|---:|---|
| `notifications/` | poll | 2 | |
| `notifications/category-counts` | poll | 2 | |
| `sync/status` | poll | 3 | |
| `sync/freshness` | poll | 47 | Stage 3 target ≤ 8 |
| `dashboard/summary` | poll | 34 | Stage 3 target ≤ 10 |
| `reservations` | list | 9 | flat (PERF-4 fix holds) |
| `customers` (pharmacist) | list | 7 | flat (PERF-4 fix holds) |
| `customers?search` | list | 7 | |
| `items?search` | list | 6 | |
| `search/universal` | list | 18 | |
| `supply/cases` | list | 5 | flat (PERF-4 fix holds) |
| `pos-orders` | list | 7 | |
| `insurance/claims` | list | 8 | |
| `purchasing/metrics` | list | 5 | |
| `purchasing/filter-options` | list | 12 | |
| `batches/stock-expiry/summary` | report | 33 | cost is mostly Python |
| `incentives/targets` | report | **12 → 52** | **N+1** (≈4 per target), expected failure until Stage 3 |
| `audit/screen-view` | track | 3 | 2.7 s in production is not SQL count — check locks / inserts |

### 6.3 `pg_stat_statements`

Pending the owner's after-closing restart (`docs/deploy/2026-11-office-pg-query-stats.md`, from the
Stage 1 ranking/stats PR). Then: `manage.py perf_top_queries --limit 20`.

### 6.4 Query budgets after Stages 3–5 (2026-11-20)

Same harness, now reloading the signed-in user before each call (so counts match a real JWT request:
about +1 query versus §6.2) and checking the ceiling against the dearer of the two calls.
First call → call after growing the rows.

| Route | Kind | Queries | vs §6.2 |
|---|---|---:|---|
| `sync/freshness` | poll | 6 → 6 | 47 → 6 |
| `dashboard/summary` | poll | 12 → 12 | 34 → 12 (stock alerts now exercised) |
| `notifications/`, `category-counts`, `sync/status` | poll | 3 | +1 (user reload) |
| `reservations` | list | 10 → 9 | first call seeds one setting |
| `customers`, `customers?search` | list | 8 | |
| `items?search` | list | 6 | |
| `search/universal` | list | 19 | now grows all four groups |
| `supply/cases`, `purchasing/metrics` | list | 6 | |
| `pos-orders` | list | 8 | |
| `insurance/claims` | list | 9 | |
| `purchasing/filter-options` | list | 13 | row check on effects added |
| `incentives/targets` | report | 9 → 9 | was 12 → 52 (N+1 fixed) |
| `batches/stock-expiry/summary` | report | 5 | 33 → 5 |
| `audit/screen-view` | track | 4 → 3 | the de-dup insert is on the first call; ceiling checks it |
| `export-jobs/<id>` | poll | 4 | Stage 4 |

`SLACK` (allowed difference between the two calls) is now 1. §6.1 p50 is the upper median; rows with
n < 5 are anecdotal.
