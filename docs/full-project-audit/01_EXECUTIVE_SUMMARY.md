# 01 — Executive summary

**Full project audit, 2026-11-15** — `main` at `56870174`, fixes on branch `claude/full-project-audit` (not
merged). Scope: all 71 app folders, 1,693 API routes, ~270 screens. Method: a mechanical inventory, six
independent read-only audits (security, backend, frontend/UX, SOFTECH, performance, business), each finding
checked against the code, then low-risk fixes with regression tests. No SOFTECH connection, no production
data changed, nothing deployed.

## Overall condition

The extension is large, broad and mostly sound. The previous product review (2026-10-30) and two security
rounds left solid foundations: every API prefix is classified, every module view checks the permission
matrix, SOFTECH writers are switch-gated (default off), dry-run by default and audited, and CI runs
backend, security sweeps, static scans, frontend unit tests and Playwright. The remaining risk sits in three
places: **one live configuration hole in the office**, **retry/concurrency edges in the SOFTECH posting
paths**, and **capacity for 20 simultaneous users**.

## Technical health (evidence-based)

| Area | Rating | Evidence |
|---|---|---|
| Backend reliability | Good, with concurrency gaps | 0 P0; 2 P1 (posted POS order deletable — fixed; unlocked `prepare_order`); several read-modify-write money paths (loyalty, vouchers — 2 fixed) |
| Frontend reliability | Fair | Builds and 131/131 unit tests pass; TanStack v5 leftovers (161 sites) silently broke a form (fixed) and cause refetch storms; 82 screens show errors as "no data" |
| Security posture | Good code, **one P0 in configuration** | Office signs tokens with the public placeholder key while DEBUG is on (SEC-1); one stored XSS (fixed); log-mode RBAC still backed by per-view matrix checks |
| Database integrity | Good | Migrations clean; missing locks/constraints in a few money paths; immutable audit rows can cascade-delete (BE-11) |
| SOFTECH integration | Good design, retry edges | 21 writers, all in the manifest; 3 P1 double-post paths only after a lost commit reply or two simultaneous writes (S-1/S-2/S-3) |
| Performance | **Risky for 20 users as deployed** | Single Daphne process; 726k unread notifications polled every 30 s; unindexed sales-history date filter (320 MB scan per dashboard poll); measured 1–7 s on key screens |
| Automated testing maturity | Strong breadth, no depth in concurrency/load | ~8,875 backend tests + sweeps + Playwright; no concurrency, load, property-based or mutation tests |
| Deployment readiness | Stage A **GO**, Stage B **NO-GO** | See [12](12_RELEASE_READINESS.md) |

## Findings by severity (90 total)

| Report | P0 | P1 | P2 | P3 | Fixed here |
|---|---|---|---|---|---|
| [03 Security](03_SECURITY_AUDIT.md) | 1 | 1 | 4 | 6 | 2 |
| [04 Backend](04_BACKEND_AUDIT.md) | 0 | 2 | 11 | 8 | 4 |
| [05 Frontend/UX](05_FRONTEND_UX_AUDIT.md) | 0 | 2 | 10 | 15 | 1 |
| [06 SOFTECH](06_SOFTECH_INTEGRATION_AUDIT.md) | 0 | 3 | 9 | 8 | 2 |
| [07 Performance](07_PERFORMANCE_AUDIT.md) | 0 | 3 | 5 | 2 | 1 |
| **Total** | **1** | **11** | **39** | **39** | **10** |

## Bugs and vulnerabilities that matter most

| Severity | Finding | Area | Business risk | Fix status | Verification |
|---|---|---|---|---|---|
| P0 | SEC-1 office `SECRET_KEY` = public placeholder, DEBUG on | config | Anyone with the repo on the office network can forge an admin token and drive the SOFTECH writers | **Needs you (D-01)** | Confirmed by equality check (no value printed) |
| P1 | SEC-2 stored XSS portal → staff receipt print | reservations | Script runs with a staff session | **Fixed** | 4 unit tests |
| P1 | BE-1 delete of a posted POS order | POS | Lost docnumber → possible second post | **Fixed** | 2 API tests |
| P1 | S-1 / BE-2 POS retry after settlement | POS ↔ SOFTECH | Second sale after a lost commit reply | Needs you (D-05) | Code read end to end |
| P1 | S-2 A/P writer without lock | finance ↔ SOFTECH | Lost update / doubled payment link | Needs you (D-06) | Code read |
| P1 | S-3 purchase idempotency on digits only | invoices ↔ SOFTECH | Duplicate purchase on retry | Needs you (D-07) | Code read |
| P1 | FE-1 offline queue replays under another user, server ignores its idempotency key | mobile | Wrong audit name; duplicates | Needs you (D-24) | Code read |
| P1 | FE-2 reservation lines dropped silently | reservations | Customer misses items | Wave 2 | Code read |
| P1 | PERF-1/2/3 notification flood, unindexed sales history, single web process | platform | Slow screens at 20 users | Needs you (D-19…D-21) | Measured single requests |
| P2 | BE-5 / BE-6 / BE-8 voucher double redeem, loyalty double deduct, negative referral adds points | vouchers, loyalty | Money leakage | **Fixed** | 5 API tests |
| P2 | S-10 coupon stocking fails on days 22–31 | vouchers ↔ SOFTECH | Coupons not stocked a third of each month | **Fixed** | unit test (fake connection) |

## Best quick wins

23 of the 33 candidates finish or switch on code that already exists. The Top 10 by return on development
time (~168 h, [09](09_TOP_30_QUICK_WINS.md)): return-window coverage, network stock in the call centre,
AP exception queue, action-line morning brief, dead-stock move lane, stock-audit finding → task, near-expiry
worklist, refill-due list, weekly HQ exception digest, tiered cover under a cash budget. Money figures behind
them come from `docs/product-review/` measurements (e.g. ≈113k past the return window for two suppliers,
≈713k dead stock that fits another branch's gap).

## Implementation decisions

| Status | Items |
|---|---|
| **Already fixed** (branch, tested) | BE-1, BE-5, BE-6, BE-8, SEC-2, SEC-3, FE-6, S-10, S-13, PERF-5 — [11](11_BUG_FIX_REGISTER.md) |
| **Recommended for immediate fixing** | SEC-1 (D-01/D-02), DEBUG off (D-03), remaining print escaping (SEC-6) |
| **Requires your approval** | 28 decisions — [14](14_DECISION_REGISTER.md) |
| **Deferred** (planned waves) | TanStack v5 clean-up, error states, N+1, native dialogs — [13](13_IMPLEMENTATION_ROADMAP.md) |
| **Not feasible here** | Load test against a production-like DB (only the live office DB exists — D-22); anything needing live SOFTECH (settlement keeps `vf2`? `chequestrans` unique index? driver error text) |
| **Requires additional data** | Index drops (stats reset by the 2026-11-12 crashes), benchmark-based targets |

## Release readiness

Stage A (VPS as reader): **GO**. Stage B (VPS becomes the SOFTECH writer): **NO-GO** until SEC-1 is closed,
the P1 posting fixes D-05…D-07 land, the web tier is scaled (D-21) and a 20-user load test passes (D-22).
