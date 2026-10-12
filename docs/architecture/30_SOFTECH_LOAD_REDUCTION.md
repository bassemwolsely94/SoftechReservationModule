# 30 — SOFTECH Load Reduction (connections & duplicate reads)

**Status:** 🔍 AUDIT DONE (2026-10-12), code-grounded · plan awaiting owner approval · nothing changed yet.
**Goal:** keep SOFTECH smooth by pulling each piece of data **once**, pulling only what
**changed**, and opening **as few connections as possible** — without making any screen
or report less fresh than it is today.

**Rules for this work**
- Read-side only. No change to any SOFTECH write channel's behaviour.
- Every change ships behind a setting with the old path kept as fallback, and with
  before/after numbers from the telemetry in step 1.0.
- Anything that depends on how SOFTECH maintains a column (e.g. `modif_lastupdate`) is
  first confirmed with a READ-ONLY probe on the owner's PC — this container cannot reach SOFTECH.

---

## 1. How SOFTECH is reached today

- `config/sybase.py` — `get_sybase_connection()` (HQ) and `get_branch_connection()` (branch
  nodes 130/140/150/160/170). Every call is a **new JDBC login** (retry ×3); there is no
  reuse or pool, and no per-query timing/row logging (only the network probe times a `SELECT 1`).
- **~290 call sites** across **~150 functions** open their own connection.
- 51 APScheduler jobs (`apps/sync/tasks.py::start_scheduler`). The ones that touch SOFTECH
  most often are below.

## 2. Findings — ranked by load

| # | Finding | Where | Frequency | Approx. load (from code) |
|---|---------|-------|-----------|--------------------------|
| F1 | **Full stock snapshot every tick.** `SELECT … FROM stkbal WHERE nowqty>0` re-reads all positive stock rows (~130k), although the query already selects `modif_lastupdate` and never uses it. | `sync_stock` (fast lane) | every 5 min | ~37M rows/day |
| F2 | **Two days of sales re-read every tick.** Customer sales lines for *yesterday + today* (`stktrans ⋈ stktransm`, doccodes 115/30) are pulled, then their lines deleted and re-inserted in PG. | `sync_sales` (fast lane) | every 5 min | 288 × 2-day window/day |
| F3 | **Transit documents re-checked forever.** For **every** 125 transfer in a 30-day window: 1 receipt lookup + 1 issued-lines query (+1 received-lines query) — including documents already received and reconciled, whose data no longer changes. | `sync_in_transit` | every 15 min | (2–3 × docs in window) × 96/day |
| F4 | **Same transfer documents fetched twice.** The ERP matcher re-reads the 125 header + lines from SOFTECH that F3 already caches in `InTransitTransfer`, and opens **one connection per pending transfer** (up to 96 polls each). | `_poll_erp_matches` → `ERPMatcher._fetch_sybase` | hourly | 1 login + up to 4 passes per pending transfer |
| F5 | **Full master data every hour.** All customers (`localcustomers ⋈ personsdata`, ~200k), all items (+ full `personsdata`, `itemssuppliers`, every lookup table), all barcodes, users. Items have `itemlastupdate`; it isn't used to pull only changes. | `run_slow_sync` | every 60 min | ~5M+ rows/day |
| F6 | **One connection per 200 customers.** Points balances are read from `localcustomerspoints` in chunks of 200, and each chunk opens and closes its own connection. | `loyalty.pic_bridge.sync_all_softech_balances` (master hook) | every 60 min | ⌈loyalty accounts ÷ 200⌉ logins/hour |
| F7 | **Duplicate POS jobs.** `_flush_pos_orders` is scheduled twice (`pos_orders_flush` + `pos_flush_queued`, every 2 min) and `_reconcile_pos_orders` twice (`pos_orders_reconcile` + `pos_reconcile`, every 5 min). Different ids, so `max_instances=1` does not stop them running **together**. Both functions are also defined twice in `tasks.py`. | `start_scheduler` | 2 / 5 min | 2× branch connections for reconcile; 2× flush attempts |
| F8 | **Two separate sales pulls.** The purchasing engine pulls sales from `stktrans` into its own cache (`purchasing_salestransactionline`) besides F2's `PurchaseHistory`. Scopes differ — the engine includes walk-in sales without a customer code — so they are not yet interchangeable. | `purchasing/engine.py` | per engine run | one extra multi-day sales scan |
| F9 | **Finance month scan every hour.** A `stktrans` GROUP BY over the whole current month (two months on days 1–5), with its own connection. | `_sync_finance_snapshots` (master hook) | every 60 min | 24 month-scans/day |
| F10 | **Live item search on a miss.** When PG has no exact hit, a `LIKE '%a%b%'` scan of `items` runs on SOFTECH (one login per search). Has a breaker for outages, but no result cache. | `catalog.views._softech_live_search` | per search miss | 1 login + 1 table scan |

Lower-impact, kept as is: the network probe (6 × `SELECT 1` / 5 min, isolated by design),
the daily jobs (expiry, AP, insurance, drift, coupons), and per-branch loops that open one
connection per branch (legitimate).

## 3. Plan

### Phase 1 — quick wins (no change in data freshness, low risk)
| Step | Change | Fixes |
|------|--------|-------|
| 1.0 | **Measure first:** timing + row count + caller for every SOFTECH query and login (in `CursorWrapper` / `_connect_with_retry`), rolled up per job; «حمل SOFTECH» panel on `/sync`. | baseline for all steps |
| 1.1 | Remove the duplicate POS job registrations and duplicate function definitions. | F7 |
| 1.2 | Points sync: one connection for all chunks. | F6 |
| 1.3 | ERP matcher: check the `InTransitTransfer` cache first; one shared connection per poll cycle for whatever still needs SOFTECH. | F4 |
| 1.4 | Transit sync: stop re-reading documents in a final state (received + reconciled); fetch issued lines once per document. | F3 |
| 1.5 | Live item search: cache each pattern's result for a few minutes; minimum query length. | F10 |

### Phase 2 — pull only what changed (needs a read-only probe first)
| Step | Change | Fixes |
|------|--------|-------|
| 2.0 | Probe command (read-only, owner's PC): is `stkbal.modif_lastupdate` set on **every** change (sales, transfers, purchases, triggers)? Is `items.itemlastupdate` reliable? Is there a usable change column on `localcustomers`? | evidence |
| 2.1 | Stock: delta by `modif_lastupdate` watermark (no `nowqty>0` filter, so sold-out rows arrive as 0) + a nightly full reconcile. | F1 |
| 2.2 | Sales: during the day pull only *today*'s new documents (watermark); re-pull *yesterday* once early morning for late edits. | F2 |
| 2.3 | Items by `itemlastupdate`; customers by change column if one exists, otherwise new-customers-only hourly + full nightly. | F5 |

### Phase 3 — one source for shared data
| Step | Change | Fixes |
|------|--------|-------|
| 3.1 | One sales mirror (all lines, walk-in included) feeding both `PurchaseHistory` consumers and the purchasing engine. Design note first — touches DUP-006. | F8 |
| 3.2 | Finance P&L snapshot from the mirror, or SOFTECH scan reduced to the open day only. | F9 |
| 3.3 | Reuse one connection per job run across all its steps (small, bounded pool). | login count |

## 4. Out of scope
Any SOFTECH write path; changing what screens show; replacing APScheduler.
