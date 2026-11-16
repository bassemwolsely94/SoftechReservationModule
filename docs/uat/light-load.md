# W7 — Light load on the UAT copy (2026-11-17)

Plan Task 11 (`docs/superpowers/plans/2026-11-16-role-uat.md`), design §5.7. This is the first time
`deploy/loadtest/locustfile.py` has been run. It is a **light** run on the office PC. The full
20–40-user test stays a cutover item for the VPS (release-readiness: "no load test").

## Read this first: the server was a single dev process

- The backend was **one `manage.py runserver --noreload` process** on 127.0.0.1:8200
  (`config.settings_uat`). That means threads under one GIL, with no gunicorn/uvicorn workers.
- It shared the PC with Postgres 16 (the ~12 GB restored copy), five other Claude UAT sessions and
  their browsers.
- So **absolute numbers are pessimistic** compared with the VPS, which will run several workers.
  Read them for *ranking* (which routes are slow and which get worse under concurrency), not as
  VPS latency.
- Other sessions' single Playwright specs may have hit the same server during the window. Heavy
  runs could not, because this run held the `heavy.ps1` lock.

## What ran

| | |
|---|---|
| Tool | Locust 2.47.0, in its own venv (`.venv-locust`, git-ignored) |
| Command | `. scripts/uat/uat-env.ps1; scripts/uat/run_light_load.ps1`, run inside `heavy.ps1` ("W7 light load") |
| Stages | 5 users × 5 min (00:15–00:20), then 10 users × 10 min (00:20–00:30); spawn rate 1/s; think time 2–6 s |
| Users | UAT mode: `UAT_USERS_JSON` = `.uat-users.json`. Role weights: pharmacist 4, salesperson 3, call_center 1, supervisor 1, purchasing 1. Each virtual user signs in once as a UAT user of its role (round-robin over the accounts of that role) |
| Requests | Read only: the login POST plus GETs. Polls: bell, freshness, dashboard. Interactive: universal / items / customers search, worklists. Role extras: pharmacist → stock-expiry summary; salesperson / call_center → customers list (+ reservations); supervisor → insurance claims + supply dashboard; purchasing → metrics + filter-options |
| Raw output | `frontend/test-results-uat/load/` (git-ignored): `load_5u_*.csv`, `load_10u_*.csv`, `memory.csv` (sampled every 10 s), Locust logs |
| Tables | `python scripts/uat/summarize_load.py frontend/test-results-uat/load` |

With 5 users and 5 weighted classes, Locust spawned no supervisor at 5 users. That is why
`insurance/claims` and `dashboard/supply` only appear at 10 users.

The think time is much shorter than the real screens' 30/60/90 s poll timers. So each virtual user
is several times busier than a real member of staff: 10 virtual users ≈ 3.5 req/s.

## Result in one paragraph

**0 failures out of 2,635 requests** (5 users: 0 / 547; 10 users: 0 / 2,088). There were no 5xx,
no timeouts and no login problems. The aggregate p95 went from 2.7 s (5 users, 1.85 req/s) to
3.0 s (10 users, 3.51 req/s). The routes the audit already named as slow are still the slowest, and
the polled ones get worse with concurrency: `sync/freshness` p95 5.1 s, `dashboard/summary` max
7.7 s. **The memory floor was never reached:** free RAM never fell below 5.8 GB, against a 3 GB floor.

## Per endpoint at 5 and 10 users (ms)

| Endpoint | 5u n | 5u fail | 5u p50 | 5u p95 | 5u max | 10u n | 10u fail | 10u p50 | 10u p95 | 10u max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `GET batches/stock-expiry/summary` | 13 | 0 | 1,700 | 3,400 | 3,435 | 54 | 0 | 2,100 | 4,400 | 6,898 |
| `GET customers` | 8 | 0 | 1,100 | 1,700 | 1,708 | 43 | 0 | 710 | 2,400 | 3,191 |
| `GET customers?search` | 44 | 0 | 820 | 2,200 | 3,664 | 159 | 0 | 820 | 2,500 | 4,660 |
| `GET dashboard/summary` | 27 | 0 | 1,700 | 3,100 | 3,150 | 113 | 0 | 1,700 | 2,700 | 7,692 |
| `GET dashboard/supply` | – | – | – | – | – | 7 | 0 | 660 | 1,200 | 1,187 |
| `GET insurance/claims` | – | – | – | – | – | 7 | 0 | 310 | 870 | 867 |
| `GET items?search` | 45 | 0 | 1,000 | 1,800 | 2,363 | 160 | 0 | 1,000 | 2,400 | 5,343 |
| `GET notifications/` | 77 | 0 | 290 | 940 | 2,340 | 299 | 0 | 340 | 1,200 | 3,127 |
| `GET notifications/category-counts` | 77 | 0 | 260 | 720 | 1,305 | 299 | 0 | 280 | 900 | 2,528 |
| `GET pos-orders` | 29 | 0 | 320 | 600 | 802 | 98 | 0 | 360 | 880 | 1,557 |
| `GET purchasing/filter-options` | 9 | 0 | 1,300 | 2,600 | 2,638 | 15 | 0 | 1,200 | 2,200 | 2,156 |
| `GET purchasing/metrics` | 9 | 0 | 990 | 1,300 | 1,275 | 15 | 0 | 830 | 1,900 | 1,857 |
| `GET reservations` | 37 | 0 | 610 | 1,800 | 2,819 | 109 | 0 | 720 | 1,700 | 3,926 |
| `GET search/universal` | 45 | 0 | 1,900 | 3,000 | 4,673 | 161 | 0 | 1,700 | 3,300 | 6,821 |
| `GET supply/cases` | 29 | 0 | 240 | 910 | 1,065 | 98 | 0 | 360 | 1,100 | 1,355 |
| `GET sync/freshness` | 29 | 0 | 2,600 | 4,400 | 4,387 | 167 | 0 | 2,800 | 5,100 | 8,783 |
| `GET sync/status` | 29 | 0 | 260 | 880 | 1,472 | 167 | 0 | 280 | 1,100 | 3,396 |
| `POST auth/login` | 5 | 0 | 2,300 | 2,500 | 2,505 | 10 | 0 | 2,500 | 2,800 | 2,768 |

