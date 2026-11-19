# Performance Stage 3.1 — Market Shortage endpoints

**Spec:** `docs/superpowers/specs/2026-11-19-performance-boost-design.md` §4 (reports ≤ 2 s p95), §6 Stage 3
item 1 and its caching rule, §9 (an "as of HH:MM" label is pre-approved; figures must stay identical).

**Endpoints:** `api/purchasing/shortage/{candidates,deltas,confirmed,med-types}/` — 19–33 s in the office
slow-request log (4 days before PR 188).

## Profile (local dev DB copy, read-only, 2026-11-19)

975,680 sales lines, 51,905 stockable items, 10,938 items with sales, 59 snapshots.

| Step inside `item_signals()` | Time | Queries |
|---|---|---|
| Sales GROUP BY (`COUNT(DISTINCT date_trunc('month'))`) | 2.3–2.8 s (3.2 s EXPLAIN) | 1 |
| Stock sum for the run | 0.34 s | 1 |
| Load **all 51,905 stockable items as model objects** | **7.8 s** (160 ms of it in Postgres) | 1 |
| `stockout_map()` | 0.3 s | 2 |

`item_signals` cold: 14.7 s; with PR 188's sales cache warm: still **10.1 s**. Every one of the four endpoints
calls it, and the page fires three of them in parallel — so the cache from PR 188 removed the repeated sales
scans but not the cost that dominates.

## Root causes

1. **Model instances for every stockable item.** `item_signals` builds 51,905 `Item` objects (deferred-field
   `.only()` objects are slow to build) and then throws away everything that is not a candidate, confirmed or
   dismissed — a few thousand at most. This runs on every call, cache or no cache.
2. **`COUNT(DISTINCT …)` per item** forces a sort per group; it is 75 % of the sales query.

## Fix

1. Decide candidacy from the sales and stock numbers *before* touching `Item` (the rule only needs those
   numbers), then load only `is_stockable AND (id IN candidates OR in_shortage OR shortage_dismissed)`.
   Same item fields, same flags read live, same arithmetic — the dict holds the same items.
2. Count sale months with a month bitmask: `BIT_OR(1 << ((year*12 + month) % 60)) FILTER (…)`, then
   `int.bit_count()` in Python. The 365-day window spans at most 13 consecutive calendar months, so no two
   months share a bit; the count is exactly the old `COUNT(DISTINCT …)` (verified equal on all 10,938 items).
   Measured 0.77–0.89 s vs 2.3–2.8 s.
3. **Age label (caching rule).** The cached sales/stock value (PR 188: per run + day, 10 min) now carries the
   time it was computed; candidates / deltas / confirmed return it as `signals_as_of`, and the page shows
   «الأرقام كما في HH:MM». No new cache, no longer TTL, nothing cached that is not already.

No migration, no index (the bitmask query uses the existing `item_id` index scan), no change to thresholds,
tiers, scores, totals or SOFTECH.

## Tests (TDD) — `apps/tests/test_shortage_perf.py`

- **Identical output:** a copy of the pre-change `item_signals` (old SQL, all items) is the reference; for a
  dataset with candidates of every tier, returns, zero-qty lines, a 13-month span, confirmed, dismissed,
  manual and quiet items, `item_signals()` and the JSON of all four endpoints equal the reference's
  (apart from the new `signals_as_of` key).
- **Query count flat:** queries for each endpoint are the same with 3 and with 15 candidate items.
- **No full item load:** an item with no sales and no flags is not loaded.

## Rollout

Code only. Expected office numbers after deploy: cold ≈ 1.3 s, warm ≈ 0.5 s per endpoint.
