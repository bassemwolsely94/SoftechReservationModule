# 06 · SPEC P-56 — Database retention and sync health

**Status:** specification (approved for spec 2026-10-30). **Build:** not yet authorised.
**Owner decisions:** keep the last 10 engine runs + one per month; commit `customers/0029` in the cutover.

## 1. Problem (measured, office PG)

**Database growth.** 9.9 GB with no retention. Of that:
- `ItemDemandMetrics`: 2.5 GB.
- Notifications + log: 1.53 GB.
- `TransferRecommendation`: 0.2 GB.

**Sync failures.** 9% of runs failed in 30 days (263 / 2,790):
- 201 SOFTECH connect timeouts;
- 20 Postgres schema mismatches, from a process started before migrations 0027/0028;
- 9 runs stuck as "running".

**Behaviour** [code]
- The full `stkbal` snapshot (~130k rows) is upserted every 5 minutes, whether or not anything changed
  (`apps/sync/tasks.py:888-955`).
- No lane retries.
- The morning jobs (07:30–08:40) depend on clock offsets.
- Request duration is not measured anywhere.

## 2. Scope

**1. Retention jobs** (daily, batched, logged in SyncLog):

| Table | Rule |
|---|---|
| `purchasing.ItemDemandMetrics` (and `ItemDemandAggregated` per run) | keep the runs of the **last 10 completed DemandCalculationRuns + the last run of each calendar month**; delete other runs' rows |
| `purchasing.TransferRecommendation` | same run rule (consistent with P-32 consolidation) |
| `notifications.*` | per P-55 Part C |
| `pbx.PBXEvent` | 90 days |
| `audit.AuditLog` | **never delete** rows whose action relates to money, SOFTECH writes, permissions or approvals (Rule 8); other noise actions 365 days. An explicit allow-list of deletable actions |

**2. Stock sync efficiency.**
- `sync_stock` writes only rows whose `quantity_on_hand` / `monthly_qty` / `on_order_qty` changed:
  - compare against a per-run in-memory map of current values, or
  - use `ON CONFLICT … DO UPDATE … WHERE (excluded.x IS DISTINCT FROM table.x)`.
- `last_synced` per row is replaced by the run timestamp, which `SyncRun` already records. **The freshness bar reads
  `SyncRun`, not row stamps.**

**3. Sync health.**
- **Stale runs:** `SyncRun` rows `running` for more than 60 min are marked `failed` ("stale — process died") by the
  heartbeat job.
- **Reconnect-and-retry once** on connection errors in every SOFTECH lane. The same rule as P-55 Part A: a failed
  read is "unknown", never "empty/zero".
- **Morning chain:** `ap_reconciliation_sync → insights_daily → supply_case_sweep → replacement_daily_check` run as
  one chained job, in order. Each step logs its own SyncLog.
- **Manual trigger:** the in-flight guard already exists (`sync/views.py:70-81`). Additionally, the scheduled lanes
  check for an in-flight manual run of the same lane and skip that tick.

**4. Schema-drift fix.**
- Commit `customers/0029` (PurchaseHistory `softech_personcode` DB default).
- Add the equivalent DB default for `customers_customer.merged_into_pic`, if it is not-null without a default.
- Runbook: **restart every process after `migrate`.**

**5. Measure before optimising.**
- A middleware logs request path template, status, duration and user role for requests over 1 s.
- An admin report shows the top 10 slow endpoints by p95 over the last 14 days.
- Live-SOFTECH-in-request paths are optimised **only where this report shows them** (POS is covered by P-39).

## 3. Acceptance criteria

- **Retention:** after a run, only the expected run ids remain (test with 15 fake runs across 3 months gives 10 + the
  monthly ones). AuditLog money/SOFTECH rows are never deleted (test).
- `sync_stock` with an unchanged snapshot performs **0 row updates** (test counts UPDATEs, or asserts unchanged
  `xmin`).
- A stale `running` row older than 60 min becomes `failed` (test).
- **A dropped connection in a lane is retried once, then the lane fails without writing partial "zero" values**
  (test with a flaky fake connection).
- The slow-request log captures a >1 s request (test with an artificial delay view).
- `test_purchasehistory_db_defaults.py` (already in the working copy) passes. Help updated for `/sync` (stale runs,
  slow-request report).

## 4. Measurement

- DB size (baseline 9.9 GB).
- Sync failure rate (baseline 9%).
- Stuck runs (baseline 9).
- p95 of the top 10 endpoints, after 2 weeks in production.