Totals:

- **5 users:** 547 requests, 0 failures (0.00 %), 1.85 req/s, p50 550 ms, p95 2,700 ms, max 4,673 ms.
- **10 users:** 2,088 requests, 0 failures (0.00 %), 3.51 req/s, p50 610 ms, p95 3,000 ms, max 8,783 ms.

Locust percentiles are bucketed to two significant figures, so p95 can print a little above max.
With n < 20, p95 is effectively the max.

**403s are not failures.** They mean the role may not open that screen. They are counted as success
and listed once more as their own row:

- 5 users: 35 in total (supply/cases 23, pos-orders 6, reservations 6).
- 10 users: 107 in total (supply/cases 76, pos-orders 12, reservations 12, insurance/claims 7).

That is RBAC enforce doing its job on screens the mix sends to every role. W2/W5 own the
question of whether each 403 is the intended matrix.

## The 15 slowest endpoints (p95 at 10 users)

| # | Endpoint | n | p50 | p95 | max |
|---:|---|---:|---:|---:|---:|
| 1 | `GET sync/freshness` | 167 | 2,800 | 5,100 | 8,783 |
| 2 | `GET batches/stock-expiry/summary` | 54 | 2,100 | 4,400 | 6,898 |
| 3 | `GET search/universal` | 161 | 1,700 | 3,300 | 6,821 |
| 4 | `POST auth/login` | 10 | 2,500 | 2,800 | 2,768 |
| 5 | `GET dashboard/summary` | 113 | 1,700 | 2,700 | 7,692 |
| 6 | `GET customers?search` | 159 | 820 | 2,500 | 4,660 |
| 7 | `GET customers` | 43 | 710 | 2,400 | 3,191 |
| 8 | `GET items?search` | 160 | 1,000 | 2,400 | 5,343 |
| 9 | `GET purchasing/filter-options` | 15 | 1,200 | 2,200 | 2,156 |
| 10 | `GET purchasing/metrics` | 15 | 830 | 1,900 | 1,857 |
| 11 | `GET reservations` | 109 | 720 | 1,700 | 3,926 |
| 12 | `GET dashboard/supply` | 7 | 660 | 1,200 | 1,187 |
| 13 | `GET notifications/` | 299 | 340 | 1,200 | 3,127 |
| 14 | `GET supply/cases` | 98 | 360 | 1,100 | 1,355 |
| 15 | `GET sync/status` | 167 | 280 | 1,100 | 3,396 |

## Comparison with the single-request timings (07_PERFORMANCE_AUDIT.md §1)

The audit timed one request at a time, as wall time inside the view, on `elrezeiky_db`. Locust
measures from the client, so its numbers also include the HTTP round-trip, middleware and queuing
behind other requests in the one process. Most of the gap below is that queuing.

| Route | Audit single request (ms) | Here p50 / p95 @10u (ms) | Reading |
|---|---:|---:|---|
| `sync/freshness` | 1,510 cold / 1,163 warm | 2,800 / 5,100 | ≈ 2.4× at p50. The worst route under load, and it is polled by every open tab. PERF-2/PERF-3 matter most. |
| `batches/stock-expiry/summary` | 3,680 (≈ 2.5 s Python) | 2,100 / 4,400 | p50 is below the audit's single run (warmer cache, smaller per-branch scope for a branch pharmacist); the tail is the GIL-bound Python. |
| `search/universal` | 1,462 (panadol) | 1,700 / 3,300 | Close at p50. The 1 s `UPPER(name) LIKE` customer scan dominates. Wildcard terms (`conco*`) and Arabic both take part in the mix. |
| `dashboard/summary` | 1,263 warm / 2,311 cold | 1,700 / 2,700 (max 7,692) | As predicted; the max shows the 9× COUNT + seq-scan family piling up. |
| `customers?search` | 666–887 (`ahmed`) | 820 / 2,500 | Same p50; the tail triples under concurrency. |
| `items?search` | 528 (panadol) | 1,000 / 2,400 | ≈ 2×. The `COUNT(DISTINCT …)` pagination count. |
| `purchasing/filter-options` | 1,829–1,861 | 1,200 / 2,200 | Faster than the audit (only 15 calls, warm cache); still among the slowest. |
| `purchasing/metrics` | 235 | 830 / 1,900 | ≈ 3.5×, mostly queuing behind slower neighbours. |
| `reservations` | 474 (59 queries, N+1) | 720 / 1,700 | The N+1 cost grows with concurrency (PERF-4). |
| `customers` (list) | 181 (54 queries, N+1) | 710 / 2,400 | ≈ 4×. The per-row restricted-branches N+1 under load. |
| `supply/cases` | 177 (53 queries, N+1) | 360 / 1,100 | ≈ 2×. |
| `notifications/category-counts` | 19–29 (85 unread), 414 (63k unread) | 280 / 900 | The UAT users have small backlogs, so this is queuing, not the backlog query. The 63k-backlog case was not in the mix. |
| `notifications/` | 34–42 | 340 / 1,200 | ≈ 8×. Pure queuing behind the slow routes in the same process. |
| `sync/status` | 23 | 280 / 1,100 | Same: a cheap route made slow by its neighbours. This is the single-process / GIL risk the audit called out. |
| `pos-orders` | 95 | 360 / 880 | ≈ 4×, queuing. |
| `insurance/claims` | 666–744 (≈ 520 ms Python) | 310 / 870 | n = 7, branch-scoped supervisor; not comparable. |

**Pattern.** Cheap routes are 5–12× slower here than alone. Expensive ones are 1–2.5× slower. That
is queuing behind the slow, polled routes inside one Python process. It supports the audit's
remedy: several workers on the VPS, plus PERF-1 to PERF-5 for the routes that are slow on their own
(freshness, dashboard summary, stock-expiry summary, universal search).

**Login:** about 2.5 s per sign-in. That is mostly password hashing on one process, and it happens
once per session, so it does not matter for steady state. Ten simultaneous logins at shift start
would queue on one process.

## Memory

From `memory.csv`, sampled every 10 s, 87 samples:

| Stage | Free RAM min / max | Postgres working set max (private) | PG processes max | runserver |
|---|---|---|---:|---:|
| 5 users | 5.81 / 7.55 GB | 2.71 GB (0.30 GB) | 35 | 0.37 GB |
| 10 users | 5.80 / 8.49 GB | 3.09 GB (0.38 GB) | 44 | 0.37 GB |

- The 3 GB floor was never reached, and Locust was not stopped early.
- Free RAM moved mostly with the other sessions, not with the load. The stage-2 maximum is higher
  than stage 1's.
- The Postgres process count rose from 28 to 44 as connections opened. This is `CONN_MAX_AGE = 0`
  churn, one connection per request thread (audit §7, "watch PG connections"). The Postgres working
  set (mostly shared buffers) grew by about 0.7 GB.
- The web process stayed flat at 0.37 GB.

## Not covered (left for the VPS run)

- 20 and 40 users, and real gunicorn/uvicorn workers.
- The 63k-unread backlog user. The `pbx/live` 6 s poll (PBX is off on the copy).
- The interference test, where one `purchasing/export` or `usage-print/sheet` runs during the poll mix.
- POS create, and production-sized GL screens.
- The scheduler's 5-minute sync bursts. The scheduler is off on the copy, and there is no SOFTECH
  host, so the real sync load is not in these numbers.

## Findings for the report (Task 13)

- **L-01 (P2, performance):** `sync/freshness`, a poll on every screen, has p95 5.1 s and max 8.8 s
  at 10 light users. It is the slowest route under load. → PERF-2/3 before cutover.
- **L-02 (P2, performance):** in one process, cheap polls (`sync/status`, `notifications/`) reach a
  p95 of about 1.1–1.2 s, against 23–42 ms alone. This confirms the single-process risk. → several
  workers on the VPS (the audit recommendation), and verify in the VPS load test.
- **L-03 (P3):** `dashboard/summary` max 7.7 s and `batches/stock-expiry/summary` max 6.9 s under 10
  users. → PERF-1 / stock-expiry Python cost.
- **L-04 (info):** 0 failures and no memory pressure at 10 users. The copy and Postgres are stable at
  this load on this PC.
- **Tooling fixes made in the locustfile:**
  - the old `/api/search/` route returned 404 → `/api/search/universal`;
  - items and customers used `?q=`, which did not filter → `?search=`;
  - the login check matched "mfa" in the body, which every successful login contains → it now reads
    `mfa_required`.

  Without these fixes, the VPS run would have refused to start.
